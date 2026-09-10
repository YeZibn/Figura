"""Convert durable Agent memory into the narrow gateway transcript contract."""

from __future__ import annotations

from typing import Iterable

from ..memory.models import Record, Run, RunStatus, Session, SessionStats
from .protocol import ConversationText, SessionSummary, SessionTranscript


def session_summary(stats: SessionStats) -> SessionSummary:
    return SessionSummary(
        id=stats.session.id,
        name=stats.session.name,
        updated_at=stats.session.updated_at,
        run_count=stats.completed_run_count,
    )


def _record_text(run: Run, kind: str, field: str) -> tuple[str, str] | None:
    for record in run.records:
        if record.kind != kind:
            continue
        value = record.payload.get(field)
        if isinstance(value, str) and value.strip():
            return value, record.created_at
    return None


def project_completed_runs(
    session: Session,
    runs: Iterable[Run],
) -> SessionTranscript:
    """Project complete user/final pairs and omit protocol/tool internals."""
    messages: list[ConversationText] = []
    completed_count = 0
    latest_timestamp = session.updated_at
    for run in runs:
        if run.status != RunStatus.COMPLETED:
            continue
        user = _record_text(run, "user", "text")
        final = _record_text(run, "final", "answer")
        if user is None or final is None:
            continue
        completed_count += 1
        latest_timestamp = max(latest_timestamp, run.updated_at)
        messages.extend(
            (
                ConversationText(f"{run.id}:user", "user", user[0], user[1]),
                ConversationText(f"{run.id}:assistant", "assistant", final[0], final[1]),
            )
        )
    summary = SessionSummary(session.id, session.name, latest_timestamp, completed_count)
    return SessionTranscript(summary, tuple(messages), ())
