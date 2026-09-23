"""Code-owned compact state shared by the Agent prompt and timeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MAX_DECISION_REFS = 32
MAX_DECISION_ISSUES = 12


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
    """Build bounded factual context without creating a business action contract.

    The Agent still needs to know which source, candidate, evidence and review
    state it is looking at.  It does not need a code-owned list of the only
    actions it may take.  Actual tool calls remain protected by each tool's
    authorization, scope, lineage and structure validation.
    """
    gate = dict(execution_gate or {})
    blocking = bool(gate.get("blocking"))
    repair_kind = _text(gate.get("repairKind") or gate.get("repair_kind"), 32) or "none"
    review_id = _text(gate.get("reviewId") or gate.get("review_id"))
    subject_id = _text(gate.get("subjectId") or gate.get("subject_id"))
    current_evidence = next((item for item in measurement_evidence if isinstance(item, Mapping)), None)
    measurement_ref = (
        current_evidence.get("measurement_ref")
        if isinstance(current_evidence, Mapping) and isinstance(current_evidence.get("measurement_ref"), Mapping)
        else {}
    )
    if review_id:
        current_unit = f"review:{review_id}"
        current_phase = _text(phase, 32) or "model"
        status = _text(gate.get("state"), 48) or ("blocked" if blocking else "ready")
    elif current_evidence is not None:
        attempt_id = _text(measurement_ref.get("attempt_id")) or "unknown"
        current_unit = f"measurement:{attempt_id}"
        current_phase = _text(phase, 32) or "model"
        status = _text(current_evidence.get("status"), 48) or "available"
    else:
        current_unit = None
        current_phase = _text(phase, 32) or "model"
        status = "ready"
    compact_evidence: dict[str, Any] | None = None
    if current_evidence is not None:
        compact_evidence = {
            key: current_evidence.get(key)
            for key in (
                "measurement_ref",
                "session_id",
                "attempt_id",
                "attachment_id",
                "panel_id",
                "tool",
                "status",
                "scope",
                "observation_scope",
                "effective_scope",
                "evidence_refs",
                "series_metadata",
                "warnings",
                "issues",
            )
            if current_evidence.get(key) is not None
        }
        for key in ("evidence_refs", "series_metadata"):
            if isinstance(compact_evidence.get(key), list):
                compact_evidence[key] = compact_evidence[key][:MAX_DECISION_REFS]
        for key in ("warnings", "issues"):
            if isinstance(compact_evidence.get(key), list):
                compact_evidence[key] = compact_evidence[key][:MAX_DECISION_ISSUES]

    attachment_ids: list[str] = []
    for value in (
        selected_panel.get("source_attachment_id") if isinstance(selected_panel, Mapping) else None,
        selected_panel.get("attachment_id") if isinstance(selected_panel, Mapping) else None,
        current_evidence.get("attachment_id") if current_evidence is not None else None,
    ):
        normalized = _text(value, 96)
        if normalized and normalized not in attachment_ids:
            attachment_ids.append(normalized)
    source_scope = generation_context.get("source_scope") if isinstance(generation_context, Mapping) else None
    if isinstance(source_scope, Mapping):
        normalized = _text(source_scope.get("attachment_id"), 96)
        if normalized and normalized not in attachment_ids:
            attachment_ids.append(normalized)

    panel_id = (
        _text(selected_panel.get("panel_id"), 96)
        if isinstance(selected_panel, Mapping)
        else None
    ) or (_text(current_evidence.get("panel_id"), 96) if current_evidence is not None else None)
    hard_constraints: list[str] = []
    if blocking and review_id:
        hard_constraints.append("current_candidate_not_publishable")
    if repair_kind == "terminal" or _text(gate.get("state"), 48) in {"exhausted", "terminal"}:
        hard_constraints.append("review_recovery_terminal")
    if blocking and retry_budget <= 0:
        hard_constraints.append("retry_budget_exhausted")
    review: dict[str, Any] | None = None
    if review_id or blocking:
        review = {
            "review_id": review_id,
            "candidate_id": subject_id,
            "state": _text(gate.get("state"), 48),
            "repair_kind": repair_kind,
            "repair_hint": _text(gate.get("nextAction") or gate.get("next_action"), 240),
            "publication_blocked": blocking,
        }
    return {
        "run_id": _text(run_id, 96),
        "unit_id": current_unit,
        "unit_type": "review" if review_id else "measurement" if current_evidence is not None else "unknown",
        "phase": current_phase,
        "status": status,
        "scope": {
            "panel_id": panel_id,
            "attachment_ids": attachment_ids[:16],
        },
        "evidence": compact_evidence,
        "candidate_id": subject_id,
        "generation_context": dict(generation_context) if isinstance(generation_context, Mapping) else None,
        "review": review,
        "repair_hint": _text(gate.get("nextAction") or gate.get("next_action"), 240),
        "hard_constraints": hard_constraints,
        "publication_status": "blocked" if blocking else "not_published",
        "budget_remaining": max(0, int(retry_budget or 0)),
    }


__all__ = ["build_decision_context"]
