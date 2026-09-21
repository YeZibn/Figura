"""ReAct-style agent loop over the LLM client + tool registry.

Unlike ``Conversation`` (pure dialogue, strips ``tool_calls`` from history),
``Agent`` keeps a model's ``tool_calls`` in the assistant entry and appends a
``tool`` observation message per call, so the model can see its own actions and
observations turn after turn. This is the key difference from the dialogue loop.

Loop semantics (native function calling, not text ReAct):
- model returns ``tool_calls`` -> the Actions; run each serially via
  ``dispatch``; observations feed back; continue.
- model returns no ``tool_calls`` -> Final Answer; stop and return ``content``.
- step budget reached -> bounded stop, no unbounded loop.

Reasoning is never echoed into ordinary records or user-visible history. The
DeepSeek thinking + tools path retains its provider-required reasoning field
only in the internal model message immediately preceding a tool result.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Callable, List, Optional, Sequence

from ..client.client import LLMClient
from ..client.models import NormalizedResult, ToolCall
from ..multimodal import ToolVisualEvidence, build_tool_observation_content
from ..prompting import assemble_prompt_context, panel_inventory_from_layout_contexts
from ..trace import (
    TraceEmitter,
    TraceSink,
    bounded_reasoning,
    summarize_arguments,
    summarize_images,
    summarize_result,
)
from ..tools.core import ToolRegistry, dispatch_observation
from ..tools.core.presentation import get_tool_presentation
from ..memory import AgentMemory, InMemoryAgentMemory, RunStatus
from ..measurement import (
    MEASUREMENT_TOOLS,
    MeasurementSession,
    measurement_target_fingerprint,
    register_measurement,
    sessions_from_state,
    sessions_to_state,
)
from ..review import (
    ChartReviewManager,
    GeneratedChartReviewAdapter,
    MeasurementReviewAdapter,
    ReviewCoordinator,
    ReviewDecision,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    review_candidate_with_vlm,
)
from ..tools.core.result import DispatchedObservation, GeneratedImage
from .tool_schema import registry_tools, tool_to_openai_schema
from .messages import assistant_entry, tool_entry
from .review_gate import (
    _BUDGET_MSG,
    _REVIEW_FAILED_MSG,
    _REVIEW_REQUIRED_MSG,
    review_gate_context,
)
from .observations import observation_status

# Sentinel returned when the step budget is exhausted.
VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]
_LAYOUT_TOOL_NAME = "inspect_chart_layout"
_DECOMPOSE_TOOL_NAME = "decompose_chart_image"
_MAX_LAYOUT_CONTEXTS = 32
_MAX_PENDING_MEASUREMENT_REPAIRS = 16
_GEOMETRY_TOOL_NAMES = frozenset(
    {"measure_bars", "extract_line_series", "extract_scatter_points", "extract_pie_slices"}
)
_SCOPED_TOOL_NAMES = _GEOMETRY_TOOL_NAMES | {"extract_text"}
_RENDER_TOOL_NAMES = frozenset({"render_chart", "generate_chart"})


def _measurement_repair_context_from_content(content: str) -> dict[str, Any] | None:
    """Extract a compact evidence decision context for the next model turn."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    measurement = data.get("measurement") if isinstance(data, Mapping) else None
    if not isinstance(measurement, Mapping):
        return None
    reference = measurement.get("reference") if isinstance(measurement.get("reference"), Mapping) else {}
    quality = measurement.get("quality") if isinstance(measurement.get("quality"), Mapping) else {}
    evidence = measurement.get("evidence") if isinstance(measurement.get("evidence"), Mapping) else {}
    decision = measurement.get("decision") if isinstance(measurement.get("decision"), Mapping) else {}
    focus_suggestion = quality.get("focus_suggestion") or quality.get("repair_action")
    result: dict[str, Any] = {
        "session_id": reference.get("session_id"),
        "attempt_id": reference.get("attempt_id"),
        "attachment_id": reference.get("attachment_id"),
        "panel_id": reference.get("panel_id"),
        "status": str(measurement.get("status") or "provisional")[:32],
        "refs": list(evidence.get("refs") or [])[:64] if isinstance(evidence.get("refs"), list) else [],
        "warnings": list(quality.get("warnings") or [])[:12] if isinstance(quality.get("warnings"), list) else [],
        "issues": list(quality.get("issues") or [])[:8] if isinstance(quality.get("issues"), list) else [],
        "focus": evidence.get("focus") if isinstance(evidence.get("focus"), Mapping) else None,
        "focus_suggestion": focus_suggestion if isinstance(focus_suggestion, Mapping) else None,
        "decision_status": str(decision.get("status") or "pending")[:32],
        "selected_refs": list(decision.get("selected_refs") or [])[:64] if isinstance(decision.get("selected_refs"), list) else [],
        "discarded_refs": list(decision.get("discarded_refs") or [])[:64] if isinstance(decision.get("discarded_refs"), list) else [],
        "next_action": "由主 Agent 选择、舍弃或调用同一测量工具携带 measurement_target 做定向补充",
    }
    return result


def _repair_context_key(context: Mapping[str, Any]) -> tuple[str, ...]:
    """Return a stable identity for one bounded repair action."""
    target = context.get("target")
    target_id = target.get("target_id") if isinstance(target, Mapping) else None
    identity = tuple(
        str(context.get(key) or "")
        for key in (
            "attachment_id",
            "panel_id",
            "session_id",
            "attempt_id",
            "parent_attempt_id",
            "action",
        )
    ) + (str(target_id or ""),)
    if any(identity):
        return identity
    return (json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)[:512],)


def _figure_has_measurement_decision(figure: Mapping[str, Any]) -> bool:
    """Return whether a figure contains an explicit child measurement choice."""
    charts = figure.get("charts")
    if not isinstance(charts, list):
        return False
    return any(
        isinstance(child, Mapping)
        and isinstance(child.get("measurement_ref"), Mapping)
        and isinstance(child.get("measurement_decision"), Mapping)
        for child in charts
    )


def _merge_measurement_repair_contexts(
    *groups: Sequence[Mapping[str, Any] | None],
) -> list[dict[str, Any]]:
    """Merge repair actions without letting a later action overwrite one."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for group in groups:
        for item in group or ():
            if not isinstance(item, Mapping):
                continue
            context = {str(key): value for key, value in list(item.items())[:24]}
            key = _repair_context_key(context)
            if key in seen:
                continue
            seen.add(key)
            result.append(context)
            if len(result) >= _MAX_PENDING_MEASUREMENT_REPAIRS:
                return result
    return result


def _measurement_repair_contexts_from_sessions(
    sessions: Mapping[str, MeasurementSession],
) -> list[dict[str, Any]]:
    """Project every session's compact evidence decision state in stable order."""
    contexts: list[dict[str, Any]] = []
    for session in sessions.values():
        current = session.current_attempt()
        if current is None:
            continue
        status = current.status
        if status in {"remeasure_required", "partial"} and session.repair_budget_remaining <= 0:
            status = "exhausted"
        focus_suggestion = (
            current.quality.get("focus_suggestion") or current.quality.get("repair_action")
            if isinstance(current.quality, Mapping)
            else None
        )
        if isinstance(focus_suggestion, Mapping):
            focus_suggestion = dict(focus_suggestion)
            focus_suggestion.setdefault("budget_remaining", session.repair_budget_remaining)
            if session.repair_budget_remaining <= 0:
                focus_suggestion["status"] = "exhausted"
        result = {
            "session_id": session.session_id,
            "attachment_id": session.attachment_id,
            "panel_id": session.panel_id,
            "attempt_id": current.attempt_id,
            "status": status,
            "refs": list(current.evidence_refs)[:64],
            "selected_refs": list(session.selected_refs),
            "discarded_refs": list(session.discarded_refs),
            "decision_status": session.decision_status,
            "focus_mode": session.focus_mode,
            "focus_suggestion": focus_suggestion,
            "budget_remaining": session.repair_budget_remaining,
            "warnings": list(current.quality.get("warnings") or [])[:12] if isinstance(current.quality, Mapping) else [],
            "issues": list(current.quality.get("issues") or [])[:8] if isinstance(current.quality, Mapping) else [],
            "next_action": "由主 Agent 选择、舍弃或调用同一测量工具携带 measurement_target 做定向补充",
        }
        contexts.append(result)
    return _merge_measurement_repair_contexts(contexts)


def _measurement_repair_context_from_sessions(
    sessions: Mapping[str, MeasurementSession],
) -> dict[str, Any] | None:
    """Backward-compatible singular projection for callers outside the loop."""
    contexts = _measurement_repair_contexts_from_sessions(sessions)
    return contexts[0] if contexts else None


