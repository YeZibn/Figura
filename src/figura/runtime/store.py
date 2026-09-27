"""Stable FiguraRunStore façade over domain-focused persistence repositories."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable, Iterator

from figura.providers.models import ProviderContinuation
from figura.tools.contracts import ReplayEffect, ToolExecutionResult

from .domain.models import (
    AttachmentMetadata,
    ExecutionRecord,
    ModelResponseFact,
    ProviderAttempt,
    Run,
    RunInput,
    RunState,
    RunStatus,
    Session,
    TerminalCode,
    ToolCallFact,
    ToolExecutionFact,
)
from .persistence.database import SqliteDatabase
from .persistence.execution_repository import ExecutionRepository
from .persistence.run_repository import RunRepository
from .persistence.session_repository import SessionRepository


class FiguraRunStore:
    """Own one Figura SQLite database and preserve its stable call surface."""

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self._database = SqliteDatabase(data_root)
        self.data_root = self._database.data_root
        self.database_path = self._database.database_path
        self._sessions = SessionRepository(self._database)
        self._runs = RunRepository(self._database, self._sessions)
        self._execution = ExecutionRepository(self._database, self._runs)

    def create_session(self, name: str | None = None) -> Session:
        return self._sessions.create_session(name)

    def assert_session(self, session_id: str) -> None:
        self._sessions.assert_session(session_id)

    def register_attachment(
        self,
        metadata: AttachmentMetadata,
        install_file: Callable[[], None],
    ) -> None:
        self._sessions.register_attachment(metadata, install_file)

    def list_attachments(self, session_id: str) -> tuple[AttachmentMetadata, ...]:
        return self._sessions.list_attachments(session_id)

    def get_attachment_metadata(
        self,
        session_id: str,
        attachment_id: str,
    ) -> AttachmentMetadata:
        return self._sessions.get_attachment_metadata(session_id, attachment_id)

    @contextmanager
    def delete_attachment_transaction(
        self,
        session_id: str,
        attachment_id: str,
    ) -> Iterator[AttachmentMetadata]:
        with self._sessions.delete_attachment_transaction(session_id, attachment_id) as metadata:
            yield metadata

    def reconcile_attachment_files(
        self,
        reconcile: Callable[[frozenset[str]], None],
    ) -> None:
        self._sessions.reconcile_attachment_files(reconcile)

    def find_idempotent_run(
        self,
        session_id: str,
        key_digest: str,
        request_fingerprint: str,
    ) -> Run | None:
        return self._runs.find_idempotent_run(session_id, key_digest, request_fingerprint)

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
        return self._runs.create_initial_run(
            session_id=session_id,
            provider_id=provider_id,
            model_id=model_id,
            input_payload=input_payload,
            key_digest=key_digest,
            request_fingerprint=request_fingerprint,
        )

    def read_run_state(self, session_id: str, run_id: str) -> RunState:
        return self._runs.read_run_state(session_id, run_id)

    def read_prior_run_states(self, session_id: str, run_id: str) -> tuple[RunState, ...]:
        return self._runs.read_prior_run_states(session_id, run_id)

    def begin_provider_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
    ) -> ProviderAttempt:
        return self._execution.begin_provider_attempt(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            attempt_id=attempt_id,
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
        return self._execution.commit_model_response(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            provider_attempt_id=provider_attempt_id,
            payload=payload,
            record_id=record_id,
            tool_calls=tool_calls,
            continuation=continuation,
            continuation_id=continuation_id,
        )

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
        return self._execution.fail_provider_attempt(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            attempt_id=attempt_id,
            outcome_unknown=outcome_unknown,
            failure_code=failure_code,
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
        return self._execution.begin_tool_attempt(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            tool_call_sequence=tool_call_sequence,
            registry_version=registry_version,
            replay_effect=replay_effect,
            attempt_id=attempt_id,
        )

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
        return self._execution.begin_tool_replay_attempt(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            tool_call_sequence=tool_call_sequence,
            previous_attempt_id=previous_attempt_id,
            registry_version=registry_version,
            attempt_id=attempt_id,
        )

    def commit_tool_result(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
        result: ToolExecutionResult,
    ) -> ToolExecutionFact:
        return self._execution.commit_tool_result(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            attempt_id=attempt_id,
            result=result,
        )

    def complete_run(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
    ) -> ExecutionRecord:
        return self._execution.complete_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
        )

    def terminal_run(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        status: RunStatus,
        terminal_code: TerminalCode,
    ) -> Run:
        return self._execution.terminal_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            status=status,
            terminal_code=terminal_code,
        )
