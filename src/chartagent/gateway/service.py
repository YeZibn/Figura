"""Application service behind the local HTTP gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..memory import SQLiteAgentMemory
from ..runtime import AgentRuntime, create_agent_runtime
from .projection import project_completed_runs, session_summary
from .protocol import (
    GatewayFault,
    SessionTranscript,
    SessionSummary,
    success,
    validate_message_text,
    validate_session_name,
)


class GatewayService:
    """Translate stable gateway operations into Agent and memory calls."""

    def __init__(
        self,
        *,
        database: str | Path | None = None,
        model: str | None = None,
        memory_factory: Callable[..., SQLiteAgentMemory] | None = None,
        runtime_factory: Callable[[str], AgentRuntime] | None = None,
    ) -> None:
        self.database = database
        self.model = model
        self._memory_factory = memory_factory or self._open_memory
        self._runtime_factory = runtime_factory or self._build_runtime

    def _open_memory(self, name: str, *, create: bool = True) -> SQLiteAgentMemory:
        return SQLiteAgentMemory(name, database=self.database, create=create)

    def _build_runtime(self, name: str) -> AgentRuntime:
        return create_agent_runtime(
            session_name=name,
            database=self.database,
            model=self.model,
        )

    def health(self) -> dict[str, Any]:
        return success({"status": "ok", "service": "ChartAgent Gateway"})

    def list_sessions(self) -> dict[str, Any]:
        sessions = [session_summary(item).to_dict() for item in SQLiteAgentMemory.list_session_stats(database=self.database)]
        return success({"sessions": sessions})

    def create_session(self, raw_name: object) -> dict[str, Any]:
        name = validate_session_name(raw_name)
        if SQLiteAgentMemory.get_session_by_name(name, database=self.database) is not None:
            raise GatewayFault("session_exists", 409, "Session name is already in use")
        try:
            memory = self._memory_factory(name)
        except ValueError as exc:
            if "already exists" in str(exc):
                raise GatewayFault("session_exists", 409, "Session name is already in use") from exc
            raise GatewayFault("invalid_request", 400, "Session could not be created") from exc
        try:
            transcript = self._empty_transcript(memory.session)
            return transcript.to_dict()
        finally:
            memory.close()

    def get_session(self, session_id: object) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        memory = self._memory_factory(session.name, create=False)
        try:
            return self._transcript(memory).to_dict()
        finally:
            memory.close()

    def submit_message(self, session_id: object, raw_text: object) -> dict[str, Any]:
        text = validate_message_text(raw_text)
        session = self._resolve_session(session_id)
        try:
            runtime = self._runtime_factory(session.name)
        except Exception as exc:  # provider setup errors are a safe gateway fault
            raise GatewayFault(
                "agent_unavailable",
                503,
                "Agent service is unavailable",
            ) from exc
        try:
            try:
                answer = runtime.agent.run(text)
            except Exception as exc:
                raise GatewayFault("agent_failed", 502, "Agent run failed") from exc
        finally:
            runtime.close()

        transcript = self._load_transcript(session)
        payload = transcript.to_dict()
        payload["answer"] = str(answer)
        return payload

    def _resolve_session(self, raw_id: object):
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise GatewayFault("invalid_request", 400, "Session ID is required")
        session = SQLiteAgentMemory.get_session_by_id(raw_id, database=self.database)
        if session is None:
            raise GatewayFault("session_not_found", 404, "Session was not found")
        return session

    def _empty_transcript(self, session) -> SessionTranscript:
        return SessionTranscript(
            SessionSummary(session.id, session.name, session.updated_at, 0),
            (),
            (),
        )

    def _load_transcript(self, session) -> SessionTranscript:
        memory = self._memory_factory(session.name, create=False)
        try:
            return self._transcript(memory)
        finally:
            memory.close()

    @staticmethod
    def _transcript(memory: SQLiteAgentMemory) -> SessionTranscript:
        return project_completed_runs(memory.session, memory.completed_runs())
