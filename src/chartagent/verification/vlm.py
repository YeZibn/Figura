"""Bounded tool-free multimodal decision for generated chart verification."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..prompting import build_chart_verification_prompt
from ..spec import ChartFigure, context_digest
from .models import MAX_ISSUES, MAX_ISSUE_TEXT, VerificationIssue

VLM_CHECKS = ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")
MAX_VLM_RESPONSE = 8_000
MAX_VLM_SPEC = 24_000
_DECISIONS = frozenset({"pass", "pass_with_warning", "fail"})
_STATUSES = frozenset({"pass", "warning", "fail"})
_TOP_LEVEL = frozenset({"decision", "confidence", "checks", "issues"})
_ISSUE_FIELDS = frozenset({"code", "location", "severity", "message"})
VLM_SYSTEM_PROMPT = build_chart_verification_prompt()


@dataclass(frozen=True)
class VLMDecision:
    decision: str
    confidence: float
    checks: Mapping[str, str]
    issues: tuple[VerificationIssue, ...]


def _data_url(content: bytes, media_type: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": f"data:{media_type.lower()};base64,{base64.b64encode(content).decode('ascii')}"}}


def _safe_spec_payload(spec: Any) -> dict[str, Any]:
    if isinstance(spec, ChartFigure):
        return {
            "kind": "chart_figure",
            "figure_id": spec.figure_id,
            "source": spec.source.to_dict(),
            "layout": spec.layout.to_dict(),
            "coverage": spec.coverage.to_dict(),
            "generation_context": spec.generation_context.to_dict() if spec.generation_context else None,
            "generation_context_digest": context_digest(spec.generation_context),
            "charts": [
                {"chart_id": child.chart_id, "title": child.title[:MAX_ISSUE_TEXT], "spec": _safe_spec_payload(child.spec)}
                for child in spec.charts[:8]
            ],
        }
    payload = spec.to_dict()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return {
        "metadata": {"chart_type": metadata.get("chart_type"), "title": str(metadata.get("title") or "")[:MAX_ISSUE_TEXT]},
        "axes": payload.get("axes"),
        "dataset": payload.get("dataset"),
        "generation_context": spec.generation_context.to_dict() if spec.generation_context else None,
        "generation_context_digest": context_digest(spec.generation_context),
    }


def build_vlm_messages(
    *,
    staged_ref: str,
    chart_spec_digest: str,
    width: int,
    height: int,
    content: bytes,
    media_type: str,
    spec: Any,
    source_image: bytes | None = None,
    source_media_type: str = "image/png",
) -> list[dict[str, Any]]:
    spec_text = json.dumps(_safe_spec_payload(spec), ensure_ascii=False, separators=(",", ":"))[:MAX_VLM_SPEC]
    context = getattr(spec, "generation_context", None)
    if context is not None and context.source_scope is not None:
        scope_text = "只检查 generation_context.source_scope 指定的 panel；不评价范围外 panel。"
    elif isinstance(spec, ChartFigure) and spec.source.panel_id:
        scope_text = "只检查 ChartFigure.source.panel_id 对应的 panel。"
    else:
        scope_text = "检查 ChartSpec 声明的完整画布，不加入未声明的外部内容。"
    parts: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            f"staged_ref={staged_ref}\nchart_spec_digest={chart_spec_digest}\nimage_size={width}x{height}\n"
            f"scope={scope_text}\ngeneration_context={json.dumps(context.to_dict() if context else None, ensure_ascii=False, separators=(',', ':'))}\n"
            f"{'ChartFigure' if isinstance(spec, ChartFigure) else 'ChartSpec'}={spec_text}"
        ),
    }]
    if source_image is not None:
        parts.extend([{"type": "text", "text": "已授权的来源范围裁剪："}, _data_url(source_image, source_media_type)])
    parts.extend([{"type": "text", "text": "待验证的生成图："}, _data_url(content, media_type)])
    return [{"role": "system", "content": VLM_SYSTEM_PROMPT}, {"role": "user", "content": parts}]


def _invalid(message: str) -> VLMDecision:
    return VLMDecision(
        "fail", 0.0, {name: "fail" for name in VLM_CHECKS},
        (VerificationIssue("invalid_vlm_output", "verification", message[:MAX_ISSUE_TEXT]),),
    )


def parse_vlm_decision(content: str) -> VLMDecision:
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_VLM_RESPONSE:
        return _invalid("VLM response is empty or exceeds the response limit")
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return _invalid("VLM response is not valid JSON")
    if not isinstance(payload, Mapping) or set(payload) != _TOP_LEVEL:
        return _invalid("VLM response must contain exactly decision, confidence, checks, and issues")
    decision = payload.get("decision")
    confidence = payload.get("confidence")
    raw_checks = payload.get("checks")
    raw_issues = payload.get("issues")
    if decision not in _DECISIONS:
        return _invalid("VLM decision is invalid")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
        return _invalid("VLM confidence is invalid")
    if not isinstance(raw_checks, Mapping) or set(raw_checks) != set(VLM_CHECKS) or any(value not in _STATUSES for value in raw_checks.values()):
        return _invalid("VLM checks must contain the six required check names and valid statuses")
    if not isinstance(raw_issues, list) or len(raw_issues) > MAX_ISSUES:
        return _invalid("VLM issues must be a bounded array")
    issues: list[VerificationIssue] = []
    for item in raw_issues:
        if not isinstance(item, Mapping) or set(item) != _ISSUE_FIELDS:
            return _invalid("VLM issue must contain exactly code, location, severity, and message")
        code, location, severity, message = (item.get(key) for key in ("code", "location", "severity", "message"))
        if not all(isinstance(value, str) and value.strip() for value in (code, location, message)):
            return _invalid("VLM issue fields must be non-empty strings")
        if any(len(value) > MAX_ISSUE_TEXT for value in (code, location, message)) or severity not in {"warning", "error"}:
            return _invalid("VLM issue fields exceed bounds or use an invalid severity")
        issues.append(VerificationIssue(code, location, message, severity))
    checks = dict(raw_checks)
    has_error = any(item.severity == "error" for item in issues)
    has_fail = "fail" in checks.values()
    has_warning = any(item.severity == "warning" for item in issues) or "warning" in checks.values()
    if decision == "pass" and (has_fail or has_warning or issues):
        return _invalid("VLM pass requires six passing checks and no issues")
    if decision == "pass_with_warning" and (has_fail or has_error or not has_warning):
        return _invalid("VLM warning requires warning-only findings and no blocking error")
    if decision == "fail" and not (has_fail or has_error):
        return _invalid("VLM fail requires a failed check or blocking issue")
    return VLMDecision(decision, float(confidence), checks, tuple(issues[:MAX_ISSUES]))


def run_vlm_verification(
    client: Any,
    *,
    staged_ref: str,
    chart_spec_digest: str,
    width: int,
    height: int,
    content: bytes,
    media_type: str,
    spec: Any,
    source_image: bytes | None = None,
    source_media_type: str = "image/png",
    chat_kwargs: Mapping[str, Any] | None = None,
    trace_kwargs: Mapping[str, Any] | None = None,
) -> VLMDecision:
    messages = build_vlm_messages(
        staged_ref=staged_ref, chart_spec_digest=chart_spec_digest, width=width, height=height,
        content=content, media_type=media_type, spec=spec, source_image=source_image,
        source_media_type=source_media_type,
    )
    kwargs: dict[str, Any] = {"tools": None, "stream": False, "max_completion_tokens": 1200, "temperature": 0}
    for key in ("model", "reasoning_effort", "trace_sink", "trace_run_id", "trace_turn"):
        value = (trace_kwargs or {}).get(key) if key.startswith("trace_") else (chat_kwargs or {}).get(key)
        if value is not None:
            kwargs[key] = value
    try:
        response = client.chat(messages, **kwargs)
    except Exception as exc:  # noqa: BLE001 - provider availability is an explicit result.
        return VLMDecision(
            "fail", 0.0, {name: "not_run" for name in VLM_CHECKS},
            (VerificationIssue("vlm_unavailable", "verification", f"internal VLM request failed: {type(exc).__name__}"),),
        )
    return parse_vlm_decision(getattr(response, "content", ""))


__all__ = ["VLM_CHECKS", "VLMDecision", "build_vlm_messages", "parse_vlm_decision", "run_vlm_verification"]
