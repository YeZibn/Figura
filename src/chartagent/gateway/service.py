"""Application service behind the local HTTP gateway."""

from __future__ import annotations

import inspect
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Sequence

from ..attachments import AttachmentRegistry
from ..memory import SQLiteAgentMemory
from ..memory.sqlite import default_database_path
from ..multimodal import build_registered_attachment_turn
from ..runtime import AgentRuntime, create_agent_runtime, probe_agent_readiness
from ..agent import AgentInterrupted, AgentRecoveryBlocked, REVIEW_INCOMPLETE_MESSAGE
from ..agent.review_gate import _REVIEW_FAILED_MSG
from ..tools.core.result import GeneratedImage
from ..trace import TraceSink, truncate_text
from .attachments import AttachmentStoreError, EphemeralAttachmentStore
from .history import GatewayHistoryStore, HistoryStoreError
from .projection import project_completed_runs, session_summary
from .runs import HistoricalRun, ManagedRun, RunManager
from .protocol import (
    AttachmentSummary,
    ContinuationKind,
    GatewayFault,
    IDEMPOTENCY_CONFLICT_CODE,
    RECOVERY_BLOCKED_CODE,
    RECOVERY_UNAVAILABLE_CODE,
    RESUME_IDEMPOTENCY_CONFLICT_CODE,
    RecoveryStatus,
    SessionTranscript,
    SessionSummary,
    SUPPORTED_PROVIDERS,
    request_fingerprint,
    success,
    validate_attachment_ids,
    validate_idempotency_key,
    validate_message_text,
    validate_session_name,
    validate_provider,
)


_SAFE_PROVIDER_STATUSES = frozenset({"ready", "unavailable", "unknown"})
_SAFE_READINESS_REASONS = frozenset({
    "missing_configuration",
    "invalid_configuration",
    "initialization_failed",
})
_MAX_PROVIDER_MODEL = 128


def _safe_reason(value: object) -> str:
    return value if isinstance(value, str) and value in _SAFE_READINESS_REASONS else "initialization_failed"


