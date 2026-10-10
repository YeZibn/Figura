"""Internal application boundary for creating and advancing durable Figura Runs."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import ExitStack
from pathlib import Path

from figura.providers import (
    FinishReason,
    MODEL_IDS,
    ProviderFactory,
    ProviderContinuation,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
)
from figura.shared.payloads import encode_json, PayloadError, payload_scope

from .codecs.tools import (
    validate_tool_call_batch,
)
from .errors import RunError, RunErrorCode
from .run_lock import PerRunExecutionLock, RunExecutionOwnership, RunExecutionLockUnavailable
from .models import (
    ActionKind,
    Run,
    RunCreateRequest,
    RunStatus,
    RunStopRequest,
    Session,
    SessionListEntry,
    TerminalCode,
)
from .records import (
    ContextCompactionOperation,
    ExecutionRecord,
    ModelResponseFact,
    ProviderAttempt,
    ProviderRequestBinding,
    RunInput,
    RunState,
    SessionContextCheckpoint,
    SessionSnapshot,
    ToolCallFact,
)
from .store import FiguraRunStore





_MAX_IDEMPOTENCY_KEY_BYTES = 128





_MAX_SESSION_NAME_BYTES = 256


class RunCoordinator:
    """Validate application requests and delegate atomic transitions to the store."""

    def __init__(self, store: FiguraRunStore, provider_factory: ProviderFactory) -> None:
        self.payload_limits = store.payload_limits
        self._store = store
        self._provider_factory = provider_factory

    @property
    def data_root(self) -> Path:
        return self._store.data_root

    def request_stop(self, session_id: str, run_id: str) -> RunStopRequest | None:
        return self._store.request_stop(session_id, run_id)

    def create_session(self, name: str | None = None) -> Session:
        if name is not None and (not isinstance(name, str) or _byte_length(name) > _MAX_SESSION_NAME_BYTES):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.create_session(name)

    def list_sessions(self) -> tuple[Session, ...]:
        return self._store.list_sessions()

    def list_session_entries(self) -> tuple[SessionListEntry, ...]:
        return self._store.list_session_entries()

    def get_session(self, session_id: str) -> Session:
        return self._store.get_session(session_id)

    def read_session_snapshot(self, session_id: str) -> SessionSnapshot:
        return self._store.read_session_snapshot(session_id)

    def read_session_context_checkpoint(
        self, session_id: str
    ) -> SessionContextCheckpoint | None:
        return self._store.read_session_context_checkpoint(session_id)

    def replace_session_context_checkpoint(
        self,
        checkpoint: SessionContextCheckpoint,
        *,
        expected_revision: int,
    ) -> SessionContextCheckpoint:
        return self._store.replace_session_context_checkpoint(
            checkpoint, expected_revision=expected_revision
        )

    def get_or_create_context_compaction_operation(
        self, **values
    ) -> ContextCompactionOperation:
        return self._store.get_or_create_context_compaction_operation(**values)

    def find_context_compaction_operation(
        self,
        session_id: str,
        target_run_id: str,
        base_record_sequence: int,
        base_tool_sequence: int,
    ) -> ContextCompactionOperation | None:
        return self._store.find_context_compaction_operation(
            session_id, target_run_id, base_record_sequence, base_tool_sequence
        )

    def bind_context_compaction_request(
        self, operation_id: str, binding: dict[str, object]
    ) -> ContextCompactionOperation:
        return self._store.bind_context_compaction_request(operation_id, binding)

    def begin_context_compaction_attempt(self, operation_id: str) -> int:
        return self._store.begin_context_compaction_attempt(operation_id)

    def read_context_compaction_operation(
        self, operation_id: str
    ) -> ContextCompactionOperation:
        return self._store.read_context_compaction_operation(operation_id)

    def fallback_context_compaction_operation(
        self, operation_id: str, failure_code: str | None
    ) -> ContextCompactionOperation:
        return self._store.fallback_context_compaction_operation(
            operation_id, failure_code
        )

    def list_running_runs(self) -> tuple[Run, ...]:
        return self._store.list_running_runs()

    @payload_scope
    def create_run(self, request: RunCreateRequest) -> Run:
        self._validate_create_request(request)
        try:
            encode_json({"text": request.text, "attachment_ids": request.attachment_ids})
        except PayloadError:
            raise RunError(RunErrorCode.INVALID_REQUEST) from None
        try:
            provider_id = ProviderId(request.provider_id)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.INVALID_REQUEST) from None
        expected_model = MODEL_IDS[provider_id]
        if request.model_id != expected_model:
            raise RunError(RunErrorCode.INVALID_REQUEST)

        key_digest = _sha256(request.idempotency_key)
        fingerprint = _request_fingerprint(request)
        self._store.assert_session(request.session_id)
        existing = self._store.find_idempotent_run(request.session_id, key_digest, fingerprint)
        if existing is not None:
            return existing

        try:
            availability = self._provider_factory.availability()
        except Exception:
            raise RunError(RunErrorCode.PROVIDER_UNAVAILABLE) from None
        selected = next(
            (item for item in availability if item.provider_id is provider_id),
            None,
        )
        if selected is None or not selected.available or selected.model_id != request.model_id:
            raise RunError(RunErrorCode.PROVIDER_UNAVAILABLE)

        try:
            with ExitStack() as locks:
                snapshot = self.read_session_snapshot(request.session_id)
                for state in snapshot.run_states:
                    locks.enter_context(RunExecutionOwnership(self.data_root).acquire(state.run.run_id))
                return self._store.create_initial_run(
                    session_id=request.session_id,
                    provider_id=provider_id.value,
                    model_id=request.model_id,
                    input_payload=RunInput(
                        text=request.text,
                        attachment_ids=tuple(request.attachment_ids),
                        requested_provider=provider_id.value,
                        requested_model=request.model_id,
                    ),
                    key_digest=key_digest,
                    request_fingerprint=fingerprint,
                )
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def read_run_state(self, session_id: str, run_id: str) -> RunState:
        return self._store.read_run_state(session_id, run_id)

    def read_prior_run_states(self, session_id: str, run_id: str) -> tuple[RunState, ...]:
        return self._store.read_prior_run_states(session_id, run_id)

    def begin_provider_attempt(
        self, session_id: str, run_id: str, expected_revision: int, *, binding: ProviderRequestBinding | None = None
    ) -> ProviderAttempt:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.begin_provider_attempt(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            attempt_id=uuid.uuid4().hex, binding=binding,
        )

    @payload_scope
    def commit_model_response(
        self,
        session_id: str,
        run_id: str,
        expected_revision: int,
        response: ProviderResponse,
        *,
        provider_attempt_id: str,
        registry_version: str | None = None,
    ) -> ExecutionRecord:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(provider_attempt_id, str) or not provider_attempt_id:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        continuation_ref = (
            uuid.uuid4().hex
            if isinstance(response, ProviderResponse) and response.continuation is not None
            else None
        )
        fact = self._model_response_fact(response, continuation_ref=continuation_ref)
        response_record_id = uuid.uuid4().hex
        tool_calls = self._tool_call_facts(response, response_record_id, registry_version)
        return self._store.commit_model_response(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            provider_attempt_id=provider_attempt_id,
            payload=fact,
            record_id=response_record_id,
            tool_calls=tool_calls,
            continuation=response.continuation,
            continuation_id=continuation_ref,
        )

    def complete_run(self, session_id: str, run_id: str, expected_revision: int) -> ExecutionRecord:
        try:
            with RunExecutionOwnership(self.data_root).acquire(run_id):
                with PerRunExecutionLock(self.data_root).acquire(run_id):
                    return self._complete_owned_run(session_id, run_id, expected_revision)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def _complete_owned_run(
        self, session_id: str, run_id: str, expected_revision: int
    ) -> ExecutionRecord:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.complete_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
        )

    def fail_provider_attempt(
        self,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
        *,
        outcome_unknown: bool,
        failure_code: str | None,
        transient: bool = False,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
        failure_category: str | None = None,
    ) -> Run:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.fail_provider_attempt(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            attempt_id=attempt_id,
            outcome_unknown=outcome_unknown,
            failure_code=failure_code, transient=transient, http_status=http_status, retry_after_seconds=retry_after_seconds, failure_category=failure_category,
        )

    def resolve_orphaned_provider_attempt(self, session_id: str, run_id: str) -> RunState:
        try:
            with RunExecutionOwnership(self.data_root).acquire(run_id):
                return self._resolve_owned_provider_attempt(session_id, run_id)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def _resolve_owned_provider_attempt(self, session_id: str, run_id: str) -> RunState:
        try:
            with PerRunExecutionLock(self._store.data_root).acquire(run_id):
                state = self._store.read_run_state(session_id, run_id)
                action = state.checkpoint.next_action
                if (
                    state.run.status is not RunStatus.RUNNING
                    or action is None
                    or action.action_kind is not ActionKind.PROVIDER_ATTEMPT
                ):
                    return state
                if action.attempt_id is None:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                self._store.fail_provider_attempt(
                    session_id=session_id,
                    run_id=run_id,
                    expected_revision=state.checkpoint.revision,
                    attempt_id=action.attempt_id,
                    outcome_unknown=True,
                    failure_code=None, transient=state.provider_attempts[-1].operation_id is not None,
                )
                return self._store.read_run_state(session_id, run_id)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def fail_run(self, session_id: str, run_id: str, expected_revision: int,
                 terminal_code: TerminalCode = TerminalCode.EXECUTION_FAILED, *,
                 terminal_message: str | None = None) -> Run:
        try:
            with RunExecutionOwnership(self.data_root).acquire(run_id):
                with PerRunExecutionLock(self.data_root).acquire(run_id):
                    return self._fail_owned_run(session_id, run_id, expected_revision,
                                                terminal_code, terminal_message=terminal_message)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def _fail_owned_run(
        self,
        session_id: str,
        run_id: str,
        expected_revision: int,
        terminal_code: TerminalCode = TerminalCode.EXECUTION_FAILED,
        *,
        terminal_message: str | None = None,
    ) -> Run:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(terminal_code, TerminalCode) or terminal_code is TerminalCode.INTERRUPTED:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.terminal_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            status=RunStatus.FAILED,
            terminal_code=terminal_code,
            terminal_message=terminal_message,
        )

    def interrupt_run(self, session_id: str, run_id: str, expected_revision: int) -> Run:
        try:
            with RunExecutionOwnership(self.data_root).acquire(run_id):
                with PerRunExecutionLock(self.data_root).acquire(run_id):
                    return self._interrupt_owned_run(session_id, run_id, expected_revision)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def _interrupt_owned_run(self, session_id: str, run_id: str, expected_revision: int) -> Run:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.terminal_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            status=RunStatus.INTERRUPTED,
            terminal_code=TerminalCode.INTERRUPTED,
        )

    @staticmethod
    def _validate_create_request(request: RunCreateRequest) -> None:
        if not isinstance(request, RunCreateRequest):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        for identity in (request.session_id, request.provider_id, request.model_id):
            if not isinstance(identity, str) or not identity or _byte_length(identity) > 128:
                raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(request.text, str):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        text_size = _byte_length(request.text)
        if text_size == 0 or not request.text.strip():
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(request.idempotency_key, str):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        key_size = _byte_length(request.idempotency_key)
        if key_size == 0 or key_size > _MAX_IDEMPOTENCY_KEY_BYTES:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(request.attachment_ids, (tuple, list)):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if any(
            not isinstance(attachment_id, str)
            or not attachment_id
            or _byte_length(attachment_id) > 128
            for attachment_id in request.attachment_ids
        ):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if len(set(request.attachment_ids)) != len(request.attachment_ids):
            raise RunError(RunErrorCode.INVALID_REQUEST)

    @staticmethod
    def _model_response_fact(
        response: ProviderResponse,
        *,
        continuation_ref: str | None = None,
    ) -> ModelResponseFact:
        if not isinstance(response, ProviderResponse):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        try:
            provider_id = ProviderId(response.provider_id)
            finish_reason = FinishReason(response.finish_reason)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        continuation = response.continuation
        if continuation is None:
            if continuation_ref is not None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        else:
            if not isinstance(continuation, ProviderContinuation):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            try:
                continuation_provider = ProviderId(continuation.provider_id)
            except (TypeError, ValueError):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
            if continuation_provider is not provider_id:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if type(continuation.format_version) is not int:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if continuation.format_version != 1:
                raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
            content = continuation.reasoning_content
            if (
                (content is not None and not isinstance(content, str))
                or (provider_id is not ProviderId.DEEPSEEK and not content)
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if not isinstance(continuation_ref, str) or not continuation_ref or _byte_length(continuation_ref) > 128:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if not isinstance(response.model_id, str) or not response.model_id or _byte_length(response.model_id) > 128:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if not isinstance(response.assistant_content, str):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if response.usage is not None and not isinstance(response.usage, ProviderUsage):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if response.provider_response_id is not None and (
            not isinstance(response.provider_response_id, str)
            or _byte_length(response.provider_response_id) > 512
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return ModelResponseFact(
            provider_id=provider_id.value,
            model_id=response.model_id,
            assistant_content=response.assistant_content,
            finish_reason=finish_reason.value,
            usage=response.usage,
            provider_response_id=response.provider_response_id,
            continuation_ref=continuation_ref,
            schema_version=3,
        )

    @staticmethod
    def _tool_call_facts(
        response: ProviderResponse,
        response_record_id: str,
        registry_version: str | None,
    ) -> tuple[ToolCallFact, ...]:
        try:
            finish_reason = FinishReason(response.finish_reason)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        if not isinstance(response.tool_calls, (tuple, list)):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        provider_calls = tuple(response.tool_calls)
        if not provider_calls:
            if finish_reason is FinishReason.TOOL_CALLS:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            return ()
        if finish_reason is not FinishReason.TOOL_CALLS:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if not isinstance(registry_version, str) or not registry_version:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if _byte_length(registry_version) > 128:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

        calls: list[ToolCallFact] = []
        for position, call in enumerate(provider_calls):
            if not isinstance(call, ProviderToolCall):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            calls.append(
                ToolCallFact(
                    response_record_id=response_record_id,
                    call_id=call.call_id,
                    tool_name=call.name,
                    arguments_json=call.arguments,
                    position=position,
                    registry_version=registry_version,
                )
            )
        normalized = tuple(calls)
        validate_tool_call_batch(normalized)
        return normalized


def _request_fingerprint(request: RunCreateRequest) -> str:
    canonical = json.dumps(
        {
            "session_id": request.session_id,
            "text": request.text,
            "attachment_ids": list(request.attachment_ids),
            "provider_id": request.provider_id,
            "model_id": request.model_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _sha256(canonical)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _byte_length(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return 2**63 - 1
