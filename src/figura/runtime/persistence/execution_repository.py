"""Atomic provider, tool, and terminal Run transitions."""

from __future__ import annotations

import sqlite3
import uuid

from figura.providers.errors import ProviderFailureCode
from figura.providers.models import FinishReason, ProviderContinuation, ProviderId
from figura.tools.contracts import ReplayEffect, ToolExecutionResult

from .._codec import (
    decode_tool_fact,
    encode_event_payload,
    encode_payload,
    encode_tool_fact,
    validate_provider_continuation_fact,
    validate_tool_call_batch,
)
from ..domain.invariants import _utf8_length, _validate_id
from ..domain.models import (
    ActionKind,
    EventKind,
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    NextAction,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderContinuationFact,
    RecordKind,
    Run,
    RunStatus,
    TERMINAL_MESSAGES,
    TerminalCode,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolFactKind,
    ToolResultFact,
)
from ..errors import RunError, RunErrorCode
from .database import SqliteDatabase, _utc_now
from .mappers import (
    _encode_action,
    _record_from_row,
    _tool_fact_from_row,
)
from .run_repository import RunRepository


def _insert_tool_fact(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    tool_sequence: int,
    kind: ToolFactKind,
    payload: ToolCallFact | ToolAttemptStartedFact | ToolResultFact,
    created_at: str,
) -> ToolExecutionFact:
    raw_payload = encode_tool_fact(kind, payload)
    connection.execute(
        "INSERT INTO run_tool_execution_facts(run_id, tool_sequence, fact_kind, schema_version, payload_json, created_at) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (run_id, tool_sequence, kind.value, raw_payload, created_at),
    )
    return ToolExecutionFact(
        run_id=run_id,
        tool_sequence=tool_sequence,
        fact_kind=kind,
        schema_version=1,
        payload=payload,
        created_at=created_at,
    )


def _next_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM run_stream_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


