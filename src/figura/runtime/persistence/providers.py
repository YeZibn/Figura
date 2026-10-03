"""ProviderRepository keeps its Runtime transaction family atomic."""

from __future__ import annotations

import uuid
from figura.providers.retries import retry_deadline
from figura.shared.payloads import decode_json, encode_json, PayloadError
from ..codecs.bindings import encode_binding, decode_binding

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
    ProviderRequestBinding,
    ProviderContinuationFact,
    ToolCallFact,
)
from ..validation import _validate_id
from .mappers import _encode_action
from .controls import assert_not_stopped, read_stop_request
from .runs import RunRepository
from .transaction_helpers import _append_run_event, _next_event_sequence


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
        binding: ProviderRequestBinding | None = None,
    ) -> ProviderAttempt:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
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
            operation_number, previous_id, operation_id = None, None, None
            action = checkpoint.next_action
            if action == NextAction(ActionKind.MODEL):
                if binding is not None:
                    if (binding.run_id, binding.provider_id, binding.model_id, binding.base_record_sequence, binding.base_tool_sequence) != (run_id, run.provider, run.model, checkpoint.last_committed_record_sequence, checkpoint.last_committed_tool_sequence):
                        raise RunError(RunErrorCode.INVALID_TRANSITION)
                    raw_binding = encode_binding(binding)
                    connection.execute("INSERT INTO run_provider_request_bindings VALUES (?, ?, ?, ?, ?)",
                        (binding.operation_id, run_id, binding.base_record_sequence, binding.base_tool_sequence, raw_binding))
                    operation_id, operation_number = binding.operation_id, 1
            elif action is not None and action.action_kind is ActionKind.PROVIDER_RETRY:
                previous = connection.execute("SELECT * FROM run_provider_attempts WHERE run_id = ? AND attempt_id = ?", (run_id, action.attempt_id)).fetchone()
                if previous is None or previous["status"] not in {"known_failure", "outcome_unknown"} or previous["failure_category"] not in {"temporary_unsent", "temporary_rejected", "temporary_unknown"} or not previous["next_eligible_at"] or previous["next_eligible_at"] > now:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                row = connection.execute("SELECT payload_json FROM run_provider_request_bindings WHERE operation_id = ?", (previous["operation_id"],)).fetchone()
                if row is None or binding is None or encode_binding(binding) != row[0]:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                if not binding.generation_only or previous["operation_attempt_number"] >= binding.max_attempts:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                operation_id, operation_number, previous_id = binding.operation_id, previous["operation_attempt_number"] + 1, previous["attempt_id"]
            else:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            attempt_sequence = int(
                connection.execute(
                    "SELECT COUNT(*) FROM run_provider_attempts WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            ) + 1
            connection.execute(
                "INSERT INTO run_provider_attempts(attempt_id, run_id, attempt_sequence, "
                "base_record_sequence, base_tool_sequence, status, response_record_id, failure_code, "
                "started_at, finished_at, operation_id, operation_attempt_number, retry_of_attempt_id) VALUES (?, ?, ?, ?, ?, 'started', NULL, NULL, ?, NULL, ?, ?, ?)",
                (
                    attempt_id,
                    run_id,
                    attempt_sequence,
                    checkpoint.last_committed_record_sequence,
                    checkpoint.last_committed_tool_sequence,
                    now, operation_id, operation_number, previous_id,
                ),
            )
            action_json = _encode_action(
                NextAction(ActionKind.PROVIDER_ATTEMPT, attempt_id=attempt_id)
            )
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET schema_version = 2, revision = revision + 1, next_action_json = ?, "
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
            operation_id=operation_id, operation_attempt_number=operation_number, retry_of_attempt_id=previous_id,
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
            or payload.schema_version not in {2, 3}
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
        try:
            encode_json({"response": decode_json(raw_payload), "tool_calls": [decode_json(raw) for raw in raw_tool_facts],
                "continuation": {"provider_id": continuation.provider_id, "format_version": continuation.format_version,
                    "reasoning_content": continuation.reasoning_content} if continuation else None})
        except PayloadError:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
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
                    schema_version=2,
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
                    "VALUES (?, ?, 'tool_call', 2, ?, ?)",
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
                "UPDATE run_execution_checkpoints SET schema_version = 2, revision = revision + 1, last_committed_record_sequence = ?, "
                "last_committed_tool_sequence = ?, "
                "next_action_json = ?, updated_at = ? WHERE run_id = ? AND revision = ?",
                (sequence, last_tool_sequence, next_action, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if tool_calls:
                _append_run_event(
                    connection,
                    run_id=run_id,
                    kind=EventKind.RUN_PROGRESS,
                    payload={"checkpoint_revision": expected_revision + 1},
                    created_at=now,
                )
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
        transient: bool = False,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
        failure_category: str | None = None,
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
            stopping = read_stop_request(connection, run_id) is not None
            if stopping:
                terminal_code = TerminalCode.INTERRUPTED
                message = TERMINAL_MESSAGES[terminal_code]
                event_json = encode_event_payload(EventKind.RUN_INTERRUPTED, {"terminal_code": terminal_code.value})
            status = RunStatus.INTERRUPTED if stopping else RunStatus.FAILED
            event_kind = EventKind.RUN_INTERRUPTED if stopping else EventKind.RUN_FAILED
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
                "SELECT * FROM run_provider_attempts WHERE run_id = ? AND attempt_id = ?",
                (run_id, attempt_id),
            ).fetchone()
            if attempt_row is None or attempt_row["status"] != ProviderAttemptStatus.STARTED.value:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            category = failure_category
            if category is None:
                category = ("temporary_unknown" if outcome_unknown else "temporary_rejected" if http_status is not None else "temporary_unsent") if transient else "invalid_response" if failure_code == "invalid_provider_response" else "internal_error" if failure_code is None else "permanent"
            if category not in {"temporary_unsent", "temporary_rejected", "temporary_unknown", "permanent", "invalid_response", "internal_error"} or transient != category.startswith("temporary_"):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if category == "temporary_unknown" and not outcome_unknown or category in {"temporary_unsent", "temporary_rejected"} and outcome_unknown:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            retry = transient and not stopping and attempt_row["operation_id"] is not None and attempt_row["operation_attempt_number"] < 4
            if retry:
                binding_row = connection.execute("SELECT payload_json FROM run_provider_request_bindings WHERE operation_id = ?", (attempt_row["operation_id"],)).fetchone()
                retry = binding_row is not None and decode_binding(binding_row[0]).generation_only
            due = retry_deadline(attempt_row["operation_attempt_number"], retry_after_seconds) if retry else None
            cursor = connection.execute(
                "UPDATE run_provider_attempts SET status = ?, failure_code = ?, finished_at = ?, failure_category = ?, http_status = ?, next_eligible_at = ? "
                "WHERE run_id = ? AND attempt_id = ? AND status = 'started'",
                (attempt_status.value, failure_code, now, category, http_status, due, run_id, attempt_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if retry:
                connection.execute("UPDATE run_execution_checkpoints SET schema_version = 2, revision = revision + 1, next_action_json = ?, updated_at = ? WHERE run_id = ? AND revision = ?",
                    (_encode_action(NextAction(ActionKind.PROVIDER_RETRY, attempt_id=attempt_id)), now, run_id, expected_revision))
                _append_run_event(connection, run_id=run_id, kind=EventKind.RUN_PROGRESS,
                    payload={"checkpoint_revision": expected_revision + 1}, created_at=now)
                return run
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
