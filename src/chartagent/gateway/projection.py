"""Convert durable Agent memory into the narrow gateway transcript contract."""

from __future__ import annotations

from typing import Iterable

from ..memory.models import Record, Run, RunStatus, Session, SessionStats
from .protocol import AttachmentSummary, ConversationText, SessionSummary, SessionTranscript

REGISTERED_ATTACHMENT_MARKER = "\n\nRegistered image attachments (load with load_image when useful):"


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


def _attachment_ids(run: Run) -> tuple[str, ...]:
    return tuple(
        str(record.payload["attachment_id"])
        for record in run.records
        if record.kind == "attachment" and record.payload.get("attachment_id")
    )


def _display_user_text(text: str) -> str:
    return text.split(REGISTERED_ATTACHMENT_MARKER, 1)[0].rstrip()


def project_completed_runs(
    session: Session,
    runs: Iterable[Run],
    attachments: Iterable[AttachmentSummary | dict] = (),
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
        attachment_ids = _attachment_ids(run)
        messages.extend(
            (
                ConversationText(
                    f"{run.id}:user",
                    "user",
                    _display_user_text(user[0]),
                    user[1],
                    attachment_ids,
                ),
                ConversationText(f"{run.id}:assistant", "assistant", final[0], final[1]),
            )
        )
    summary = SessionSummary(session.id, session.name, latest_timestamp, completed_count)
    projected = tuple(
        item.to_dict() if isinstance(item, AttachmentSummary) else dict(item)
        for item in attachments
    )
    return SessionTranscript(summary, tuple(messages), projected)