def _measurement_repair_message(contexts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a compatibility continuation message for legacy callers."""
    payload = {"measurement_evidence": [dict(item) for item in contexts[:_MAX_PENDING_MEASUREMENT_REPAIRS]]}
    return {
        "role": "user",
        "content": (
            "当前测量结果需要主 Agent 结合 evidence.refs 做选择；如需补充，只能在同一 attachment/panel/session 内使用有界 measurement_target。"
            "不要猜测缺失数值，也不要使用未接受 attempt：\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        ),
    }


def _repair_target_context(
    target: object,
    sessions: Mapping[str, MeasurementSession],
    *,
    source_attachment_id: str | None,
    source_panel_id: str | None,
    source_tool: str,
    parent_attempt_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate a model target before an authorized sensor is dispatched."""
    if not isinstance(target, Mapping):
        return None, {
            "status": "rejected",
            "code": "measurement_target_invalid",
            "location": "measurement_target",
            "message": "measurement_target must be an object",
            "next_action": "重新读取当前 attempt 的 evidence.refs，再决定是否发起定向补充",
        }
    if not source_attachment_id:
        return None, {
            "status": "rejected",
            "code": "measurement_source_mismatch",
            "location": "measurement_target",
            "message": "targeted remeasurement requires the current attachment",
            "next_action": "恢复当前来源后再发起定向重测",
        }
    requested_attachment = target.get("attachment_id") or target.get("source_attachment_id")
    if requested_attachment is not None and str(requested_attachment) != source_attachment_id:
        return None, {
            "status": "rejected",
            "code": "measurement_source_mismatch",
            "location": "measurement_target.attachment_id",
            "message": "measurement target does not belong to the current attachment",
            "next_action": "只使用当前 measurement.evidence.refs，不要提交其他附件的 target",
        }
    requested_panel = target.get("panel_id") or target.get("panelId")
    if requested_panel is not None and source_panel_id and str(requested_panel) != source_panel_id:
        return None, {
            "status": "rejected",
            "code": "measurement_panel_mismatch",
            "location": "measurement_target.panel_id",
            "message": "measurement target does not belong to the current panel",
            "next_action": "只使用当前 panel 的 evidence.refs 或区域",
        }
    session = next(
        (
            item
            for item in reversed(list(sessions.values()))
            if item.attachment_id == source_attachment_id and item.panel_id == source_panel_id
        ),
        None,
    )
    if session is None:
        return None, {
            "status": "rejected",
            "code": "measurement_session_not_found",
            "location": "measurement_target",
            "message": "targeted remeasurement has no current measurement session",
            "next_action": "先读取当前 panel 的完整测量结果，再根据 evidence.refs 决定补充区域",
        }
    normalized, error = session.validate_repair_target(
        target,
        tool=source_tool,
        parent_attempt_id=parent_attempt_id,
    )
    if error is not None:
        return None, error
    if normalized is not None:
        normalized["panel_id"] = source_panel_id
        normalized["attachment_id"] = source_attachment_id
        normalized["target_fingerprint"] = measurement_target_fingerprint(normalized, tool=source_tool)
    return normalized, None


def _attach_visual_observation_refs(
    observation: DispatchedObservation,
    references: Sequence[dict[str, Any]],
) -> DispatchedObservation:
    """Attach managed visual-resource refs to decomposition crop records."""
    if not references or not observation.images:
        return observation
    try:
        payload = json.loads(observation.content)
    except (TypeError, json.JSONDecodeError):
        return observation
    if not isinstance(payload, dict):
        return observation
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("panels"), list):
        return observation
    by_key = {
        str(reference.get("resourceKey")): reference
        for reference in references
        if isinstance(reference, dict) and isinstance(reference.get("resourceKey"), str)
    }
    ordered_refs = [reference for reference in references if isinstance(reference, dict)]
    for image_index, image in enumerate(observation.images):
        metadata = image.metadata if hasattr(image.metadata, "get") else {}
        panel_id = metadata.get("panel_id") if isinstance(metadata, dict) else None
        resource_key = metadata.get("resource_key") if isinstance(metadata, dict) else None
        if not isinstance(panel_id, str):
            continue
        panel = next(
            (item for item in data["panels"] if isinstance(item, dict) and item.get("id") == panel_id),
            None,
        )
        if panel is None or not isinstance(panel.get("crop"), dict):
            continue
        reference = by_key.get(resource_key) if isinstance(resource_key, str) else None
        if reference is None and len(ordered_refs) == len(observation.images):
            reference = ordered_refs[image_index]
        crop = dict(panel["crop"])
        crop["resource_ref"] = dict(reference) if isinstance(reference, dict) else None
        crop["status"] = "persisted" if reference is not None else "unavailable"
        panel["crop"] = crop
        layout_context = panel.get("layout_context")
        if isinstance(layout_context, dict):
            panel_context = dict(layout_context.get("panel") or {})
            panel_context["crop_ref"] = crop["resource_ref"]
            layout_context["panel"] = panel_context
    payload["data"] = data
    return DispatchedObservation(
        content=json.dumps(payload, ensure_ascii=False),
        images=observation.images,
    )


