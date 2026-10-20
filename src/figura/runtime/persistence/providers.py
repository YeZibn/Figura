"""ProviderRepository keeps its Runtime transaction family atomic."""

from __future__ import annotations

import uuid
from dataclasses import fields
from figura.providers.retries import retry_deadline
from figura.shared.payloads import decode_json, encode_json, PayloadError
from ..codecs.provider_requests import encode_provider_request, decode_provider_request

from figura.providers.errors import ProviderFailureCode
from figura.providers.models import (
    FinishReason,
    ProviderContinuation,
    ProviderId,
    ProviderUsage,
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
    ProviderRequestRecord,
    ContextCompactionOperation,
    ProviderContinuationFact,
    ToolCallFact,
)
from ..validation import _validate_id
from ..codecs.provider_requests import encode_provider_request, validate_provider_request
from .mappers import _encode_action
from .controls import assert_not_stopped, read_stop_request
from .runs import RunRepository
from .transaction_helpers import _append_run_event, _next_event_sequence


def _synthetic_runtime_request(run: Run, checkpoint, request_id: str, created_at: str) -> ProviderRequestRecord:
    """Build a canonical fixture identity for direct Runtime transaction tests."""
    digest = "0" * 64
    manifest = {
        "prompt_digest": digest,
        "registry_version": "runtime-direct-v1",
        "registry_digest": digest,
        "adapter_contract_version": 1,
        "images": [],
    }
    return ProviderRequestRecord(
        request_id=request_id,
        run_id=run.run_id,
        purpose="agent_turn",
        compaction_operation_id=None,
        base_record_sequence=checkpoint.last_committed_record_sequence,
        base_tool_sequence=checkpoint.last_committed_tool_sequence,
        provider_id=run.provider,
        model_id=run.model,
        request_fingerprint=digest,
        endpoint_identity=digest,
        prompt_digest=digest,
        tool_registry_digest=digest,
        options={
            "max_completion_tokens": None,
            "thinking_mode": True,
            "reasoning_effort": None,
            "connect_timeout_seconds": 10.0,
            "write_timeout_seconds": 30.0,
        },
        asset_manifest=manifest,
        created_at=created_at,
    )


def _insert_provider_request(connection, request: ProviderRequestRecord, request_json: str) -> None:
    estimate = request.context_estimate
    estimate_json = None if estimate is None else encode_json(
        {item.name: getattr(estimate, item.name) for item in fields(estimate)}, maximum=1024
    )
    options_json = encode_json(dict(request.options), maximum=4096)
    manifest_json = encode_json(dict(request.asset_manifest), maximum=262144)
    connection.execute(
        "INSERT INTO run_provider_requests(request_id, run_id, purpose, compaction_operation_id, base_record_sequence, base_tool_sequence, provider_id, model_id, endpoint_identity, request_fingerprint, request_contract_version, stream_contract_version, timeout_policy_version, retry_policy_version, max_attempts, generation_only, options_json, asset_manifest_json, prompt_digest, tool_registry_digest, context_estimate_json, context_projection, context_checkpoint_revision, context_checkpoint_operation_id, created_at, request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            request.request_id, request.run_id, request.purpose,
            request.compaction_operation_id, request.base_record_sequence,
            request.base_tool_sequence, request.provider_id, request.model_id,
            request.endpoint_identity, request.request_fingerprint,
            request.request_contract_version, request.stream_contract_version,
            request.timeout_policy_version, request.retry_policy_version,
            request.max_attempts, int(request.generation_only), options_json,
            manifest_json, request.prompt_digest, request.tool_registry_digest,
            estimate_json, request.context_projection,
            request.context_checkpoint_revision, request.context_checkpoint_operation_id,
            request.created_at, request_json,
        ),
    )


