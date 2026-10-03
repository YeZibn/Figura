"""RunTransitionRepository keeps its Runtime transaction family atomic."""

from __future__ import annotations

import uuid

from figura.providers.models import FinishReason
from figura.storage.database import SqliteDatabase, _utc_now

from ..codecs.events import encode_event_payload
from ..codecs.records import encode_payload
from ..errors import (
    RunError,
    RunErrorCode,
)
from ..models import (
    ActionKind,
    EventKind,
    RecordKind,
    Run,
    RunStatus,
    TERMINAL_MESSAGES,
    PREPARATION_MESSAGES,
    TerminalCode,
)
from ..records import (
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
)
from .mappers import _record_from_row
from .controls import assert_not_stopped, read_stop_request
from .runs import RunRepository
from .transaction_helpers import _next_event_sequence


class RunTransitionRepository:
    def __init__(self, database: SqliteDatabase, runs: RunRepository) -> None:
        self._database = database
        self._runs = runs

    def complete_run(
        self, *, session_id: str, run_id: str, expected_revision: int
    ) -> ExecutionRecord:
        now = _utc_now()
        with self._database.write() as connection:
            assert_not_stopped(connection, run_id)
            current_state = self._runs._read_run_state_from_connection(connection, session_id, run_id)
            run = current_state.run
            checkpoint = current_state.checkpoint
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            action = checkpoint.next_action
            if action is None or action.action_kind is not ActionKind.FINAL or not action.response_record_id:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            response_row = connection.execute(
                "SELECT * FROM run_execution_records WHERE record_id = ? AND run_id = ?",
                (action.response_record_id, run_id),
            ).fetchone()
            if response_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_record = _record_from_row(response_row)
            if response_record.record_kind is not RecordKind.MODEL_RESPONSE:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response = response_record.payload
            if not isinstance(response, ModelResponseFact) or response.finish_reason != FinishReason.STOP.value:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if not response.assistant_content.strip():
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            final_record_id = uuid.uuid4().hex
            sequence = checkpoint.last_committed_record_sequence + 1
            payload = FinalAnswerFact(response_record_id=response_record.record_id)
            raw_payload = encode_payload(RecordKind.FINAL_ANSWER, payload)
            connection.execute(
                "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
                "VALUES (?, ?, ?, 'final_answer', 2, ?, ?)",
                (final_record_id, run_id, sequence, raw_payload, now),
            )
            cursor = connection.execute(
                "UPDATE runs SET status = 'completed', finished_at = ?, final_record_id = ? "
                "WHERE run_id = ? AND session_id = ? AND status = 'running'",
                (now, final_record_id, run_id, session_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET schema_version = 2, revision = revision + 1, last_committed_record_sequence = ?, "
                "next_action_json = NULL, updated_at = ? WHERE run_id = ? AND revision = ?",
                (sequence, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            event_sequence = _next_event_sequence(connection, run_id)
            event_json = encode_event_payload(EventKind.RUN_COMPLETED, {"final_artifact_refs": ()})
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, ?, 'run_completed', ?, ?)",
                (run_id, event_sequence, event_json, now),
            )
        return ExecutionRecord(final_record_id, run_id, sequence, RecordKind.FINAL_ANSWER, payload, now)

    def terminal_run(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        status: RunStatus,
        terminal_code: TerminalCode,
        terminal_message: str | None = None,
    ) -> Run:
        if status not in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        if (status is RunStatus.INTERRUPTED) != (terminal_code is TerminalCode.INTERRUPTED):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        now = _utc_now()
        event_kind = EventKind.RUN_INTERRUPTED if status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
        if terminal_message is not None:
            try:
                valid = isinstance(terminal_message, str) and 0 < len(terminal_message.encode("utf-8")) <= 256
            except UnicodeEncodeError:
                valid = False
            if (
                not valid
                or terminal_code is not TerminalCode.EXECUTION_FAILED
                or terminal_message not in PREPARATION_MESSAGES.values()
            ):
                raise RunError(RunErrorCode.INVALID_REQUEST)
        message = terminal_message if terminal_message is not None else TERMINAL_MESSAGES[terminal_code]
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if read_stop_request(connection, run_id) is not None:
                status = RunStatus.INTERRUPTED
                terminal_code = TerminalCode.INTERRUPTED
                message = TERMINAL_MESSAGES[terminal_code]
                event_kind = EventKind.RUN_INTERRUPTED
            if status is RunStatus.INTERRUPTED:
                connection.execute(
                    "UPDATE run_provider_attempts SET status = 'outcome_unknown', failure_category = 'permanent', finished_at = ? "
                    "WHERE run_id = ? AND status = 'started'", (now, run_id),
                )
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            cursor = connection.execute(
                "UPDATE runs SET status = ?, finished_at = ?, terminal_code = ?, terminal_message = ? "
                "WHERE run_id = ? AND session_id = ? AND status = 'running'",
                (status.value, now, terminal_code.value, message, run_id, session_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET schema_version = 2, revision = revision + 1, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            event_sequence = _next_event_sequence(connection, run_id)
            event_json = encode_event_payload(event_kind, {"terminal_code": terminal_code.value})
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, event_sequence, event_kind.value, event_json, now),
            )
        return Run(
            run_id=run.run_id,
            session_id=run.session_id,
            ordinal=run.ordinal,
            input_record_id=run.input_record_id,
            status=status,
            provider=run.provider,
            model=run.model,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=now,
            terminal_code=terminal_code.value,
            terminal_message=message,
        )
