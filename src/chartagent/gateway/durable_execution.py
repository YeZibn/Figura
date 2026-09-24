"""Gateway implementation of the run-scoped durable execution port."""

from __future__ import annotations

from collections.abc import Mapping

from ..durable_execution import CommittedExecutionEntry
from ..tools.core.result import GeneratedImage
from ..verification.models import ChartManifest, VerificationResult
from .history import GatewayHistoryStore
from .runs import ManagedRun


class GatewayDurableExecutionPort:
    """Bind durable Gateway operations to one Run and its session."""

    def __init__(
        self,
        *,
        run: ManagedRun,
        session_id: str,
        history_store: GatewayHistoryStore,
    ) -> None:
        self._run = run
        self._session_id = session_id
        self._history_store = history_store

    def stage_chart(
        self,
        image: GeneratedImage,
        manifest: ChartManifest,
    ) -> Mapping[str, Any] | None:
        if manifest.run_id != self._run.run_id or manifest.session_id != self._session_id:
            return None
        return self._history_store.stage_chart(
            self._run.run_id,
            self._session_id,
            image,
            manifest,
        )

    def record_verification(self, result: VerificationResult) -> Mapping[str, Any] | None:
        return self._history_store.record_verification(result)

    def promote_chart(
        self,
        manifest: ChartManifest,
        verification_ref: str,
    ) -> Mapping[str, Any] | None:
        if manifest.session_id != self._session_id:
            return None
        return self._history_store.promote_staged_chart(
            manifest.run_id,
            self._session_id,
            manifest.staged_ref,
            verification_ref,
        )

    def resolve_execution_result(self, work_key: str) -> Mapping[str, Any] | None:
        entry = self._history_store.get_execution_entry_by_work_key_in_lineage(
            self._run.run_id,
            work_key,
        )
        return entry.payload if entry is not None else None

    def resolve_staged_chart(self, staged_ref: str) -> Mapping[str, Any] | None:
        return self._history_store.get_staged_chart_by_reference(self._session_id, staged_ref)

    def resolve_staged_work(self, work_key: str) -> Mapping[str, Any] | None:
        return self._history_store.get_staged_chart_by_work_key(self._session_id, work_key)

    def commit_execution_entry(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        turn: int,
        next_action_kind: str,
        work_key: str | None = None,
        call_id: str | None = None,
        message_entry_id: str | None = None,
        staged_ref: str | None = None,
        verification_ref: str | None = None,
        event_kind: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> CommittedExecutionEntry:
        return self._run.commit_execution_entry(
            kind,
            payload,
            turn=turn,
            next_action_kind=next_action_kind,
            work_key=work_key,
            call_id=call_id,
            message_entry_id=message_entry_id,
            staged_ref=staged_ref,
            verification_ref=verification_ref,
            event_kind=event_kind,
            event_payload=event_payload,
        )


__all__ = ["GatewayDurableExecutionPort"]