def _append_provider_progress(
    connection, run_id: str, purpose: str, attempt_id: str, phase: str,
    checkpoint_revision: int, created_at: str,
) -> None:
    if purpose not in {"agent_turn", "context_compaction"}:
        return
    _append_run_event(
        connection,
        run_id=run_id,
        kind=EventKind.RUN_PROGRESS,
        payload={
            "checkpoint_revision": checkpoint_revision,
            "provider_purpose": purpose,
            "attempt_id": attempt_id,
            "phase": phase,
        },
        created_at=created_at,
    )


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
        request: ProviderRequestRecord | None = None,
        auxiliary: bool = False,
        request_bytes: int | None = None,
    ) -> ProviderAttempt:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        _validate_id(attempt_id)
        now = _utc_now()
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            assert_not_stopped(connection, run_id)
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING or checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if request is None:
                request = _synthetic_runtime_request(run, checkpoint, attempt_id, now)
            validate_provider_request(request)
            if (request.run_id, request.base_record_sequence, request.base_tool_sequence) != (
                run_id, checkpoint.last_committed_record_sequence, checkpoint.last_committed_tool_sequence
            ):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if request.purpose == "context_compaction":
                if not auxiliary or not isinstance(request.compaction_operation_id, str):
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                action = checkpoint.next_action
                if action is None or action.action_kind not in {ActionKind.MODEL, ActionKind.PROVIDER_RETRY}:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
            elif request.purpose == "agent_turn":
                if auxiliary:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                action = checkpoint.next_action
            elif request.purpose == "historical_import":
                if auxiliary:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                action = checkpoint.next_action
            else:
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            from ..codecs.provider_requests import encode_provider_request
            request_json = encode_provider_request(request)
            existing = connection.execute(
                "SELECT request_json FROM run_provider_requests WHERE request_id=? AND run_id=?",
                (request.request_id, run_id),
            ).fetchone()
            if existing is None:
                _insert_provider_request(connection, request, request_json)
            elif existing["request_json"] != request_json:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

            if request.purpose == "context_compaction":
                operation = connection.execute(
                    "SELECT * FROM session_context_compaction_operations WHERE operation_id=?",
                    (request.compaction_operation_id,),
                ).fetchone()
                if (
                    operation is None or operation["session_id"] != session_id
                    or operation["target_run_id"] != run_id or operation["status"] != "preparing"
                    or operation["base_record_sequence"] != request.base_record_sequence
                    or operation["base_tool_sequence"] != request.base_tool_sequence
                ):
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                if operation["provider_request_id"] not in (None, request.request_id):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if operation["provider_request_id"] is None:
                    connection.execute(
                        "UPDATE session_context_compaction_operations SET provider_request_id=?, updated_at=? WHERE operation_id=? AND provider_request_id IS NULL",
                        (request.request_id, now, request.compaction_operation_id),
                    )
                previous = connection.execute(
                    "SELECT * FROM run_provider_attempts WHERE request_id=? ORDER BY attempt_sequence DESC LIMIT 1",
                    (request.request_id,),
                ).fetchone()
                if previous is not None and previous["status"] == "started":
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                if previous is not None and (
                    previous["status"] not in {"known_failure", "outcome_unknown"}
                    or previous["next_eligible_at"] is None
                    or previous["next_eligible_at"] > now
                ):
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                retry_of = previous["attempt_id"] if previous is not None else None
            else:
                retry_of = None
                if action == NextAction(ActionKind.MODEL) or action is not None and action.action_kind is ActionKind.MODEL:
                    if request.purpose == "agent_turn" and action.action_kind is not ActionKind.MODEL:
                        raise RunError(RunErrorCode.INVALID_TRANSITION)
                    previous = connection.execute(
                        "SELECT * FROM run_provider_attempts WHERE request_id=? ORDER BY attempt_sequence DESC LIMIT 1",
                        (request.request_id,),
                    ).fetchone()
                    if previous is not None:
                        raise RunError(RunErrorCode.INVALID_TRANSITION)
                elif action is not None and action.action_kind is ActionKind.PROVIDER_RETRY:
                    previous = connection.execute(
                        "SELECT * FROM run_provider_attempts WHERE run_id=? AND attempt_id=?",
                        (run_id, action.attempt_id),
                    ).fetchone()
                    if (
                        previous is None or previous["request_id"] != request.request_id
                        or previous["status"] not in {"known_failure", "outcome_unknown"}
                        or previous["failure_category"] not in {"temporary_unsent", "temporary_rejected", "temporary_unknown"}
                        or not previous["next_eligible_at"] or previous["next_eligible_at"] > now
                        or previous["attempt_sequence"] >= request.max_attempts
                    ):
                        raise RunError(RunErrorCode.INVALID_TRANSITION)
                    retry_of = previous["attempt_id"]
                    retry_row = connection.execute(
                        "SELECT request_json FROM run_provider_requests WHERE request_id=?",
                        (request.request_id,),
                    ).fetchone()
                    if retry_row is None or retry_row["request_json"] != request_json:
                        raise RunError(RunErrorCode.INVALID_TRANSITION)
                else:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)

            attempt_sequence = int(connection.execute(
                "SELECT COUNT(*) FROM run_provider_attempts WHERE request_id=?", (request.request_id,)
            ).fetchone()[0]) + 1
            run_attempt_sequence = int(connection.execute(
                "SELECT COUNT(*) FROM run_provider_attempts WHERE run_id=?", (run_id,)
            ).fetchone()[0]) + 1
            if attempt_sequence > request.max_attempts:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            connection.execute(
                "INSERT INTO run_provider_attempts(attempt_id, run_id, request_id, attempt_sequence, run_attempt_sequence, phase, base_record_sequence, base_tool_sequence, status, response_record_id, failure_code, started_at, finished_at, connected_at, request_sent_at, response_headers_at, first_event_at, last_activity_at, failure_phase, provider_request_id, request_bytes, response_bytes, usage_json, retry_of_attempt_id, failure_category, http_status, next_eligible_at) "
                "VALUES (?, ?, ?, ?, ?, 'connecting', ?, ?, 'started', NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL, ?, NULL, NULL, NULL)",
                (
                    attempt_id, run_id, request.request_id, attempt_sequence,
                    run_attempt_sequence, request.base_record_sequence, request.base_tool_sequence,
                    now, request_bytes, retry_of,
                ),
            )
            if not auxiliary and request.purpose != "historical_import":
                action_json = _encode_action(NextAction(ActionKind.PROVIDER_ATTEMPT, attempt_id=attempt_id))
                cursor = connection.execute(
                    "UPDATE run_execution_checkpoints SET schema_version=2, revision=revision+1, next_action_json=?, updated_at=? WHERE run_id=? AND revision=?",
                    (action_json, now, run_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise RunError(RunErrorCode.STALE_CHECKPOINT)
            _append_provider_progress(
                connection,
                run_id,
                request.purpose,
                attempt_id,
                "connecting",
                expected_revision + (0 if auxiliary else 1),
                now,
            )

        return ProviderAttempt(
            attempt_id=attempt_id, run_id=run_id, request_id=request.request_id,
            attempt_sequence=attempt_sequence, run_attempt_sequence=run_attempt_sequence,
            request_attempt_number=attempt_sequence,
            base_record_sequence=request.base_record_sequence,
            base_tool_sequence=request.base_tool_sequence,
            status=ProviderAttemptStatus.STARTED, response_record_id=None,
            failure_code=None, started_at=now, finished_at=None,
            retry_of_attempt_id=retry_of, phase="connecting", request_bytes=request_bytes,
        )

    def update_provider_attempt_phase(
        self,
        *,
        session_id: str,
        run_id: str,
        attempt_id: str,
        phase: str,
        provider_request_id: str | None = None,
        http_status: int | None = None,
        activity: bool = False,
        first_event: bool = False,
        usage: ProviderUsage | None = None,
        response_bytes: int | None = None,
    ) -> None:
        if phase not in {"connecting", "sending", "awaiting_response", "streaming"}:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        _validate_id(attempt_id)
        now = _utc_now()
        with self._database.write() as connection:
            self._runs._scoped_run(connection, session_id, run_id)
            row = connection.execute(
                "SELECT a.*, q.purpose FROM run_provider_attempts a JOIN run_provider_requests q USING(request_id) WHERE a.run_id=? AND a.attempt_id=?",
                (run_id, attempt_id),
            ).fetchone()
            if row is None or row["status"] != "started":
                return
            phase_rank = {"connecting": 0, "sending": 1, "awaiting_response": 2, "streaming": 3}
            if phase_rank[phase] < phase_rank[row["phase"]]:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            first_event_at = row["first_event_at"]
            if first_event and first_event_at is None:
                first_event_at = now
            usage_json = None
            if usage is not None:
                usage_json = encode_json({item.name: getattr(usage, item.name) for item in fields(ProviderUsage)}, maximum=1024)
            if response_bytes is not None and (type(response_bytes) is not int or response_bytes < 0):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            cursor = connection.execute(
                "UPDATE run_provider_attempts SET phase=?, response_headers_at=CASE WHEN ? = 'awaiting_response' THEN COALESCE(response_headers_at, ?) ELSE response_headers_at END, first_event_at=COALESCE(first_event_at, ?), last_activity_at=CASE WHEN ? THEN ? ELSE last_activity_at END, provider_request_id=COALESCE(?, provider_request_id), http_status=COALESCE(?, http_status), response_bytes=COALESCE(?, response_bytes), usage_json=COALESCE(?, usage_json) WHERE run_id=? AND attempt_id=? AND status='started'",
                (phase, phase, now, first_event_at, int(activity), now,
                 provider_request_id, http_status, response_bytes, usage_json, run_id, attempt_id),
            )
            if cursor.rowcount != 1:
                return
            if phase != row["phase"]:
                checkpoint = self._runs._checkpoint_for_write(connection, run_id)
                _append_provider_progress(connection, run_id, row["purpose"], attempt_id, phase, checkpoint.revision, now)

    def begin_auxiliary_provider_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
        request: ProviderRequestRecord,
        request_bytes: int | None = None,
    ) -> ProviderAttempt:
        if request.purpose != "context_compaction":
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self.begin_provider_attempt(
            session_id=session_id, run_id=run_id, expected_revision=expected_revision,
            attempt_id=attempt_id, request=request, auxiliary=True, request_bytes=request_bytes,
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
                "SELECT a.*, q.purpose FROM run_provider_attempts a JOIN run_provider_requests q USING(request_id) WHERE a.run_id = ? AND a.attempt_id = ?",
                (run_id, provider_attempt_id),
            ).fetchone()
            if (
                attempt_row is None
                or attempt_row["status"] != ProviderAttemptStatus.STARTED.value
                or attempt_row["purpose"] != "agent_turn"
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
        cancelled: bool = False,
    ) -> Run:
        if type(expected_revision) is not int or expected_revision < 1 or type(outcome_unknown) is not bool or type(cancelled) is not bool:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        _validate_id(attempt_id)
        if failure_code is not None:
            if not isinstance(failure_code, str):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            try:
                failure_code = ProviderFailureCode(failure_code).value
            except ValueError:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        if not outcome_unknown and not cancelled and failure_code is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

        now = _utc_now()
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            stopping = read_stop_request(connection, run_id) is not None
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING or checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            attempt_row = connection.execute(
                "SELECT a.*, q.purpose, q.generation_only, q.max_attempts FROM run_provider_attempts a JOIN run_provider_requests q USING(request_id) WHERE a.run_id=? AND a.attempt_id=?",
                (run_id, attempt_id),
            ).fetchone()
            if attempt_row is None or attempt_row["status"] != ProviderAttemptStatus.STARTED.value:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            purpose = attempt_row["purpose"]
            auxiliary = purpose == "context_compaction"
            if not auxiliary and checkpoint.next_action != NextAction(ActionKind.PROVIDER_ATTEMPT, attempt_id=attempt_id):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            category = failure_category
            if category is None:
                category = (
                    "temporary_unknown" if outcome_unknown
                    else "temporary_rejected" if http_status is not None
                    else "temporary_unsent"
                ) if transient else "invalid_response" if failure_code == "invalid_provider_response" else "internal_error" if failure_code is None else "permanent"
            if category not in {"temporary_unsent", "temporary_rejected", "temporary_unknown", "permanent", "invalid_response", "internal_error"} or transient != category.startswith("temporary_"):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if (category == "temporary_unknown" and not outcome_unknown) or (category in {"temporary_unsent", "temporary_rejected"} and outcome_unknown):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            retry = (
                transient and not stopping and not cancelled
                and bool(attempt_row["generation_only"])
                and purpose != "historical_import"
                and attempt_row["attempt_sequence"] < attempt_row["max_attempts"]
            )
            due = retry_deadline(attempt_row["attempt_sequence"], retry_after_seconds) if retry else None
            terminal_attempt_status = (
                ProviderAttemptStatus.CANCELLED if cancelled or stopping
                else ProviderAttemptStatus.OUTCOME_UNKNOWN if outcome_unknown
                else ProviderAttemptStatus.KNOWN_FAILURE
            )
            cursor = connection.execute(
                "UPDATE run_provider_attempts SET status=?, failure_code=?, finished_at=?, failure_phase=phase, failure_category=?, http_status=?, next_eligible_at=?, last_activity_at=COALESCE(last_activity_at, ?) WHERE run_id=? AND attempt_id=? AND status='started'",
                (terminal_attempt_status.value, failure_code, now, category, http_status, due, now, run_id, attempt_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            if retry:
                if auxiliary:
                    _append_provider_progress(connection, run_id, purpose, attempt_id, attempt_row["phase"], checkpoint.revision, now)
                    return run
                connection.execute(
                    "UPDATE run_execution_checkpoints SET schema_version=2, revision=revision+1, next_action_json=?, updated_at=? WHERE run_id=? AND revision=?",
                    (_encode_action(NextAction(ActionKind.PROVIDER_RETRY, attempt_id=attempt_id)), now, run_id, expected_revision),
                )
                _append_provider_progress(connection, run_id, purpose, attempt_id, attempt_row["phase"], expected_revision + 1, now)
                return run

            if auxiliary and not (stopping or cancelled):
                return run

            terminal_code = (
                TerminalCode.INTERRUPTED if stopping or cancelled
                else TerminalCode.PROVIDER_OUTCOME_UNKNOWN if outcome_unknown
                else TerminalCode.EXECUTION_FAILED
            )
            status = RunStatus.INTERRUPTED if terminal_code is TerminalCode.INTERRUPTED else RunStatus.FAILED
            event_kind = EventKind.RUN_INTERRUPTED if status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
            message = TERMINAL_MESSAGES[terminal_code]
            connection.execute(
                "UPDATE runs SET status=?, finished_at=?, terminal_code=?, terminal_message=? WHERE run_id=? AND session_id=? AND status='running'",
                (status.value, now, terminal_code.value, message, run_id, session_id),
            )
            connection.execute(
                "UPDATE run_execution_checkpoints SET schema_version=2, revision=revision+1, next_action_json=NULL, updated_at=? WHERE run_id=? AND revision=?",
                (now, run_id, expected_revision),
            )
            event_json = encode_event_payload(event_kind, {"terminal_code": terminal_code.value})
            sequence = _next_event_sequence(connection, run_id)
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, sequence, event_kind.value, event_json, now),
            )
        return Run(
            run_id=run.run_id, session_id=run.session_id, ordinal=run.ordinal,
            input_record_id=run.input_record_id, status=status, provider=run.provider,
            model=run.model, created_at=run.created_at, started_at=run.started_at,
            finished_at=now, terminal_code=terminal_code.value, terminal_message=message,
        )