def _safe_model(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return truncate_text(value.strip(), _MAX_PROVIDER_MODEL)


def _safe_provider_status(provider: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"status": "unknown", "provider": provider, "reason": "initialization_failed"}
    raw_status = value.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in _SAFE_PROVIDER_STATUSES else "unknown"
    result: dict[str, Any] = {"status": status, "provider": provider}
    if status == "ready":
        model = _safe_model(value.get("model"))
        if model is not None:
            result["model"] = model
    else:
        result["reason"] = _safe_reason(value.get("reason"))
    return result


def _safe_readiness(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"status": "unavailable", "reason": "initialization_failed"}
    raw_status = value.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in _SAFE_PROVIDER_STATUSES else "unavailable"
    result: dict[str, Any] = {"status": status}
    if status != "ready":
        result["reason"] = _safe_reason(value.get("reason"))
    provider = value.get("provider")
    if provider in SUPPORTED_PROVIDERS:
        result["provider"] = provider
    model = _safe_model(value.get("model"))
    if model is not None:
        result["model"] = model
    if "providers" in value:
        raw_providers = value.get("providers")
        result["providers"] = {
            name: _safe_provider_status(name, raw_providers[name])
            for name in SUPPORTED_PROVIDERS
            if isinstance(raw_providers, Mapping) and name in raw_providers
        }
    return result


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
        readiness_probe: Callable[[], dict[str, Any]] | None = None,
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
        provider: str | None = None,
        model: str | None = None,
        run_id: str | None = None,
        trace_sink: TraceSink | None = None,
        visual_observation_sink: Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]] | None = None,
        interruption_event: Any = None,
        recovery_context: Mapping[str, Any] | None = None,
        checkpoint_sink: Callable[..., bool] | None = None,
        operation_begin: Callable[..., dict[str, Any]] | None = None,
        operation_complete: Callable[..., dict[str, Any] | None] | None = None,
        operation_uncertain: Callable[..., dict[str, Any] | None] | None = None,
    ) -> AgentRuntime:
        effective_model = model if model is not None else self.model
        return create_agent_runtime(
            provider=provider,
            session_name=name,
            database=self.database,
            model=effective_model,
            run_id=run_id,
            trace_sink=trace_sink,
            visual_observation_sink=visual_observation_sink,
            interruption_event=interruption_event,
            recovery_context=recovery_context,
            checkpoint_sink=checkpoint_sink,
            operation_begin=operation_begin,
            operation_complete=operation_complete,
            operation_uncertain=operation_uncertain,
        )

    def health(self) -> dict[str, Any]:
        try:
            readiness = _safe_readiness(self._readiness_probe())
        except Exception:
            readiness = {"status": "unavailable", "reason": "initialization_failed"}
        status = "ready" if readiness.get("status") == "ready" else "unavailable"
        agent: dict[str, Any] = {"status": status}
        if status != "ready":
            reason = readiness.get("reason")
            if reason in {"missing_configuration", "invalid_configuration", "initialization_failed"}:
                agent["reason"] = reason
            else:
                agent["reason"] = "initialization_failed"
        for key in ("provider", "model", "providers"):
            if key in readiness and readiness[key] is not None:
                agent[key] = readiness[key]
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
        raw_provider: object = None,
    ) -> dict[str, Any]:
        run = self._start_managed_run(session_id, raw_text, raw_attachment_ids, raw_provider)
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
        raw_provider: object = None,
        raw_idempotency_key: object = None,
        raw_retry_of: object = None,
    ) -> dict[str, Any]:
        run = self._start_managed_run(
            session_id,
            raw_text,
            raw_attachment_ids,
            raw_provider,
            raw_idempotency_key,
            raw_retry_of,
        )
        return success({"run": run.accepted.to_dict()})

    def resume_run(
        self,
        session_id: object,
        run_id: object,
        raw_idempotency_key: object,
        raw_checkpoint_id: object = None,
    ) -> dict[str, Any]:
        """Create an explicit child run from a validated durable checkpoint."""
        session = self._resolve_session(session_id)
        parent = self.get_run(session.id, run_id)
        idempotency_key = validate_idempotency_key(raw_idempotency_key, allow_none=False)
        checkpoint_id = raw_checkpoint_id.strip() if isinstance(raw_checkpoint_id, str) else None
        if checkpoint_id is not None and (not checkpoint_id.startswith("chk_") or len(checkpoint_id) > 128):
            raise GatewayFault("invalid_request", 400, "checkpointId is invalid")
        fingerprint = hashlib.sha256(
            f"resume:{session.id}:{parent.run_id}:{checkpoint_id or ''}".encode("utf-8")
        ).hexdigest()
        existing = self._history.get_idempotency(idempotency_key)
        if existing is not None:
            if existing["sessionId"] != session.id or existing["requestFingerprint"] != fingerprint:
                raise GatewayFault(RESUME_IDEMPOTENCY_CONFLICT_CODE, 409, "恢复请求标识已用于其他请求")
            existing_run = self._runs.get(existing["runId"])
            if existing_run is not None:
                return success({"run": existing_run.accepted.to_dict(), "duplicate": True})
            historical = self._runs.historical(session.id, existing["runId"])
            if historical is not None:
                return success({"run": historical.accepted.to_dict(), "duplicate": True})
            raise GatewayFault("run_unavailable", 404, "原恢复运行记录已不可用")
        if not parent.terminal:
            raise GatewayFault("run_not_terminal", 409, "只有已结束的运行才能继续执行")
        checkpoint = self._history.get_checkpoint(session.id, parent.run_id, checkpoint_id)
        recovery = self._history.get_recovery(session.id, parent.run_id) or {}
        if checkpoint is None:
            if recovery.get("status") == RecoveryStatus.BLOCKED.value:
                raise GatewayFault(RECOVERY_BLOCKED_CODE, 409, "该运行暂时无法继续执行", recovery.get("blockedReason", "recovery_blocked"))
            raise GatewayFault(RECOVERY_UNAVAILABLE_CODE, 409, "该运行没有可用的继续执行检查点", recovery.get("blockedReason", "recovery_unavailable"))
        if recovery.get("status") != RecoveryStatus.AVAILABLE.value or checkpoint.status is not RecoveryStatus.AVAILABLE:
            raise GatewayFault(RECOVERY_BLOCKED_CODE, 409, "该运行暂时无法继续执行", recovery.get("blockedReason", "recovery_blocked"))
        reference_error = self._validate_recovery_references(session, parent.run_id, checkpoint.state)
        if reference_error is not None:
            self._history.mark_recovery(
                session.id, parent.run_id, RecoveryStatus.UNAVAILABLE,
                reason=reference_error,
            )
            raise GatewayFault(RECOVERY_UNAVAILABLE_CODE, 409, "继续执行所需的图表或附件已不可用", reference_error)
        uncertain = [
            item for item in self._history.list_operations(parent.run_id)
            if item.get("state") in {"in_flight", "uncertain"}
        ]
        if uncertain:
            self._history.mark_recovery(
                session.id, parent.run_id, RecoveryStatus.BLOCKED,
                reason="operation_outcome_uncertain",
            )
            raise GatewayFault(RECOVERY_BLOCKED_CODE, 409, "该运行在操作边界中断，无法安全继续执行", "operation_outcome_uncertain")
        with self._runs.session_operation():
            if self._runs.has_active(session.id):
                raise GatewayFault("session_busy", 409, "会话正在运行 Agent")
            root_run_id = getattr(parent, "root_run_id", None) or parent.run_id
            try:
                child = self._runs.start(
                    session.id,
                    lambda run: self._execute_resume_run(run, session.name, checkpoint.state, checkpoint.checkpoint_id),
                    provider=getattr(parent, "provider", None),
                    model=getattr(parent, "model", None),
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                    parent_run_id=parent.run_id,
                    root_run_id=root_run_id,
                    continuation_kind=ContinuationKind.RESUME,
                    idempotency_operation_kind="resume",
                    idempotency_parent_run_id=parent.run_id,
                    idempotency_checkpoint_id=checkpoint.checkpoint_id,
                )
            except RuntimeError as exc:
                raise GatewayFault("run_limit", 429, "Too many Agent runs are active") from exc
        return success({"run": child.accepted.to_dict(), "duplicate": False})

    def _validate_recovery_references(
        self,
        session: Any,
        run_id: str,
        state: Mapping[str, Any],
    ) -> str | None:
        """Re-authorize opaque checkpoint references without reading local paths."""
        attachment_ids = state.get("attachmentIds") if isinstance(state.get("attachmentIds"), list) else []
        if attachment_ids:
            memory = self._memory_factory(session.name, create=False)
            try:
                for attachment_id in attachment_ids[:16]:
                    if not isinstance(attachment_id, str):
                        return "required_attachment_unavailable"
                    item = memory.get_attachment(attachment_id)
                    if item is None or self._validated_attachment(memory, item)[1] is not None:
                        return "required_attachment_unavailable"
            finally:
                memory.close()
        visual_references = state.get("visualReferences") if isinstance(state.get("visualReferences"), list) else []
        for reference in visual_references[:32]:
            if not isinstance(reference, Mapping):
                continue
            reference_id = reference.get("artifactId") or reference.get("candidateId") or reference.get("observationId")
            if not isinstance(reference_id, str):
                continue
            if reference.get("artifactId") and self._history.get_artifact(session.id, run_id, reference_id, artifact_kind="generated_chart") is None:
                return "required_artifact_unavailable"
            if reference.get("candidateId") and self._history.get_candidate(session.id, run_id, reference_id) is None:
                return "required_candidate_unavailable"
            if reference.get("observationId") and self._history.get_artifact(session.id, run_id, reference_id, artifact_kind="visual_observation") is None:
                return "required_observation_unavailable"
        return None

    def interrupt_run(
        self,
        session_id: object,
        run_id: object,
        raw_reason: object = "user_cancelled",
    ) -> dict[str, Any]:
        session = self._resolve_session(session_id)
        run = self.get_run(session.id, run_id)
        reason = raw_reason if isinstance(raw_reason, str) and raw_reason in {
            "user_cancelled",
            "gateway_restarted",
        } else "user_cancelled"
        if isinstance(run, ManagedRun) and not run.terminal:
            try:
                self._history.request_interrupt(run.run_id)
            except Exception as exc:  # noqa: BLE001 - memory state remains authoritative
                raise GatewayFault("gateway_storage_error", 500, "运行中断状态保存失败") from exc
            changed = run.interrupt(
                reason,
                "运行已按用户请求中断" if reason == "user_cancelled" else "Gateway 重启，运行已中断",
                reason,
            )
        else:
            changed = False
        return success({
            "run": run.accepted.to_dict(),
            "changed": changed,
        })

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

    def get_generated_candidate(
        self,
        session_id: object,
        run_id: object,
        candidate_id: object,
    ) -> tuple[bytes, str]:
        session = self._resolve_session(session_id)
        run = self.get_run(session.id, run_id)
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise GatewayFault("invalid_request", 400, "Candidate ID is required")
        item = self._history.get_candidate(session.id, run.run_id, candidate_id)
        if item is None:
            raise GatewayFault("generated_candidate_unavailable", 404, "Generated chart candidate is unavailable")
        return item

    def get_generated_chart_preview(
        self,
        session_id: object,
        run_id: object,
        reference_id: object,
    ) -> tuple[bytes, str]:
        """Resolve either a candidate or its current published artifact."""
        session = self._resolve_session(session_id)
        run = self.get_run(session.id, run_id)
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise GatewayFault("invalid_request", 400, "Chart preview reference is required")
        item = self._history.get_chart_preview(session.id, run.run_id, reference_id)
        if item is None:
            raise GatewayFault("generated_chart_preview_unavailable", 404, "Generated chart preview is unavailable")
        return item

    def _start_managed_run(
        self,
        session_id: object,
        raw_text: object,
        raw_attachment_ids: object,
        raw_provider: object = None,
        raw_idempotency_key: object = None,
        raw_retry_of: object = None,
    ) -> ManagedRun | HistoricalRun:
        text = validate_message_text(raw_text)
        attachment_ids = validate_attachment_ids(raw_attachment_ids)
        idempotency_key = validate_idempotency_key(raw_idempotency_key)
        retry_of = raw_retry_of.strip() if isinstance(raw_retry_of, str) else None
        if retry_of is not None and (not retry_of or len(retry_of) > 128):
            raise GatewayFault("invalid_request", 400, "retryOf is invalid")
        session, prompt = self._prepare_prompt(session_id, raw_text, raw_attachment_ids)
        requested_provider = validate_provider(raw_provider)
        try:
            readiness = _safe_readiness(self._readiness_probe())
        except Exception as exc:
            raise GatewayFault(
                "agent_unavailable",
                503,
                "Agent service is unavailable",
                "initialization_failed",
            ) from exc
        if requested_provider is not None:
            provider = requested_provider
        elif readiness.get("provider") in SUPPORTED_PROVIDERS:
            provider = readiness["provider"]
        elif readiness.get("status") == "ready" and "providers" not in readiness:
            # Preserve the legacy top-level readiness hook, which represented
            # only the OpenAI-compatible default before provider discovery.
            provider = "openai"
        else:
            raise GatewayFault(
                "agent_unavailable",
                503,
                "Agent service is unavailable",
                readiness.get("reason", "initialization_failed"),
            )
        validate_provider(provider, allow_none=False)
        if "providers" in readiness:
            provider_status = readiness["providers"].get(provider)
            if not isinstance(provider_status, Mapping):
                raise GatewayFault(
                    "agent_unavailable",
                    503,
                    "Agent service is unavailable",
                    "invalid_configuration",
                )
        else:
            if requested_provider is not None and readiness.get("provider") not in (None, provider):
                raise GatewayFault(
                    "agent_unavailable",
                    503,
                    "Agent service is unavailable",
                    "invalid_configuration",
                )
            if requested_provider in {"qwen", "deepseek"} and readiness.get("provider") is None:
                raise GatewayFault(
                    "agent_unavailable",
                    503,
                    "Agent service is unavailable",
                    "invalid_configuration",
                )
            provider_status = readiness
        if provider_status.get("status") != "ready":
            raise GatewayFault("agent_unavailable", 503, "Agent service is unavailable", provider_status.get("reason", "missing_configuration"))
        model = _safe_model(provider_status.get("model")) or (_safe_model(self.model) if provider == "openai" else None)
        try:
            with self._runs.session_operation():
                current = self._resolve_session(session.id)
                fingerprint = request_fingerprint(current.id, text, attachment_ids, provider)
                if idempotency_key is not None:
                    existing = self._history.get_idempotency(idempotency_key)
                    if existing is not None:
                        if (
                            existing["sessionId"] != current.id
                            or existing["requestFingerprint"] != fingerprint
                        ):
                            raise GatewayFault(
                                IDEMPOTENCY_CONFLICT_CODE,
                                409,
                                "Idempotency-Key 已用于其他请求",
                            )
                        existing_run = self._runs.get(existing["runId"])
                        if existing_run is not None:
                            return existing_run
                        historical = self._runs.historical(current.id, existing["runId"])
                        if historical is not None:
                            return historical
                        raise GatewayFault("run_unavailable", 404, "原运行记录已不可用")
                if retry_of is not None:
                    parent = self.get_run(current.id, retry_of)
                    if not parent.terminal:
                        raise GatewayFault("run_not_terminal", 409, "只有已结束的运行才能重试")
                parent_run_id = None
                root_run_id = None
                continuation_kind = None
                if retry_of is not None:
                    parent_run_id = retry_of
                    root_run_id = getattr(parent, "root_run_id", None) or parent.run_id
                    continuation_kind = ContinuationKind.RETRY
                return self._runs.start(
                    current.id,
                    lambda run: self._execute_run(run, current.name, prompt, attachment_ids=attachment_ids),
                    provider=provider,
                    model=model,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint if idempotency_key is not None else None,
                    retry_of=retry_of,
                    parent_run_id=parent_run_id,
                    root_run_id=root_run_id,
                    continuation_kind=continuation_kind,
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

    def _execute_run(
        self,
        run: ManagedRun,
        session_name: str,
        prompt: str,
        *,
        attachment_ids: Sequence[str] = (),
        recovery_context: Mapping[str, Any] | None = None,
        checkpoint_id: str | None = None,
    ) -> None:
        if run.interruption_requested():
            return
        if recovery_context is None:
            run.create_checkpoint(
                {
                    "prompt": prompt,
                    "attachmentIds": list(attachment_ids),
                    "nextAction": "model",
                },
                phase="accepted",
                next_action="model",
            )
        elif checkpoint_id:
            run.publish("resume_started", {"parentCheckpointId": checkpoint_id})
        visual_sink = lambda tool_name, call_id, images: self._store_observations(
            run,
            images,
        )
        try:
            runtime = self._build_runtime_for_run(run, session_name, visual_sink, recovery_context=recovery_context)
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
            except AgentRecoveryBlocked:
                run.publish("run_failed", {"code": RECOVERY_BLOCKED_CODE, "reason": "operation_outcome_uncertain", "message": "运行无法安全继续执行"})
                run.fail(RECOVERY_BLOCKED_CODE, 409, "运行无法安全继续执行", "operation_outcome_uncertain")
                return
            except AgentInterrupted:
                if not run.terminal:
                    run.interrupt("user_cancelled", "运行已按用户请求中断")
                return
            except Exception as exc:
                run.publish("run_failed", {"code": "agent_failed", "message": "Agent run failed"})
                run.fail("agent_failed", 502, "Agent run failed")
                return
        finally:
            runtime.close()

        if run.interruption_requested() or run.terminal:
            return
        if str(answer) in {REVIEW_INCOMPLETE_MESSAGE, _REVIEW_FAILED_MSG}:
            run.publish(
                "run_failed",
                {
                    "code": "review_incomplete" if str(answer) == REVIEW_INCOMPLETE_MESSAGE else "review_failed",
                    "message": "Generated chart review did not complete within the bounded run" if str(answer) == REVIEW_INCOMPLETE_MESSAGE else "Generated chart review failed; no artifact was published",
                },
            )
            if str(answer) == REVIEW_INCOMPLETE_MESSAGE:
                run.fail("review_incomplete", 422, "Generated chart review did not complete", "review_incomplete")
            else:
                run.fail("review_failed", 422, "Generated chart review failed", "review_failed")
            return
        if not run.has_event("final_answer"):
            run.publish("final_answer", {"answer": str(answer)})
        run.complete(str(answer))

    def _execute_resume_run(
        self,
        run: ManagedRun,
        session_name: str,
        state: Mapping[str, Any],
        checkpoint_id: str,
    ) -> None:
        prompt = state.get("prompt") if isinstance(state.get("prompt"), str) else "继续执行已提交的图表分析"
        attachments = state.get("attachmentIds") if isinstance(state.get("attachmentIds"), list) else []
        self._execute_run(
            run,
            session_name,
            prompt,
            attachment_ids=tuple(item for item in attachments if isinstance(item, str)),
            recovery_context=state,
            checkpoint_id=checkpoint_id,
        )

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
        recovery_context: Mapping[str, Any] | None = None,
    ) -> AgentRuntime:
        factory = self._runtime_factory
        kwargs: dict[str, Any] = {
            "run_id": run.run_id,
            "provider": run.provider,
            "model": run.model,
            "trace_sink": run.publish_trace,
            "visual_observation_sink": visual_sink,
            "interruption_event": run.interruption_requested,
            "recovery_context": recovery_context,
            "checkpoint_sink": run.create_checkpoint,
            "operation_begin": run.begin_operation,
            "operation_complete": run.complete_operation,
            "operation_uncertain": run.mark_operation_uncertain,
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
            publication_operation_id = None
            if is_generated_chart and metadata.get("candidateId"):
                publication_operation_id = f"publication:{getattr(image, 'metadata', {}).get('candidateId')}"
                run.begin_operation(publication_operation_id, "publication")
            try:
                if is_generated_chart and metadata.get("candidateId"):
                    reference = self._history.add_candidate(run.run_id, run.session_id, image)
                    publication = str(metadata.get("publicationStatus", "unpublished"))
                    if reference is not None and publication in {"published", "published_with_warning"}:
                        reference = self._history.promote_candidate(
                            run.run_id,
                            run.session_id,
                            str(metadata.get("candidateId")),
                            str(metadata.get("reviewId", "")),
                            str(metadata.get("chartSpecDigest", "")),
                            candidate_status=str(metadata.get("candidateStatus", "")),
                            review_status=str(metadata.get("reviewStatus", "")),
                            publication_status=publication,
                            review=metadata.get("review") if isinstance(metadata.get("review"), Mapping) else None,
                        )
                else:
                    reference = self._history.add_artifact(run.run_id, run.session_id, image)
            except Exception:  # noqa: BLE001 - visual evidence must not stop the run
                if publication_operation_id:
                    run.mark_operation_uncertain(publication_operation_id, reason="publication_outcome_uncertain")
                reference = None
            else:
                if publication_operation_id:
                    run.complete_operation(
                        publication_operation_id,
                        result={"status": "published" if reference and str(metadata.get("publicationStatus")) in {"published", "published_with_warning"} else "recorded"},
                        references=reference if isinstance(reference, Mapping) else None,
                    )
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
                resource_key = metadata.get("resource_key") if isinstance(metadata, Mapping) else None
                if isinstance(resource_key, str) and resource_key:
                    reference = dict(reference)
                    reference["resourceKey"] = resource_key[:96]
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
