"""Compose Runtime persistence repositories over one SQLite database."""

from __future__ import annotations

import os
import sqlite3

from figura.providers.models import ProviderContinuation
from figura.storage.database import SqliteDatabase
from figura.tools.contracts import ReplayEffect, ToolExecutionResult

from .models import (
    Run,
    RunStatus,
    Session,
    SessionListEntry,
    TerminalCode,
)
from .records import (
    ExecutionRecord,
    ModelResponseFact,
    ProviderAttempt,
    RunInput,
    RunState,
    SessionSnapshot,
    ToolCallFact,
    ToolExecutionFact,
)
from .persistence.providers import ProviderRepository
from .persistence.runs import RunRepository
from .persistence.sessions import SessionRepository
from .persistence.snapshots import SnapshotRepository
from .persistence.run_transitions import RunTransitionRepository
from .persistence.tools import ToolRepository


class FiguraRunStore:
    """Own the SQLite database and coordinate Runtime persistence operations."""

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self._database = SqliteDatabase(data_root)
        self.data_root = self._database.data_root
        self.database_path = self._database.database_path
        self._sessions = SessionRepository(self._database)
        self._runs = RunRepository(self._database)
        self._snapshots = SnapshotRepository(self._database, self._runs)
        self._providers = ProviderRepository(self._database, self._runs)
        self._tools = ToolRepository(self._database, self._runs)
        self._transitions = RunTransitionRepository(self._database, self._runs)

    @property
    def database(self) -> SqliteDatabase:
        return self._database

    def create_session(self, name: str | None = None) -> Session:
        return self._sessions.create_session(name)

    def assert_session(self, session_id: str) -> None:
        self._sessions.assert_session(session_id)

    def list_sessions(self) -> tuple[Session, ...]:
        return self._sessions.list_sessions()

    def list_session_entries(self) -> tuple[SessionListEntry, ...]:
        return self._sessions.list_session_entries()

    def get_session(self, session_id: str) -> Session:
        return self._sessions.get_session(session_id)

    def session_exists(self, session_id: str) -> bool:
        return self._sessions.session_exists(session_id)

    def session_deletion_resources(
        self, connection: sqlite3.Connection, session_id: str
    ) -> tuple[tuple[str, str], ...]:
        """Read render-file identities while the caller holds the write lock."""
        self._sessions.assert_deletable(connection, session_id)
        return self._runs.session_render_calls(connection, session_id)

    def list_chart_render_calls(self) -> tuple[tuple[str, str], ...]:
        with self._database.read() as connection:
            return self._runs.all_chart_render_calls(connection)

    def begin_session_deletion(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        """Authorize a Session purge after checking it under the caller's write lock."""
        self._sessions.assert_deletable(connection, session_id)
        self._sessions.begin_deletion(connection, session_id)

    def delete_session_run_facts(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        self._sessions.assert_deletable(connection, session_id)
        self._runs.delete_session_facts(connection, session_id)

    def delete_session_runs(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        self._sessions.assert_deletable(connection, session_id)
        self._runs.delete_session_rows(connection, session_id)

    def complete_session_deletion(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        self._sessions.complete_deletion(connection, session_id)

    def read_session_snapshot(self, session_id: str) -> SessionSnapshot:
        return self._snapshots.read_session_snapshot(session_id)

    def list_running_runs(self) -> tuple[Run, ...]:
        return self._runs.list_running_runs()

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
        return self._snapshots.read_prior_run_states(session_id, run_id)

    def begin_provider_attempt(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        attempt_id: str,
    ) -> ProviderAttempt:
        return self._providers.begin_provider_attempt(
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
        return self._providers.commit_model_response(
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
        return self._providers.fail_provider_attempt(
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
        return self._tools.begin_tool_attempt(
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
        return self._tools.begin_tool_replay_attempt(
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
        return self._tools.commit_tool_result(
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
        return self._transitions.complete_run(
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
        terminal_message: str | None = None,
    ) -> Run:
        return self._transitions.terminal_run(
            session_id=session_id,
            run_id=run_id,
            expected_revision=expected_revision,
            status=status,
            terminal_code=terminal_code,
            terminal_message=terminal_message,
        )
