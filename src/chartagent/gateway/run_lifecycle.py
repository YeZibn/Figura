"""Thread-safe Gateway run lifecycle and historical projections."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Mapping
from threading import Condition, Event, RLock
from typing import Iterable
from dataclasses import dataclass
from uuid import uuid4

from ..decision_timeline import enrich_event_payload
from ..trace import TraceEvent, sanitize_payload
from .history import GatewayHistoryStore
from .protocol import (
    CheckpointPhase,
    ContinuationKind,
    ObservationReference,
    RecoveryStatus,
    RunRecovery,
    RunAccepted,
    RunEvent,
    RunStatus,
    utc_timestamp,
)

DEFAULT_MAX_RUN_EVENTS = 256
DEFAULT_RUN_RETENTION_SECONDS = 120.0

def _recovery_from_dict(value: dict | None) -> RunRecovery:
    if not isinstance(value, dict):
        return RunRecovery()
    try:
        status = RecoveryStatus(value.get("status", RecoveryStatus.UNAVAILABLE.value))
    except ValueError:
        status = RecoveryStatus.UNAVAILABLE
    try:
        phase = CheckpointPhase(value["phase"]) if value.get("phase") else None
    except ValueError:
        phase = None
    return RunRecovery(
        status=status,
        checkpoint_id=value.get("checkpointId"),
        checkpoint_version=value.get("checkpointVersion"),
        phase=phase,
        next_action=value.get("nextAction"),
        blocked_reason=value.get("blockedReason"),
        updated_at=value.get("updatedAt"),
        expires_at=value.get("expiresAt"),
    )

class ManagedRun:
    """Thread-safe run state with bounded event replay."""

    def __init__(
        self,
        session_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        max_events: int = DEFAULT_MAX_RUN_EVENTS,
        retention_seconds: float = DEFAULT_RUN_RETENTION_SECONDS,
        history_store: GatewayHistoryStore | None = None,
        run_id: str | None = None,
        retry_of: str | None = None,
        parent_run_id: str | None = None,
        root_run_id: str | None = None,
        continuation_kind: ContinuationKind | str | None = None,
        execution_gate: Mapping[str, object] | None = None,
    ) -> None:
        self.run_id = run_id or f"run_{uuid4().hex}"
        self.session_id = session_id
        self.provider = provider
        self.model = model
        self.retry_of = retry_of
        self.parent_run_id = parent_run_id or retry_of
        self.root_run_id = root_run_id or self.run_id
        self.continuation_kind = ContinuationKind(continuation_kind) if continuation_kind is not None else None
        self.recovery = RunRecovery()
        default_gate: dict[str, object] = {
            "state": "open",
            "blocking": False,
            "issues": [],
        }
        self.execution_gate: dict[str, object] = (
            sanitize_payload(dict(list(execution_gate.items())[:32]))
            if isinstance(execution_gate, Mapping)
            else default_gate
        )
        self.status = RunStatus.RUNNING
        self.answer: str | None = None
        self.error_code: str | None = None
        self.error_status: int = 502
        self.error_message: str | None = None
        self.error_reason: str | None = None
        self.created_at = utc_timestamp()
        self.finished_at: float | None = None
        self.retention_seconds = retention_seconds
        self.history_store = history_store
        self.history_warning: str | None = None
        self.cancel_requested = False
        self._events: deque[RunEvent] = deque(maxlen=max_events)
        self._next_sequence = 0
        self._interrupt_event = Event()
        self._condition = Condition(RLock())

    @property
    def accepted(self) -> RunAccepted:
        recovery = self.recovery
        if self.history_store is not None:
            try:
                projection = self.history_store.get_recovery(self.session_id, self.run_id)
                if projection is not None:
                    recovery = _recovery_from_dict(projection)
            except Exception:  # noqa: BLE001 - live projection has a safe local fallback
                pass
        return RunAccepted(
            run_id=self.run_id,
            session_id=self.session_id,
            status=self.status,
            provider=self.provider,
            model=self.model,
            terminal_code=self.error_code,
            terminal_message=self.error_message,
            retry_of=self.retry_of,
            parent_run_id=self.parent_run_id,
            root_run_id=self.root_run_id,
            continuation_kind=self.continuation_kind,
            recovery=recovery,
            execution_gate=self.execution_gate,
        )

    @property
    def terminal(self) -> bool:
        return self.status is not RunStatus.RUNNING

    @property
    def expired(self) -> bool:
        return self.finished_at is not None and time.monotonic() - self.finished_at > self.retention_seconds

    def interruption_requested(self) -> bool:
        return self._interrupt_event.is_set()

    def publish(self, kind: str, payload: dict | None = None) -> RunEvent | None:
        with self._condition:
            if self.terminal:
                return None
            return self._publish_locked(kind, payload)

    def _publish_locked(self, kind: str, payload: dict | None = None) -> RunEvent:
        """Append one event while the run condition lock is held."""
        self._next_sequence += 1
        event = RunEvent(
            run_id=self.run_id,
            sequence=self._next_sequence,
            kind=kind,
            payload=enrich_event_payload(
                kind,
                payload or {},
                run_id=self.run_id,
                sequence=self._next_sequence,
            ),
        )
        if self.history_store is not None:
            try:
                self.history_store.append_event(event)
            except Exception:  # noqa: BLE001 - trace persistence cannot stop a run
                self._mark_history_warning()
        self._events.append(event)
        self._condition.notify_all()
        return event

    def publish_trace(self, event: TraceEvent) -> None:
        # Provider reasoning is intentionally not a desktop event. The CLI's
        # explicit reasoning flag remains the only surface that can display it.
        if event.kind == "reasoning":
            return
        payload = dict(event.detail_payload or event.payload)
        if event.turn is not None:
            payload.setdefault("turn", event.turn)
        payload["traceSequence"] = event.sequence
        self.publish(event.kind, payload)

    def update_execution_gate(self, gate: Mapping[str, object]) -> dict[str, object]:
        """Persist and project the current shared review gate."""
        clean = sanitize_payload(dict(list(gate.items())[:32]))
        with self._condition:
            if clean == self.execution_gate:
                return dict(self.execution_gate)
            self.execution_gate = clean
            if not self.terminal:
                self._publish_locked(
                    "review_gate_updated",
                    {
                        "execution_gate": clean,
                        "review_id": clean.get("reviewId") or clean.get("review_id"),
                        "candidate_id": clean.get("subjectId") or clean.get("subject_id"),
                        "attempt": clean.get("attempt"),
                        "repair_kind": clean.get("repairKind") or clean.get("repair_kind"),
                        "blocking": clean.get("blocking"),
                    },
                )
            self._condition.notify_all()
        self._update_history(self.status, execution_gate=clean)
        return dict(clean)

    def create_checkpoint(
        self,
        state: dict,
        *,
        phase: CheckpointPhase | str,
        next_action: str,
        status: RecoveryStatus | str = RecoveryStatus.AVAILABLE,
        blocked_reason: str | None = None,
    ) -> bool:
        """Persist a recovery boundary before announcing it to consumers."""
        if self.history_store is None:
            return False
        try:
            checkpoint = self.history_store.create_checkpoint(
                self.session_id,
                self.run_id,
                state,
                phase=phase,
                next_action=next_action,
                status=status,
                blocked_reason=blocked_reason,
                sequence=self._next_sequence,
            )
            self.recovery = _recovery_from_dict(checkpoint.public())
            return True
        except Exception:  # noqa: BLE001 - recovery failures become bounded metadata
            self.recovery = RunRecovery(
                status=RecoveryStatus.UNAVAILABLE,
                blocked_reason="checkpoint_persistence_failed",
            )
            return False

    def begin_operation(self, operation_id: str, operation_kind: str, *, request_fingerprint: str | None = None) -> dict:
        if self.history_store is None:
            return {"operationId": operation_id, "state": "in_flight"}
        return self.history_store.begin_operation(
            self.run_id, operation_id, operation_kind, request_fingerprint=request_fingerprint,
        )

    def complete_operation(self, operation_id: str, *, result: dict | None = None, references: dict | None = None) -> dict | None:
        if self.history_store is None:
            return None
        completed = self.history_store.complete_operation(
            self.run_id, operation_id, result=result, references=references,
        )
        if completed is not None:
            self.publish("operation_completed", {
                "operationId": operation_id,
                "operationKind": completed.get("operationKind"),
                "state": completed.get("state"),
            })
        return completed

    def mark_operation_uncertain(self, operation_id: str, *, reason: str | None = None) -> dict | None:
        if self.history_store is None:
            return None
        uncertain = self.history_store.uncertain_operation(self.run_id, operation_id, reason=reason)
        if uncertain is not None:
            try:
                self.history_store.mark_recovery(
                    self.session_id,
                    self.run_id,
                    RecoveryStatus.BLOCKED,
                    reason="operation_outcome_uncertain",
                )
            except Exception:  # noqa: BLE001 - local projection remains conservative
                pass
            self.recovery = RunRecovery(
                status=RecoveryStatus.BLOCKED,
                blocked_reason="operation_outcome_uncertain",
            )
            self.publish("recovery_blocked", {
                "operationId": operation_id,
                "reason": "operation_outcome_uncertain",
            })
        return uncertain

    def has_event(self, kind: str) -> bool:
        with self._condition:
            return any(event.kind == kind for event in self._events)

    def complete(self, answer: str) -> None:
        with self._condition:
            if self.terminal:
                return
            if self.cancel_requested or self._interrupt_event.is_set():
                should_interrupt = True
            else:
                should_interrupt = False
            if should_interrupt:
                self._set_interrupted_locked("user_cancelled", "运行已按用户请求中断")
                self._publish_locked("run_interrupted", {
                    "code": self.error_code,
                    "reason": self.error_reason,
                    "message": self.error_message,
                })
                self._condition.notify_all()
            else:
                self.answer = str(answer)
                self.status = RunStatus.COMPLETED
                self.finished_at = time.monotonic()
                self._condition.notify_all()
        if should_interrupt:
            self._update_history(
                RunStatus.INTERRUPTED,
                terminal_code=self.error_code,
                terminal_message=self.error_message,
                cancel_requested=True,
            )
            return
        self._update_history(RunStatus.COMPLETED, answer_source=self.answer)

    def fail(self, code: str, status: int, message: str, reason: str | None = None) -> None:
        with self._condition:
            if self.terminal:
                return
            if self.cancel_requested or self._interrupt_event.is_set():
                self._set_interrupted_locked("user_cancelled", "运行已按用户请求中断")
                self._publish_locked("run_interrupted", {
                    "code": self.error_code,
                    "reason": self.error_reason,
                    "message": self.error_message,
                })
                interrupted = True
            else:
                interrupted = False
            if not interrupted:
                self.error_code = code
                self.error_status = status
                self.error_message = message
                self.error_reason = reason
                self.status = RunStatus.FAILED
                self.finished_at = time.monotonic()
            self._condition.notify_all()
        if interrupted:
            self._update_history(
                RunStatus.INTERRUPTED,
                terminal_code=self.error_code,
                terminal_message=self.error_message,
                cancel_requested=True,
            )
            return
        self._update_history(
            RunStatus.FAILED,
            terminal_code=self.error_code,
            terminal_message=self.error_message,
        )

    def interrupt(
        self,
        code: str = "user_cancelled",
        message: str = "运行已按用户请求中断",
        reason: str | None = None,
    ) -> bool:
        """Request and terminalize cooperative work exactly once."""
        with self._condition:
            if self.terminal:
                return False
            self.cancel_requested = True
            self._interrupt_event.set()
            self._set_interrupted_locked(code, message, reason)
            self._publish_locked("run_interrupted", {
                "code": code,
                "reason": reason or code,
                "message": message,
            })
            self._condition.notify_all()
        self._update_history(
            RunStatus.INTERRUPTED,
            terminal_code=code,
            terminal_message=message,
            cancel_requested=True,
        )
        return True

    def _set_interrupted_locked(
        self,
        code: str,
        message: str,
        reason: str | None = None,
    ) -> None:
        self.cancel_requested = True
        self._interrupt_event.set()
        self.error_code = code
        self.error_status = 499
        self.error_message = message
        self.error_reason = reason or code
        self.status = RunStatus.INTERRUPTED
        self.finished_at = time.monotonic()

    def _mark_history_warning(self) -> None:
        if self.history_warning is None:
            self.history_warning = "执行记录未能完整持久化"
        if self.history_store is not None:
            try:
                self.history_store.update_run(
                    self.run_id,
                    self.status,
                    terminal_code=self.error_code,
                    terminal_message=self.error_message,
                    answer_source=self.answer,
                    history_warning=self.history_warning,
                )
            except Exception:  # noqa: BLE001 - diagnostics remain isolated
                pass

    def _update_history(self, status: RunStatus, **kwargs) -> None:
        if self.history_store is None:
            return
        try:
            self.history_store.update_run(
                self.run_id,
                status,
                history_warning=self.history_warning,
                **kwargs,
            )
        except Exception:  # noqa: BLE001 - diagnostics remain isolated
            self._mark_history_warning()

    def _durable_events(self, after_sequence: int) -> tuple[list[RunEvent], bool, int | None]:
        if self.history_store is None:
            return [], False, None
        try:
            snapshot = self.history_store.history(self.session_id, self.run_id, after_sequence)
            if snapshot is None:
                return [], False, None
            return [RunEvent(**_event_kwargs(item)) for item in snapshot["events"]], bool(snapshot["historyGap"]), snapshot.get("firstSequence")
        except Exception:  # noqa: BLE001 - live replay can fall back to memory
            return [], False, None

    def wait_terminal(self, timeout: float | None = None) -> bool:
        with self._condition:
            if not self.terminal:
                self._condition.wait_for(lambda: self.terminal, timeout=timeout)
            return self.terminal

    def iter_events(self, after_sequence: int = 0, *, heartbeat_seconds: float = 15.0) -> Iterable[RunEvent | None]:
        cursor = max(0, after_sequence)
        durable, history_gap, first_sequence = self._durable_events(cursor)
        if history_gap:
            gap_sequence = max(cursor, (first_sequence or cursor) - 1)
            yield RunEvent(
                self.run_id,
                gap_sequence,
                "history_gap",
                {"code": "history_gap", "afterSequence": cursor, "firstSequence": first_sequence},
            )
        for event in durable:
            if event.sequence > cursor:
                cursor = event.sequence
                yield event
        while True:
            with self._condition:
                pending = [event for event in self._events if event.sequence > cursor]
                terminal = self.terminal
                if not pending and not terminal:
                    self._condition.wait(timeout=heartbeat_seconds)
                    pending = [event for event in self._events if event.sequence > cursor]
                    terminal = self.terminal
                    if not pending and not terminal:
                        yield None
                        continue
            for event in pending:
                cursor = event.sequence
                yield event
            if terminal:
                return


def _event_kwargs(value: dict) -> dict:
    """Convert the public camel-case event shape back into the dataclass."""
    return {
        "run_id": value["runId"],
        "sequence": value["sequence"],
        "kind": value["kind"],
        "payload": value.get("payload", {}),
        "timestamp": value.get("timestamp", ""),
    }


class HistoricalRun:
    """Read-only run view used after the in-memory replay window expires."""

    def __init__(self, summary: dict, history_store: GatewayHistoryStore) -> None:
        self.run_id = str(summary["runId"])
        self.session_id = str(summary["sessionId"])
        self.status = RunStatus(str(summary["status"]))
        self.answer = summary.get("answer")
        self.error_code = summary.get("terminalCode")
        self.error_message = summary.get("terminalMessage")
        self.history_warning = summary.get("historyWarning")
        self.provider = summary.get("provider")
        self.model = summary.get("model")
        self.cancel_requested = bool(summary.get("cancelRequested"))
        self.retry_of = summary.get("retryOf")
        self.parent_run_id = summary.get("parentRunId") or self.retry_of
        self.root_run_id = summary.get("rootRunId") or self.run_id
        try:
            self.continuation_kind = ContinuationKind(summary.get("continuationKind")) if summary.get("continuationKind") else None
        except ValueError:
            self.continuation_kind = None
        self.recovery = _recovery_from_dict(summary.get("recovery"))
        raw_gate = summary.get("executionGate")
        self.execution_gate = (
            sanitize_payload(dict(list(raw_gate.items())[:32]))
            if isinstance(raw_gate, Mapping)
            else {"state": "open", "blocking": False, "issues": []}
        )
        self.history_store = history_store

    @property
    def accepted(self) -> RunAccepted:
        return RunAccepted(
            run_id=self.run_id,
            session_id=self.session_id,
            status=self.status,
            provider=self.provider,
            model=self.model,
            terminal_code=self.error_code,
            terminal_message=self.error_message,
            retry_of=self.retry_of,
            parent_run_id=self.parent_run_id,
            root_run_id=self.root_run_id,
            continuation_kind=self.continuation_kind,
            recovery=self.recovery,
            execution_gate=self.execution_gate,
        )

    @property
    def terminal(self) -> bool:
        return self.status is not RunStatus.RUNNING

    def wait_terminal(self, timeout: float | None = None) -> bool:
        return self.terminal

    def iter_events(self, after_sequence: int = 0, *, heartbeat_seconds: float = 15.0) -> Iterable[RunEvent | None]:
        snapshot = self.history_store.history(self.session_id, self.run_id, max(0, after_sequence))
        if snapshot is None:
            return
        if snapshot["historyGap"]:
            first_sequence = snapshot.get("firstSequence")
            yield RunEvent(
                self.run_id,
                max(max(0, after_sequence), (first_sequence or max(0, after_sequence)) - 1),
                "history_gap",
                {
                    "code": "history_gap",
                    "afterSequence": max(0, after_sequence),
                    "firstSequence": first_sequence,
                },
            )
        for item in snapshot["events"]:
            yield RunEvent(**_event_kwargs(item))

__all__ = ["ManagedRun", "HistoricalRun", "_recovery_from_dict"]
