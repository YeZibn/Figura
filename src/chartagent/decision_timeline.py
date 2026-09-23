"""Bounded correlation metadata for the decision timeline.

Execution events remain the source of truth.  This module only projects a
small, deterministic envelope so clients can group events without
reconstructing domain state from free-form tool results.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CORRELATION_VERSION = 1
MAX_ID = 160
MAX_ACTION_TEXT = 240
MAX_ACTION_ITEMS = 16
MAX_FAILURE_CODE = 96
MAX_FAILURE_MESSAGE = 240

UNIT_TYPES = frozenset({"measurement", "generation", "review", "publication", "observation"})
PHASES = frozenset({"observe", "decide", "assemble", "render", "review", "repair", "publish", "action"})
ACTORS = frozenset({"agent", "tool", "system", "vlm"})
ROLES = frozenset({"observation", "decision", "action", "gate", "review", "publication"})


class TimelineProtocolError(ValueError):
    """Raised when a timeline event cannot satisfy the strict event contract."""

    code = "invalid_timeline_event"

_REVIEW_KINDS = frozenset(
    {
        "review_started",
        "review_completed",
        "review_repair_required",
        "review_failed",
        "review_subcheck",
    }
)
_PUBLICATION_KINDS = frozenset({"generated_chart_published", "generated_chart_rejected"})

_STRICT_KINDS = frozenset(
    {
        *_REVIEW_KINDS,
        *_PUBLICATION_KINDS,
        "tool_call",
        "tool_result",
        "tool_skipped",
        "visual_observation",
        "generated_chart",
        "assembly_validation_failure",
    }
)
_RETIRED_KINDS = frozenset(
    {
        "chart_review_started",
        "chart_review_required",
        "chart_review_repair_required",
        "chart_review_completed",
    }
)

def _text(value: object, limit: int = MAX_ID) -> str:
    return str(value or "").strip()[:limit]


def _first(mapping: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _phase(kind: str, payload: Mapping[str, Any]) -> str:
    explicit = _text(payload.get("phase"), 32).lower()
    if explicit not in PHASES:
        raise TimelineProtocolError(f"事件 {kind} 缺少有效 phase")
    return explicit


def _actor(kind: str, payload: Mapping[str, Any]) -> str:
    explicit = _text(payload.get("actor"), 32).lower()
    if explicit not in ACTORS:
        raise TimelineProtocolError(f"事件 {kind} 缺少有效 actor")
    return explicit


def _role(kind: str, payload: Mapping[str, Any]) -> str:
    explicit = _text(payload.get("role"), 32).lower()
    if explicit not in ROLES:
        raise TimelineProtocolError(f"事件 {kind} 的 role 无效")
    return explicit


def _strict_identity(kind: str, payload: Mapping[str, Any]) -> tuple[str, str, str | None]:
    unit_id = _text(payload.get("unit_id"))
    if not unit_id:
        raise TimelineProtocolError(f"事件 {kind} 缺少 unit_id")
    unit_type = _text(payload.get("unit_type"), 32).lower()
    if unit_type not in UNIT_TYPES:
        raise TimelineProtocolError(f"事件 {kind} 的 unit_type 必须是 canonical 类型")
    call_id = _text(payload.get("call_id"))
    if kind in {"tool_call", "tool_result", "tool_skipped", "visual_observation"} and not call_id:
        raise TimelineProtocolError(f"事件 {kind} 缺少 call_id")
    review_id = _text(payload.get("review_id"))
    if kind in _REVIEW_KINDS and not review_id:
        raise TimelineProtocolError(f"事件 {kind} 缺少 review_id")
    parent_unit_id = _text(payload.get("parent_unit_id")) or None
    if parent_unit_id == unit_id:
        raise TimelineProtocolError(f"事件 {kind} 的 parent_unit_id 不能指向自身")
    return unit_id, unit_type, parent_unit_id


def _state(payload: Mapping[str, Any], kind: str) -> str:
    value = _first(payload, "state", "status")
    if value not in (None, ""):
        return _text(value, 64)
    raise TimelineProtocolError(f"事件 {kind} 缺少 state/status")


def _bounded_action(value: object, *, default_required: bool = False) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {"required": bool(value.get("required", default_required))}
        for key in ("allowed", "blocked"):
            raw = value.get(key)
            if isinstance(raw, (list, tuple)):
                result[key] = [_text(item, 80) for item in list(raw)[:MAX_ACTION_ITEMS] if _text(item, 80)]
        reason = _text(value.get("reason") or value.get("message"), MAX_ACTION_TEXT)
        if reason:
            result["reason"] = reason
        label = _text(value.get("label") or value.get("action"), MAX_ACTION_TEXT)
        if label:
            result["label"] = label
        return result
    if isinstance(value, str) and value.strip():
        return {"required": default_required, "allowed": [_text(value, 80)], "blocked": []}
    return None


def _next_action(kind: str, payload: Mapping[str, Any], phase: str, state: str) -> dict[str, Any] | None:
    explicit = _first(payload, "next_action", "nextAction")
    normalized = _bounded_action(explicit, default_required=bool(payload.get("blocking") or payload.get("required")))
    if normalized is not None:
        return normalized
    # The absence of an explicit hint is meaningful: it is not an action
    # obligation and must not become a synthesized tool whitelist.
    return None


def _process_context(kind: str, payload: Mapping[str, Any], *, sequence: int | None) -> dict[str, Any]:
    """Return only deterministic process/operation fields for lifecycle events."""
    result: dict[str, Any] = {}
    process_id = _text(_first(payload, "process_id", "processId"), MAX_ID)
    operation_id = _text(_first(payload, "operation_id", "operationId"), MAX_ID)
    turn = payload.get("turn")
    try:
        turn_value = max(1, int(turn)) if turn is not None else None
    except (TypeError, ValueError):
        turn_value = None
    if not process_id and turn_value is not None:
        process_id = f"turn:{turn_value}"
    if not process_id and operation_id:
        process_id = f"operation:{operation_id}"
    if process_id:
        result["process_id"] = process_id
    if operation_id:
        result["operation_id"] = operation_id
    if turn_value is not None:
        result["turn"] = turn_value
    return result


def _failure_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize already-classified failure fields without inferring errors."""
    fields: dict[str, Any] = {}
    aliases = {
        "failure_category": ("failure_category", "failureCategory"),
        "failure_code": ("failure_code", "failureCode"),
        "safe_message": ("safe_message", "safeMessage"),
        "location": ("location", "field_location", "fieldLocation"),
        "action_hint": ("action_hint", "actionHint"),
        "first_failure_ref": ("first_failure_ref", "firstFailureRef"),
    }
    for target, keys in aliases.items():
        value = _first(payload, *keys)
        if value not in (None, ""):
            if target == "first_failure_ref" and isinstance(value, Mapping):
                fields[target] = {
                    _text(key, 48): _text(item, MAX_FAILURE_CODE)
                    for key, item in list(value.items())[:8]
                    if _text(key, 48) and item not in (None, "")
                }
            else:
                fields[target] = _text(value, MAX_FAILURE_MESSAGE if target == "safe_message" else MAX_FAILURE_CODE)
    provider_status = _first(payload, "provider_status", "providerStatus")
    if provider_status is not None:
        try:
            fields["provider_status"] = int(provider_status)
        except (TypeError, ValueError):
            pass
    if "retryable" in payload:
        fields["retryable"] = bool(payload["retryable"])
    if "outcome_known" in payload or "outcomeKnown" in payload:
        fields["outcome_known"] = bool(_first(payload, "outcome_known", "outcomeKnown"))
    return fields