class ExecutionRepository:
    """Own complete provider, tool, checkpoint, and terminal transactions."""

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

    def begin_tool_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        tool_call_sequence: int,
        registry_version: str,
        replay_effect: ReplayEffect,
        attempt_id: str | None = None,
    ) -> ToolExecutionFact:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if type(tool_call_sequence) is not int or tool_call_sequence < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(registry_version, str) or not registry_version or _utf8_length(registry_version) > 128:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        try:
            effect = ReplayEffect(replay_effect)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        attempt_id = attempt_id or uuid.uuid4().hex
        _validate_id(attempt_id)
        now = _utc_now()

        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            expected_action = NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=tool_call_sequence)
            if checkpoint.next_action != expected_action:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            call_row = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND tool_sequence = ?",
                (run_id, tool_call_sequence),
            ).fetchone()
            if call_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call_fact = _tool_fact_from_row(call_row)
            if call_fact.fact_kind is not ToolFactKind.TOOL_CALL or not isinstance(call_fact.payload, ToolCallFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_fact.payload
            if call.registry_version != registry_version:
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            attempt_rows = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_attempt_started' "
                "ORDER BY tool_sequence",
                (run_id,),
            ).fetchall()
            attempt_number = 1
            for row in attempt_rows:
                existing = _tool_fact_from_row(row)
                if (
                    isinstance(existing.payload, ToolAttemptStartedFact)
                    and existing.payload.tool_call_sequence == tool_call_sequence
                ):
                    attempt_number += 1
            start = ToolAttemptStartedFact(
                tool_call_sequence=tool_call_sequence,
                call_id=call.call_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                replay_effect=effect,
                registry_version=registry_version,
            )
            tool_sequence = checkpoint.last_committed_tool_sequence + 1
            fact = _insert_tool_fact(
                connection,
                run_id=run_id,
                tool_sequence=tool_sequence,
                kind=ToolFactKind.TOOL_ATTEMPT_STARTED,
                payload=start,
                created_at=now,
            )
            action_json = _encode_action(
                NextAction(
                    ActionKind.TOOL_ATTEMPT,
                    tool_call_sequence=tool_call_sequence,
                    attempt_id=attempt_id,
                )
            )
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, "
                "last_committed_tool_sequence = ?, next_action_json = ?, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (tool_sequence, action_json, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
        return fact

    def begin_tool_replay_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        tool_call_sequence: int,
        previous_attempt_id: str,
        registry_version: str,
        attempt_id: str | None = None,
    ) -> ToolExecutionFact:
        """Append a replay attempt for an unresolved call after its owner lock is held."""
        if (
            type(expected_revision) is not int
            or expected_revision < 1
            or type(tool_call_sequence) is not int
            or tool_call_sequence < 1
        ):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        _validate_id(previous_attempt_id)
        if not isinstance(registry_version, str) or not registry_version or _utf8_length(registry_version) > 128:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        attempt_id = attempt_id or uuid.uuid4().hex
        _validate_id(attempt_id)
        now = _utc_now()

        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if checkpoint.next_action != NextAction(
                ActionKind.TOOL_ATTEMPT,
                tool_call_sequence=tool_call_sequence,
                attempt_id=previous_attempt_id,
            ):
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            call_row = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND tool_sequence = ?",
                (run_id, tool_call_sequence),
            ).fetchone()
            if call_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call_fact = _tool_fact_from_row(call_row)
            if call_fact.fact_kind is not ToolFactKind.TOOL_CALL or not isinstance(call_fact.payload, ToolCallFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_fact.payload
            if call.registry_version != registry_version:
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            attempt_rows = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_attempt_started' "
                "ORDER BY tool_sequence",
                (run_id,),
            ).fetchall()
            attempts_for_call: list[ToolAttemptStartedFact] = []
            for row in attempt_rows:
                existing = _tool_fact_from_row(row)
                if not isinstance(existing.payload, ToolAttemptStartedFact):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if existing.payload.tool_call_sequence == tool_call_sequence:
                    attempts_for_call.append(existing.payload)
                if existing.payload.attempt_id == attempt_id:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
            if not attempts_for_call or attempts_for_call[-1].attempt_id != previous_attempt_id:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            previous = attempts_for_call[-1]
            if (
                previous.registry_version != registry_version
                or previous.replay_effect is ReplayEffect.RECONCILE_REQUIRED
            ):
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            result_rows = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_result' "
                "ORDER BY tool_sequence",
                (run_id,),
            ).fetchall()
            for row in result_rows:
                existing = _tool_fact_from_row(row)
                if isinstance(existing.payload, ToolResultFact) and existing.payload.attempt_id == previous_attempt_id:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)

            start = ToolAttemptStartedFact(
                tool_call_sequence=tool_call_sequence,
                call_id=call.call_id,
                attempt_id=attempt_id,
                attempt_number=previous.attempt_number + 1,
                replay_effect=previous.replay_effect,
                registry_version=registry_version,
            )
            tool_sequence = checkpoint.last_committed_tool_sequence + 1
            fact = _insert_tool_fact(
                connection,
                run_id=run_id,
                tool_sequence=tool_sequence,
                kind=ToolFactKind.TOOL_ATTEMPT_STARTED,
                payload=start,
                created_at=now,
            )
            action_json = _encode_action(
                NextAction(
                    ActionKind.TOOL_ATTEMPT,
                    tool_call_sequence=tool_call_sequence,
                    attempt_id=attempt_id,
                )
            )
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, "
                "last_committed_tool_sequence = ?, next_action_json = ?, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (tool_sequence, action_json, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
        return fact

    def commit_tool_result(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
        result: ToolExecutionResult,
    ) -> ToolExecutionFact:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(result, ToolExecutionResult):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        _validate_id(attempt_id)
        now = _utc_now()

        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            action = checkpoint.next_action
            if (
                action is None
                or action.action_kind is not ActionKind.TOOL_ATTEMPT
                or action.attempt_id != attempt_id
                or type(action.tool_call_sequence) is not int
            ):
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            call_row = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND tool_sequence = ?",
                (run_id, action.tool_call_sequence),
            ).fetchone()
            if call_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call_fact = _tool_fact_from_row(call_row)
            if call_fact.fact_kind is not ToolFactKind.TOOL_CALL or not isinstance(call_fact.payload, ToolCallFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_fact.payload
            if result.call_id != call.call_id or result.tool_name != call.tool_name:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

            start_rows = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_attempt_started' "
                "ORDER BY tool_sequence",
                (run_id,),
            ).fetchall()
            matching_start: ToolAttemptStartedFact | None = None
            latest_for_call: ToolAttemptStartedFact | None = None
            for row in start_rows:
                existing = _tool_fact_from_row(row)
                if not isinstance(existing.payload, ToolAttemptStartedFact):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if existing.payload.tool_call_sequence == action.tool_call_sequence:
                    latest_for_call = existing.payload
                if existing.payload.attempt_id == attempt_id:
                    matching_start = existing.payload
            if matching_start is None or latest_for_call is None or latest_for_call.attempt_id != attempt_id:
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            existing_result_rows = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_result' "
                "ORDER BY tool_sequence",
                (run_id,),
            ).fetchall()
            for row in existing_result_rows:
                existing = _tool_fact_from_row(row)
                if isinstance(existing.payload, ToolResultFact) and existing.payload.attempt_id == attempt_id:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)

            result_fact = ToolResultFact(
                tool_call_sequence=action.tool_call_sequence,
                attempt_id=attempt_id,
                call_id=call.call_id,
                tool_name=call.tool_name,
                outcome=result.outcome,
                result=result.result,
                error=result.error,
            )
            tool_sequence = checkpoint.last_committed_tool_sequence + 1
            fact = _insert_tool_fact(
                connection,
                run_id=run_id,
                tool_sequence=tool_sequence,
                kind=ToolFactKind.TOOL_RESULT,
                payload=result_fact,
                created_at=now,
            )

            call_rows = connection.execute(
                "SELECT * FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_call' "
                "ORDER BY tool_sequence",
                (run_id,),
            ).fetchall()
            batch_calls: list[tuple[int, ToolCallFact]] = []
            for row in call_rows:
                existing = _tool_fact_from_row(row)
                if isinstance(existing.payload, ToolCallFact) and existing.payload.response_record_id == call.response_record_id:
                    batch_calls.append((existing.tool_sequence, existing.payload))
            batch_calls.sort(key=lambda pair: pair[1].position)
            current_positions = [index for index, (sequence, _call) in enumerate(batch_calls) if sequence == action.tool_call_sequence]
            if len(current_positions) != 1:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            current_position = current_positions[0]
            next_action = (
                NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=batch_calls[current_position + 1][0])
                if current_position + 1 < len(batch_calls)
                else NextAction(ActionKind.MODEL)
            )
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, "
                "last_committed_tool_sequence = ?, next_action_json = ?, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (tool_sequence, _encode_action(next_action), now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
        return fact

    def complete_run(
        self, *, session_id: str, run_id: str, expected_revision: int
    ) -> ExecutionRecord:
        now = _utc_now()
        with self._database.write() as connection:
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
                "VALUES (?, ?, ?, 'final_answer', 1, ?, ?)",
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
                "UPDATE run_execution_checkpoints SET revision = revision + 1, last_committed_record_sequence = ?, "
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
    ) -> Run:
        if status not in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        if (status is RunStatus.INTERRUPTED) != (terminal_code is TerminalCode.INTERRUPTED):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        now = _utc_now()
        event_kind = EventKind.RUN_INTERRUPTED if status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
        message = TERMINAL_MESSAGES[terminal_code]
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
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
                "UPDATE run_execution_checkpoints SET revision = revision + 1, updated_at = ? "
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
