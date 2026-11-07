"""Project periodic task-reflection metadata from committed Run responses."""

from __future__ import annotations

from figura.runtime.models import RecordKind
from figura.runtime.records import RunState


TASK_REFLECTION_INTERVAL_ROUNDS = 20


def project_task_reflection(state: RunState) -> dict[str, int] | None:
    """Return a cue only after each twentieth committed model response."""
    if not isinstance(state, RunState):
        raise TypeError("state must be a RunState")

    completed_rounds = sum(
        record.record_kind is RecordKind.MODEL_RESPONSE
        for record in state.records
    )
    if (
        completed_rounds == 0
        or completed_rounds % TASK_REFLECTION_INTERVAL_ROUNDS != 0
    ):
        return None
    return {
        "completed_rounds": completed_rounds,
        "interval_rounds": TASK_REFLECTION_INTERVAL_ROUNDS,
    }
