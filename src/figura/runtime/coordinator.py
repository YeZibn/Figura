"""Internal application boundary for creating and advancing durable Figura Runs."""

from __future__ import annotations

import hashlib
import json

from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderUsage

from .errors import RunError, RunErrorCode
from .models import (
    ExecutionRecord,
    ModelResponseFact,
    Run,
    RunCreateRequest,
    RunInput,
    RunState,
    RunStatus,
    Session,
    TerminalCode,
)
from .store import FiguraRunStore

_MAX_INPUT_BYTES = 64 * 1024
_MAX_IDEMPOTENCY_KEY_BYTES = 128
_MAX_RESPONSE_BYTES = 128 * 1024
_MAX_SESSION_NAME_BYTES = 256


class RunCoordinator:
    """Validate application requests and delegate atomic transitions to the store."""

    def __init__(self, store: FiguraRunStore, provider_factory: ProviderFactory) -> None:
        self._store = store
        self._provider_factory = provider_factory

    def create_session(self, name: str | None = None) -> Session:
        if name is not None and (not isinstance(name, str) or _byte_length(name) > _MAX_SESSION_NAME_BYTES):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.create_session(name)

    def create_run(self, request: RunCreateRequest) -> Run:
        self._validate_create_request(request)
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

        return self._store.create_initial_run(
            session_id=request.session_id,
            provider_id=provider_id.value,
            model_id=request.model_id,
            input_payload=RunInput(
                text=request.text,
                attachment_ids=(),
                requested_provider=provider_id.value,
                requested_model=request.model_id,
            ),
            key_digest=key_digest,
            request_fingerprint=fingerprint,
        )

    def read_run_state(self, session_id: str, run_id: str) -> RunState:
        return self._store.read_run_state(session_id, run_id)

    def commit_model_response(
        self,
        session_id: str,
        run_id: str,
        expected_revision: int,
        response: ProviderResponse,
    ) -> ExecutionRecord:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        fact = self._model_response_fact(response)
        return self._store.commit_model_response(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            payload=fact,
        )

    def complete_run(
        self, session_id: str, run_id: str, expected_revision: int
    ) -> ExecutionRecord:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._store.complete_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
        )

    def fail_run(
        self,
        session_id: str,
        run_id: str,
        expected_revision: int,
        terminal_code: TerminalCode = TerminalCode.EXECUTION_FAILED,
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
        )

    def interrupt_run(self, session_id: str, run_id: str, expected_revision: int) -> Run:
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
        if text_size == 0 or text_size > _MAX_INPUT_BYTES or not request.text.strip():
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(request.idempotency_key, str):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        key_size = _byte_length(request.idempotency_key)
        if key_size == 0 or key_size > _MAX_IDEMPOTENCY_KEY_BYTES:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(request.attachment_ids, (tuple, list)):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if request.attachment_ids:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

    @staticmethod
    def _model_response_fact(response: ProviderResponse) -> ModelResponseFact:
        if not isinstance(response, ProviderResponse):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if response.tool_calls or response.continuation is not None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        try:
            provider_id = ProviderId(response.provider_id)
            finish_reason = FinishReason(response.finish_reason)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        if not isinstance(response.model_id, str) or not response.model_id or _byte_length(response.model_id) > 128:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if not isinstance(response.assistant_content, str) or _byte_length(response.assistant_content) > _MAX_RESPONSE_BYTES:
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
        )


def _request_fingerprint(request: RunCreateRequest) -> str:
    canonical = json.dumps(
        {
            "session_id": request.session_id,
            "text": request.text,
            "attachment_ids": [],
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
