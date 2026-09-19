"""Tool-free multimodal review for generated chart candidates."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Sequence

from ..prompting import build_reviewer_prompt
from ..spec import ChartSpec
from ..tools.core.result import GeneratedImage
from .manager import (
    MAX_REVIEW_ISSUES,
    MAX_REVIEW_TEXT,
    ChartCandidate,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
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
_REQUIRED_TOP_LEVEL_FIELDS = frozenset({"decision", "confidence", "checks", "issues"})
_REQUIRED_ISSUE_FIELDS = frozenset({"code", "location", "severity", "message"})
MAX_REVIEW_RESPONSE = 8_000
MAX_REVIEW_SPEC = 24_000

_LEGACY_VLM_REVIEW_SYSTEM_PROMPT = """你是 Figura 的图表视觉一致性审核器，不是图表生成器。

你只能根据本次消息中的三类证据进行一次审核：
1. 原图（如果提供）：判断源图的视觉语义、方向、布局和标签关系；
2. 生成候选图：判断实际渲染出的图表内容；
3. ChartSpec：判断期望的图表类型、数据、类别、系列和坐标结构。

不要调用工具，不要使用外部知识，不要臆造图像中看不见的内容。ChartSpec
不是候选图已经正确的证明，候选图的视觉事实也不能改变 ChartSpec 的数据。
如果原图、候选图和 ChartSpec 之间存在冲突，必须把冲突记录为问题，不能自行
选择一个来源后静默通过。

请在内部完成以下检查，不要输出推理过程：

一、建立坐标和方向
- 区分整张画布是否发生旋转、图表本身是横向还是纵向、坐标轴正方向和类别顺序；
- 找到绘图区边界、坐标轴、零点和零基线；
- 对柱状图检查柱体是否从坐标系的零基线开始，不要把图片底边、绘图区边缘或最近的网格线自动当成基准线；
- 对横向柱状图检查纵向零基线，对纵向柱状图检查横向零基线；
- 如果关键方向或坐标关系无法确认，不能直接判定为 pass。

二、检查结构和语义
- 图表类型、标题、坐标轴和图例是否匹配；
- 类别顺序、系列数量和系列身份是否匹配；
- 数值、相对大小、点位或扇区比例是否映射到正确的类别和系列；
- 标签是否与正确的图形元素关联；
- 是否存在裁切、遮挡、重叠或低对比度导致的关键内容不可读。

三、按图表类型检查
- bar：横向/纵向方向、零基线、柱体长度或高度、类别顺序、分组和标签关联；
- line：横纵坐标方向、点的顺序、折线连接关系、系列身份和点位变化；
- pie：扇区数量、相对比例、类别顺序、标签和图例关联；扇区起始角的风格差异不是错误；
- scatter：x/y 方向、点的相对位置、坐标范围和系列身份。

四、决定严重程度
- 图表类型、方向、类别顺序、系列身份、数值映射、零基线或关键标签错误属于 fail；
- 非关键的拥挤、轻微遮挡、低对比度或可读性问题可以是 pass_with_warning；
- 纯字体、抗锯齿、颜色细节或装饰风格差异，只要不改变语义或可读性，不应判定为 fail；
- pass 只允许在所有关键关系都能确认且没有任何 issue 时使用。

只返回一个 JSON 对象，禁止 Markdown、解释文字、代码围栏或额外字段。必须严格符合以下格式：

{
  "decision": "pass | pass_with_warning | fail",
  "confidence": 0.0,
  "checks": {
    "chart_type": "pass | warning | fail",
    "orientation": "pass | warning | fail",
    "layout": "pass | warning | fail",
    "data_mapping": "pass | warning | fail",
    "labels": "pass | warning | fail",
    "readability": "pass | warning | fail"
  },
  "issues": [
    {
      "code": "string",
      "location": "ChartSpec 字段或图像区域",
      "severity": "warning | error",
      "message": "简短、可修正的说明"
    }
  ]
}

