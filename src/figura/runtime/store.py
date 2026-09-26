"""SQLite-backed, Figura-owned persistence for Sessions and Runs."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from figura.providers.models import FinishReason
from figura.tools.contracts import ReplayEffect, ToolExecutionResult, ToolOutcome

from ._codec import (
    decode_event_payload,
    decode_payload,
    decode_tool_fact,
    encode_event_payload,
    encode_payload,
    encode_tool_fact,
    validate_tool_call_batch,
)
from .errors import RunError, RunErrorCode
from .models import (
    ActionKind,
    EventKind,
    ExecutionCheckpoint,
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    NextAction,
    RecordKind,
    Run,
    RunInput,
    RunState,
    RunStatus,
    RunStreamEvent,
    Session,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolFactKind,
    ToolResultFact,
    TerminalCode,
    TERMINAL_MESSAGES,
)

_SCHEMA_VERSION = 2
_BUSY_TIMEOUT_MS = 5000
_DB_FILENAME = "figura.sqlite3"


class FiguraRunStore:
    """Own one Figura SQLite database under an explicitly injected data root."""

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self.data_root = Path(data_root).expanduser()
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database_path = self.data_root / _DB_FILENAME
        existed = self.database_path.exists()
        self._initialize()
        if not existed:
            try:
                self.database_path.chmod(0o600)
            except OSError:
                raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def create_session(self, name: str | None = None) -> Session:
        if name is not None and (not isinstance(name, str) or _utf8_length(name) > 256):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        now = _utc_now()
        session = Session(uuid.uuid4().hex, name, now, now)
        with self._write() as connection:
            connection.execute(
                "INSERT INTO sessions(session_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session.session_id, session.name, session.created_at, session.updated_at),
            )
        return session

    def assert_session(self, session_id: str) -> None:
        _validate_id(session_id)
        with self._read() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)

    def find_idempotent_run(
        self, session_id: str, key_digest: str, request_fingerprint: str
    ) -> Run | None:
        _validate_id(session_id)
        with self._read() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            row = connection.execute(
                "SELECT request_fingerprint, run_id FROM run_idempotency "
                "WHERE session_id = ? AND idempotency_key_digest = ?",
                (session_id, key_digest),
            ).fetchone()
            if row is None:
                return None
            if row["request_fingerprint"] != request_fingerprint:
                raise RunError(RunErrorCode.IDEMPOTENCY_CONFLICT)
            run_row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
                (row["run_id"], session_id),
            ).fetchone()
            if run_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return _run_from_row(run_row)

    def create_initial_run(
        self,
        *,
        session_id: str,
        provider_id: str,
        model_id: str,
        input_payload: RunInput,
        key_digest: str,
        request_fingerprint: str,
    ) -> Run:
        now = _utc_now()
        run_id = uuid.uuid4().hex
        input_record_id = uuid.uuid4().hex
        input_json = encode_payload(RecordKind.INPUT, input_payload)
        action_json = _encode_action(NextAction(ActionKind.MODEL))
        created_event_json = encode_event_payload(
            EventKind.RUN_CREATED, {"session_id": session_id, "ordinal": 1}
        )
        with self._write() as connection:
            session_row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)

            existing = connection.execute(
                "SELECT request_fingerprint, run_id FROM run_idempotency "
                "WHERE session_id = ? AND idempotency_key_digest = ?",
                (session_id, key_digest),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise RunError(RunErrorCode.IDEMPOTENCY_CONFLICT)
                run_row = connection.execute(
                    "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
                    (existing["run_id"], session_id),
                ).fetchone()
                if run_row is None:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                return _run_from_row(run_row)

            ordinal_row = connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM runs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            ordinal = int(ordinal_row[0])
            created_event_json = encode_event_payload(
                EventKind.RUN_CREATED, {"session_id": session_id, "ordinal": ordinal}
            )
            # The input-record foreign key is deferred, so the whole bundle is
            # checked only when this transaction commits.
            connection.execute(
                "INSERT INTO runs(run_id, session_id, ordinal, input_record_id, status, provider, model, "
                "created_at, started_at, finished_at, terminal_code, terminal_message, final_record_id) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
                (run_id, session_id, ordinal, input_record_id, provider_id, model_id, now, now),
            )
            connection.execute(
                "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
                "VALUES (?, ?, 1, 'input', 1, ?, ?)",
                (input_record_id, run_id, input_json, now),
            )
            connection.execute(
                "INSERT INTO run_execution_checkpoints(run_id, revision, last_committed_record_sequence, last_committed_tool_sequence, next_action_json, schema_version, updated_at) "
                "VALUES (?, 1, 1, 0, ?, 1, ?)",
                (run_id, action_json, now),
            )
            connection.execute(
                "INSERT INTO run_idempotency(session_id, idempotency_key_digest, request_fingerprint, run_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, key_digest, request_fingerprint, run_id, now),
            )
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, 1, 'run_created', ?, ?)",
                (run_id, created_event_json, now),
            )
        return Run(
            run_id=run_id,
            session_id=session_id,
            ordinal=ordinal,
            input_record_id=input_record_id,
            status=RunStatus.RUNNING,
            provider=provider_id,
            model=model_id,
            created_at=now,
            started_at=now,
        )

    def read_run_state(self, session_id: str, run_id: str) -> RunState:
        _validate_id(session_id)
        _validate_id(run_id)
        with self._read() as connection:
            return _read_run_state_from_connection(connection, session_id, run_id)

    def commit_model_response(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        payload: ModelResponseFact,
        record_id: str | None = None,
        tool_calls: tuple[ToolCallFact, ...] = (),
    ) -> ExecutionRecord:
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
        now = _utc_now()
        record_id = record_id or uuid.uuid4().hex
        _validate_id(record_id)
        raw_tool_facts = tuple(
            encode_tool_fact(ToolFactKind.TOOL_CALL, call) for call in tool_calls
        )
        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if checkpoint.next_action != NextAction(ActionKind.MODEL):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if payload.provider_id != run.provider or payload.model_id != run.model:
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
                "VALUES (?, ?, ?, 'model_response', 1, ?, ?)",
                (record_id, run_id, sequence, raw_payload, now),
            )
            first_tool_sequence = checkpoint.last_committed_tool_sequence + 1
            for offset, (call, raw_fact) in enumerate(zip(tool_calls, raw_tool_facts)):
                connection.execute(
                    "INSERT INTO run_tool_execution_facts(run_id, tool_sequence, fact_kind, schema_version, payload_json, created_at) "
                    "VALUES (?, ?, 'tool_call', 1, ?, ?)",
                    (run_id, first_tool_sequence + offset, raw_fact, now),
                )
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

        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
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

        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
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

        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
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
        with self._write() as connection:
            current_state = _read_run_state_from_connection(connection, session_id, run_id)
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
        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
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

    def _initialize(self) -> None:
        try:
            with self._connection() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    # Read the migration version after acquiring the writer
                    # lock so concurrent first opens cannot both create v1.
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version > _SCHEMA_VERSION:
                        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
                    if version == _SCHEMA_VERSION:
                        connection.commit()
                        return
                    if version == 0:
                        for statement in _SCHEMA:
                            connection.execute(statement)
                    elif version == 1:
                        connection.execute(
                            "ALTER TABLE run_execution_checkpoints ADD COLUMN "
                            "last_committed_tool_sequence INTEGER NOT NULL DEFAULT 0 "
                            "CHECK (last_committed_tool_sequence >= 0)"
                        )
                        for statement in _TOOL_SCHEMA:
                            connection.execute(statement)
                    else:
                        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
                    _validate_migration(connection)
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                yield connection
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except RunError:
            raise
        except sqlite3.IntegrityError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @staticmethod
    def _scoped_run(connection: sqlite3.Connection, session_id: str, run_id: str) -> Run:
        _validate_id(session_id)
        _validate_id(run_id)
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
        ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.RUN_NOT_FOUND)
        return _run_from_row(row)

    @staticmethod
    def _checkpoint_for_write(connection: sqlite3.Connection, run_id: str) -> ExecutionCheckpoint:
        row = connection.execute(
            "SELECT * FROM run_execution_checkpoints WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return _checkpoint_from_row(row)


def _read_run_state_from_connection(
    connection: sqlite3.Connection,
    session_id: str,
    run_id: str,
) -> RunState:
    _validate_id(session_id)
    _validate_id(run_id)
    run_row = connection.execute(
        "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
        (run_id, session_id),
    ).fetchone()
    if run_row is None:
        raise RunError(RunErrorCode.RUN_NOT_FOUND)
    checkpoint_row = connection.execute(
        "SELECT * FROM run_execution_checkpoints WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if checkpoint_row is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    record_rows = connection.execute(
        "SELECT * FROM run_execution_records WHERE run_id = ? ORDER BY record_sequence",
        (run_id,),
    ).fetchall()
    event_rows = connection.execute(
        "SELECT * FROM run_stream_events WHERE run_id = ? ORDER BY event_sequence",
        (run_id,),
    ).fetchall()
    tool_fact_rows = connection.execute(
        "SELECT * FROM run_tool_execution_facts WHERE run_id = ? ORDER BY tool_sequence",
        (run_id,),
    ).fetchall()
    state = RunState(
        run=_run_from_row(run_row),
        records=tuple(_record_from_row(row) for row in record_rows),
        checkpoint=_checkpoint_from_row(checkpoint_row),
        events=tuple(_event_from_row(row) for row in event_rows),
        tool_facts=tuple(_tool_fact_from_row(row) for row in tool_fact_rows),
    )
    _validate_state(state)
    return state


_CORE_SCHEMA = (
    """CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY,
        name TEXT NULL CHECK (name IS NULL OR length(CAST(name AS BLOB)) <= 256),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK (ordinal > 0),
        input_record_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'interrupted')),
        provider TEXT NOT NULL CHECK (length(CAST(provider AS BLOB)) <= 64),
        model TEXT NOT NULL CHECK (length(CAST(model AS BLOB)) <= 128),
        created_at TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NULL,
        terminal_code TEXT NULL,
        terminal_message TEXT NULL CHECK (terminal_message IS NULL OR length(CAST(terminal_message AS BLOB)) <= 256),
        final_record_id TEXT NULL,
        UNIQUE(session_id, ordinal),
        UNIQUE(run_id, session_id),
        FOREIGN KEY(input_record_id, run_id) REFERENCES run_execution_records(record_id, run_id) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(final_record_id, run_id) REFERENCES run_execution_records(record_id, run_id) DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE run_execution_records (
        record_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        record_sequence INTEGER NOT NULL CHECK (record_sequence > 0),
        record_kind TEXT NOT NULL CHECK (record_kind IN ('input', 'model_response', 'final_answer')),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 262144),
        created_at TEXT NOT NULL,
        UNIQUE(run_id, record_sequence),
        UNIQUE(record_id, run_id)
    )""",
    """CREATE TABLE run_idempotency (
        session_id TEXT NOT NULL,
        idempotency_key_digest TEXT NOT NULL CHECK (length(idempotency_key_digest) = 64),
        request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
        run_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(session_id, idempotency_key_digest),
        FOREIGN KEY(run_id, session_id) REFERENCES runs(run_id, session_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE run_execution_checkpoints (
        run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK (revision > 0),
        last_committed_record_sequence INTEGER NOT NULL CHECK (last_committed_record_sequence > 0),
        last_committed_tool_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_committed_tool_sequence >= 0),
        next_action_json TEXT NULL CHECK (next_action_json IS NULL OR (json_valid(next_action_json) AND length(CAST(next_action_json AS BLOB)) <= 1024)),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE run_stream_events (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
        event_kind TEXT NOT NULL CHECK (event_kind IN ('run_created', 'run_completed', 'run_failed', 'run_interrupted')),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 16384),
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, event_sequence)
    )""",
    """CREATE TRIGGER immutable_run_record_update BEFORE UPDATE ON run_execution_records
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    """CREATE TRIGGER immutable_run_record_delete BEFORE DELETE ON run_execution_records
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    """CREATE TRIGGER immutable_run_event_update BEFORE UPDATE ON run_stream_events
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
    """CREATE TRIGGER immutable_run_event_delete BEFORE DELETE ON run_stream_events
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
)

_TOOL_SCHEMA = (
    """CREATE TABLE run_tool_execution_facts (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        tool_sequence INTEGER NOT NULL CHECK (tool_sequence > 0),
        fact_kind TEXT NOT NULL CHECK (fact_kind IN ('tool_call', 'tool_attempt_started', 'tool_result')),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 524288),
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, tool_sequence)
    )""",
    """CREATE TRIGGER immutable_run_tool_fact_update BEFORE UPDATE ON run_tool_execution_facts
        BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END""",
    """CREATE TRIGGER immutable_run_tool_fact_delete BEFORE DELETE ON run_tool_execution_facts
        BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END""",
)

_SCHEMA = (*_CORE_SCHEMA, *_TOOL_SCHEMA)


def _validate_migration(connection: sqlite3.Connection) -> None:
    foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    quick_check = connection.execute("PRAGMA quick_check").fetchone()
    if foreign_key_violations or quick_check is None or quick_check[0] != "ok":
        raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value or _utf8_length(value) > 128:
        raise RunError(RunErrorCode.INVALID_REQUEST)


def _utf8_length(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return 2**63 - 1


def _run_from_row(row: sqlite3.Row) -> Run:
    try:
        status = RunStatus(row["status"])
    except ValueError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    return Run(
        run_id=row["run_id"],
        session_id=row["session_id"],
        ordinal=row["ordinal"],
        input_record_id=row["input_record_id"],
        status=status,
        provider=row["provider"],
        model=row["model"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        terminal_code=row["terminal_code"],
        terminal_message=row["terminal_message"],
        final_record_id=row["final_record_id"],
    )


def _record_from_row(row: sqlite3.Row) -> ExecutionRecord:
    try:
        kind = RecordKind(row["record_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    if row["schema_version"] != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    payload = decode_payload(kind, row["payload_json"])
    return ExecutionRecord(
        record_id=row["record_id"],
        run_id=row["run_id"],
        record_sequence=row["record_sequence"],
        record_kind=kind,
        payload=payload,
        created_at=row["created_at"],
    )


def _checkpoint_from_row(row: sqlite3.Row) -> ExecutionCheckpoint:
    if row["schema_version"] != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    return ExecutionCheckpoint(
        run_id=row["run_id"],
        revision=row["revision"],
        last_committed_record_sequence=row["last_committed_record_sequence"],
        last_committed_tool_sequence=(
            row["last_committed_tool_sequence"]
            if "last_committed_tool_sequence" in row.keys()
            else 0
        ),
        next_action=_decode_action(row["next_action_json"]),
        schema_version=row["schema_version"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: sqlite3.Row) -> RunStreamEvent:
    try:
        kind = EventKind(row["event_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return RunStreamEvent(
        run_id=row["run_id"],
        event_sequence=row["event_sequence"],
        event_kind=kind,
        payload=decode_event_payload(kind, row["payload_json"]),
        created_at=row["created_at"],
    )


def _tool_fact_from_row(row: sqlite3.Row) -> ToolExecutionFact:
    try:
        kind = ToolFactKind(row["fact_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    payload = decode_tool_fact(kind, row["schema_version"], row["payload_json"])
    return ToolExecutionFact(
        run_id=row["run_id"],
        tool_sequence=row["tool_sequence"],
        fact_kind=kind,
        schema_version=row["schema_version"],
        payload=payload,
        created_at=row["created_at"],
    )


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


def _encode_action(action: NextAction | None) -> str | None:
    if action is None:
        return None
    if (
        action.action_kind is ActionKind.MODEL
        and action.response_record_id is None
        and action.tool_call_sequence is None
        and action.attempt_id is None
    ):
        value = {"action_kind": "model"}
    elif (
        action.action_kind is ActionKind.FINAL
        and action.response_record_id
        and action.tool_call_sequence is None
        and action.attempt_id is None
    ):
        value = {"action_kind": "final", "response_record_id": action.response_record_id}
    elif (
        action.action_kind is ActionKind.TOOL_EXECUTION
        and action.response_record_id is None
        and type(action.tool_call_sequence) is int
        and action.tool_call_sequence > 0
        and action.attempt_id is None
    ):
        value = {"action_kind": "tool_execution", "tool_call_sequence": action.tool_call_sequence}
    elif (
        action.action_kind is ActionKind.TOOL_ATTEMPT
        and action.response_record_id is None
        and type(action.tool_call_sequence) is int
        and action.tool_call_sequence > 0
        and isinstance(action.attempt_id, str)
        and action.attempt_id
        and len(action.attempt_id.encode("utf-8")) <= 128
    ):
        value = {
            "action_kind": "tool_attempt",
            "tool_call_sequence": action.tool_call_sequence,
            "attempt_id": action.attempt_id,
        }
    else:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _decode_action(raw: str | None) -> NextAction | None:
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > 1024:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        value = json.loads(raw)
        if value == {"action_kind": "model"}:
            return NextAction(ActionKind.MODEL)
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "response_record_id"}
            and value["action_kind"] == "final"
            and isinstance(value["response_record_id"], str)
            and value["response_record_id"]
            and len(value["response_record_id"].encode("utf-8")) <= 128
        ):
            return NextAction(ActionKind.FINAL, value["response_record_id"])
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "tool_call_sequence"}
            and value["action_kind"] == "tool_execution"
            and type(value["tool_call_sequence"]) is int
            and value["tool_call_sequence"] > 0
        ):
            return NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=value["tool_call_sequence"])
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "tool_call_sequence", "attempt_id"}
            and value["action_kind"] == "tool_attempt"
            and type(value["tool_call_sequence"]) is int
            and value["tool_call_sequence"] > 0
            and isinstance(value["attempt_id"], str)
            and value["attempt_id"]
            and len(value["attempt_id"].encode("utf-8")) <= 128
        ):
            return NextAction(
                ActionKind.TOOL_ATTEMPT,
                tool_call_sequence=value["tool_call_sequence"],
                attempt_id=value["attempt_id"],
            )
    except (TypeError, ValueError):
        pass
    raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _next_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM run_stream_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def _validate_state(state: RunState) -> None:
    run, checkpoint = state.run, state.checkpoint
    records, events, tool_facts = state.records, state.events, state.tool_facts
    if (
        checkpoint.run_id != run.run_id
        or checkpoint.schema_version != 1
        or type(checkpoint.last_committed_tool_sequence) is not int
        or checkpoint.last_committed_tool_sequence < 0
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if not records or len(records) != checkpoint.last_committed_record_sequence:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if [record.record_sequence for record in records] != list(range(1, len(records) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if len(tool_facts) != checkpoint.last_committed_tool_sequence:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if [fact.tool_sequence for fact in tool_facts] != list(range(1, len(tool_facts) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    first = records[0]
    if first.record_kind is not RecordKind.INPUT or first.record_id != run.input_record_id:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    input_fact = first.payload
    if not isinstance(input_fact, RunInput) or input_fact.attachment_ids:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if (input_fact.requested_provider, input_fact.requested_model) != (run.provider, run.model):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    response_records: list[ExecutionRecord] = []
    final_records: list[ExecutionRecord] = []
    saw_final = False
    for index, record in enumerate(records[1:], start=1):
        if record.record_kind is RecordKind.MODEL_RESPONSE and not saw_final:
            response_records.append(record)
        elif record.record_kind is RecordKind.FINAL_ANSWER and not saw_final and index == len(records) - 1:
            final_records.append(record)
            saw_final = True
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    response_by_id: dict[str, ExecutionRecord] = {}
    response_position: dict[str, int] = {}
    last_non_tool_response = -1
    for response_index, record in enumerate(response_records):
        response = record.payload
        if (
            not isinstance(response, ModelResponseFact)
            or (response.provider_id, response.model_id) != (run.provider, run.model)
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            finish_reason = FinishReason(response.finish_reason)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        response_by_id[record.record_id] = record
        response_position[record.record_id] = response_index
        if finish_reason is not FinishReason.TOOL_CALLS:
            last_non_tool_response = response_index
    if last_non_tool_response >= 0 and last_non_tool_response != len(response_records) - 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    calls_by_response: dict[str, list[tuple[ToolExecutionFact, ToolCallFact]]] = {}
    calls_by_sequence: dict[int, tuple[ToolExecutionFact, ToolCallFact]] = {}
    calls_by_id: dict[str, tuple[ToolExecutionFact, ToolCallFact]] = {}
    attempts_by_id: dict[str, tuple[ToolExecutionFact, ToolAttemptStartedFact]] = {}
    results_by_attempt: dict[str, tuple[ToolExecutionFact, ToolResultFact]] = {}

    for fact in tool_facts:
        if fact.run_id != run.run_id or fact.schema_version != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact):
            call = fact.payload
            response_record = response_by_id.get(call.response_record_id)
            if response_record is None or call.call_id in calls_by_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_payload = response_record.payload
            if not isinstance(response_payload, ModelResponseFact) or response_payload.finish_reason != FinishReason.TOOL_CALLS.value:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            calls_by_response.setdefault(call.response_record_id, []).append((fact, call))
            calls_by_sequence[fact.tool_sequence] = (fact, call)
            calls_by_id[call.call_id] = (fact, call)
        elif fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED and isinstance(fact.payload, ToolAttemptStartedFact):
            attempt = fact.payload
            call_pair = calls_by_sequence.get(attempt.tool_call_sequence)
            if call_pair is None or attempt.attempt_id in attempts_by_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_pair[1]
            prior_attempts = [item for item in attempts_by_id.values() if item[1].tool_call_sequence == attempt.tool_call_sequence]
            if (
                attempt.call_id != call.call_id
                or attempt.registry_version != call.registry_version
                or attempt.attempt_number != len(prior_attempts) + 1
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attempts_by_id[attempt.attempt_id] = (fact, attempt)
        elif fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact):
            result = fact.payload
            attempt_pair = attempts_by_id.get(result.attempt_id)
            if attempt_pair is None or result.attempt_id in results_by_attempt:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attempt = attempt_pair[1]
            call_pair = calls_by_sequence.get(result.tool_call_sequence)
            if call_pair is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_pair[1]
            if (
                attempt.tool_call_sequence != result.tool_call_sequence
                or result.call_id != call.call_id
                or result.tool_name != call.tool_name
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            results_by_attempt[result.attempt_id] = (fact, result)
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    batch_response_ids = [
        record.record_id
        for record in response_records
        if isinstance(record.payload, ModelResponseFact)
        and record.payload.finish_reason == FinishReason.TOOL_CALLS.value
    ]
    if set(calls_by_response) != set(batch_response_ids):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    batch_rank = {response_id: index for index, response_id in enumerate(batch_response_ids)}
    call_position: dict[int, int] = {}
    for response_id in batch_response_ids:
        call_pairs = calls_by_response[response_id]
        call_pairs.sort(key=lambda pair: pair[1].position)
        if not 1 <= len(call_pairs) <= 64:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if [call.position for _, call in call_pairs] != list(range(len(call_pairs))):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if len({call.registry_version for _, call in call_pairs}) != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        call_sequences = [fact.tool_sequence for fact, _ in call_pairs]
        if call_sequences != list(range(call_sequences[0], call_sequences[0] + len(call_sequences))):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        for position, (fact, _call) in enumerate(call_pairs):
            call_position[fact.tool_sequence] = position

    fact_batch_ranks: list[int] = []
    for fact in tool_facts:
        if isinstance(fact.payload, ToolCallFact):
            response_id = fact.payload.response_record_id
        else:
            call_pair = calls_by_sequence.get(fact.payload.tool_call_sequence)
            if call_pair is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_id = call_pair[1].response_record_id
        fact_batch_ranks.append(batch_rank[response_id])
    if fact_batch_ranks != sorted(fact_batch_ranks):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if fact_batch_ranks and fact_batch_ranks[0] != 0:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    for left, right in zip(fact_batch_ranks, fact_batch_ranks[1:]):
        if right > left + 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    unresolved_action: NextAction | None = None
    for rank, response_id in enumerate(batch_response_ids):
        call_pairs = calls_by_response[response_id]
        batch_facts = [fact for fact in tool_facts if fact_batch_ranks[fact.tool_sequence - 1] == rank]
        call_facts = [fact for fact in batch_facts if fact.fact_kind is ToolFactKind.TOOL_CALL]
        if [fact.tool_sequence for fact in call_facts] != [fact.tool_sequence for fact, _ in call_pairs]:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if any(fact.fact_kind is ToolFactKind.TOOL_CALL for fact in batch_facts[len(call_pairs):]):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        next_position = 0
        latest_attempt_by_call: dict[int, str] = {}
        attempt_counts: dict[int, int] = {}
        for fact in batch_facts[len(call_pairs):]:
            payload = fact.payload
            call_sequence = payload.tool_call_sequence
            position = call_position[call_sequence]
            if position != next_position:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if isinstance(payload, ToolAttemptStartedFact):
                attempt_counts[call_sequence] = attempt_counts.get(call_sequence, 0) + 1
                if payload.attempt_number != attempt_counts[call_sequence]:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                latest_attempt_by_call[call_sequence] = payload.attempt_id
            elif isinstance(payload, ToolResultFact):
                if latest_attempt_by_call.get(call_sequence) != payload.attempt_id:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                next_position += 1
            else:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

        if rank < len(batch_response_ids) - 1 and next_position != len(call_pairs):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if next_position < len(call_pairs):
            current_sequence = call_pairs[next_position][0].tool_sequence
            current_attempt_id = latest_attempt_by_call.get(current_sequence)
            unresolved_action = (
                NextAction(ActionKind.TOOL_ATTEMPT, tool_call_sequence=current_sequence, attempt_id=current_attempt_id)
                if current_attempt_id is not None
                else NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=current_sequence)
            )

    if set(results_by_attempt) - set(attempts_by_id):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    final_records = [record for record in records if record.record_kind is RecordKind.FINAL_ANSWER]
    if len(final_records) > 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if final_records:
        final = final_records[0]
        if not response_records or not isinstance(final.payload, FinalAnswerFact):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if final.payload.response_record_id != response_records[-1].record_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        last_response = response_records[-1].payload
        if (
            not isinstance(last_response, ModelResponseFact)
            or last_response.finish_reason != FinishReason.STOP.value
            or not last_response.assistant_content.strip()
            or unresolved_action is not None
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if unresolved_action is not None:
        expected_action = unresolved_action
    elif response_records and isinstance(response_records[-1].payload, ModelResponseFact):
        latest_response = response_records[-1]
        latest_fact = latest_response.payload
        expected_action = (
            NextAction(ActionKind.MODEL)
            if latest_fact.finish_reason == FinishReason.TOOL_CALLS.value
            else NextAction(ActionKind.FINAL, latest_response.record_id)
        )
    else:
        expected_action = NextAction(ActionKind.MODEL)

    if run.status is RunStatus.RUNNING:
        if (
            run.finished_at is not None
            or run.terminal_code is not None
            or run.final_record_id is not None
            or final_records
            or checkpoint.next_action != expected_action
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    elif run.status is RunStatus.COMPLETED:
        if (
            run.finished_at is None
            or run.terminal_code is not None
            or run.terminal_message is not None
            or checkpoint.next_action is not None
            or not final_records
            or run.final_record_id != final_records[0].record_id
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if expected_action.action_kind is not ActionKind.FINAL:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    else:
        if (
            run.finished_at is None
            or checkpoint.next_action != expected_action
            or run.final_record_id is not None
            or final_records
            or run.terminal_code not in {code.value for code in TerminalCode}
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            code = TerminalCode(run.terminal_code)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        if run.terminal_message != TERMINAL_MESSAGES[code]:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if (run.status is RunStatus.INTERRUPTED) != (code is TerminalCode.INTERRUPTED):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if not events or [event.event_sequence for event in events] != list(range(1, len(events) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if events[0].event_kind is not EventKind.RUN_CREATED:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    created_payload = events[0].payload
    if created_payload != {"session_id": run.session_id, "ordinal": run.ordinal}:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if run.status is RunStatus.RUNNING:
        if len(events) != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    elif len(events) != 2:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    else:
        terminal_event = events[1]
        if run.status is RunStatus.COMPLETED:
            if terminal_event.event_kind is not EventKind.RUN_COMPLETED or terminal_event.payload != {"final_artifact_refs": ()}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            expected_kind = EventKind.RUN_INTERRUPTED if run.status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
            if terminal_event.event_kind is not expected_kind or terminal_event.payload != {"terminal_code": run.terminal_code}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
