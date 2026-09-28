"""ProviderRepository keeps its Runtime transaction family atomic."""

from __future__ import annotations

import uuid

from figura.providers.errors import ProviderFailureCode
from figura.providers.models import (
    FinishReason,
    ProviderContinuation,
    ProviderId,
)
from figura.storage.database import SqliteDatabase, _utc_now

from ..codecs.events import encode_event_payload
from ..codecs.records import (
    encode_payload,
    validate_provider_continuation_fact,
)
from ..codecs.tools import (
    decode_tool_fact,
    encode_tool_fact,
    validate_tool_call_batch,
)
from ..errors import (
    RunError,
    RunErrorCode,
)
from ..models import (
    ActionKind,
    EventKind,
    NextAction,
    ProviderAttemptStatus,
    RecordKind,
    Run,
    RunStatus,
    TERMINAL_MESSAGES,
    TerminalCode,
    ToolFactKind,
)
from ..records import (
    ExecutionRecord,
    ModelResponseFact,
    ProviderAttempt,
    ProviderContinuationFact,
    ToolCallFact,
)
from ..validation import _validate_id
from .mappers import _encode_action
from .runs import RunRepository
from .transaction_helpers import _next_event_sequence


class ProviderRepository:
    def __init__(self, database: SqliteDatabase, runs: RunRepository) -> None:
        self._database = database
        self._runs = runs

    def begin_provider_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
    ) -> ProviderAttempt:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        _validate_id(attempt_id)
        now = _utc_now()
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if checkpoint.next_action != NextAction(ActionKind.MODEL):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            attempt_sequence = int(
                connection.execute(
                    "SELECT COUNT(*) FROM run_provider_attempts WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            ) + 1
            if attempt_sequence > 8:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            connection.execute(
                "INSERT INTO run_provider_attempts(attempt_id, run_id, attempt_sequence, "
                "base_record_sequence, base_tool_sequence, status, response_record_id, failure_code, "
                "started_at, finished_at) VALUES (?, ?, ?, ?, ?, 'started', NULL, NULL, ?, NULL)",
                (
                    attempt_id,
                    run_id,
                    attempt_sequence,
                    checkpoint.last_committed_record_sequence,
                    checkpoint.last_committed_tool_sequence,
                    now,
                ),
            )
            action_json = _encode_action(
                NextAction(ActionKind.PROVIDER_ATTEMPT, attempt_id=attempt_id)
            )
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, next_action_json = ?, "
                "updated_at = ? WHERE run_id = ? AND revision = ?",
                (action_json, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
        return ProviderAttempt(
            attempt_id=attempt_id,
            run_id=run_id,
            attempt_sequence=attempt_sequence,
            base_record_sequence=checkpoint.last_committed_record_sequence,
            base_tool_sequence=checkpoint.last_committed_tool_sequence,
            status=ProviderAttemptStatus.STARTED,
            response_record_id=None,
            failure_code=None,
            started_at=now,
            finished_at=None,
        )

    def commit_model_response(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        provider_attempt_id: str,
        payload: ModelResponseFact,
        record_id: str | None = None,
        tool_calls: tuple[ToolCallFact, ...] = (),
        continuation: ProviderContinuation | None = None,
        continuation_id: str | None = None,
    ) -> ExecutionRecord:
        if not isinstance(provider_attempt_id, str) or not provider_attempt_id:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        _validate_id(provider_attempt_id)
        if (
            not isinstance(payload, ModelResponseFact)
            or type(payload.schema_version) is not int
            or payload.schema_version != 2
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        if (
            (continuation is None) != (continuation_id is None)
            or payload.continuation_ref != continuation_id
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        raw_payload = encode_payload(RecordKind.MODEL_RESPONSE, payload)
        if not isinstance(tool_calls, tuple):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if tool_calls:
            validate_tool_call_batch(tool_calls)
            if payload.finish_reason != FinishReason.TOOL_CALLS.value:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if len({call.registry_version for call in tool_calls}) != 1:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        elif payload.finish_reason == FinishReason.TOOL_CALLS.value:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        record_id = record_id or uuid.uuid4().hex
        _validate_id(record_id)
        raw_tool_facts = tuple(
            encode_tool_fact(ToolFactKind.TOOL_CALL, call) for call in tool_calls
        )
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            expected_action = NextAction(
                ActionKind.PROVIDER_ATTEMPT, attempt_id=provider_attempt_id
            )
            if checkpoint.next_action != expected_action:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            attempt_row = connection.execute(
                "SELECT * FROM run_provider_attempts WHERE run_id = ? AND attempt_id = ?",
                (run_id, provider_attempt_id),
            ).fetchone()
            if (
                attempt_row is None
                or attempt_row["status"] != ProviderAttemptStatus.STARTED.value
                or attempt_row["base_record_sequence"] != checkpoint.last_committed_record_sequence
                or attempt_row["base_tool_sequence"] != checkpoint.last_committed_tool_sequence
            ):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if payload.provider_id != run.provider or payload.model_id != run.model:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            now = _utc_now()
            continuation_fact: ProviderContinuationFact | None = None
            if continuation is not None:
                if not isinstance(continuation, ProviderContinuation):
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                if not isinstance(continuation_id, str) or not continuation_id:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                try:
                    continuation_provider = ProviderId(continuation.provider_id)
                except (TypeError, ValueError):
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
                continuation_fact = ProviderContinuationFact(
                    continuation_id=continuation_id,
                    run_id=run_id,
                    response_record_id=record_id,
                    provider_id=continuation_provider.value,
                    format_version=continuation.format_version,
                    schema_version=1,
                    reasoning_content=continuation.reasoning_content,
                    created_at=now,
                )
                validate_provider_continuation_fact(continuation_fact)
            if continuation_fact is not None and (
                continuation_fact.run_id != run_id
                or continuation_fact.response_record_id != record_id
                or continuation_fact.provider_id != run.provider
                or payload.continuation_ref != continuation_fact.continuation_id
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if any(call.response_record_id != record_id for call in tool_calls):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            existing_call_ids: set[str] = set()
            existing_call_rows = connection.execute(
                "SELECT schema_version, payload_json FROM run_tool_execution_facts "
                "WHERE run_id = ? AND fact_kind = 'tool_call'",
                (run_id,),
            ).fetchall()
            for existing_call_row in existing_call_rows:
                existing_call = decode_tool_fact(
                    ToolFactKind.TOOL_CALL,
                    existing_call_row["schema_version"],
                    existing_call_row["payload_json"],
                )
                if isinstance(existing_call, ToolCallFact):
                    existing_call_ids.add(existing_call.call_id)
            if any(call.call_id in existing_call_ids for call in tool_calls):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            sequence = checkpoint.last_committed_record_sequence + 1
            connection.execute(
                "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
                "VALUES (?, ?, ?, 'model_response', ?, ?, ?)",
                (record_id, run_id, sequence, payload.schema_version, raw_payload, now),
            )
            if continuation_fact is not None:
                connection.execute(
                    "INSERT INTO run_provider_continuations(continuation_id, run_id, response_record_id, provider_id, "
                    "format_version, schema_version, reasoning_content, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        continuation_fact.continuation_id,
                        continuation_fact.run_id,
                        continuation_fact.response_record_id,
                        continuation_fact.provider_id,
                        continuation_fact.format_version,
                        continuation_fact.schema_version,
                        continuation_fact.reasoning_content,
                        continuation_fact.created_at,
                    ),
                )
            first_tool_sequence = checkpoint.last_committed_tool_sequence + 1
            for offset, (call, raw_fact) in enumerate(zip(tool_calls, raw_tool_facts)):
                connection.execute(
                    "INSERT INTO run_tool_execution_facts(run_id, tool_sequence, fact_kind, schema_version, payload_json, created_at) "
                    "VALUES (?, ?, 'tool_call', 1, ?, ?)",
                    (run_id, first_tool_sequence + offset, raw_fact, now),
                )
            attempt_cursor = connection.execute(
                "UPDATE run_provider_attempts SET status = 'response_committed', response_record_id = ?, "
                "finished_at = ? WHERE run_id = ? AND attempt_id = ? AND status = 'started'",
                (record_id, now, run_id, provider_attempt_id),
            )
            if attempt_cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            next_action = _encode_action(
                NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=first_tool_sequence)
                if tool_calls
                else NextAction(ActionKind.FINAL, record_id)
            )
            last_tool_sequence = checkpoint.last_committed_tool_sequence + len(tool_calls)
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, last_committed_record_sequence = ?, "
                "last_committed_tool_sequence = ?, "
                "next_action_json = ?, updated_at = ? WHERE run_id = ? AND revision = ?",
                (sequence, last_tool_sequence, next_action, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
        return ExecutionRecord(record_id, run_id, sequence, RecordKind.MODEL_RESPONSE, payload, now)

    def fail_provider_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
        outcome_unknown: bool,
        failure_code: str | None,
    ) -> Run:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        _validate_id(attempt_id)
        if type(outcome_unknown) is not bool:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if failure_code is not None:
            if not isinstance(failure_code, str):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            try:
                failure_code = ProviderFailureCode(failure_code).value
            except ValueError:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        if not outcome_unknown and failure_code is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

        terminal_code = (
            TerminalCode.PROVIDER_OUTCOME_UNKNOWN
            if outcome_unknown
            else TerminalCode.EXECUTION_FAILED
        )
        attempt_status = (
            ProviderAttemptStatus.OUTCOME_UNKNOWN
            if outcome_unknown
            else ProviderAttemptStatus.KNOWN_FAILURE
        )
        now = _utc_now()
        message = TERMINAL_MESSAGES[terminal_code]
        event_json = encode_event_payload(
            EventKind.RUN_FAILED, {"terminal_code": terminal_code.value}
        )
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            expected_action = NextAction(
                ActionKind.PROVIDER_ATTEMPT, attempt_id=attempt_id
            )
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if checkpoint.next_action != expected_action:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            attempt_row = connection.execute(
                "SELECT status FROM run_provider_attempts WHERE run_id = ? AND attempt_id = ?",
                (run_id, attempt_id),
            ).fetchone()
            if attempt_row is None or attempt_row["status"] != ProviderAttemptStatus.STARTED.value:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE run_provider_attempts SET status = ?, failure_code = ?, finished_at = ? "
                "WHERE run_id = ? AND attempt_id = ? AND status = 'started'",
                (attempt_status.value, failure_code, now, run_id, attempt_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE runs SET status = 'failed', finished_at = ?, terminal_code = ?, terminal_message = ? "
                "WHERE run_id = ? AND session_id = ? AND status = 'running'",
                (now, terminal_code.value, message, run_id, session_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            event_sequence = _next_event_sequence(connection, run_id)
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, ?, 'run_failed', ?, ?)",
                (run_id, event_sequence, event_json, now),
            )
        return Run(
            run_id=run.run_id,
            session_id=run.session_id,
            ordinal=run.ordinal,
            input_record_id=run.input_record_id,
            status=RunStatus.FAILED,
            provider=run.provider,
            model=run.model,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=now,
            terminal_code=terminal_code.value,
            terminal_message=message,
        )