顶层字段必须且只能是 decision、confidence、checks、issues；checks 必须且只能包含
六个固定名称；issues 最多 32 项，每项必须且只能包含 code、location、severity、message。
decision 的关系必须一致：pass 要求六项 checks 全为 pass 且 issues 为空；
pass_with_warning 不得有 fail 或 error，且必须至少有一个 warning；fail 必须至少有一个
fail check 或 error issue。confidence 必须是 0 到 1 之间的数字。"""

# Keep the old literal only as a migration fallback; production callers use
# the packaged Markdown resource so the reviewer prompt has one source of truth.
VLM_REVIEW_SYSTEM_PROMPT = build_reviewer_prompt()


def _data_url(content: bytes, media_type: str) -> dict[str, Any]:
    payload = base64.b64encode(content).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type.lower()};base64,{payload}"},
    }


def _safe_spec_payload(spec: ChartSpec) -> dict[str, Any]:
    """Keep provenance paths and unrelated metadata out of the reviewer input."""
    payload = spec.to_dict()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return {
        "metadata": {
            "chart_type": metadata.get("chart_type"),
            "title": str(metadata.get("title") or "")[:MAX_REVIEW_TEXT],
        },
        "axes": payload.get("axes"),
        "dataset": payload.get("dataset"),
    }


def build_vlm_review_messages(
    candidate: ChartCandidate,
    spec: ChartSpec,
    *,
    source_image: bytes | None = None,
    source_media_type: str = "image/png",
) -> list[dict[str, Any]]:
    """Build a fresh, tool-free multimodal request for one candidate."""
    spec_text = json.dumps(_safe_spec_payload(spec), ensure_ascii=False, separators=(",", ":"))
    if len(spec_text) > MAX_REVIEW_SPEC:
        spec_text = spec_text[:MAX_REVIEW_SPEC]
    context = [
        {
            "type": "text",
            "text": (
                f"candidate_id={candidate.candidate_id}\n"
                f"review_id={candidate.review_id}\n"
                f"chart_spec_digest={candidate.chart_spec_digest}\n"
                f"candidate_size={candidate.width}x{candidate.height}\n"
                f"ChartSpec={spec_text}"
            ),
        },
    ]
    if source_image is not None:
        context.extend(
            [
                {"type": "text", "text": "原图（source image）："},
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
    if set(payload) != _REQUIRED_TOP_LEVEL_FIELDS:
        return _invalid_result("VLM review response must contain exactly the required top-level fields")

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
    )


def review_candidate_with_vlm(
    client: Any,
    candidate: ChartCandidate,
    spec: ChartSpec,
    *,
    source_image: bytes | None = None,
    source_media_type: str = "image/png",
    chat_kwargs: Mapping[str, Any] | None = None,
    trace_kwargs: Mapping[str, Any] | None = None,
    max_attempts: int = 2,
) -> ReviewResult:
    """Run a bounded extra multimodal model call with no tools.

    Invalid model JSON is a semantic result and is not retried. Provider/runtime
    exceptions receive one bounded retry because the review call is otherwise
    independent from the main Agent turn.
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
    parsed: ReviewResult | None = None
    attempts = max(1, min(int(max_attempts), 2))
    for attempt in range(attempts):
        try:
            result = client.chat(messages, **kwargs)
        except Exception as exc:  # noqa: BLE001 - provider failure is a review result.
            if attempt + 1 < attempts:
                continue
            parsed = _invalid_result(f"internal VLM review call failed: {type(exc).__name__}")
            parsed = replace(parsed, suggested_action="retry_review", recovery_classification="transient_review_failure")
            break
        parsed = parse_vlm_review(getattr(result, "content", ""))
        break
    if parsed is None:  # pragma: no cover - defensive loop boundary
        parsed = _invalid_result("internal VLM review call did not return a result")
    return replace(
        parsed,
        candidate_id=candidate.candidate_id,
        review_id=candidate.review_id,
        chart_spec_digest=candidate.chart_spec_digest,
    )


__all__ = [
    "VLM_REVIEW_CHECKS",
    "VLM_REVIEW_SYSTEM_PROMPT",
    "build_vlm_review_messages",
    "parse_vlm_review",
    "review_candidate_with_vlm",
]
