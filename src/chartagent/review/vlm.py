"""Tool-free multimodal review for generated chart candidates."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Sequence

from ..prompting import build_reviewer_prompt
from ..spec import ChartFigure, ChartSpec, context_digest
from ..tools.core.result import GeneratedImage
from .models import (
    MAX_REVIEW_ISSUES,
    MAX_REVIEW_TEXT,
    ChartCandidate,
    ChartSemantic,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    REPAIR_KINDS,
)

VLM_REVIEW_CHECKS = (
    "chart_type",
    "orientation",
    "layout",
    "data_mapping",
    "labels",
    "readability",
)
_CHECK_STATUSES = frozenset({"pass", "warning", "fail"})
_DECISIONS = frozenset({"pass", "pass_with_warning", "fail"})
_LEGACY_TOP_LEVEL_FIELDS = frozenset({"decision", "confidence", "checks", "issues"})
_REPAIR_TOP_LEVEL_FIELDS = _LEGACY_TOP_LEVEL_FIELDS | frozenset({"repair_kind", "target"})
_REQUIRED_ISSUE_FIELDS = frozenset({"code", "location", "severity", "message"})
MAX_REVIEW_RESPONSE = 8_000
MAX_REVIEW_SPEC = 24_000

# Reviewer policy has one source of truth in the packaged Markdown assets.
VLM_REVIEW_SYSTEM_PROMPT = build_reviewer_prompt()


def _data_url(content: bytes, media_type: str) -> dict[str, Any]:
    payload = base64.b64encode(content).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type.lower()};base64,{payload}"},
    }


def _safe_spec_payload(spec: ChartSemantic) -> dict[str, Any]:
    """Keep provenance paths out while preserving figure-level semantics."""
    if isinstance(spec, ChartFigure):
        return {
            "kind": "chart_figure",
            "figure_id": spec.figure_id,
            "source": spec.source.to_dict(),
            "layout": spec.layout.to_dict(),
            "coverage": spec.coverage.to_dict(),
            "generation_context": spec.generation_context.to_dict() if spec.generation_context is not None else None,
            "generation_context_digest": context_digest(spec.generation_context),
            "charts": [
                {
                    "chart_id": child.chart_id,
                    "title": child.title[:MAX_REVIEW_TEXT],
                    "spec": _safe_spec_payload(child.spec),
                }
                for child in spec.charts[:8]
            ],
        }
    payload = spec.to_dict()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return {
        "metadata": {
            "chart_type": metadata.get("chart_type"),
            "title": str(metadata.get("title") or "")[:MAX_REVIEW_TEXT],
        },
        "axes": payload.get("axes"),
        "dataset": payload.get("dataset"),
        "generation_context": spec.generation_context.to_dict() if spec.generation_context is not None else None,
        "generation_context_digest": context_digest(spec.generation_context),
    }


def build_vlm_review_messages(
    candidate: ChartCandidate,
    spec: ChartSemantic,
    *,
    source_image: bytes | None = None,
    source_media_type: str = "image/png",
) -> list[dict[str, Any]]:
    """Build a fresh, tool-free multimodal request for one candidate."""
    spec_text = json.dumps(_safe_spec_payload(spec), ensure_ascii=False, separators=(",", ":"))
    if len(spec_text) > MAX_REVIEW_SPEC:
        spec_text = spec_text[:MAX_REVIEW_SPEC]
    context = candidate.generation_context or getattr(spec, "generation_context", None)
    if context is not None and context.source_scope is not None:
        review_scope = (
            "当前候选只审核 generation_context.source_scope 指定的 panel；"
            "原图中未列出的 panel 不属于本候选，不能因为它们未生成而报错。"
        )
    elif isinstance(spec, ChartFigure) and spec.source.panel_id:
        review_scope = "当前候选只审核 ChartFigure.source.panel_id 对应的 panel；其他 panel 不属于本候选。"
    else:
        review_scope = "当前候选审核其声明的完整画布；不得把未声明的外部 panel 加入检查。"
    context_summary = context.to_dict() if context is not None else None
    context = [
        {
            "type": "text",
            "text": (
                f"candidate_id={candidate.candidate_id}\n"
                f"review_id={candidate.review_id}\n"
                f"chart_spec_digest={candidate.chart_spec_digest}\n"
                f"candidate_size={candidate.width}x{candidate.height}\n"
                f"review_scope={review_scope}\n"
                f"generation_context={json.dumps(context_summary, ensure_ascii=False, separators=(',', ':'))}\n"
                f"{'ChartFigure' if isinstance(spec, ChartFigure) else 'ChartSpec'}={spec_text}"
            ),
        },
    ]
    if source_image is not None:
        context.extend(
            [
                {"type": "text", "text": "授权来源裁剪（source scope crop；不是整张附件）："},
                _data_url(source_image, source_media_type),
            ]
        )
    context.extend(
        [
            {"type": "text", "text": "生成候选图（candidate image）："},
            _data_url(candidate.content, candidate.media_type),
        ]
    )
    return [
        {"role": "system", "content": VLM_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]


def _invalid_result(message: str) -> ReviewResult:
    return ReviewResult(
        status=ReviewStatus.FAILED,
        checks={"vlm_review": "failed"},
        issues=(ReviewIssue("invalid_vlm_output", "review", message[:MAX_REVIEW_TEXT]),),
        evidence=(),
        decision="fail",
        confidence=0.0,
        review_mode="vlm",
        repair_kind="terminal",
    )


def _json_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().startswith("```"):
            return "\n".join(lines[1:-1]).strip()
    return text


def parse_vlm_review(content: str) -> ReviewResult:
    """Parse and validate the bounded JSON contract returned by the VLM."""
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_REVIEW_RESPONSE:
        return _invalid_result("VLM review response is empty or exceeds the response limit")
    try:
        payload = json.loads(_json_text(content))
    except (TypeError, json.JSONDecodeError):
        return _invalid_result("VLM review response is not valid JSON")
    if not isinstance(payload, Mapping):
        return _invalid_result("VLM review response must be a JSON object")
    fields = set(payload)
    if fields not in {_LEGACY_TOP_LEVEL_FIELDS, _REPAIR_TOP_LEVEL_FIELDS}:
        return _invalid_result("VLM review response must contain exactly the required top-level fields")
    has_repair_fields = fields == _REPAIR_TOP_LEVEL_FIELDS

    decision = payload.get("decision")
    if decision not in _DECISIONS:
        return _invalid_result("VLM review decision is invalid")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
        return _invalid_result("VLM review confidence must be a finite number within 0..1")

    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, Mapping) or set(raw_checks) != set(VLM_REVIEW_CHECKS):
        return _invalid_result("VLM review checks must contain exactly the required check names")
    checks = {name: raw_checks[name] for name in VLM_REVIEW_CHECKS}
    if any(status not in _CHECK_STATUSES for status in checks.values()):
        return _invalid_result("VLM review contains an invalid check status")

    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list) or len(raw_issues) > MAX_REVIEW_ISSUES:
        return _invalid_result("VLM review issues must be a bounded array")
    issues: list[ReviewIssue] = []
    for item in raw_issues:
        if not isinstance(item, Mapping):
            return _invalid_result("VLM review issue is not an object")
        if set(item) != _REQUIRED_ISSUE_FIELDS:
            return _invalid_result("VLM review issue must contain exactly the required fields")
        code, location, message, severity = (
            item.get("code"),
            item.get("location"),
            item.get("message"),
            item.get("severity"),
        )
        if not all(isinstance(value, str) and value.strip() for value in (code, location, message)):
            return _invalid_result("VLM review issue fields must be non-empty strings")
        if any(len(value) > MAX_REVIEW_TEXT for value in (code, location, message)):
            return _invalid_result("VLM review issue fields exceed the text limit")
        if severity not in {"warning", "error"}:
            return _invalid_result("VLM review issue severity is invalid")
        issues.append(ReviewIssue(code, location, message, severity))

    repair_kind = _derive_repair_kind(decision, issues)
    repair_target: dict[str, Any] | None = None
    if has_repair_fields:
        raw_repair_kind = payload.get("repair_kind")
        if not isinstance(raw_repair_kind, str) or raw_repair_kind not in REPAIR_KINDS:
            return _invalid_result("VLM repair_kind is invalid")
        repair_kind = raw_repair_kind
        raw_target = payload.get("target")
        if raw_target is not None:
            repair_target, target_error = _bounded_repair_target(raw_target)
            if target_error is not None:
                return _invalid_result(target_error)
    if decision in {"pass", "pass_with_warning"} and repair_kind != "none":
        return _invalid_result("a passing review must use repair_kind=none")
    if decision == "fail" and repair_kind == "none":
        return _invalid_result("a failed review must identify a bounded repair_kind")

    has_error = any(issue.severity == "error" for issue in issues)
    has_fail = "fail" in checks.values()
    has_warning = any(issue.severity == "warning" for issue in issues) or "warning" in checks.values()
    if decision == "pass" and (has_fail or has_warning or issues):
        return _invalid_result("VLM pass requires all checks to pass and no issues")
    if decision == "pass_with_warning" and (has_fail or has_error or not has_warning):
        return _invalid_result("VLM warning requires warning-only checks or issues and no blocking error")
    if decision == "fail" and not (has_fail or has_error):
        return _invalid_result("VLM fail requires a failed check or blocking error")

    evidence = ({
        "kind": "vlm_review",
        "decision": decision,
        "confidence": float(confidence),
        "checks": dict(checks),
    },)
    return ReviewResult(
        status=ReviewStatus.COMPLETED,
        checks=dict(checks),
        issues=tuple(issues[:MAX_REVIEW_ISSUES]),
        evidence=evidence,
        decision=decision,
        confidence=float(confidence),
        review_mode="vlm",
        repair_kind=repair_kind,
        repair_target=repair_target,
    )


def _derive_repair_kind(decision: str, issues: Sequence[ReviewIssue]) -> str:
    """Keep old reviewer JSON readable while assigning a safe next action."""
    if decision in {"pass", "pass_with_warning"}:
        return "none"
    codes = {issue.code for issue in issues}
    if codes & {"source_binding_failure", "source_scope_unavailable", "stale_source_scope", "scope_mismatch"}:
        return "source_rebind"
    if codes & {"evidence_needed", "value_uncertain", "measurement_insufficient", "missing_evidence"}:
        return "evidence_needed"
    return "spec_only"


def _bounded_repair_target(value: object) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, "VLM repair target must be an object or null"
    allowed = {"scope", "panel_id", "refs", "fields", "series", "category", "bbox_source_px", "reason"}
    if any(key not in allowed for key in value):
        return None, "VLM repair target contains an unsupported field"
    result: dict[str, Any] = {}
    for key in ("scope", "panel_id", "series", "category", "reason"):
        if key in value:
            item = value[key]
            if not isinstance(item, str) or not item.strip():
                return None, f"VLM repair target {key} must be a non-empty string"
            result[key] = item.strip()[:MAX_REVIEW_TEXT]
    for key in ("refs", "fields"):
        if key in value:
            items = value[key]
            if not isinstance(items, list) or len(items) > 16 or any(not isinstance(item, str) or not item.strip() for item in items):
                return None, f"VLM repair target {key} must be a bounded string array"
            result[key] = [item.strip()[:64] for item in items]
    if "bbox_source_px" in value:
        bbox = value["bbox_source_px"]
        if not isinstance(bbox, list) or len(bbox) != 4 or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in bbox):
            return None, "VLM repair target bbox_source_px must contain four finite numbers"
        result["bbox_source_px"] = [float(item) for item in bbox]
    if not result:
        return None, "VLM repair target must identify a bounded scope, ref, field or reason"
    return result, None


def review_candidate_with_vlm(
    client: Any,
    candidate: ChartCandidate,
    spec: ChartSemantic,
    *,
    source_image: bytes | None = None,
    source_media_type: str = "image/png",
    chat_kwargs: Mapping[str, Any] | None = None,
    trace_kwargs: Mapping[str, Any] | None = None,
) -> ReviewResult:
    """Run a bounded extra multimodal model call with no tools.

    One candidate review performs at most one model call. A failed or malformed
    response becomes a fail-closed semantic result for this candidate attempt.
    """
    messages = build_vlm_review_messages(
        candidate,
        spec,
        source_image=source_image,
        source_media_type=source_media_type,
    )
    kwargs: dict[str, Any] = {
        "tools": None,
        "stream": False,
        "max_completion_tokens": 1200,
        "temperature": 0,
    }
    for key in ("model", "reasoning_effort"):
        value = (chat_kwargs or {}).get(key)
        if value is not None:
            kwargs[key] = value
    for key in ("trace_sink", "trace_run_id", "trace_turn"):
        value = (trace_kwargs or {}).get(key)
        if value is not None:
            kwargs[key] = value
    try:
        result = client.chat(messages, **kwargs)
        parsed = parse_vlm_review(getattr(result, "content", ""))
    except Exception as exc:  # noqa: BLE001 - provider failure is a review result.
        parsed = _invalid_result(f"internal VLM review call failed: {type(exc).__name__}")
        parsed = replace(parsed, suggested_action="retry_review", recovery_classification="transient_review_failure")
    return replace(
        parsed,
        candidate_id=candidate.candidate_id,
        review_id=candidate.review_id,
        chart_spec_digest=candidate.chart_spec_digest,
        candidate_attempt=candidate.lineage_attempt,
    )


__all__ = [
    "VLM_REVIEW_CHECKS",
    "VLM_REVIEW_SYSTEM_PROMPT",
    "build_vlm_review_messages",
    "parse_vlm_review",
    "review_candidate_with_vlm",
]