def _transition_id(kind: str, payload: Mapping[str, Any]) -> str:
    explicit = _text(payload.get("transition_id"), 128)
    if not explicit:
        raise TimelineProtocolError(f"事件 {kind} 缺少 transition_id")
    return explicit


def enrich_event_payload(
    kind: str,
    payload: Mapping[str, Any] | None = None,
    *,
    run_id: str = "",
    sequence: int | None = None,
) -> dict[str, Any]:
    """Validate and return one strict, bounded timeline envelope.

    Lifecycle events which are not business timeline nodes remain plain
    process records.  Every event that can enter the user timeline must,
    however, arrive with an explicit canonical identity.  This boundary never
    invents a unit or parent relation and rejects retired review aliases.
    """
    source = dict(payload or {})
    event_kind = str(kind or "")
    if event_kind in _RETIRED_KINDS:
        raise TimelineProtocolError(f"事件 {event_kind} 已废弃，请使用 canonical review 生命周期")
    if event_kind not in _STRICT_KINDS:
        process = _process_context(event_kind, source, sequence=sequence)
        failure = _failure_context(source)
        source.update(process)
        source.update(failure)
        return source
    unit_id, unit_type, parent_unit_id = _strict_identity(event_kind, source)
    phase = _phase(event_kind, source)
    actor = _actor(event_kind, source)
    state = _state(source, event_kind)
    envelope: dict[str, Any] = {
        "correlation_version": CORRELATION_VERSION,
        "unit_id": unit_id,
        "unit_type": unit_type,
        "phase": phase,
        "actor": actor,
        "role": _role(event_kind, source),
        "parent_unit_id": parent_unit_id,
        "transition_id": _transition_id(event_kind, source),
    }
    if "state" not in source and event_kind != "tool_result":
        envelope["state"] = state
    if event_kind == "tool_result" and "status" not in source:
        envelope["status"] = state
    action = _next_action(event_kind, source, phase, state)
    if action is not None:
        envelope["next_action"] = action
    envelope.update(_process_context(event_kind, source, sequence=sequence))
    envelope.update(_failure_context(source))
    source.update(envelope)
    return source


__all__ = [
    "ACTORS",
    "CORRELATION_VERSION",
    "PHASES",
    "ROLES",
    "UNIT_TYPES",
    "TimelineProtocolError",
    "enrich_event_payload",
]
