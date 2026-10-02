"""ToolRepository keeps its Runtime transaction family atomic."""

from __future__ import annotations

import uuid

from figura.storage.database import SqliteDatabase, _utc_now
from figura.tools.contracts import (
    ReplayEffect,
    ToolExecutionResult,
)

from ..errors import (
    RunError,
    RunErrorCode,
)
from ..models import (
    ActionKind,
    EventKind,
    NextAction,
    RunStatus,
    ToolFactKind,
)
from ..record_validation import _utf8_length
from ..records import (
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolResultFact,
)
from ..validation import _validate_id
from .mappers import (
    _encode_action,
    _tool_fact_from_row,
)
from .controls import assert_not_stopped, read_stop_request
from .runs import RunRepository
from .transaction_helpers import _append_run_event, _insert_tool_fact


class ToolRepository:
    def __init__(self, database: SqliteDatabase, runs: RunRepository) -> None:
        self._database = database
        self._runs = runs

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
            assert_not_stopped(connection, run_id)
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
            _append_run_event(
                connection,
                run_id=run_id,
                kind=EventKind.RUN_PROGRESS,
                payload={"checkpoint_revision": expected_revision + 1},
                created_at=now,
            )
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
            assert_not_stopped(connection, run_id)
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
            _append_run_event(
                connection,
                run_id=run_id,
                kind=EventKind.RUN_PROGRESS,
                payload={"checkpoint_revision": expected_revision + 1},
                created_at=now,
            )
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
            _append_run_event(
                connection,
                run_id=run_id,
                kind=EventKind.RUN_PROGRESS,
                payload={"checkpoint_revision": expected_revision + 1},
                created_at=now,
            )
        return fact
