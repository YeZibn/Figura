"""Bounded correlation metadata for the decision timeline.

Execution events remain the source of truth.  This module only projects a
small, deterministic envelope so clients can group events without
reconstructing domain state from free-form tool results.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CORRELATION_VERSION = 1
MAX_ID = 160
MAX_ACTION_TEXT = 240
MAX_ACTION_ITEMS = 16

UNIT_TYPES = frozenset({"measurement", "generation", "review", "publication", "observation", "legacy", "unknown"})
PHASES = frozenset({"observe", "decide", "assemble", "render", "review", "repair", "publish", "action", "unknown"})
ACTORS = frozenset({"agent", "tool", "system", "vlm", "unknown"})
ROLES = frozenset({"observation", "decision", "action", "gate", "review", "publication", "legacy"})

_MEASUREMENT_KINDS = frozenset(
    {
        "measurement_observed",
        "measurement_repair_required",
        "measurement_repair_rejected",
        "measurement_repair_exhausted",
        "measurement_decision_required",
        "measurement_focus_requested",
        "measurement_focus_applied",
        "measurement_focus_failed",
        "measurement_evidence_selected",
        "measurement_evidence_discarded",
    }
)
_REVIEW_KINDS = frozenset(
    {
        "review_started",
        "review_completed",
        "review_repair_required",
        "review_failed",
        "review_gate_required",
        "review_gate_updated",
        "chart_review_started",
        "chart_review_required",
        "chart_review_repair_required",
        "chart_review_completed",
        "review_subcheck",
    }
)
_PUBLICATION_KINDS = frozenset({"generated_chart_published", "generated_chart_rejected"})


def _text(value: object, limit: int = MAX_ID) -> str:
    return str(value or "").strip()[:limit]


def _first(mapping: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _nested_mapping(mapping: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _candidate_id(payload: Mapping[str, Any]) -> str:
    return _text(_first(payload, "candidate_id", "candidateId", "subject_id", "subjectId"))


def _review_id(payload: Mapping[str, Any]) -> str:
    return _text(_first(payload, "review_id", "reviewId"))


def _collection_id(payload: Mapping[str, Any]) -> str:
    return _text(_first(payload, "collection_id", "collectionId"))


def _measurement_identity(payload: Mapping[str, Any]) -> str:
    reference = _nested_mapping(payload, "measurement_reference", "measurementReference", "reference")
    decision = _nested_mapping(payload, "decision")
    target = _nested_mapping(payload, "target", "measurement_target", "measurementTarget")
    return _text(
        _first(
            payload,
            "attempt_id",
            "attemptId",
            "session_id",
            "sessionId",
            reference.get("attempt_id"),
            reference.get("attemptId"),
            reference.get("session_id"),
            reference.get("sessionId"),
            decision.get("attempt_id"),
            target.get("attempt_id"),
            target.get("attemptId"),
        )
    )


def _phase(kind: str, payload: Mapping[str, Any]) -> str:
    if kind in {"measurement_focus_requested", "measurement_focus_applied", "measurement_focus_failed", "measurement_observed"}:
        return "observe"
    if kind in {"measurement_decision_required", "measurement_evidence_selected", "measurement_evidence_discarded"}:
        return "decide"
    if kind.startswith("measurement_repair"):
        return "repair"
    if kind == "assembly_validation_failure" or str(payload.get("tool_name") or "") == "assemble_spec":
        return "assemble"
    if kind == "generated_chart" or str(payload.get("tool_name") or "") in {"render_chart", "render_figure"}:
        return "render"
    if kind in _PUBLICATION_KINDS:
        return "publish"
    if kind in {"review_repair_required", "chart_review_repair_required"}:
        return "repair"
    if kind in _REVIEW_KINDS:
        return "review"
    if kind in {"tool_call", "tool_result", "visual_observation"}:
        return "observe" if kind == "visual_observation" else "action"
    return "unknown"


def _actor(kind: str, payload: Mapping[str, Any]) -> str:
    explicit = _text(payload.get("actor"), 32).lower()
    if explicit in {"agent", "tool", "system", "vlm", "unknown"}:
        return explicit
    if kind in {"measurement_evidence_selected", "measurement_evidence_discarded", "measurement_decision_required", "measurement_focus_requested"}:
        return "agent"
    if kind in {"tool_call", "tool_result", "visual_observation", "measurement_observed", "measurement_focus_applied", "measurement_focus_failed"}:
        return "tool"
    if kind == "review_subcheck" and str(payload.get("check_type") or "") in {"semantic_vlm", "vlm"}:
        return "vlm"
    if payload.get("internal_review") is True or str(payload.get("review_mode") or payload.get("reviewMode")) == "vlm":
        return "vlm"
    if kind in _REVIEW_KINDS or kind in _PUBLICATION_KINDS:
        return "system"
    return "unknown"


def _role(kind: str, phase: str) -> str:
    if kind in {"measurement_observed", "visual_observation"}:
        return "observation"
    if kind in {"measurement_evidence_selected", "measurement_evidence_discarded", "measurement_decision_required"}:
        return "decision"
    if kind in _PUBLICATION_KINDS or kind == "generated_chart":
        return "publication"
    if kind in _REVIEW_KINDS or phase == "review":
        return "gate" if kind.startswith("review_gate") else "review"
    if kind in {"tool_call", "tool_result", "measurement_focus_requested", "measurement_focus_applied", "measurement_focus_failed", "assembly_validation_failure"}:
        return "action"
    return "legacy"


def _unit_identity(kind: str, payload: Mapping[str, Any], *, run_id: str, sequence: int | None) -> tuple[str, str, str | None]:
    explicit = _text(_first(payload, "unit_id", "unitId"))
    explicit_type = _text(_first(payload, "unit_type", "unitType"), 32).lower()
    if explicit:
        return explicit, explicit_type if explicit_type in {"measurement", "generation", "review", "publication", "observation", "legacy", "unknown"} else "unknown", _text(_first(payload, "parent_unit_id", "parentUnitId")) or None

    collection_id = _collection_id(payload)
    candidate_id = _candidate_id(payload)
    review_id = _review_id(payload)
    measurement_id = _measurement_identity(payload)
    tool_name = str(payload.get("tool_name") or "")
    if kind in _MEASUREMENT_KINDS or tool_name in {"measure_bars", "measure_line", "measure_pie", "measure_scatter"}:
        identity = measurement_id or _text(_first(payload, "call_id", "callId"))
        return f"measurement:{identity or 'unknown'}", "measurement", None
    if kind in _PUBLICATION_KINDS:
        identity = candidate_id or review_id or _text(_first(payload, "call_id", "callId"))
        return f"publication:{identity or 'unknown'}", "publication", None
    if kind in _REVIEW_KINDS:
        if collection_id and not candidate_id and not review_id:
            return f"review:collection:{collection_id}", "review", None
        identity = review_id or candidate_id or _text(_first(payload, "call_id", "callId"))
        parent = f"review:collection:{collection_id}" if collection_id else (f"generation:{candidate_id}" if candidate_id else None)
        return f"review:{identity or 'unknown'}", "review", parent
    if kind == "generated_chart" or tool_name in {"assemble_spec", "render_chart", "render_figure"}:
        identity = candidate_id or collection_id or _text(_first(payload, "call_id", "callId"))
        return f"generation:{identity or 'unknown'}", "generation", None
    if kind in {"tool_call", "tool_result", "visual_observation"}:
        if candidate_id or collection_id:
            identity = candidate_id or collection_id
            return f"generation:{identity}", "generation", None
        call_id = _text(_first(payload, "call_id", "callId"))
        return f"observation:{call_id or f'{kind}:{sequence or 0}'}", "observation", None
    return f"legacy:{_text(run_id, 96)}:{_text(kind, 48)}:{sequence or 0}", "legacy", None


def _parent_unit(payload: Mapping[str, Any], unit_id: str, inferred: str | None, unit_type: str) -> str | None:
    explicit = _text(_first(payload, "parent_unit_id", "parentUnitId"))
    if explicit and explicit != unit_id:
        return explicit
    if inferred and inferred != unit_id:
        return inferred
    if unit_type == "measurement":
        parent_attempt = _text(_first(payload, "parent_attempt", "parent_attempt_id", "parentAttempt", "parentAttemptId"))
        if parent_attempt:
            return f"measurement:{parent_attempt}"
    if unit_type == "review":
        collection_id = _collection_id(payload)
        candidate_id = _candidate_id(payload)
        if collection_id and unit_id != f"review:collection:{collection_id}":
            return f"review:collection:{collection_id}"
        if candidate_id and unit_id != f"generation:{candidate_id}":
            return f"generation:{candidate_id}"
    if unit_type == "publication":
        candidate_id = _candidate_id(payload)
        if candidate_id:
            return f"review:{_review_id(payload) or candidate_id}"
    return None


def _state(payload: Mapping[str, Any], kind: str) -> str:
    value = _first(payload, "state", "status", "review_status", "reviewStatus", "candidate_status", "candidateStatus", "publication_status", "publicationStatus", "decision_status", "decisionStatus")
    if value not in (None, ""):
        return _text(value, 64)
    return {"measurement_focus_requested": "pending", "measurement_focus_applied": "pending", "measurement_decision_required": "pending", "review_started": "reviewing", "chart_review_started": "reviewing"}.get(kind, "unknown")


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
    blocking = bool(payload.get("blocking"))
    if kind in {"measurement_focus_requested", "measurement_focus_applied"}:
        return {"required": bool(payload.get("required", False)), "allowed": ["observe_same_scope", "abandon"], "blocked": ["assemble", "publish"], "reason": "范围已应用，等待同一 measurement attempt 的 observation"}
    if kind == "measurement_focus_failed":
        return {"required": blocking, "allowed": ["request_same_scope_measurement", "abandon"], "blocked": ["assemble", "publish"], "reason": "局部范围没有形成足够 observation"}
    if kind in {"measurement_observed", "measurement_decision_required"}:
        return {"required": kind == "measurement_decision_required" or state in {"partial", "provisional", "pending"}, "allowed": ["select_evidence", "discard_evidence", "request_same_scope_measurement", "abandon"], "blocked": ["publish"], "reason": "先完成当前 attempt 的证据决策"}
    if kind in {"measurement_evidence_selected", "measurement_evidence_discarded"}:
        return {"required": False, "allowed": ["assemble"], "blocked": ["cross_scope_measurement"], "reason": "证据决策已记录，assemble 只消费当前 decision"}
    if kind in {"review_repair_required", "chart_review_repair_required"}:
        repair_kind = _text(_first(payload, "repair_kind", "repairKind"), 32) or "spec_only"
        allowed = {"evidence_needed": ["same_scope_evidence"], "source_rebind": ["rebind_source"], "spec_only": ["assemble"], "terminal": ["stop"]}.get(repair_kind, ["repair"])
        return {"required": True, "allowed": allowed, "blocked": ["publish"], "reason": "按 repair phase 顺序继续"}
    if kind in {"review_started", "chart_review_started", "review_gate_updated", "review_gate_required"} or blocking:
        return {"required": True, "allowed": ["deterministic_audit", "semantic_vlm_review", "repair", "wait"], "blocked": ["publish"], "reason": "审核门禁仍在阻塞主链路"}
    if kind in {"generated_chart_published", "generated_chart_rejected"}:
        return {"required": False, "allowed": [], "blocked": ["publish" if kind.endswith("rejected") else "duplicate_publish"], "reason": "该 publication transition 已终结"}
    return None


def _transition_id(kind: str, payload: Mapping[str, Any], unit_id: str, phase: str, state: str) -> str:
    explicit = _text(_first(payload, "transition_id", "transitionId"), 128)
    if explicit:
        return explicit
    review_id = _review_id(payload)
    candidate_id = _candidate_id(payload)
    if phase in {"review", "publish"} and (review_id or candidate_id):
        identity = {"unit": unit_id, "review": review_id, "candidate": candidate_id, "attempt": _first(payload, "attempt", "candidate_attempt", "candidateAttempt"), "phase": phase, "state": state}
    else:
        identity = {"unit": unit_id, "phase": phase, "state": state, "kind": kind, "attempt": _first(payload, "attempt", "candidate_attempt", "candidateAttempt"), "call": _first(payload, "call_id", "callId")}
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"transition:{digest[:24]}"


def enrich_event_payload(
    kind: str,
    payload: Mapping[str, Any] | None = None,
    *,
    run_id: str = "",
    sequence: int | None = None,
) -> dict[str, Any]:
    """Return the original payload plus a bounded deterministic envelope."""
    source = dict(payload or {})
    event_kind = str(kind or "")
    applicable = event_kind in _MEASUREMENT_KINDS or event_kind in _REVIEW_KINDS or event_kind in _PUBLICATION_KINDS or event_kind in {
        "tool_call",
        "tool_result",
        "visual_observation",
        "generated_chart",
        "assembly_validation_failure",
    }
    if not applicable and not _first(source, "unit_id", "unitId", "candidate_id", "candidateId", "review_id", "reviewId", "attempt_id", "attemptId"):
        # Preserve the exact payload shape for ordinary model/terminal events;
        # only decision-bearing events need correlation metadata.
        return source
    unit_id, unit_type, inferred_parent = _unit_identity(event_kind, source, run_id=run_id, sequence=sequence)
    phase = _phase(event_kind, source)
    actor = _actor(event_kind, source)
    state = _state(source, event_kind)
    envelope: dict[str, Any] = {
        "correlation_version": CORRELATION_VERSION,
        "unit_id": unit_id,
        "unit_type": unit_type,
        "phase": phase,
        "actor": actor,
        "role": _role(event_kind, phase),
        "parent_unit_id": _parent_unit(source, unit_id, inferred_parent, unit_type),
        "transition_id": _transition_id(event_kind, source, unit_id, phase, state),
    }
    action = _next_action(event_kind, source, phase, state)
    if action is not None:
        envelope["next_action"] = action
    source.update(envelope)
    return source


def legacy_envelope(run_id: str, sequence: int, kind: str) -> dict[str, str | int]:
    """Return a conservative client-side envelope for pre-correlation events."""
    return {
        "correlation_version": 0,
        "unit_id": f"legacy:{_text(run_id, 96)}:{_text(kind, 48)}:{max(0, int(sequence))}",
        "unit_type": "legacy",
        "phase": "unknown",
        "actor": "unknown",
        "role": "legacy",
    }


__all__ = ["ACTORS", "CORRELATION_VERSION", "PHASES", "ROLES", "UNIT_TYPES", "enrich_event_payload", "legacy_envelope"]
