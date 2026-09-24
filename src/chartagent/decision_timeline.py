"""Bounded correlation metadata for the decision timeline.

Execution events remain the source of truth.  This module only projects a
small, deterministic envelope so clients can group events without
reconstructing domain state from free-form tool results.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CORRELATION_VERSION = 2
MAX_ID = 160
MAX_ACTION_TEXT = 240
MAX_ACTION_ITEMS = 16
MAX_FAILURE_CODE = 96
MAX_FAILURE_MESSAGE = 240

UNIT_TYPES = frozenset({"measurement", "generation", "verification", "artifact", "observation"})
PHASES = frozenset({"observe", "decide", "assemble", "render", "verify", "publish", "action"})
ACTORS = frozenset({"agent", "tool", "system", "vlm"})
ROLES = frozenset({"observation", "decision", "action", "verification", "artifact"})


class TimelineProtocolError(ValueError):
    """Raised when a timeline event cannot satisfy the strict event contract."""

    code = "invalid_timeline_event"


class UnsupportedTimelineVersion(TimelineProtocolError):
    """Raised when an event belongs to a retired or unsupported protocol."""

    code = "unsupported_timeline_version"

_STRICT_KINDS = frozenset(
    {
        "chart_staged",
        "chart_verification_result",
        "chart_promotion_result",
        "tool_call",
        "tool_result",
        "tool_skipped",
        "visual_observation",
        "assembly_validation_failure",
    }
)

# Tool results describe a call outcome with `status`; verification and
# promotion facts use `state`.
EVENT_STATUS_FIELD_BY_KIND = {
    kind: "status" if kind == "tool_result" else "state"
    for kind in _STRICT_KINDS
}

_STRICT_CAMEL_ALIASES = frozenset(
    {
        "correlationVersion",
        "unitId",
        "unitType",
        "parentUnitId",
        "transitionId",
        "callId",
        "toolName",
        "runId",
        "processId",
        "operationId",
        "nextAction",
        "failureCategory",
        "failureCode",
        "safeMessage",
        "fieldLocation",
        "actionHint",
        "firstFailureRef",
        "providerStatus",
        "outcomeKnown",
        "chartSpecDigest",
        "sourceScope",
        "sourceAttachmentIds",
        "panelIds",
        "collectionId",
        "figureId",
        "maxAttempts",
        "remainingAttempts",
        "createdAt",
        "updatedAt",
        "subjectRef",
        "generationContext",
        "stagedRef",
        "verificationRef",
        "artifactId",
        "manifestDigest",
        "traceSequence",
    }
)
_RETIRED_KINDS = frozenset(
    {
        "review_started",
        "review_completed",
        "review_repair_required",
        "review_failed",
        "review_subcheck",
        "chart_review_started",
        "chart_review_required",
        "chart_review_completed",
        "chart_review_failed",
        "chart_review_subcheck",
        "chart_review_repair_required",
        "review_gate_required",
        "review_gate_updated",
        "review_gate_blocked",
        "review_gate_opened",
        "generated_chart_published",
        "generated_chart_rejected",
        "generated_chart",
    }
)
_RETIRED_FIELDS = frozenset(
    {
        "candidate_id", "candidateId", "candidate_attempt", "candidateAttempt",
        "review_id", "reviewId", "review_type", "reviewType", "review_status", "reviewStatus",
        "publication_status", "publicationStatus", "repair_kind", "repairKind",
        "repair_phase", "repairPhase", "execution_gate", "executionGate", "review_gate", "reviewGate",
        "artifacts",
    }
)


def is_strict_timeline_event_kind(kind: str) -> bool:
    return kind in _STRICT_KINDS

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
    if kind in {"tool_call", "tool_result", "tool_skipped", "visual_observation", "chart_staged"} and not call_id:
        raise TimelineProtocolError(f"事件 {kind} 缺少 call_id")
    parent_unit_id = _text(payload.get("parent_unit_id")) or None
    if parent_unit_id == unit_id:
        raise TimelineProtocolError(f"事件 {kind} 的 parent_unit_id 不能指向自身")
    return unit_id, unit_type, parent_unit_id


def _state(payload: Mapping[str, Any], kind: str) -> str:
    field = EVENT_STATUS_FIELD_BY_KIND[kind]
    alias = "state" if field == "status" else "status"
    if alias in payload:
        raise TimelineProtocolError(f"事件 {kind} 只能使用 {field}")
    if kind == "tool_result" and "tool_status" in payload:
        raise TimelineProtocolError("事件 tool_result 不允许重复字段 tool_status")
    value = payload.get(field)
    if isinstance(value, str) and value.strip():
        return _text(value, 64)
    raise TimelineProtocolError(f"事件 {kind} 缺少有效 {field}")


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
    explicit = payload.get("next_action")
    normalized = _bounded_action(explicit, default_required=bool(payload.get("blocking") or payload.get("required")))
    if normalized is not None:
        return normalized
    # The absence of an explicit hint is meaningful: it is not an action
    # obligation and must not become a synthesized tool whitelist.
    return None


def _process_context(kind: str, payload: Mapping[str, Any], *, sequence: int | None) -> dict[str, Any]:
    """Return only deterministic process/operation fields for lifecycle events."""
    result: dict[str, Any] = {}
    process_id = _text(payload.get("process_id"), MAX_ID)
    operation_id = _text(payload.get("operation_id"), MAX_ID)
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
        "failure_category": ("failure_category",),
        "failure_code": ("failure_code",),
        "safe_message": ("safe_message",),
        "location": ("location",),
        "action_hint": ("action_hint",),
        "first_failure_ref": ("first_failure_ref",),
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
    provider_status = payload.get("provider_status")
    if provider_status is not None:
        try:
            fields["provider_status"] = int(provider_status)
        except (TypeError, ValueError):
            pass
    if "retryable" in payload:
        fields["retryable"] = bool(payload["retryable"])
    if "outcome_known" in payload:
        fields["outcome_known"] = bool(payload["outcome_known"])
    return fields


def _transition_id(kind: str, payload: Mapping[str, Any]) -> str:
    explicit = _text(payload.get("transition_id"), 128)
    if not explicit:
        raise TimelineProtocolError(f"事件 {kind} 缺少 transition_id")
    return explicit


def _validate_v2_fields(kind: str, payload: Mapping[str, Any]) -> None:
    retired = _RETIRED_FIELDS.intersection(payload)
    if retired:
        field = sorted(retired)[0]
        raise TimelineProtocolError(f"事件 {kind} 不允许已退役字段 {field}")
    aliases = _STRICT_CAMEL_ALIASES.intersection(payload)
    if aliases:
        alias = sorted(aliases)[0]
        raise TimelineProtocolError(f"事件 {kind} 不允许非 canonical 字段 {alias}")
    if "correlation_version" in payload and (
        type(payload["correlation_version"]) is not int
        or payload["correlation_version"] != CORRELATION_VERSION
    ):
        raise UnsupportedTimelineVersion(f"事件 {kind} 的 timeline 版本不受支持")


def validate_timeline_event(kind: str, payload: Mapping[str, Any]) -> None:
    """Validate a persisted event without enriching or rewriting its payload."""
    event_kind = str(kind or "")
    if event_kind in _RETIRED_KINDS:
        raise UnsupportedTimelineVersion(f"事件 {event_kind} 已从当前 timeline 协议退役")
    if event_kind not in _STRICT_KINDS:
        return
    version = payload.get("correlation_version")
    if type(version) is not int or version != CORRELATION_VERSION:
        raise UnsupportedTimelineVersion(f"事件 {event_kind} 的 timeline 版本不受支持")
    _validate_v2_fields(event_kind, payload)
    _strict_identity(event_kind, payload)
    _phase(event_kind, payload)
    _actor(event_kind, payload)
    _role(event_kind, payload)
    _state(payload, event_kind)
    _transition_id(event_kind, payload)


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
    invents a unit or parent relation and rejects retired lifecycle aliases.
    """
    source = dict(payload or {})
    event_kind = str(kind or "")
    if event_kind in _RETIRED_KINDS:
        raise UnsupportedTimelineVersion(f"事件 {event_kind} 已从当前图表验证协议退役")
    if event_kind not in _STRICT_KINDS:
        process = _process_context(event_kind, source, sequence=sequence)
        failure = _failure_context(source)
        source.update(process)
        source.update(failure)
        return source
    _validate_v2_fields(event_kind, source)
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
    envelope[EVENT_STATUS_FIELD_BY_KIND[event_kind]] = state
    action = _next_action(event_kind, source, phase, state)
    if action is not None:
        envelope["next_action"] = action
    envelope.update(_process_context(event_kind, source, sequence=sequence))
    envelope.update(_failure_context(source))
    source.update(envelope)
    validate_timeline_event(event_kind, source)
    return source


__all__ = [
    "ACTORS",
    "CORRELATION_VERSION",
    "EVENT_STATUS_FIELD_BY_KIND",
    "PHASES",
    "ROLES",
    "UNIT_TYPES",
    "TimelineProtocolError",
    "UnsupportedTimelineVersion",
    "enrich_event_payload",
    "is_strict_timeline_event_kind",
    "validate_timeline_event",
]
