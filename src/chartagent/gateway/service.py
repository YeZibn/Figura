"""Application service behind the local HTTP gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..attachments import AttachmentRegistry
from ..memory import SQLiteAgentMemory
from ..multimodal import build_registered_attachment_turn
from ..runtime import AgentRuntime, create_agent_runtime
from .attachments import AttachmentStoreError, EphemeralAttachmentStore
from .projection import project_completed_runs, session_summary
from .protocol import (
    AttachmentSummary,
    GatewayFault,
    SessionTranscript,
    SessionSummary,
    success,
    validate_attachment_ids,
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
        attachment_store: EphemeralAttachmentStore | None = None,
        attachment_root: str | Path | None = None,
    ) -> None:
        self.database = database
        self.model = model
        self._memory_factory = memory_factory or self._open_memory
        self._runtime_factory = runtime_factory or self._build_runtime
        self._attachment_store = attachment_store or EphemeralAttachmentStore(attachment_root)

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

    def submit_message(
        self,
        session_id: object,
        raw_text: object,
        raw_attachment_ids: object = None,
    ) -> dict[str, Any]:
        text = validate_message_text(raw_text)
        session = self._resolve_session(session_id)
        attachment_ids = validate_attachment_ids(raw_attachment_ids)
        attachment_metadata: list[dict[str, Any]] = []
        if attachment_ids:
            memory = self._memory_factory(session.name, create=False)
            try:
                registry = self._registry(memory)
                for attachment_id in attachment_ids:
                    item, error = registry.validate(attachment_id)
                    if item is None:
                        if registry.get(attachment_id) is None:
                            raise GatewayFault("attachment_not_found", 404, "Attachment was not found")
                        raise GatewayFault("attachment_unavailable", 409, "Attachment is unavailable")
                    if error:
                        raise GatewayFault("attachment_unavailable", 409, "Attachment is unavailable")
                    attachment_metadata.append(item.metadata())
            finally:
                memory.close()
        prompt = build_registered_attachment_turn(text, attachment_metadata) if attachment_metadata else text
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
                answer = runtime.agent.run(prompt)
            except Exception as exc:
                raise GatewayFault("agent_failed", 502, "Agent run failed") from exc
        finally:
            runtime.close()

        transcript = self._load_transcript(session)
        payload = transcript.to_dict()
        payload["answer"] = str(answer)
        return payload

    def upload_attachment(
        self,
        session_id: object,
        filename: object,
        media_type: object,
        content: bytes,
    ) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        if not isinstance(filename, str) or not isinstance(media_type, str):
            raise GatewayFault("invalid_request", 400, "Attachment metadata is invalid")
        memory = self._memory_factory(session.name, create=False)
        staged = None
        try:
            try:
                staged = self._attachment_store.stage(session.id, filename, media_type, content)
            except AttachmentStoreError as exc:
                raise GatewayFault(exc.code, exc.status, exc.message) from exc
            registry = self._registry(memory, save=True)
            try:
                item = registry.register(
                    str(staged),
                    ordinal=len(memory.list_attachments()) + 1,
                    filename=filename,
                )
            except (OSError, ValueError) as exc:
                self._attachment_store.remove(staged)
                raise GatewayFault("invalid_image", 400, "Attachment could not be registered") from exc
            return success({"attachment": self._attachment_summary(item, registry).to_dict()})
        finally:
            memory.close()

    def list_attachments(self, session_id: object) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        memory = self._memory_factory(session.name, create=False)
        try:
            registry = self._registry(memory)
            attachments = [
                self._attachment_summary(item, registry).to_dict()
                for item in memory.list_attachments()
            ]
            return success({"attachments": attachments})
        finally:
            memory.close()

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

    def _transcript(self, memory: SQLiteAgentMemory) -> SessionTranscript:
        registry = self._registry(memory)
        attachments = [
            self._attachment_summary(item, registry)
            for item in memory.list_attachments()
        ]
        return project_completed_runs(memory.session, memory.completed_runs(), attachments)

    @staticmethod
    def _registry(
        memory: SQLiteAgentMemory,
        *,
        save: bool = False,
    ) -> AttachmentRegistry:
        return AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment if save else None,
            load=memory.get_attachment,
        )

    @staticmethod
    def _attachment_summary(item, registry: AttachmentRegistry) -> AttachmentSummary:
        _, error = registry.validate(item.id)
        return AttachmentSummary(
            attachment_id=item.id,
            filename=item.filename,
            media_type=item.media_type,
            byte_count=item.byte_count,
            sha256=item.sha256,
            status="unavailable" if error else "registered",
            preview_available=False,
        )
