"""Application service behind the local HTTP gateway."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Sequence

from ..attachments import AttachmentRegistry
from ..memory import SQLiteAgentMemory
from ..memory.sqlite import default_database_path
from ..multimodal import build_registered_attachment_turn
from ..runtime import AgentRuntime, create_agent_runtime, probe_agent_readiness
from ..tools.result import GeneratedImage
from ..trace import TraceSink
from .attachments import AttachmentStoreError, EphemeralAttachmentStore
from .history import GatewayHistoryStore, HistoryStoreError
from .projection import project_completed_runs, session_summary
from .runs import HistoricalRun, ManagedRun, RunManager
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
        run_manager: RunManager | None = None,
        history_store: GatewayHistoryStore | None = None,
        readiness_probe: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.database = Path(database).expanduser() if database is not None else default_database_path()
        self.model = model
        self._memory_factory = memory_factory or self._open_memory
        self._runtime_factory = runtime_factory or self._build_runtime
        self._attachment_store = attachment_store or EphemeralAttachmentStore(
            attachment_root,
            database=self.database,
        )
        self._history = history_store or GatewayHistoryStore(self.database)
        self._history.interrupt_running_runs()
        self._runs = run_manager or RunManager(history_store=self._history)
        if run_manager is not None:
            self._runs.history_store = self._history
        self._readiness_probe = readiness_probe or (lambda: probe_agent_readiness(model=self.model))

    def _open_memory(self, name: str, *, create: bool = True) -> SQLiteAgentMemory:
        return SQLiteAgentMemory(name, database=self.database, create=create)

    def _build_runtime(
        self,
        name: str,
        *,
        run_id: str | None = None,
        trace_sink: TraceSink | None = None,
        visual_observation_sink: Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]] | None = None,
    ) -> AgentRuntime:
        return create_agent_runtime(
            session_name=name,
            database=self.database,
            model=self.model,
            run_id=run_id,
            trace_sink=trace_sink,
            visual_observation_sink=visual_observation_sink,
        )

    def health(self) -> dict[str, Any]:
        try:
            readiness = self._readiness_probe()
        except Exception:
            readiness = {"status": "unavailable", "reason": "initialization_failed"}
        status = "ready" if readiness.get("status") == "ready" else "unavailable"
        agent: dict[str, str] = {"status": status}
        if status != "ready":
            reason = readiness.get("reason")
            if reason in {"missing_configuration", "invalid_configuration", "initialization_failed"}:
                agent["reason"] = reason
            else:
                agent["reason"] = "initialization_failed"
        return success({"status": "ok", "service": "Figura Gateway", "agent": agent})

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

    def delete_session(self, session_id: object) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        with self._runs.session_operation():
            if self._runs.has_active(session.id):
                raise GatewayFault("session_busy", 409, "Session has an active Agent run")
            try:
                self._history.delete_session(session.id)
            except HistoryStoreError as exc:
                raise GatewayFault("gateway_storage_error", 500, "运行记录清理失败") from exc
            attachments = SQLiteAgentMemory.delete_session_by_id(
                session.id,
                database=self.database,
            )
        if attachments is None:
            raise GatewayFault("session_not_found", 404, "Session was not found")

        cleanup_pending = False
        for item in attachments:
            if not self._attachment_store.is_managed_path(session.id, item.canonical_path):
                continue
            try:
                self._attachment_store.remove_managed(session.id, item.canonical_path)
            except AttachmentStoreError:
                cleanup_pending = True
        try:
            self._attachment_store.remove_session(session.id)
        except AttachmentStoreError:
            cleanup_pending = True
        result: dict[str, Any] = {"sessionId": session.id, "deleted": True}
        if cleanup_pending:
            result["cleanupPending"] = True
        return success(result)

    def delete_attachment(self, session_id: object, attachment_id: object) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        if not isinstance(attachment_id, str) or not attachment_id.strip():
            raise GatewayFault("invalid_request", 400, "Attachment ID is required")
        with self._runs.session_operation():
            if self._runs.has_active(session.id):
                raise GatewayFault("session_busy", 409, "Session has an active Agent run")
            memory = self._memory_factory(session.name, create=False)
            try:
                item = memory.get_attachment(attachment_id)
            finally:
                memory.close()
            if item is None:
                raise GatewayFault("attachment_not_found", 404, "Attachment was not found")
            if self._attachment_store.is_managed_path(session.id, item.canonical_path):
                try:
                    self._attachment_store.remove_managed(session.id, item.canonical_path)
                except AttachmentStoreError as exc:
                    raise GatewayFault(exc.code, exc.status, exc.message) from exc
            deleted = SQLiteAgentMemory.delete_attachment_by_id(
                session.id,
                attachment_id,
                database=self.database,
            )
        if deleted is None:
            raise GatewayFault("attachment_not_found", 404, "Attachment was not found")
        return success({"sessionId": session.id, "attachmentId": attachment_id, "deleted": True})

    def submit_message(
        self,
        session_id: object,
        raw_text: object,
        raw_attachment_ids: object = None,
    ) -> dict[str, Any]:
        run = self._start_managed_run(session_id, raw_text, raw_attachment_ids)
        if not run.wait_terminal(timeout=3600):
            run.fail("run_timeout", 504, "Agent run timed out")
        if run.status.value == "failed":
            raise GatewayFault(
                run.error_code or "agent_failed",
                run.error_status,
                run.error_message or "Agent run failed",
                run.error_reason,
            )
        session = self._resolve_session(session_id)
        transcript = self._load_transcript(session)
        payload = transcript.to_dict()
        payload["answer"] = str(run.answer or "")
        payload["runId"] = run.run_id
        return payload

    def start_run(
        self,
        session_id: object,
        raw_text: object,
        raw_attachment_ids: object = None,
    ) -> dict[str, Any]:
        run = self._start_managed_run(session_id, raw_text, raw_attachment_ids)
        return success({"run": run.accepted.to_dict()})

    def get_run(self, session_id: object, run_id: object) -> ManagedRun:
        session = self._resolve_session(session_id)
        if not isinstance(run_id, str) or not run_id.strip():
            raise GatewayFault("invalid_request", 400, "Run ID is required")
        run = self._runs.get(run_id)
        if run is not None and run.session_id == session.id:
            return run
        historical = self._runs.historical(session.id, run_id)
        if historical is not None:
            return historical
        if run is not None and run.session_id != session.id:
            raise GatewayFault("run_not_found", 404, "Run was not found")
        if self._history.get_run(session.id, run_id) is not None:
            return self._runs.historical(session.id, run_id)  # type: ignore[return-value]
        raise GatewayFault("run_unavailable", 404, "Run history is no longer available")

    def list_runs(self, session_id: object) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        return success({"runs": self._history.list_runs(session.id)})

    def get_run_history(
        self,
        session_id: object,
        run_id: object,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        if not isinstance(run_id, str) or not run_id.strip():
            raise GatewayFault("invalid_request", 400, "Run ID is required")
        history = self._history.history(session.id, run_id, max(0, int(after_sequence)))
        if history is None:
            if self._runs.get(run_id) is not None:
                raise GatewayFault("event_history_unavailable", 503, "Run history is not available")
            raise GatewayFault("run_unavailable", 404, "Run history is no longer available")
        return success(history)

    def get_observation(
        self,
        session_id: object,
        run_id: object,
        observation_id: object,
    ) -> tuple[bytes, str]:
        session = self._resolve_session(session_id)
        run = self.get_run(session.id, run_id)
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise GatewayFault("invalid_request", 400, "Observation ID is required")
        item = self._history.get_artifact(
            session.id,
            run.run_id,
            observation_id,
            artifact_kind="visual_observation",
        )
        if item is None:
            item = self._runs.observations.get(run.run_id, session.id, observation_id)
        if item is None:
            raise GatewayFault("observation_not_found", 404, "Observation was not found")
        return item

    def get_generated_artifact(
        self,
        session_id: object,
        run_id: object,
        artifact_id: object,
    ) -> tuple[bytes, str]:
        session = self._resolve_session(session_id)
        run = self.get_run(session.id, run_id)
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise GatewayFault("invalid_request", 400, "Artifact ID is required")
        item = self._history.get_artifact(
            session.id,
            run.run_id,
            artifact_id,
            artifact_kind="generated_chart",
        )
        if item is None:
            raise GatewayFault("generated_artifact_unavailable", 404, "Generated chart is unavailable")
        return item

    def _start_managed_run(
        self,
        session_id: object,
        raw_text: object,
        raw_attachment_ids: object,
    ) -> ManagedRun:
        session, prompt = self._prepare_prompt(session_id, raw_text, raw_attachment_ids)
        try:
            with self._runs.session_operation():
                current = self._resolve_session(session.id)
                return self._runs.start(
                    current.id,
                    lambda run: self._execute_run(run, current.name, prompt),
                )
        except RuntimeError as exc:
            raise GatewayFault("run_limit", 429, "Too many Agent runs are active") from exc

    def _prepare_prompt(
        self,
        session_id: object,
        raw_text: object,
        raw_attachment_ids: object,
    ) -> tuple[Any, str]:
        text = validate_message_text(raw_text)
        session = self._resolve_session(session_id)
        attachment_ids = validate_attachment_ids(raw_attachment_ids)
        attachment_metadata: list[dict[str, Any]] = []
        if attachment_ids:
            memory = self._memory_factory(session.name, create=False)
            try:
                registry = self._registry(memory)
                for attachment_id in attachment_ids:
                    item = registry.get(attachment_id)
                    if item is None:
                        raise GatewayFault("attachment_not_found", 404, "Attachment was not found")
                    item, error = self._validated_attachment(memory, item)
                    if error:
                        raise GatewayFault("attachment_unavailable", 409, "Attachment is unavailable")
                    attachment_metadata.append(item.metadata())
            finally:
                memory.close()
        prompt = build_registered_attachment_turn(text, attachment_metadata) if attachment_metadata else text
        return session, prompt

    def _execute_run(self, run: ManagedRun, session_name: str, prompt: str) -> None:
        visual_sink = lambda tool_name, call_id, images: self._store_observations(
            run,
            images,
        )
        try:
            runtime = self._build_runtime_for_run(run, session_name, visual_sink)
        except Exception as exc:  # provider setup errors are a safe gateway fault
            reason = self._agent_setup_failure_reason(exc)
            run.publish(
                "run_failed",
                {
                    "code": "agent_unavailable",
                    "reason": reason,
                    "message": "Agent service is unavailable",
                },
            )
            run.fail("agent_unavailable", 503, "Agent service is unavailable", reason)
            return
        try:
            try:
                answer = runtime.agent.run(prompt)
            except Exception as exc:
                run.publish("run_failed", {"code": "agent_failed", "message": "Agent run failed"})
                run.fail("agent_failed", 502, "Agent run failed")
                return
        finally:
            runtime.close()

        if not run.has_event("final_answer"):
            run.publish("final_answer", {"answer": str(answer)})
        run.complete(str(answer))

    @staticmethod
    def _agent_setup_failure_reason(error: Exception) -> str:
        if isinstance(error, ValueError):
            if "API key" in str(error):
                return "missing_configuration"
            return "invalid_configuration"
        return "initialization_failed"

    def _build_runtime_for_run(
        self,
        run: ManagedRun,
        session_name: str,
        visual_sink: Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]],
    ) -> AgentRuntime:
        factory = self._runtime_factory
        kwargs: dict[str, Any] = {
            "run_id": run.run_id,
            "trace_sink": run.publish_trace,
            "visual_observation_sink": visual_sink,
        }
        try:
            parameters = inspect.signature(factory).parameters.values()
            accepts_kwargs = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters)
            supported = {
                item.name
                for item in parameters
                if item.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            }
            if not accepts_kwargs:
                kwargs = {key: value for key, value in kwargs.items() if key in supported}
        except (TypeError, ValueError):
            kwargs = {}
        return factory(session_name, **kwargs)

    def _store_observations(
        self,
        run: ManagedRun,
        images: Sequence[GeneratedImage],
    ) -> list[dict[str, Any]]:
        references = []
        for image in images:
            metadata = getattr(image, "metadata", {})
            is_generated_chart = isinstance(metadata, Mapping) and metadata.get("kind") == "generated_chart"
            reference = None
            try:
                reference = self._history.add_artifact(run.run_id, run.session_id, image)
            except Exception:  # noqa: BLE001 - visual evidence must not stop the run
                reference = None
            if is_generated_chart:
                if reference is None:
                    references.append({
                        "artifactKind": "generated_chart",
                        "status": "unavailable",
                        "caption": str(getattr(image, "caption", "生成图表"))[:240],
                        "reason": "artifact_persistence_failed",
                    })
                else:
                    references.append(reference)
                continue
            if reference is None:
                fallback = self._runs.observations.add(run.run_id, run.session_id, image)
                if fallback is not None:
                    reference = fallback.to_dict()
            if reference is not None:
                references.append(reference)
        return references

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
            return success({"attachment": self._attachment_summary(memory, item).to_dict()})
        finally:
            memory.close()

    def list_attachments(self, session_id: object) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        memory = self._memory_factory(session.name, create=False)
        try:
            registry = self._registry(memory)
            attachments = [
                self._attachment_summary(memory, item).to_dict()
                for item in memory.list_attachments()
            ]
            return success({"attachments": attachments})
        finally:
            memory.close()

    def get_attachment_content(
        self,
        session_id: object,
        attachment_id: object,
    ) -> tuple[bytes, str]:
        session = self._resolve_session(session_id)
        if not isinstance(attachment_id, str) or not attachment_id.strip():
            raise GatewayFault("invalid_request", 400, "Attachment ID is required")
        memory = self._memory_factory(session.name, create=False)
        try:
            item = memory.get_attachment(attachment_id)
            if item is None:
                raise GatewayFault("attachment_not_found", 404, "Attachment was not found")
            item, error = self._validated_attachment(memory, item)
            if error or item is None:
                raise GatewayFault("attachment_unavailable", 409, "Attachment is unavailable")
            try:
                return Path(item.canonical_path).read_bytes(), item.media_type
            except OSError as exc:
                raise GatewayFault("attachment_unavailable", 409, "Attachment is unavailable") from exc
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
            (),
        )

    def _load_transcript(self, session) -> SessionTranscript:
        memory = self._memory_factory(session.name, create=False)
        try:
            return self._transcript(memory)
        finally:
            memory.close()

    def _transcript(self, memory: SQLiteAgentMemory) -> SessionTranscript:
        attachments = [
            self._attachment_summary(memory, item)
            for item in memory.list_attachments()
        ]
        runs = tuple(self._history.list_runs(memory.session.id))
        transcript = project_completed_runs(
            memory.session,
            memory.completed_runs(),
            attachments,
            canonical_run_ids=(item["runId"] for item in runs),
        )
        return replace(transcript, runs=runs)

    def _validated_attachment(self, memory: SQLiteAgentMemory, item):
        if not self._attachment_store.is_managed_path(memory.session.id, item.canonical_path):
            migrated = self._attachment_store.migrate_legacy(
                memory.session.id,
                item.filename,
                item.media_type,
                item.canonical_path,
                item.sha256,
            )
            if migrated is not None:
                memory.update_attachment_path(item.id, str(migrated))
                return replace(item, canonical_path=str(migrated)), None
        registry = AttachmentRegistry(
            session_id=memory.session.id,
            load=lambda attachment_id: item if attachment_id == item.id else None,
        )
        validated, error = registry.validate(item.id)
        if not error:
            return item, None
        migrated = self._attachment_store.migrate_legacy(
            memory.session.id,
            item.filename,
            item.media_type,
            item.canonical_path,
            item.sha256,
        )
        if migrated is None:
            return item, error
        memory.update_attachment_path(item.id, str(migrated))
        return replace(item, canonical_path=str(migrated)), None

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

    def _attachment_summary(self, memory: SQLiteAgentMemory, item) -> AttachmentSummary:
        _, error = self._validated_attachment(memory, item)
        return AttachmentSummary(
            attachment_id=item.id,
            filename=item.filename,
            media_type=item.media_type,
            byte_count=item.byte_count,
            sha256=item.sha256,
            status="unavailable" if error else "registered",
            preview_available=error is None,
        )

    def close(self) -> None:
        self._runs.close()
        self._history.close()
