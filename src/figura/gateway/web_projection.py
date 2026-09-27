"""Safe, read-only projections for the Figura local web API."""

from __future__ import annotations

from figura.runtime import (
    ActionKind,
    AttachmentMetadata,
    EventKind,
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    RecordKind,
    Run,
    RunInput,
    RunState,
    Session,
    SessionSnapshot,
    RunStreamEvent,
)


def session_summary(
    session: Session,
    run_count: int,
    latest_activity: str | None = None,
) -> dict[str, object]:
    return {
        "id": session.session_id,
        "name": session.name,
        "createdAt": session.created_at,
        "updatedAt": max(session.updated_at, latest_activity or session.updated_at),
        "runCount": run_count,
    }


def session_snapshot(snapshot: SessionSnapshot) -> dict[str, object]:
    runs = [run_summary(state) for state in snapshot.run_states]
    activity_values = [snapshot.session.updated_at]
    activity_values.extend(item.created_at for item in snapshot.attachments)
    activity_values.extend(state.run.finished_at or state.run.created_at for state in snapshot.run_states)
    session = session_summary(
        snapshot.session,
        len(snapshot.run_states),
        max(activity_values),
    )

    messages: list[dict[str, object]] = []
    for state in snapshot.run_states:
        input_record = next(
            (record for record in state.records if record.record_id == state.run.input_record_id),
            None,
        )
        if input_record is None or not isinstance(input_record.payload, RunInput):
            continue
        payload = input_record.payload
        messages.append(
            {
                "id": f"{state.run.run_id}:user",
                "runId": state.run.run_id,
                "kind": "user",
                "text": payload.text,
                "timestamp": input_record.created_at,
                **({"attachmentIds": list(payload.attachment_ids)} if payload.attachment_ids else {}),
            }
        )
        answer = _accepted_answer(state)
        if answer is not None:
            answer_text, timestamp = answer
            messages.append(
                {
                    "id": f"{state.run.run_id}:assistant",
                    "runId": state.run.run_id,
                    "kind": "assistant",
                    "text": answer_text,
                    "timestamp": timestamp,
                }
            )

    return {
        "session": session,
        "messages": messages,
        "attachments": [attachment(item) for item in snapshot.attachments],
        "runs": runs,
    }


def attachment(metadata: AttachmentMetadata) -> dict[str, object]:
    return {
        "id": metadata.attachment_id,
        "filename": metadata.filename,
        "mediaType": metadata.media_type,
        "byteCount": metadata.byte_count,
        "createdAt": metadata.created_at,
    }


def run_summary(state: RunState) -> dict[str, object]:
    run = state.run
    action = state.checkpoint.next_action
    needs_reconciliation = (
        run.status.value == "running"
        and action is not None
        and action.action_kind is ActionKind.TOOL_ATTEMPT
    )
    return {
        "runId": run.run_id,
        "sessionId": run.session_id,
        "ordinal": run.ordinal,
        "status": run.status.value,
        "provider": run.provider,
        "model": run.model,
        "createdAt": run.created_at,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "terminalCode": run.terminal_code,
        "terminalMessage": run.terminal_message,
        "executionState": "needs_reconciliation" if needs_reconciliation else "active",
    }


def run_handle(run: Run) -> dict[str, object]:
    return {
        "runId": run.run_id,
        "sessionId": run.session_id,
        "ordinal": run.ordinal,
        "status": run.status.value,
        "provider": run.provider,
        "model": run.model,
        "createdAt": run.created_at,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "terminalCode": run.terminal_code,
        "terminalMessage": run.terminal_message,
    }


def run_history(state: RunState, after_sequence: int = 0) -> dict[str, object]:
    events = [
        event_projection(state, event)
        for event in state.events
        if event.event_sequence > after_sequence
    ]
    return {"run": run_summary(state), "events": events, "historyGap": False}


def event_projection(state: RunState, event: RunStreamEvent) -> dict[str, object]:
    payload: dict[str, object]
    if event.event_kind is EventKind.RUN_CREATED:
        payload = {"ordinal": state.run.ordinal}
    elif event.event_kind is EventKind.RUN_COMPLETED:
        payload = {}
    else:
        payload = {"terminalCode": state.run.terminal_code}
    return {
        "runId": state.run.run_id,
        "sequence": event.event_sequence,
        "kind": event.event_kind.value,
        "timestamp": event.created_at,
        "payload": payload,
    }


def event_id(state: RunState, event: RunStreamEvent) -> str:
    return f"{state.run.run_id}:{event.event_sequence}"


def _accepted_answer(state: RunState) -> tuple[str, str] | None:
    if state.run.final_record_id is None:
        return None
    final_record = next(
        (record for record in state.records if record.record_id == state.run.final_record_id),
        None,
    )
    if (
        final_record is None
        or final_record.record_kind is not RecordKind.FINAL_ANSWER
        or not isinstance(final_record.payload, FinalAnswerFact)
    ):
        return None
    response_record = next(
        (
            record
            for record in state.records
            if record.record_id == final_record.payload.response_record_id
        ),
        None,
    )
    if (
        response_record is None
        or response_record.record_kind is not RecordKind.MODEL_RESPONSE
        or not isinstance(response_record.payload, ModelResponseFact)
    ):
        return None
    return response_record.payload.assistant_content, final_record.created_at
