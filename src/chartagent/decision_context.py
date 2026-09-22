"""Code-owned compact state shared by the Agent prompt and timeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MAX_DECISION_REFS = 32
MAX_DECISION_ACTIONS = 12


def _text(value: object, limit: int = 160) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


def build_decision_context(
    *,
    run_id: str,
    execution_gate: Mapping[str, Any] | None = None,
    measurement_evidence: Sequence[Mapping[str, Any]] = (),
    selected_panel: Mapping[str, Any] | None = None,
    generation_context: Mapping[str, Any] | None = None,
    phase: str = "model",
    retry_budget: int = 0,
) -> dict[str, Any]:
    """Build a bounded action contract without copying the whole timeline."""
    gate = dict(execution_gate or {})
    blocking = bool(gate.get("blocking"))
    repair_kind = _text(gate.get("repairKind") or gate.get("repair_kind"), 32) or "none"
    review_id = _text(gate.get("reviewId") or gate.get("review_id"))
    subject_id = _text(gate.get("subjectId") or gate.get("subject_id"))
    current_evidence = next((item for item in measurement_evidence if isinstance(item, Mapping)), None)
    if blocking and review_id:
        current_unit = f"review:{review_id}"
        current_phase = _text(gate.get("repairPhase") or gate.get("repair_phase"), 32) or "review"
        status = _text(gate.get("state"), 48) or "blocked"
        if repair_kind == "evidence_needed":
            allowed = ["same_scope_measurement", "abandon_evidence"]
            blocked = ["cross_scope_measurement", "assemble", "publish"]
        elif repair_kind == "spec_only":
            allowed = ["assemble", "correct_chart_spec"]
            blocked = ["measure_other_scope", "publish"]
        elif repair_kind == "source_rebind":
            allowed = ["rebind_source"]
            blocked = ["measure_old_scope", "assemble", "publish"]
        else:
            allowed = ["stop_and_keep_unpublished"]
            blocked = ["assemble", "render", "publish"]
        required = True
    elif current_evidence is not None:
        attempt_id = _text(current_evidence.get("attempt_id")) or "unknown"
        current_unit = f"measurement:{attempt_id}"
        current_phase = "decide"
        status = _text(current_evidence.get("decision_status") or current_evidence.get("status"), 48) or "pending"
        allowed = ["select_evidence", "discard_evidence", "same_scope_measurement", "abandon_evidence"]
        blocked = ["publish"]
        required = False
    else:
        current_unit = None
        current_phase = phase
        status = "ready"
        allowed = ["observe", "measure", "assemble", "render"]
        blocked = []
        required = False
    compact_evidence: dict[str, Any] | None = None
    if current_evidence is not None:
        compact_evidence = {
            key: current_evidence.get(key)
            for key in (
                "session_id",
                "attempt_id",
                "attachment_id",
                "panel_id",
                "decision_status",
                "observation_scope",
                "effective_scope",
                "selected_refs",
                "discarded_refs",
                "refs",
                "budget_remaining",
            )
            if current_evidence.get(key) is not None
        }
        for key in ("selected_refs", "discarded_refs", "refs"):
            if isinstance(compact_evidence.get(key), list):
                compact_evidence[key] = compact_evidence[key][:MAX_DECISION_REFS]
    return {
        "unit_id": current_unit,
        "unit_type": "review" if blocking and review_id else "measurement" if current_evidence is not None else "unknown",
        "phase": current_phase,
        "status": status,
        "required": required,
        "scope": {
            "panel_id": selected_panel.get("panel_id") if isinstance(selected_panel, Mapping) else None,
            "attachment_ids": [],
        },
        "evidence": compact_evidence,
        "candidate_id": subject_id,
        "generation_context": dict(generation_context) if isinstance(generation_context, Mapping) else None,
        "allowed_actions": allowed[:MAX_DECISION_ACTIONS],
        "blocked_actions": blocked[:MAX_DECISION_ACTIONS],
        "next_action": _text(gate.get("nextAction") or gate.get("next_action"), 240) or (
            "完成同一 scope 的 observation 或明确 abandon" if required and repair_kind == "evidence_needed" else "由主 Agent 选择当前 evidence 或继续观察"
        ),
        "budget_remaining": max(0, int(retry_budget or 0)),
    }


__all__ = ["build_decision_context"]