def _artifact_records_from_observation(
    tool_name: str,
    call_id: str,
    content: str,
    source_attachment_ids: Sequence[str],
    references: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Create a small attributable index while retaining the native result."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    warnings = payload.get("warnings", [])
    if isinstance(data, dict) and isinstance(data.get("warnings"), list):
        warnings = data.get("warnings")
    warnings = [str(item)[:240] for item in warnings[:12]] if isinstance(warnings, list) else []
    panel_ids = []
    panels = data.get("panels") if isinstance(data, dict) else None
    if isinstance(panels, list):
        panel_ids = [str(item.get("id"))[:96] for item in panels if isinstance(item, dict) and item.get("id")]
    measurement = data.get("measurement") if isinstance(data, dict) else None
    status = "failed" if payload.get("error") else "observed"
    if isinstance(measurement, dict):
        status = str(measurement.get("status") or status)[:64]
        reference = measurement.get("reference")
        if isinstance(reference, dict) and isinstance(reference.get("panel_id"), str):
            panel_ids = [reference["panel_id"]]
    measurement_quality = measurement.get("quality") if isinstance(measurement, dict) else None
    measurement_issues = measurement_quality.get("issues", []) if isinstance(measurement_quality, dict) else []
    measurement_evidence = measurement.get("evidence") if isinstance(measurement, dict) and isinstance(measurement.get("evidence"), dict) else {}
    measurement_decision = measurement.get("decision") if isinstance(measurement, dict) and isinstance(measurement.get("decision"), dict) else {}
    records: list[dict[str, Any]] = [
        {
            "artifact_id": f"observation:{call_id}"[:128],
            "kind": "observation",
            "status": status,
            "source_attachment_ids": list(source_attachment_ids),
            "panel_ids": panel_ids,
            "lineage": [tool_name],
            "confidence": data.get("confidence") if isinstance(data, dict) else None,
            "warnings": warnings,
            "resource_refs": list(references),
        }
    ]
    if isinstance(measurement, dict):
        records[0].update(
            {
                "measurement_status": status,
                "measurement_reference": dict(measurement.get("reference") or {}) if isinstance(measurement.get("reference"), dict) else None,
                "measurement_issues": [item for item in measurement_issues[:8] if isinstance(item, dict)],
                "measurement_evidence_refs": list(measurement_evidence.get("refs") or [])[:64] if isinstance(measurement_evidence.get("refs"), list) else [],
                "measurement_selected_refs": list(measurement_decision.get("selected_refs") or [])[:64] if isinstance(measurement_decision.get("selected_refs"), list) else [],
                "measurement_discarded_refs": list(measurement_decision.get("discarded_refs") or [])[:64] if isinstance(measurement_decision.get("discarded_refs"), list) else [],
                "measurement_decision_status": str(measurement_decision.get("status") or "pending")[:32],
                "measurement_focus": dict(measurement_evidence.get("focus") or {}) if isinstance(measurement_evidence.get("focus"), dict) else None,
            }
        )
    if tool_name == "assemble_spec" and not payload.get("error"):
        assembled_kind = data.get("kind") if isinstance(data, dict) else None
        if assembled_kind == "chart_figure":
            records.append(
                {
                    "artifact_id": f"figure:{data.get('figure_id') or call_id}"[:128],
                    "kind": "ChartFigure",
                    "status": "validated",
                    "source_attachment_ids": [data.get("source", {}).get("attachment_id")] if isinstance(data.get("source"), dict) else list(source_attachment_ids),
                    "panel_ids": [data.get("source", {}).get("panel_id")] if isinstance(data.get("source"), dict) else panel_ids,
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "provenance": data.get("provenance"),
                    "coverage": data.get("coverage"),
                    "child_chart_ids": [item.get("chart_id") for item in data.get("charts", []) if isinstance(item, dict)],
                }
            )
        elif assembled_kind == "chart_spec_collection":
            records.append(
                {
                    "artifact_id": f"chartspec-collection:{data.get('collection_id') or call_id}"[:128],
                    "kind": "ChartSpecCollection",
                    "status": "validated",
                    "source_attachment_ids": list(source_attachment_ids),
                    "panel_ids": panel_ids,
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "provenance": data.get("provenance"),
                    "figure_count": len(data.get("figures", [])) if isinstance(data.get("figures"), list) else 0,
                }
            )
        else:
            records.append(
                {
                    "artifact_id": f"chartspec:{call_id}"[:128],
                    "kind": "ChartSpec",
                    "status": "validated",
                    "source_attachment_ids": list(source_attachment_ids),
                    "panel_ids": panel_ids,
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "provenance": data.get("provenance"),
                }
            )
    for item in panels or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        crop = item.get("crop") if isinstance(item.get("crop"), dict) else {}
        crop_refs = [crop.get("resource_ref")] if isinstance(crop.get("resource_ref"), dict) else []
        records.append(
            {
                "artifact_id": f"panel:{item['id']}"[:128],
                "kind": "panel",
                "status": item.get("status", "observed"),
                "source_attachment_ids": list(source_attachment_ids),
                "panel_ids": [str(item["id"])],
                "lineage": [f"observation:{call_id}"],
                "confidence": item.get("confidence"),
                "warnings": item.get("warnings", []),
                "resource_refs": crop_refs or list(references),
            }
        )
    review_items = data.get("review") if isinstance(data, dict) else None
    if not isinstance(review_items, list) and isinstance(data, dict) and isinstance(data.get("candidate"), dict):
        review_items = [data["candidate"]]
    if isinstance(review_items, list):
        for index, item in enumerate(review_items[:16], start=1):
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidateId") or f"{call_id}:{index}")[:128]
            candidate_status = str(item.get("candidateStatus") or item.get("status") or "candidate")[:64]
            records.append(
                {
                    "artifact_id": f"candidate:{candidate_id}"[:128],
                    "kind": "candidate",
                    "status": candidate_status,
                    "source_attachment_ids": item.get("sourceAttachmentIds", source_attachment_ids),
                    "panel_ids": item.get("panelIds", panel_ids),
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "resource_refs": list(references),
                }
            )
            review = item.get("review")
            if isinstance(review, dict):
                records.append(
                    {
                        "artifact_id": f"review:{item.get('reviewId') or candidate_id}"[:128],
                        "kind": "review",
                        "status": review.get("status", item.get("reviewStatus", "unknown")),
                        "source_attachment_ids": item.get("sourceAttachmentIds", source_attachment_ids),
                        "panel_ids": item.get("panelIds", panel_ids),
                        "lineage": [f"candidate:{candidate_id}"],
                        "confidence": review.get("confidence"),
                        "warnings": [str(issue.get("message")) for issue in review.get("issues", []) if isinstance(issue, dict)],
                    }
                )
    return records[:48]


def _measurement_trace_fields(content: str) -> dict[str, Any]:
    """Project only bounded measurement lifecycle fields into trace events."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {}
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    measurement = data.get("measurement") if isinstance(data, dict) else None
    if not isinstance(measurement, dict):
        return {}
    reference = measurement.get("reference")
    quality = measurement.get("quality")
    evidence = measurement.get("evidence") if isinstance(measurement.get("evidence"), dict) else {}
    decision = measurement.get("decision") if isinstance(measurement.get("decision"), dict) else {}
    result: dict[str, Any] = {
        "measurement_status": str(measurement.get("status") or "unknown")[:48],
        "measurement_reference": {
            key: reference.get(key)
            for key in ("session_id", "attempt_id", "attachment_id", "panel_id")
            if isinstance(reference, dict) and reference.get(key) is not None
        },
    }
    if isinstance(evidence, dict):
        result["measurement_evidence_refs"] = list(evidence.get("refs") or [])[:64]
        focus = evidence.get("focus")
        if isinstance(focus, Mapping):
            result["measurement_focus"] = {
                key: focus.get(key)
                for key in ("requested", "applied", "status", "mode", "target_refs", "search_scope")
                if focus.get(key) is not None
            }
    if isinstance(decision, dict):
        result["measurement_decision_status"] = str(decision.get("status") or "pending")[:32]
        result["measurement_selected_refs"] = list(decision.get("selected_refs") or [])[:64]
        result["measurement_discarded_refs"] = list(decision.get("discarded_refs") or [])[:64]
    if isinstance(quality, dict):
        result["measurement_issue_count"] = min(
            16,
            len(quality.get("issues", [])) if isinstance(quality.get("issues"), list) else 0,
        )
        result["measurement_blocking"] = bool(quality.get("blocking"))
        repair_action = quality.get("repair_action")
        if isinstance(repair_action, Mapping):
            result["measurement_focus_suggestion"] = dict(repair_action)
            result["measurement_repair_action"] = {
                key: repair_action.get(key)
                for key in ("action", "status", "tool", "attachment_id", "panel_id", "parent_attempt_id", "fields", "target", "next_action")
                if repair_action.get(key) is not None
            }
            result["measurement_repair_status"] = str(repair_action.get("status") or "available")[:32]
    target = measurement.get("target")
    if isinstance(target, Mapping):
        result["measurement_target"] = {
            key: target.get(key)
            for key in (
                "target_id",
                "panel_id",
                "parent_attempt_id",
                "region_kind",
                "fields",
                "bbox_source_px",
                "source_image_size",
                "bbox_px",
                "local_image_size",
                "clipped",
            )
            if target.get(key) is not None
        }
    return result


def _trace_result_summary(content: str) -> Any:
    """Keep tool-result traces useful without duplicating the quality envelope.

    The model-facing observation keeps the complete measurement envelope.  The
    Gateway trace already projects its bounded lifecycle fields at the event
    level, so omitting the duplicate envelope from ``result`` leaves room for
    the structured sensor data (including panel scope) to remain inspectable.
    """
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return summarize_result(content)
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and "measurement" in data:
            payload = dict(payload)
            payload["data"] = dict(data)
            payload["data"].pop("measurement", None)
        content = json.dumps(payload, ensure_ascii=False)
    return summarize_result(content)


class AgentInterrupted(RuntimeError):
    """Raised when a cooperative run interruption is observed."""


class AgentRecoveryBlocked(RuntimeError):
    """Raised when a continuation reaches an operation with an unknown outcome."""


class Agent:
    """Minimal ReAct agent loop owning its history in memory.

    Args:
        client: ``LLMClient`` used for every model turn.
        registry: ``ToolRegistry`` whose registered tools are exposed to the model.
        system: optional system prompt, kept first in the history.
        max_steps: maximum number of tool-calling turns before stopping.
        **chat_kwargs: forwarded to every ``client.chat(...)`` call (e.g. model,
            reasoning_effort, temperature).
    """

    def __init__(
        self,
        client: LLMClient,
        registry: ToolRegistry,
        *,
        system: Optional[str] = None,
        max_steps: int = 10,
        trace: Optional[TraceSink] = None,
        trace_sink: Optional[TraceSink] = None,
        trace_reasoning: bool = False,
        trace_run_id: Optional[str] = None,
        run_id: Optional[str] = None,
        visual_observation_sink: Optional[VisualObservationSink] = None,
        memory: Optional[AgentMemory] = None,
        attachments: Any = None,
        context_budget: int = 24000,
        review_manager: Optional[ChartReviewManager] = None,
        review_coordinator: Optional[ReviewCoordinator] = None,
        interruption_event: Any = None,
        recovery_context: Optional[dict[str, Any]] = None,
        checkpoint_sink: Optional[Callable[..., bool]] = None,
        operation_begin: Optional[Callable[..., dict[str, Any]]] = None,
        operation_complete: Optional[Callable[..., dict[str, Any] | None]] = None,
        operation_uncertain: Optional[Callable[..., dict[str, Any] | None]] = None,
        execution_gate_sink: Optional[Callable[[Mapping[str, Any]], Any]] = None,
        **chat_kwargs: Any,
    ) -> None:
        self.client = client
        self.registry = registry
        self._system = system
        self.max_steps = max_steps
        self._chat_kwargs = chat_kwargs
        self._trace_sink = trace if trace is not None else trace_sink
        self._trace_reasoning = trace_reasoning
        if run_id is not None and trace_run_id is not None and run_id != trace_run_id:
            raise ValueError("run_id and trace_run_id must identify the same run")
        self._run_id = run_id
        self._trace_run_id = trace_run_id or run_id
        self._visual_observation_sink = visual_observation_sink
        self.memory = memory or InMemoryAgentMemory(context_budget=context_budget)
        self.attachments = attachments
        self._review_manager = review_manager or ChartReviewManager(attachments=attachments)
        self._review_coordinator = review_coordinator or ReviewCoordinator()
        self._measurement_review_adapter = MeasurementReviewAdapter()
        self._generated_chart_review_adapter = GeneratedChartReviewAdapter()
        self._interruption_event = interruption_event
        self._recovery_context = recovery_context
        self._checkpoint_sink = checkpoint_sink
        self._operation_begin = operation_begin
        self._operation_complete = operation_complete
        self._operation_uncertain = operation_uncertain
        self._execution_gate_sink = execution_gate_sink
        self.context_budget = context_budget
        self._messages: List[ChatCompletionMessageParam] = []
        self._current_messages: List[ChatCompletionMessageParam] = []
        if system is not None:
            self._messages.append({"role": "system", "content": system})  # type: ignore[arg-type]

    @property
    def messages(self) -> List[ChatCompletionMessageParam]:
        """Read-only view of the running history (for inspection/tests)."""
        return list(self._messages)

    def reset(self) -> None:
        """Clear history, keeping only the system prompt."""
        self._messages = []
        self._current_messages = []
        reset = getattr(self.memory, "reset", None)
        if callable(reset):
            reset()

    def close(self) -> None:
        """Release retained conversation content, including generated images."""
        self.reset()
        close = getattr(self.memory, "close", None)
        if callable(close):
            close()

    def run(self, user_input: str | list[dict], *, recovery_context: Optional[dict[str, Any]] = None) -> str:
        """Drive one user turn to completion (final answer or budget cap).

        ``user_input`` is a plain string or an OpenAI multimodal content list
        (e.g. from ``build_user_content``); it is appended to history and
        forwarded to the client unchanged.
        """
        if self._interruption_requested():
            raise AgentInterrupted("Agent run was interrupted before it started")
        recovery = recovery_context if recovery_context is not None else self._recovery_context
        run = self.memory.begin_run(self._run_id) if self._run_id is not None else self.memory.begin_run()
        self._messages = []
        self._current_messages = []
        layout_contexts: dict[str, dict[str, Any]] = {}
        artifact_records: list[dict[str, Any]] = []
        checkpoint_references: list[dict[str, Any]] = []
        measurement_sessions: dict[str, MeasurementSession] = {}
        pending_measurement_repairs: list[dict[str, Any]] = []
        if isinstance(recovery, dict):
            loader = getattr(self.memory, "recovery_context", None)
            hydrated = loader(recovery, budget=self.context_budget) if callable(loader) else []
            if hydrated:
                self._current_messages.extend(hydrated)  # type: ignore[arg-type]
            raw_layouts = recovery.get("layoutContexts")
            if isinstance(raw_layouts, dict):
                layout_contexts = {
                    str(key): value for key, value in list(raw_layouts.items())[:_MAX_LAYOUT_CONTEXTS]
                    if isinstance(value, dict)
                }
            raw_artifacts = recovery.get("artifactIndex")
            if isinstance(raw_artifacts, list):
                artifact_records = [
                    item for item in raw_artifacts[:48] if isinstance(item, dict)
                ]
            measurement_sessions = sessions_from_state(recovery.get("measurementSessions"))
            review_state = recovery.get("reviewState") if isinstance(recovery.get("reviewState"), Mapping) else {}
            self._review_coordinator.restore(review_state.get("records", []))
            if isinstance(review_state.get("executionGate"), Mapping):
                self._review_coordinator.restore_gate(run.id, review_state["executionGate"])
            elif isinstance(recovery.get("executionGate"), Mapping):
                self._review_coordinator.restore_gate(run.id, recovery["executionGate"])
            pending_measurement_repairs = _measurement_repair_contexts_from_sessions(measurement_sessions)
            raw_repairs = recovery.get("pendingMeasurementRepairs")
            if isinstance(raw_repairs, list):
                pending_measurement_repairs = _merge_measurement_repair_contexts(
                    pending_measurement_repairs,
                    raw_repairs,
                )
            elif isinstance(recovery.get("pendingMeasurementRepair"), dict):
                pending_measurement_repairs = _merge_measurement_repair_contexts(
                    pending_measurement_repairs,
                    [recovery["pendingMeasurementRepair"]],
                )
        user_message = {"role": "user", "content": user_input}
        self.memory.append(run, "user", {"message": user_message, "text": user_input if isinstance(user_input, str) else "[image attachment turn]"})
        if isinstance(user_input, str):
            run_attachment_ids = tuple(re.findall(r"\batt_[A-Za-z0-9]+\b", user_input))
            for ordinal, attachment_id in enumerate(run_attachment_ids, start=1):
                self.memory.append(run, "attachment", {"attachment_id": attachment_id, "ordinal": ordinal})
                if self.attachments is not None:
                    self.attachments.bind_run(attachment_id, run.id)
        else:
            run_attachment_ids = ()
        self._hydrate_persisted_panel_contexts(layout_contexts, run_attachment_ids)
        selected_panel_id: str | None = None
        current_tool_name: str | None = None
        pending_action = "检查当前请求并选择所需证据"
        if not self._current_messages or self._current_messages[-1].get("role") != "user":
            self._current_messages.append(user_message)  # type: ignore[arg-type]
        tools = registry_tools(self.registry)
        emitter = (
            TraceEmitter(self._trace_sink, run_id=self._trace_run_id or run.id)
            if self._trace_sink is not None
            else None
        )

        pending_recovery_calls = self._recovery_tool_calls(recovery)
        if isinstance(recovery, dict) and recovery.get("nextAction") == "final" and isinstance(recovery.get("pendingAnswer"), str):
            answer = str(recovery["pendingAnswer"])
            self.memory.append(run, "final", {"answer": answer, "recovered": True})
            self.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
            return answer
        for step in range(self.max_steps):
            turn = step + 1
            system_message = None
            prompt_metadata: dict[str, Any] | None = None
            if self._system:
                review_gate = self._review_manager.gate(run.id)
                panel_inventory = panel_inventory_from_layout_contexts(layout_contexts)
                selected_panel = next(
                    (item for item in panel_inventory if item.get("panel_id") == selected_panel_id),
                    None,
                )
                prompt_context = assemble_prompt_context(
                    tools=self.registry.list(),
                    artifacts=artifact_records,
                    runtime_state={
                        "run_id": run.id,
                        "phase": "model",
                        "active_source": run_attachment_ids,
                        "selected_panel": selected_panel,
                        "current_tool": current_tool_name,
                        "pending_action": pending_action,
                        "measurement_evidence": pending_measurement_repairs,
                        "recovery_status": "recovery_context_loaded" if recovery else "none",
                        "retry_count": max(
                            [
                                int(item.get("attempts", 0) or 0)
                                for item in (review_gate.get("failed") or [])
                                if isinstance(item, dict)
                            ]
                            or [0]
                        ),
                        "retry_budget": self.max_steps,
                        "publication_status": "published" if review_gate.get("published") else "not_published",
                        "execution_gate": self._review_coordinator.gate(run.id).to_dict(),
                    },
                    panel_inventory=panel_inventory,
                    review_gate=review_gate,
                )
                prompt_metadata = prompt_context["metadata"]
                dynamic = "\n\n".join(
                    (prompt_context["tools"], prompt_context["runtime"], prompt_context["artifacts"])
                )
                system_message = {"role": "system", "content": f"{self._system}\n\n{dynamic}"}
            self._messages = self.memory.context(run, system_message, self.context_budget, current_messages=self._current_messages)
            if emitter is not None and not isinstance(self.client, LLMClient):
                emitter.emit(
                    "model_started",
                    turn=turn,
                    model=self._chat_kwargs.get("model"),
                    message_count=len(self._messages),
                    tool_count=len(tools),
                    prompt_bundle=prompt_metadata,
                )
            chat_kwargs = dict(self._chat_kwargs)
            if emitter is not None and isinstance(self.client, LLMClient):
                chat_kwargs.update(
                    trace_sink=emitter,
                    trace_run_id=emitter.run_id,
                    trace_turn=turn,
                )
            self._raise_if_interrupted(run)
            operation_id = f"model:{turn}"
            if pending_recovery_calls:
                result = NormalizedResult(tool_calls=pending_recovery_calls, finish_reason="tool_calls")
                pending_recovery_calls = []
            else:
                self._begin_work_unit(operation_id, "model")
                try:
                    result = self.client.chat(self._messages, tools=tools, **chat_kwargs)
                except Exception as exc:
                    self._uncertain_work_unit(operation_id, "model_response_outcome_uncertain")
                    self.memory.append(run, "error", {"error_code": "agent_call_failed", "error_type": type(exc).__name__[:64]})
                    self.memory.finish(run, RunStatus.FAILED, "error")
                    if emitter is not None and not isinstance(self.client, LLMClient):
                        emitter.emit(
                            "model_completed",
                            turn=turn,
                            status="error",
                            error_code="agent_call_failed",
                            error_type=type(exc).__name__[:64],
                        )
                    raise
                self._complete_work_unit(operation_id, "model", self._model_result_payload(result))

            if emitter is not None and not isinstance(self.client, LLMClient):
                emitter.emit(
                    "model_completed",
                    turn=turn,
                    status="ok",
                    content_length=len(result.content),
                    reasoning_available=bool(result.reasoning),
                    tool_calls=len(result.tool_calls),
                    finish_reason=result.finish_reason,
                )
            if emitter is not None and self._trace_reasoning:
                emitter.emit(
                    "reasoning",
                    turn=turn,
                    status="available" if result.reasoning else "unavailable",
                    reasoning=bounded_reasoning(result.reasoning),
                )

            if not result.tool_calls:
                self._raise_if_interrupted(run)
                assistant_message = assistant_entry(result)
                gate = self._review_manager.gate(run.id)
                if gate["pending"]:
                    # Preserve the attempted answer as model context, but do
                    # not turn it into a terminal record or trace event.
                    self._current_messages.append(assistant_message)
                    self._messages.append(assistant_message)
                    self.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {"role": "user", "content": review_gate_context(gate)}
                    self._current_messages.append(gate_message)  # type: ignore[arg-type]
                    self._messages.append(gate_message)  # type: ignore[arg-type]
                    self.memory.append(run, "review_gate", {"state": gate})
                    if emitter is not None:
                        emitter.emit("chart_review_required", turn=turn, state=gate)
                    continue
                if gate["failed"]:
                    self._current_messages.append(assistant_message)
                    self._messages.append(assistant_message)
                    self.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {"role": "user", "content": review_gate_context(gate)}
                    self.memory.append(run, "review_gate", {"state": gate})
                    if gate.get("retryable") and turn < self.max_steps:
                        self._current_messages.append(gate_message)  # type: ignore[arg-type]
                        self._messages.append(gate_message)  # type: ignore[arg-type]
                        self._checkpoint(
                            run,
                            phase="review",
                            next_action=str((gate.get("recoveryActions") or [{}])[0].get("action", "correct_chart_spec")),
                            state=self._checkpoint_state(
                                user_input,
                                self._current_messages,
                                layout_contexts,
                                run_attachment_ids,
                                turn,
                                pending_tool_calls=(),
                                visual_references=checkpoint_references,
                                artifact_records=artifact_records,
                                measurement_sessions=measurement_sessions,
                                pending_measurement_repairs=pending_measurement_repairs,
                            ),
                        )
                        if emitter is not None:
                            emitter.emit("chart_review_repair_required", turn=turn, state=gate)
                        continue
                    if emitter is not None:
                        emitter.emit("generated_chart_rejected", turn=turn, state=gate, reason="review_failed")
                    self.memory.append(run, "terminal", {"answer": _REVIEW_FAILED_MSG, "review_gate": gate})
                    self.memory.finish(run, RunStatus.FAILED, "review_failed")
                    return _REVIEW_FAILED_MSG
                shared_gate = self._review_coordinator.gate(run.id)
                if shared_gate.blocking:
                    self._current_messages.append(assistant_message)
                    self._messages.append(assistant_message)
                    self.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {
                        "role": "user",
                        "content": json.dumps(
                            {"type": "execution_review_gate", "execution_gate": shared_gate.to_dict()},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                    self._current_messages.append(gate_message)  # type: ignore[arg-type]
                    self._messages.append(gate_message)  # type: ignore[arg-type]
                    self.memory.append(run, "review_gate", {"state": shared_gate.to_dict()})
                    if emitter is not None:
                        emitter.emit("review_gate_required", turn=turn, execution_gate=shared_gate.to_dict())
                    if shared_gate.state.value in {"failed", "exhausted"} or turn >= self.max_steps:
                        self.memory.append(
                            run,
                            "terminal",
                            {"answer": _REVIEW_FAILED_MSG, "execution_gate": shared_gate.to_dict()},
                        )
                        self.memory.finish(run, RunStatus.FAILED, "review_failed")
                        return _REVIEW_FAILED_MSG
                    self._checkpoint(
                        run,
                        phase="review",
                        next_action=shared_gate.next_action or "repair_review_gate",
                        state=self._checkpoint_state(
                            user_input,
                            self._current_messages,
                            layout_contexts,
                            run_attachment_ids,
                            turn,
                            pending_tool_calls=(),
                            visual_references=checkpoint_references,
                            artifact_records=artifact_records,
                            measurement_sessions=measurement_sessions,
                            pending_measurement_repairs=pending_measurement_repairs,
                        ),
                    )
                    continue
                self._current_messages.append(assistant_message)
                self._messages.append(assistant_message)
                self.memory.append(run, "assistant", {"message": assistant_message})
                self._checkpoint(
                    run,
                    phase="model",
                    next_action="final",
                    state=self._checkpoint_state(
                        user_input,
                        self._current_messages,
                        layout_contexts,
                        run_attachment_ids,
                        turn,
                        pending_tool_calls=(),
                        pending_answer=result.content,
                        visual_references=checkpoint_references,
                        artifact_records=artifact_records,
                        measurement_sessions=measurement_sessions,
                        pending_measurement_repairs=pending_measurement_repairs,
                    ),
                )
                if isinstance(recovery, dict) and recovery.get("nextAction") == "final" and isinstance(recovery.get("pendingAnswer"), str):
                    answer = str(recovery["pendingAnswer"])
                    self.memory.append(run, "final", {"answer": answer, "recovered": True})
                    self.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
                    return answer
                self.memory.append(run, "final", {"answer": result.content, "finish_reason": result.finish_reason})
                self.memory.finish(run, RunStatus.COMPLETED, "final")
                if emitter is not None:
                    emitter.emit(
                        "final_answer",
                        turn=turn,
                        answer=result.content,
                        finish_reason=result.finish_reason,
                    )
                return result.content

            assistant_message = assistant_entry(
                result,
                include_reasoning=(
                    getattr(getattr(self.client, "config", None), "provider", None) == "deepseek"
                    and getattr(getattr(self.client, "config", None), "enable_thinking", False)
                    and bool(result.reasoning)
                ),
            )
            # ``assistant_message`` is the model-facing message. The memory
            # record stays sanitized and content/tool-call-only so provider
            # reasoning cannot leak into transcripts or ordinary records.
            assistant_record = assistant_entry(result)
            self._current_messages.append(assistant_message)
            self._messages.append(assistant_message)
            self.memory.append(run, "assistant", {"message": assistant_record})
            self._checkpoint(
                run,
                phase="model",
                next_action="tool",
                state=self._checkpoint_state(
                    user_input,
                    self._current_messages,
                    layout_contexts,
                    run_attachment_ids,
                    turn,
                    pending_tool_calls=result.tool_calls,
                    visual_references=checkpoint_references,
                    artifact_records=artifact_records,
                    measurement_sessions=measurement_sessions,
                    pending_measurement_repairs=pending_measurement_repairs,
                ),
            )
            visual_evidence: list[ToolVisualEvidence] = []
            for call_index, call in enumerate(result.tool_calls):
                self._raise_if_interrupted(run)
                current_tool_name = call.name
                pending_action = f"执行 {call.name} 并把结果作为当前 run 的证据"
                try:
                    call_arguments = json.loads(call.arguments) if call.arguments.strip() else {}
                except (TypeError, json.JSONDecodeError):
                    call_arguments = {}
                if not self._review_gate_allows_call(
                    run.id,
                    call.name,
                    call_arguments if isinstance(call_arguments, Mapping) else {},
                ):
                    active_gate = self._review_coordinator.gate(run.id)
                    self._skip_tool_calls(
                        run,
                        result.tool_calls[call_index:],
                        gate=active_gate,
                        emitter=emitter,
                        turn=turn,
                    )
                    self._checkpoint(
                        run,
                        phase="review",
                        next_action="model",
                        state=self._checkpoint_state(
                            user_input,
                            self._current_messages,
                            layout_contexts,
                            run_attachment_ids,
                            turn,
                            pending_tool_calls=(),
                            visual_references=checkpoint_references,
                            artifact_records=artifact_records,
                            measurement_sessions=measurement_sessions,
                            pending_measurement_repairs=pending_measurement_repairs,
                        ),
                    )
                    break
                if isinstance(call_arguments, dict) and isinstance(call_arguments.get("panel_id"), str):
                    selected_panel_id = call_arguments["panel_id"]
                operation_kind = "render" if call.name in _RENDER_TOOL_NAMES else "tool"
                operation_id = f"{operation_kind}:{turn}:{call.id}"
                operation = self._begin_work_unit(operation_id, operation_kind)
                if isinstance(recovery, dict) and operation.get("state") in {"in_flight", "uncertain"}:
                    self._uncertain_work_unit(operation_id, "operation_outcome_uncertain")
                    raise AgentRecoveryBlocked("operation outcome is uncertain")
                if emitter is not None:
                    presentation = get_tool_presentation(call.name, tool=self.registry.get(call.name))
                    emitter.emit(
                        "tool_call",
                        turn=turn,
                        tool_name=call.name,
                        tool_display_name=presentation.display_name,
                        tool_label=presentation.label,
                        call_id=call.id,
                        arguments=summarize_arguments(call.arguments),
                    )
                source_panel_id = call_arguments.get("panel_id") if isinstance(call_arguments.get("panel_id"), str) else None
                source_attachment_id = call_arguments.get("attachment_id") if isinstance(call_arguments.get("attachment_id"), str) else None
                raw_measurement_target = call_arguments.get("measurement_target") if isinstance(call_arguments, dict) else None
                if source_panel_id is None and isinstance(raw_measurement_target, Mapping):
                    candidate_panel = raw_measurement_target.get("panel_id")
                    if isinstance(candidate_panel, str) and candidate_panel.strip():
                        source_panel_id = candidate_panel
                parent_attempt_id = None
                if call.name in MEASUREMENT_TOOLS:
                    for session in reversed(list(measurement_sessions.values())):
                        if session.attachment_id == source_attachment_id and session.panel_id in {source_panel_id, None, "__source__"}:
                            parent_attempt_id = session.current_attempt_id
                            break
                prepared_target: dict[str, Any] | None = None
                repair_error: dict[str, Any] | None = None
                if call.name in MEASUREMENT_TOOLS and raw_measurement_target is not None:
                    prepared_target, repair_error = _repair_target_context(
                        raw_measurement_target,
                        measurement_sessions,
                        source_attachment_id=source_attachment_id,
                        source_panel_id=source_panel_id,
                        source_tool=call.name,
                        parent_attempt_id=parent_attempt_id,
                    )
                    if repair_error is None and prepared_target is not None:
                        call_arguments["measurement_target"] = prepared_target
                dispatch_arguments = self._layout_arguments(
                    call.name,
                    json.dumps(call_arguments, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(call_arguments, dict)
                    else call.arguments,
                    layout_contexts,
                )
                routing_error = self._panel_routing_error(
                    call.name,
                    dispatch_arguments,
                    layout_contexts,
                )
                if repair_error is not None:
                    observation = DispatchedObservation(
                        json.dumps(
                            {
                                "error": "measurement repair rejected",
                                "measurement_repair": repair_error,
                            },
                            ensure_ascii=False,
                        )
                    )
                elif routing_error is not None:
                    observation = DispatchedObservation(
                        json.dumps({"error": routing_error}, ensure_ascii=False)
                    )
                else:
                    observation = dispatch_observation(
                        self.registry,
                        call.name,
                        dispatch_arguments,
                        source_run_id=run.id,
                        source_panel_id=source_panel_id,
                        source_parent_attempt_id=parent_attempt_id,
                        source_measurement_target=prepared_target,
                        measurement_context=measurement_sessions if call.name == "assemble_spec" else None,
                    )
                self._raise_if_interrupted(run)
                if call.name in {_LAYOUT_TOOL_NAME, _DECOMPOSE_TOOL_NAME}:
                    self._remember_layout_context(
                        observation.content,
                        call.arguments,
                        layout_contexts,
                    )
                review_operation_id = None
                if any(
                    isinstance(getattr(image, "metadata", None), dict)
                    and image.metadata.get("kind") == "generated_chart"
                    for image in observation.images
                ):
                    review_operation_id = f"review:{turn}:{call.id}"
                    self._begin_work_unit(review_operation_id, "review")
                observation = self._apply_generation_review(
                    observation,
                    run=run,
                    run_id=run.id,
                    call_id=call.id,
                    arguments=call.arguments,
                    source_attachment_ids=run_attachment_ids,
                    emitter=emitter,
                    turn=turn,
                )
                self._raise_if_interrupted(run)
                if review_operation_id:
                    self._complete_work_unit(review_operation_id, "review", {"status": "completed"})
                observation_refs: Sequence[dict[str, Any]] = ()
                sink_images = observation.images
                if self._visual_observation_sink is not None and sink_images:
                    self._raise_if_interrupted(run)
                    try:
                        observation_refs = self._visual_observation_sink(
                            call.name,
                            call.id,
                            sink_images,
                        )
                    except Exception:  # noqa: BLE001 - observation diagnostics cannot abort the Agent
                        observation_refs = ()
                observation = _attach_visual_observation_refs(observation, observation_refs)
                if call.name == "assemble_spec":
                    self._release_measurement_gate_from_assembly(
                        run,
                        observation.content,
                        emitter=emitter,
                        turn=turn,
                        call_id=call.id,
                    )
                if call.name in MEASUREMENT_TOOLS:
                    if prepared_target is not None and emitter is not None:
                        emitter.emit(
                            "measurement_focus_requested",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            target={
                                key: prepared_target.get(key)
                                for key in (
                                    "target_id",
                                    "target_fingerprint",
                                    "panel_id",
                                    "parent_attempt_id",
                                    "resolved_refs",
                                    "mode",
                                    "fields",
                                    "region_kind",
                                )
                                if prepared_target.get(key) is not None
                            },
                        )
                    try:
                        measurement_payload = json.loads(observation.content)
                        measurement_data = measurement_payload.get("data") if isinstance(measurement_payload, dict) else None
                        if isinstance(measurement_data, dict):
                            measurement_session = register_measurement(measurement_sessions, measurement_data)
                            measurement_review = self._measurement_review_adapter.submit(
                                self._review_coordinator,
                                run_id=run.id,
                                tool_name=call.name,
                                payload=measurement_payload,
                                session=measurement_session,
                            )
                            if measurement_review is not None:
                                self._record_shared_review(
                                    run,
                                    measurement_review,
                                    emitter=emitter,
                                    turn=turn,
                                    tool_name=call.name,
                                    call_id=call.id,
                                )
                            pending_measurement_repairs = _measurement_repair_contexts_from_sessions(
                                measurement_sessions
                            )
                    except (TypeError, json.JSONDecodeError):
                        pass
                repair_context = _measurement_repair_context_from_content(observation.content)
                if repair_context is not None:
                    pending_measurement_repairs = _merge_measurement_repair_contexts(
                        pending_measurement_repairs,
                        [repair_context],
                    )
                    pending_action = str(repair_context.get("next_action") or "等待主 Agent 证据决策")[:240]
                    self.memory.append(run, "measurement_decision", {"state": repair_context})
                    if emitter is not None:
                        emitter.emit(
                            "measurement_decision_required",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            decision=repair_context,
                        )
                        focus = repair_context.get("focus")
                        if isinstance(focus, Mapping) and focus.get("requested"):
                            emitter.emit(
                                "measurement_focus_applied"
                                if focus.get("applied") and focus.get("status") == "applied"
                                else "measurement_focus_failed",
                                turn=turn,
                                tool_name=call.name,
                                call_id=call.id,
                                focus={
                                    key: focus.get(key)
                                    for key in ("requested", "applied", "status", "mode", "target_refs", "search_scope", "region_px")
                                    if focus.get(key) is not None
                                },
                            )
                elif call.name in MEASUREMENT_TOOLS:
                    pending_measurement_repairs = _measurement_repair_contexts_from_sessions(
                        measurement_sessions
                    )
                artifact_records.extend(
                    _artifact_records_from_observation(
                        call.name,
                        call.id,
                        observation.content,
                        run_attachment_ids,
                        observation_refs,
                    )
                )
                artifact_records = artifact_records[-48:]
                tool_message = tool_entry(call, observation.content)
                self._current_messages.append(tool_message)
                self._messages.append(tool_message)
                self.memory.append(
                    run,
                    "tool",
                    {
                        "message": tool_message,
                        "tool_name": call.name,
                        "status": observation_status(observation.content),
                        **_measurement_trace_fields(observation.content),
                    },
                )
                checkpoint_references.extend(
                    item for item in observation_refs if isinstance(item, dict)
                )
                self._complete_work_unit(
                    operation_id,
                    operation_kind,
                    {"status": observation_status(observation.content)},
                    {"observations": list(observation_refs)},
                )
                remaining_calls = result.tool_calls[call_index + 1:]
                shared_gate = self._review_coordinator.gate(run.id)
                stop_batch = shared_gate.blocking
                if stop_batch and remaining_calls:
                    self._skip_tool_calls(
                        run,
                        remaining_calls,
                        gate=shared_gate,
                        emitter=emitter,
                        turn=turn,
                    )
                    remaining_calls = ()
                self._checkpoint(
                    run,
                    phase="tool",
                    next_action="tool" if remaining_calls else "model",
                    state=self._checkpoint_state(
                        user_input,
                        self._current_messages,
                        layout_contexts,
                        run_attachment_ids,
                        turn,
                        pending_tool_calls=remaining_calls,
                        visual_references=checkpoint_references,
                        artifact_records=artifact_records,
                        measurement_sessions=measurement_sessions,
                        pending_measurement_repairs=pending_measurement_repairs,
                    ),
                )
                pending_action = "处理工具观察并决定下一步证据或 ChartSpec 操作"
                if emitter is not None:
                    self._raise_if_interrupted(run)
                    image_payload = {"images": summarize_images(observation.images)}
                    if observation_refs:
                        generated_refs = [
                            reference
                            for reference in observation_refs
                            if reference.get("artifactKind") == "generated_chart"
                        ]
                        regular_refs = [
                            reference
                            for reference in observation_refs
                            if reference.get("artifactKind") != "generated_chart"
                        ]
                        if regular_refs:
                            image_payload["observations"] = regular_refs
                        if generated_refs:
                            image_payload["artifacts"] = generated_refs
                    emitter.emit(
                        "tool_result",
                        turn=turn,
                        tool_name=call.name,
                        tool_display_name=presentation.display_name,
                        tool_label=presentation.label,
                        call_id=call.id,
                        status=observation_status(observation.content),
                        tool_status=observation_status(observation.content),
                        result=_trace_result_summary(observation.content),
                        image_count=len(observation.images),
                        **_measurement_trace_fields(observation.content),
                    )
                    review_items = self._review_items(observation.content)
                    for item in review_items:
                        review_status = item.get("reviewStatus")
                        candidate_status = item.get("candidateStatus")
                        publication_status = item.get("publicationStatus")
                        common_review_fields = {
                            "tool_name": call.name,
                            "tool_display_name": presentation.display_name,
                            "tool_label": presentation.label,
                            "call_id": call.id,
                            "candidate_id": item.get("candidateId"),
                            "review_id": item.get("reviewId"),
                            "candidate_status": candidate_status,
                            "review_status": review_status,
                            "publication_status": publication_status,
                            "review_mode": item.get("reviewMode"),
                            "internal_review": item.get("reviewMode") == "vlm",
                        }
                        if candidate_status == "review_pending" and review_status in {"pending", "requires_model_decision"}:
                            emitter.emit(
                                "chart_review_started",
                                turn=turn,
                                **common_review_fields,
                            )
                        if item.get("reviewStatus") == "completed":
                            emitter.emit(
                                "chart_review_completed",
                                turn=turn,
                                **common_review_fields,
                            )
                            if item.get("publicationStatus") in {"published", "published_with_warning"}:
                                emitter.emit(
                                    "generated_chart_published",
                                    turn=turn,
                                    **common_review_fields,
                                )
                            if item.get("publicationStatus") == "rejected":
                                emitter.emit(
                                    "generated_chart_rejected",
                                    turn=turn,
                                    **common_review_fields,
                                    reason="review_failed",
                                )
                    if observation.images:
                        emitter.emit(
                            "generated_chart" if any(
                                image.metadata.get("kind") == "generated_chart"
                                for image in observation.images
                                if hasattr(image.metadata, "get")
                            ) else "visual_observation",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            **image_payload,
                        )
                visual_evidence.extend(
                    ToolVisualEvidence(call.name, call.id, generated)
                    for generated in observation.images
                )
                if stop_batch:
                    break
            if visual_evidence:
                self._raise_if_interrupted(run)
                visual_message = {
                    "role": "user",
                    "content": build_tool_observation_content(visual_evidence),
                }
                self._current_messages.append(visual_message)  # type: ignore[arg-type]
                self._messages.append(visual_message)  # type: ignore[arg-type]
                self.memory.append(
                    run,
                    "visual_metadata",
                    {
                        "tool_count": len(visual_evidence),
                        "tools": [item.tool_name for item in visual_evidence],
                        "call_ids": [item.tool_call_id for item in visual_evidence],
                        "image_count": len(visual_evidence),
                    },
                )
            pending_measurement_repairs = _merge_measurement_repair_contexts(
                _measurement_repair_contexts_from_sessions(measurement_sessions),
            )
            self._checkpoint(
                run,
                phase="tool",
                next_action="model",
                state=self._checkpoint_state(
                    user_input,
                    self._current_messages,
                    layout_contexts,
                    run_attachment_ids,
                    turn,
                    pending_tool_calls=(),
                    visual_references=checkpoint_references,
                    artifact_records=artifact_records,
                    measurement_sessions=measurement_sessions,
                    pending_measurement_repairs=pending_measurement_repairs,
                ),
            )
        self._raise_if_interrupted(run)
        terminal_answer = _BUDGET_MSG
        terminal_gate = self._review_manager.gate(run.id)
        shared_terminal_gate = self._review_coordinator.gate(run.id)
        if shared_terminal_gate.blocking:
            terminal_answer = _REVIEW_FAILED_MSG if shared_terminal_gate.state.value in {"failed", "exhausted"} else _REVIEW_REQUIRED_MSG
        elif terminal_gate["pending"] or terminal_gate["failed"]:
            terminal_answer = _REVIEW_REQUIRED_MSG if terminal_gate["pending"] else _REVIEW_FAILED_MSG
        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=self.max_steps,
                max_steps=self.max_steps,
                answer=terminal_answer,
                review_gate=terminal_gate,
                execution_gate=shared_terminal_gate.to_dict(),
            )
        review_blocked = shared_terminal_gate.blocking or terminal_gate["pending"] or terminal_gate["failed"]
        self.memory.append(run, "terminal", {"answer": terminal_answer, "max_steps": self.max_steps, "review_gate": terminal_gate, "execution_gate": shared_terminal_gate.to_dict()})
        self.memory.finish(run, RunStatus.FAILED if review_blocked else RunStatus.COMPLETED, "review_failed" if review_blocked else "budget")
        return terminal_answer

    def _review_gate_allows_call(self, run_id: str, call_name: str, arguments: Mapping[str, Any]) -> bool:
        """Allow only the repair action that owns an active shared gate."""
        gate = self._review_coordinator.gate(run_id)
        if not gate.blocking:
            return True
        if gate.review_type is None:
            return False
        if gate.state.value in {"failed", "exhausted"}:
            return False
        if gate.review_type.value == "measurement":
            if call_name == "assemble_spec":
                # Assembly is the explicit decision boundary, but it must
                # carry the current measurement reference and the main
                # Agent's explicit selection.  Otherwise a model could
                # bypass a blocked measurement by assembling an unrelated
                # spec and waiting for the next turn.
                direct_ref = arguments.get("measurement_ref")
                if isinstance(direct_ref, Mapping):
                    # The assembler can accept a legacy/no-bounded-ref
                    # measurement without a separate decision.  If the
                    # current attempt exposes bounded candidates, the
                    # assembler itself returns measurement_decision_required.
                    return True
                for figure_key in ("figure",):
                    figure = arguments.get(figure_key)
                    if isinstance(figure, Mapping) and _figure_has_measurement_decision(figure):
                        return True
                figures = arguments.get("figures")
                if isinstance(figures, list) and any(
                    isinstance(figure, Mapping) and _figure_has_measurement_decision(figure)
                    for figure in figures
                ):
                    return True
                return False
            if call_name not in MEASUREMENT_TOOLS:
                return False
            target = arguments.get("measurement_target")
            if not isinstance(target, Mapping):
                return False
            parent_attempt_id = target.get("parent_attempt_id")
            if parent_attempt_id is None:
                return bool(target.get("refs") or target.get("bbox_source_px") or target.get("bbox_px"))
            return isinstance(parent_attempt_id, str) and parent_attempt_id == gate.subject_id
        if gate.review_type.value == "generated_chart":
            return call_name in _RENDER_TOOL_NAMES or call_name == "assemble_spec"
        return False

    def _record_shared_review(
        self,
        run: Any,
        record: Any,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        tool_name: str,
        call_id: str,
        emit_start: bool = True,
    ) -> None:
        """Persist and expose one normalized review transition."""
        payload = record.to_dict()
        payload["execution_gate"] = self._review_coordinator.gate(record.run_id).to_dict()
        payload.update({"tool_name": tool_name, "call_id": call_id})
        self.memory.append(run, "review", {"state": payload})
        if self._execution_gate_sink is not None:
            try:
                self._execution_gate_sink(payload["execution_gate"])
            except Exception:  # noqa: BLE001 - gate projection cannot stop the Agent
                pass
        if emitter is None:
            return
        if record.state.value == "reviewing":
            emitter.emit(
                "review_started",
                turn=turn,
                review_id=record.review_id,
                review_type=record.review_type.value,
                subject_id=record.subject_id,
                attempt=record.attempt,
                blocking=True,
                tool_name=tool_name,
                call_id=call_id,
            )
            return
        if emit_start:
            emitter.emit(
                "review_started",
                turn=turn,
                review_id=record.review_id,
                review_type=record.review_type.value,
                subject_id=record.subject_id,
                attempt=record.attempt,
                blocking=True,
                tool_name=tool_name,
                call_id=call_id,
            )
        if record.state.value in {"passed", "passed_with_warning"}:
            emitter.emit("review_completed", turn=turn, **payload)
        elif record.state.value == "repair_required":
            emitter.emit("review_repair_required", turn=turn, **payload)
        else:
            emitter.emit("review_failed", turn=turn, **payload)

    def _release_measurement_gate_from_assembly(
        self,
        run: Any,
        content: str,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        call_id: str,
    ) -> None:
        """Release a measurement gate only after assembly records a decision."""
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if data is None and isinstance(payload, Mapping):
            data = payload
        if not isinstance(data, Mapping) or data.get("error"):
            return
        gate = self._review_coordinator.gate(run.id)
        if (
            not gate.blocking
            or gate.review_type is None
            or gate.review_type.value != "measurement"
            or not gate.review_id
        ):
            return
        decisions: list[Mapping[str, Any]] = []
        direct_decision = data.get("_measurement_decision")
        if isinstance(direct_decision, Mapping):
            decisions.append(direct_decision)
        nested_decisions = data.get("_measurement_decisions")
        if isinstance(nested_decisions, list):
            decisions.extend(item for item in nested_decisions[:64] if isinstance(item, Mapping))
        for decision in decisions:
            attempt_id = str(decision.get("attempt_id") or "").strip()
            if not attempt_id or gate.subject_id != attempt_id:
                continue
            try:
                record = self._review_coordinator.apply(
                    gate.review_id,
                    ReviewDecision(
                        decision="pass",
                        next_action="主 Agent 已选择当前测量证据；允许进入后续生成阶段",
                        evidence=(
                            {
                                "attempt_id": attempt_id,
                                "selected_refs": list(decision.get("selected_refs") or [])[:64],
                                "discarded_refs": list(decision.get("discarded_refs") or [])[:64],
                            },
                        ),
                        details={"decision_source": "main_agent_assembly"},
                    ),
                )
            except (KeyError, TypeError, ValueError):
                return
            self._record_shared_review(
                run,
                record,
                emitter=emitter,
                turn=turn,
                tool_name="assemble_spec",
                call_id=call_id,
                emit_start=False,
            )
            if emitter is not None:
                emitter.emit(
                    "measurement_evidence_selected",
                    turn=turn,
                    tool_name="assemble_spec",
                    call_id=call_id,
                    session_id=decision.get("session_id"),
                    attempt_id=attempt_id,
                    selected_refs=list(decision.get("selected_refs") or [])[:64],
                    discarded_refs=list(decision.get("discarded_refs") or [])[:64],
                    decision_status=str(decision.get("decision_status") or "selected")[:32],
                )
            return

    def _skip_tool_calls(
        self,
        run: Any,
        calls: Sequence[ToolCall],
        *,
        gate: Any,
        emitter: TraceEmitter | None,
        turn: int,
    ) -> None:
        """Append protocol-safe not-started results for calls blocked by a gate."""
        if not calls:
            return
        content = json.dumps(
            {
                "error": "review gate blocked",
                "status": "not_started",
                "review_gate": gate.to_dict(),
                "next_action": gate.next_action or "等待审核门禁释放",
            },
            ensure_ascii=False,
        )
        for call in calls:
            message = tool_entry(call, content)
            self._current_messages.append(message)
            self._messages.append(message)
            self.memory.append(
                run,
                "tool",
                {
                    "message": message,
                    "tool_name": call.name,
                    "status": "not_started",
                    "reason": "review_gate_blocked",
                    "review_gate": gate.to_dict(),
                },
            )
            if emitter is not None:
                presentation = get_tool_presentation(call.name, tool=self.registry.get(call.name))
                emitter.emit(
                    "tool_skipped",
                    turn=turn,
                    tool_name=call.name,
                    tool_display_name=presentation.display_name,
                    tool_label=presentation.label,
                    call_id=call.id,
                    status="not_started",
                    reason="review_gate_blocked",
                    review_gate=gate.to_dict(),
                )

    def _begin_work_unit(self, operation_id: str, operation_kind: str) -> dict[str, Any]:
        if self._operation_begin is None:
            return {"operationId": operation_id, "state": "in_flight"}
        try:
            result = self._operation_begin(operation_id, operation_kind)
            return result if isinstance(result, dict) else {"operationId": operation_id, "state": "in_flight"}
        except Exception:  # noqa: BLE001 - journaling remains a bounded diagnostic
            return {"operationId": operation_id, "state": "in_flight"}

    def _complete_work_unit(
        self,
        operation_id: str,
        operation_kind: str,
        result: dict[str, Any] | None = None,
        references: dict[str, Any] | None = None,
    ) -> None:
        if self._operation_complete is None:
            return
        try:
            self._operation_complete(operation_id, result=result, references=references)
        except Exception:  # noqa: BLE001 - trace persistence cannot stop the Agent
            self._uncertain_work_unit(operation_id, f"{operation_kind}_persistence_failed")

    def _uncertain_work_unit(self, operation_id: str, reason: str) -> None:
        if self._operation_uncertain is None:
            return
        try:
            self._operation_uncertain(operation_id, reason=reason)
        except Exception:  # noqa: BLE001 - bounded recovery fallback
            pass

    def _checkpoint(
        self,
        run: Any,
        *,
        state: dict[str, Any],
        phase: str,
        next_action: str,
    ) -> None:
        if self._checkpoint_sink is None:
            return
        try:
            checkpoint_state = dict(state)
            checkpoint_state.setdefault("phase", phase)
            checkpoint_state["nextAction"] = next_action
            # The review coordinator is the single source of truth for the
            # run-level gate.  Persist both its bounded record history and
            # the current projection at every durable boundary so a resume
            # cannot silently continue past an active review.
            if hasattr(run, "id"):
                review_state = self._review_coordinator.to_state(run.id)
                checkpoint_state["reviewState"] = review_state
                checkpoint_state["executionGate"] = review_state.get("executionGate", {})
            self._checkpoint_sink(checkpoint_state, phase=phase, next_action=next_action)
        except Exception:  # noqa: BLE001 - checkpoint failure is surfaced as unavailable metadata
            return

    @staticmethod
    def _checkpoint_state(
        user_input: str | list[dict],
        messages: Sequence[dict[str, Any]],
        layout_contexts: dict[str, dict[str, Any]],
        attachment_ids: Sequence[str],
        turn: int,
        *,
        pending_tool_calls: Sequence[ToolCall],
        pending_answer: str | None = None,
        visual_references: Sequence[dict[str, Any]] = (),
        artifact_records: Sequence[dict[str, Any]] = (),
        measurement_sessions: Mapping[str, MeasurementSession] | None = None,
        pending_measurement_repairs: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        repairs = (
            _merge_measurement_repair_contexts(pending_measurement_repairs)
            if pending_measurement_repairs is not None
            else _measurement_repair_contexts_from_sessions(measurement_sessions or {})
        )
        result = {
            "prompt": user_input if isinstance(user_input, str) else "[image attachment turn]",
            "messages": list(messages),
            "layoutContexts": layout_contexts,
            "attachmentIds": list(attachment_ids),
            "currentTurn": turn,
            "pendingToolCalls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in pending_tool_calls
            ],
            "visualReferences": list(visual_references)[:32],
            "artifactIndex": list(artifact_records)[:48],
            "measurementSessions": sessions_to_state(measurement_sessions or {}),
            "pendingMeasurementRepairs": repairs,
            # Keep the old field as a compatibility projection for older
            # reconnect consumers. Never choose one action when there are
            # multiple pending panels.
            "pendingMeasurementRepair": repairs[0] if len(repairs) == 1 else None,
        }
        if pending_answer is not None:
            result["pendingAnswer"] = pending_answer
        return result

    @staticmethod
    def _model_result_payload(result: NormalizedResult) -> dict[str, Any]:
        return {
            "content": result.content,
            "finishReason": result.finish_reason,
            "toolCalls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in result.tool_calls
            ],
        }

    @staticmethod
    def _recovery_tool_calls(recovery: Optional[dict[str, Any]]) -> list[ToolCall]:
        if not isinstance(recovery, dict) or recovery.get("nextAction") not in {"tool", "dispatch_tool"}:
            return []
        raw = recovery.get("pendingToolCalls")
        if not isinstance(raw, list):
            return []
        calls: list[ToolCall] = []
        for item in raw[:16]:
            if not isinstance(item, dict):
                continue
            if not all(isinstance(item.get(key), str) and item.get(key) for key in ("id", "name", "arguments")):
                continue
            calls.append(ToolCall(item["id"], item["name"], item["arguments"]))
        return calls

    def _interruption_requested(self) -> bool:
        event = self._interruption_event
        if event is None:
            return False
        if callable(event):
            try:
                return bool(event())
            except Exception:  # noqa: BLE001 - cancellation must remain best effort
                return False
        is_set = getattr(event, "is_set", None)
        return bool(is_set()) if callable(is_set) else bool(event)

    def _raise_if_interrupted(self, run: Any) -> None:
        if not self._interruption_requested():
            return
        try:
            self.memory.finish(run, RunStatus.INTERRUPTED, "interrupted")
        finally:
            raise AgentInterrupted("Agent run was interrupted")

    @staticmethod
    def _layout_arguments(
        tool_name: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> str:
        """Inject one cached validated layout into a geometry call."""
        if tool_name not in _GEOMETRY_TOOL_NAMES or not layout_contexts:
            return arguments
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return arguments
        if not isinstance(parsed, dict) or parsed.get("layout_context") is not None:
            return arguments
        attachment_id = parsed.get("attachment_id")
        panel_id = parsed.get("panel_id")
        context = None
        if isinstance(attachment_id, str) and isinstance(panel_id, str) and panel_id:
            context = layout_contexts.get(f"{attachment_id}::{panel_id}")
        if context is None and isinstance(attachment_id, str):
            context = layout_contexts.get(attachment_id)
        if context is None and len(layout_contexts) == 1:
            context = next(iter(layout_contexts.values()))
        if context is None:
            return arguments
        parsed["layout_context"] = context
        # Keep the public call compatible with direct test/custom sensors; the
        # authorized adapter recovers the panel ID from the injected context.
        parsed.pop("panel_id", None)
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _panel_routing_error(
        tool_name: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> str | None:
        """Reject an unresolved explicit panel route before sensor dispatch."""
        if tool_name not in _SCOPED_TOOL_NAMES:
            return None
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict) or "panel_id" not in parsed:
            return None
        panel_id = parsed.get("panel_id")
        attachment_id = parsed.get("attachment_id")
        if not isinstance(panel_id, str) or not panel_id.strip():
            return "panel routing failed: panel_id must be a non-empty stable identifier"
        if not isinstance(attachment_id, str) or not attachment_id.strip():
            return "panel routing failed: attachment_id is required with panel_id"
        key = f"{attachment_id}::{panel_id}"
        context = layout_contexts.get(key)
        if not isinstance(context, dict):
            return f"panel routing failed: {panel_id!r} is not registered for this attachment"
        scope = context.get("analysis_scope", context.get("panel_scope"))
        if not isinstance(scope, dict) or not isinstance(scope.get("bbox_px"), (list, tuple)):
            return f"panel routing failed: {panel_id!r} has no usable analysis scope"
        return None

    def _hydrate_persisted_panel_contexts(
        self,
        layout_contexts: dict[str, dict[str, Any]],
        attachment_ids: Sequence[str],
    ) -> None:
        """Load durable panel scopes into this run's routing cache."""
        store = getattr(self.attachments, "panel_store", None)
        if store is None or not hasattr(store, "list_panel_handoffs"):
            return
        ids = tuple(attachment_ids)
        if not ids and hasattr(store, "get_active_source"):
            ids = tuple(getattr(store.get_active_source(), "attachment_ids", ()) or ())
        for attachment_id in ids[:16]:
            try:
                handoffs = store.list_panel_handoffs(attachment_id)
            except Exception:  # noqa: BLE001 - persisted routing is advisory
                continue
            for handoff in handoffs[:_MAX_LAYOUT_CONTEXTS]:
                context = {
                    "version": 1,
                    "context_id": f"{handoff.panel_id}_layout",
                    "source_attachment_id": handoff.attachment_id,
                    "coordinate_system": "polar_2d" if handoff.chart_type == "pie" else "cartesian_2d" if handoff.role == "chart" or handoff.chart_type in {"bar", "line", "scatter"} else "unknown",
                    "analysis_scope": {
                        "role": "panel_scope",
                        "bbox_px": list(handoff.analysis_scope),
                        "source_origin_px": list(handoff.source_origin),
                        "confidence": handoff.confidence,
                        "evidence": ["persisted_panel_handoff"],
                    },
                    "measurement_frame": None,
                    "panel": {
                        "id": handoff.panel_id,
                        "name": handoff.name,
                        "source_bbox_px": list(handoff.source_bbox),
                        "scope_bbox_px": list(handoff.analysis_scope),
                    },
                    "validation": {
                        "status": "accepted" if handoff.status == "active" else "partial",
                        "accepted_for_analysis": handoff.status == "active",
                        "accepted_for_measurement": False,
                        "confidence": handoff.confidence,
                        "warnings": list(handoff.warnings),
                    },
                    "evidence": ["persisted_panel_handoff", "source_coordinates"],
                }
                layout_contexts[f"{attachment_id}::{handoff.panel_id}"] = context
                if len(layout_contexts) >= _MAX_LAYOUT_CONTEXTS:
                    return

    @staticmethod
    def _remember_layout_context(
        content: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> None:
        try:
            payload = json.loads(content)
            parsed_arguments = json.loads(arguments) if arguments.strip() else {}
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(payload, dict) or not isinstance(parsed_arguments, dict):
            return
        attachment_id = parsed_arguments.get("attachment_id")
        if not isinstance(attachment_id, str) or not attachment_id:
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        if isinstance(data.get("panels"), list):
            for panel in data["panels"]:
                if not isinstance(panel, dict) or not isinstance(panel.get("id"), str):
                    continue
                context = panel.get("layout_context")
                if not isinstance(context, dict):
                    continue
                cached = dict(context)
                cached["source_attachment_id"] = attachment_id
                panel_summary = dict(cached.get("panel") or {})
                panel_summary.update(
                    {
                        "id": panel["id"],
                        "name": panel.get("name"),
                        "chart_type": panel.get("chart_type"),
                    }
                )
                cached["panel"] = panel_summary
                layout_contexts[f"{attachment_id}::{panel['id']}"] = cached
                while len(layout_contexts) > _MAX_LAYOUT_CONTEXTS:
                    layout_contexts.pop(next(iter(layout_contexts)))
            return
        context = data.get("layout_context")
        if not isinstance(context, dict):
            return
        cached = dict(context)
        cached["source_attachment_id"] = attachment_id
        layout_contexts[attachment_id] = cached
        while len(layout_contexts) > _MAX_LAYOUT_CONTEXTS:
            layout_contexts.pop(next(iter(layout_contexts)))

    @staticmethod
    def _review_items(content: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(content)
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data.get("review") if isinstance(data, dict) else None
            if not isinstance(items, list):
                items = payload.get("review") if isinstance(payload, dict) else None
            if not isinstance(items, list) and isinstance(payload, dict) and isinstance(payload.get("candidate"), dict):
                items = [payload["candidate"]]
            return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    def _apply_generation_review(
        self,
        observation: Any,
        *,
        run: Any | None = None,
        run_id: str,
        call_id: str,
        arguments: str,
        source_attachment_ids: Sequence[str],
        emitter: TraceEmitter | None = None,
        turn: int | None = None,
    ) -> Any:
        """Run the post-generation hook before tool evidence reaches the model."""
        if not observation.images:
            return observation
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except (TypeError, json.JSONDecodeError):
            return observation
        spec_payload = args.get("spec") if isinstance(args, dict) else None
        if not isinstance(spec_payload, dict):
            return observation
        try:
            from ..spec import ChartFigure, ChartSpec, ChartSpecCollection

            collection = None
            if spec_payload.get("kind") == "chart_figure":
                figure_specs = [ChartFigure.from_dict(spec_payload)]
            elif spec_payload.get("kind") == "chart_spec_collection":
                collection = ChartSpecCollection.from_dict(spec_payload)
                figure_specs = list(collection.figures)
            else:
                figure_specs = [ChartSpec.from_dict(spec_payload)]
        except (TypeError, ValueError, KeyError):
            return observation
        generated: list[GeneratedImage] = []
        review_payloads: list[dict[str, Any]] = []
        changed = False
        for image in observation.images:
            metadata = image.metadata if hasattr(image.metadata, "get") else {}
            if metadata.get("kind") != "generated_chart":
                generated.append(image)
                continue
            # Legacy custom tools without a ChartSpec digest remain readable;
            # renderer-produced images always carry the digest and enter this
            # mandatory lifecycle.
            if not metadata.get("chart_spec_digest"):
                generated.append(image)
                continue
            review_spec = figure_specs[0]
            if collection is not None and len(figure_specs) > 1:
                figure_id = metadata.get("figure_id") or metadata.get("figureId")
                review_spec = next(
                    (figure for figure in figure_specs if figure.figure_id == figure_id),
                    figure_specs[0],
                )
            candidate = self._review_manager.create_candidate(
                run_id,
                call_id,
                image,
                review_spec,
                source_attachment_ids=source_attachment_ids,
            )
            # Open the shared gate before any VLM/provider review work.  The
            # generated artifact is therefore never visible as publishable
            # while the semantic review is still in flight.
            initial_shared_review = self._generated_chart_review_adapter.submit(
                self._review_coordinator,
                candidate=candidate,
            )
            if run is not None:
                self._record_shared_review(
                    run,
                    initial_shared_review,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                )
            if candidate.review_status is ReviewStatus.PENDING:
                semantic_result: ReviewResult | None = None
                if candidate.policy.semantic_required:
                    source_payload = self._review_manager.source_payload(candidate)
                    if source_payload is None:
                        semantic_result = ReviewResult(
                            status=ReviewStatus.FAILED,
                            checks={"source_evidence": "failed"},
                            issues=(ReviewIssue(
                                "source_binding_failure",
                                "source_attachment_ids",
                                "authorized source attachment is unavailable; bind an active source before retrying",
                            ),),
                            decision="fail",
                            confidence=0.0,
                            review_mode="vlm",
                            suggested_action="rebind_source",
                            recovery_classification="source_binding_failure",
                        )
                    else:
                        if emitter is not None:
                            emitter.emit(
                                "chart_review_started",
                                turn=turn,
                                internal_review=True,
                                tool_count=0,
                                candidate_id=candidate.candidate_id,
                                review_id=candidate.review_id,
                                review_mode="vlm",
                            )
                        semantic_result = review_candidate_with_vlm(
                            self.client,
                            candidate,
                            review_spec,
                            source_image=source_payload[0],
                            source_media_type=source_payload[1],
                            chat_kwargs=self._chat_kwargs,
                            trace_kwargs=(
                                {
                                    "trace_sink": emitter,
                                    "trace_run_id": emitter.run_id,
                                    "trace_turn": turn,
                                }
                                if emitter is not None and isinstance(self.client, LLMClient)
                                else None
                            ),
                        )
                candidate = self._review_manager.process(candidate, semantic_result=semantic_result)
            shared_review = self._generated_chart_review_adapter.submit(
                self._review_coordinator,
                candidate=candidate,
            )
            if run is not None:
                self._record_shared_review(
                    run,
                    shared_review,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                    emit_start=False,
                )
            generated.append(self._review_manager.decorate_image(image, candidate))
            review_payloads.append(candidate.safe_metadata())
            changed = True
        if not changed:
            return observation
        content = observation.content
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, dict):
                    data = dict(data)
                    data["review"] = review_payloads
                    payload["data"] = data
                payload["review"] = review_payloads
                content = json.dumps(payload, ensure_ascii=False)
        except (TypeError, json.JSONDecodeError):
            pass
        from ..tools.core.result import DispatchedObservation

        return DispatchedObservation(content=content, images=tuple(generated))


_assistant_entry = assistant_entry
_tool_entry = tool_entry
_observation_status = observation_status
