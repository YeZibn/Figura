"""Typed boundary for run-scoped durable execution operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .tools.core.result import GeneratedImage
    from .verification.models import ChartManifest, VerificationResult


class CommittedExecutionEntry(Protocol):
    """The committed identity returned to callers that advance a cursor."""

    entry_id: str
    sequence: int


class DurableExecutionPort(Protocol):
    """Durable operations available to one Gateway-backed Agent run."""

    def stage_chart(
        self,
        image: GeneratedImage,
        manifest: ChartManifest,
    ) -> Mapping[str, Any] | None: ...

    def record_verification(
        self,
        result: VerificationResult,
    ) -> Mapping[str, Any] | None: ...

    def promote_chart(
        self,
        manifest: ChartManifest,
        verification_ref: str,
    ) -> Mapping[str, Any] | None: ...

    def resolve_execution_result(self, work_key: str) -> Mapping[str, Any] | None: ...

    def resolve_staged_chart(self, staged_ref: str) -> Mapping[str, Any] | None: ...

    def resolve_staged_work(self, work_key: str) -> Mapping[str, Any] | None: ...

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
    ) -> CommittedExecutionEntry: ...


__all__ = ["CommittedExecutionEntry", "DurableExecutionPort"]
