"""Measurement evidence flow helpers used by the Agent orchestration."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..measurement import (
    MeasurementSession,
    measurement_target_fingerprint,
    register_measurement,
)

MAX_PENDING_MEASUREMENT_REPAIRS = 16


def measurement_repair_context_from_content(content: str) -> dict[str, Any] | None:
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
    decision_status = str(decision.get("status") or "pending")[:32]
    if decision_status in {"selected", "discarded", "abandoned"}:
        return None
    focus_suggestion = quality.get("focus_suggestion") or quality.get("repair_action")
    return {
        "session_id": reference.get("session_id"),
        "attempt_id": reference.get("attempt_id"),
        "attachment_id": reference.get("attachment_id"),
        "panel_id": reference.get("panel_id"),
        "status": str(measurement.get("status") or "provisional")[:32],
        "refs": list(evidence.get("refs") or [])[:64] if isinstance(evidence.get("refs"), list) else [],
        "warnings": list(quality.get("warnings") or [])[:12] if isinstance(quality.get("warnings"), list) else [],
        "issues": list(quality.get("issues") or [])[:8] if isinstance(quality.get("issues"), list) else [],
        "focus": evidence.get("focus") if isinstance(evidence.get("focus"), Mapping) else None,
        "observation_scope": measurement.get("observation_scope") if isinstance(measurement.get("observation_scope"), Mapping) else None,
        "series_map": dict(decision.get("series_map") or {}) if isinstance(decision.get("series_map"), Mapping) else {},
        "evidence_basis": str(decision.get("evidence_basis") or "")[:80] or None,
        "focus_suggestion": focus_suggestion if isinstance(focus_suggestion, Mapping) else None,
        "decision_status": decision_status,
        "selected_refs": list(decision.get("selected_refs") or [])[:64] if isinstance(decision.get("selected_refs"), list) else [],
        "discarded_refs": list(decision.get("discarded_refs") or [])[:64] if isinstance(decision.get("discarded_refs"), list) else [],
        "next_action": "由主 Agent 选择、舍弃或调用同一测量工具携带 measurement_target 做定向补充",
    }


def repair_context_key(context: Mapping[str, Any]) -> tuple[str, ...]:
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


def merge_measurement_repair_contexts(
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
            key = repair_context_key(context)
            if key in seen:
                continue
            seen.add(key)
            result.append(context)
            if len(result) >= MAX_PENDING_MEASUREMENT_REPAIRS:
                return result
    return result


def measurement_repair_contexts_from_sessions(
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
        contexts.append(
            {
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
                "observation_scope": current.observation_scope,
                "series_map": dict(session.series_map),
                "evidence_basis": session.evidence_basis,
                "budget_remaining": session.repair_budget_remaining,
                "warnings": list(current.quality.get("warnings") or [])[:12] if isinstance(current.quality, Mapping) else [],
                "issues": list(current.quality.get("issues") or [])[:8] if isinstance(current.quality, Mapping) else [],
                "next_action": "由主 Agent 选择、舍弃或调用同一测量工具携带 measurement_target 做定向补充",
            }
        )
    return merge_measurement_repair_contexts(contexts)


def repair_target_context(
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


def measurement_data_from_content(content: str) -> Mapping[str, Any] | None:
    """Return the data object from a measurement observation, if present."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    return data if isinstance(data, Mapping) and isinstance(data.get("measurement"), Mapping) else None


def register_measurement_observation(
    sessions: dict[str, MeasurementSession],
    content: str,
) -> MeasurementSession | None:
    """Register a measurement observation without duplicating payload parsing."""
    data = measurement_data_from_content(content)
    if data is None:
        return None
    return register_measurement(sessions, data)


def measurement_decisions_from_content(content: str) -> list[Mapping[str, Any]]:
    """Extract bounded explicit evidence decisions from an assemble result."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return []
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if data is None and isinstance(payload, Mapping):
        data = payload
    if not isinstance(data, Mapping) or data.get("error"):
        return []
    decisions: list[Mapping[str, Any]] = []
    direct_decision = data.get("_measurement_decision")
    if isinstance(direct_decision, Mapping):
        decisions.append(direct_decision)
    nested_decisions = data.get("_measurement_decisions")
    if isinstance(nested_decisions, list):
        decisions.extend(item for item in nested_decisions[:64] if isinstance(item, Mapping))
    return decisions


def measurement_trace_fields(content: str) -> dict[str, Any]:
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
    result["measurement_evidence_refs"] = list(evidence.get("refs") or [])[:64]
    focus = evidence.get("focus")
    if isinstance(focus, Mapping):
        result["measurement_focus"] = {
            key: focus.get(key)
            for key in ("requested", "applied", "status", "mode", "target_refs", "search_scope")
            if focus.get(key) is not None
        }
    result["measurement_decision_status"] = str(decision.get("status") or "pending")[:32]
    result["measurement_selected_refs"] = list(decision.get("selected_refs") or [])[:64]
    result["measurement_discarded_refs"] = list(decision.get("discarded_refs") or [])[:64]
    result["measurement_series_map"] = dict(decision.get("series_map") or {}) if isinstance(decision.get("series_map"), Mapping) else {}
    result["measurement_evidence_basis"] = str(decision.get("evidence_basis") or "")[:80] or None
    observation_scope = measurement.get("observation_scope")
    if isinstance(observation_scope, Mapping):
        result["measurement_observation_scope"] = {
            key: observation_scope.get(key)
            for key in ("scope_id", "panel_id", "coordinate_space", "status", "applied", "requested", "include", "exclude", "source_regions", "objectives", "search_scope")
            if observation_scope.get(key) is not None
        }
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


# Compatibility names used while callers migrate to the descriptive names.
_measurement_repair_context_from_content = measurement_repair_context_from_content
_repair_context_key = repair_context_key
_merge_measurement_repair_contexts = merge_measurement_repair_contexts
_measurement_repair_contexts_from_sessions = measurement_repair_contexts_from_sessions
_repair_target_context = repair_target_context
_measurement_trace_fields = measurement_trace_fields
