"""Bounded in-memory runs and temporary visual observations for the Gateway."""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from contextlib import contextmanager
from threading import Condition, Event, RLock
from typing import Callable, Iterable
from uuid import uuid4

from ..tools.core.result import (
    DEFAULT_MAX_GENERATED_IMAGE_BYTES,
    DEFAULT_MAX_GENERATED_IMAGES,
    GeneratedImage,
    SUPPORTED_GENERATED_IMAGE_MIME_TYPES,
)
from ..trace import TraceEvent
from .history import GatewayHistoryStore, HistoryStoreError
from .protocol import (
    MAX_EVENT_PAYLOAD,
    ObservationReference,
    RunAccepted,
    RunEvent,
    RunStatus,
    sanitize_payload,
    utc_timestamp,
)


DEFAULT_MAX_RUNS = 64
DEFAULT_MAX_RUN_EVENTS = 256
DEFAULT_RUN_RETENTION_SECONDS = 120.0
DEFAULT_OBSERVATION_RETENTION_SECONDS = 120.0


@dataclass
class _StoredObservation:
    run_id: str
    session_id: str
    reference: ObservationReference
    content: bytes
    expires_at: float


class ObservationStore:
    """Short-lived, session-scoped bytes for generated visual evidence."""

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_GENERATED_IMAGE_BYTES,
        max_images: int = DEFAULT_MAX_GENERATED_IMAGES,
        retention_seconds: float = DEFAULT_OBSERVATION_RETENTION_SECONDS,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_images = max_images
        self.retention_seconds = retention_seconds
        self._items: dict[str, _StoredObservation] = {}
        self._run_counts: dict[str, int] = {}
        self._lock = RLock()

    def add(
        self,
        run_id: str,
        session_id: str,
        image: GeneratedImage,
    ) -> ObservationReference | None:
        media_type = image.media_type.lower() if isinstance(image.media_type, str) else ""
        if (
            not isinstance(image.content, bytes)
            or not image.content
            or len(image.content) > self.max_bytes
            or media_type not in SUPPORTED_GENERATED_IMAGE_MIME_TYPES
            or not isinstance(image.caption, str)
            or not image.caption.strip()
        ):
            return None
        with self._lock:
            self.cleanup()
            count = self._run_counts.get(run_id, 0)
            if count >= self.max_images:
                return None
            observation_id = f"obs_{uuid4().hex}"
            reference = ObservationReference(
                observation_id=observation_id,
                media_type=media_type,
                caption=image.caption,
                byte_count=len(image.content),
            )
            self._items[observation_id] = _StoredObservation(
                run_id=run_id,
                session_id=session_id,
                reference=reference,
                content=image.content,
                expires_at=time.monotonic() + self.retention_seconds,
            )
            self._run_counts[run_id] = count + 1
            return reference

    def get(self, run_id: str, session_id: str, observation_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            self.cleanup()
            item = self._items.get(observation_id)
            if item is None or item.run_id != run_id or item.session_id != session_id:
                return None
            return item.content, item.reference.media_type

    def cleanup(self) -> None:
        now = time.monotonic()
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            item = self._items.pop(key)
            remaining = self._run_counts.get(item.run_id, 1) - 1
            if remaining > 0:
                self._run_counts[item.run_id] = remaining
            else:
                self._run_counts.pop(item.run_id, None)

    def close(self) -> None:
        with self._lock:
            self._items.clear()
            self._run_counts.clear()


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
    ) -> None:
        self.run_id = run_id or f"run_{uuid4().hex}"
        self.session_id = session_id
        self.provider = provider
        self.model = model
        self.retry_of = retry_of
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
        return RunAccepted(
            self.run_id,
            self.session_id,
            self.status,
            self.provider,
            self.model,
            self.error_code,
            self.error_message,
            self.retry_of,
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
            payload=sanitize_payload(payload or {}),
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
        payload = dict(event.payload)
        if event.turn is not None:
            payload.setdefault("turn", event.turn)
        payload["traceSequence"] = event.sequence
        self.publish(event.kind, payload)

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
        self.history_store = history_store

    @property
    def accepted(self) -> RunAccepted:
        return RunAccepted(
            self.run_id,
            self.session_id,
            self.status,
            self.provider,
            self.model,
            self.error_code,
            self.error_message,
            self.retry_of,
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


class RunManager:
    """Own active and recently completed runs without durable trace state."""

    def __init__(
        self,
        *,
        max_runs: int = DEFAULT_MAX_RUNS,
        max_events: int = DEFAULT_MAX_RUN_EVENTS,
        retention_seconds: float = DEFAULT_RUN_RETENTION_SECONDS,
        observation_store: ObservationStore | None = None,
        history_store: GatewayHistoryStore | None = None,
    ) -> None:
        self.max_runs = max_runs
        self.max_events = max_events
        self.retention_seconds = retention_seconds
        self.observations = observation_store or ObservationStore(retention_seconds=retention_seconds)
        self.history_store = history_store
        self._runs: dict[str, ManagedRun] = {}
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chartagent-run")

    def create(
        self,
        session_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
        retry_of: str | None = None,
    ) -> ManagedRun:
        with self._lock:
            self.cleanup()
            active_count = sum(not run.terminal for run in self._runs.values())
            if active_count >= self.max_runs:
                raise RuntimeError("active run limit exceeded")
            run = ManagedRun(
                session_id,
                provider=provider,
                model=model,
                max_events=self.max_events,
                retention_seconds=self.retention_seconds,
                history_store=self.history_store,
                retry_of=retry_of,
            )
            self._runs[run.run_id] = run
            if self.history_store is not None:
                try:
                    self.history_store.create_run(
                        run.run_id,
                        session_id,
                        provider=provider,
                        model=model,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        retry_of=retry_of,
                    )
                except Exception:  # noqa: BLE001 - keep the live run usable
                    run._mark_history_warning()
            payload = {"status": RunStatus.RUNNING.value}
            if provider:
                payload["provider"] = provider
            if model:
                payload["model"] = model
            run.publish("run_started", payload)
            return run

    @contextmanager
    def session_operation(self):
        """Serialize session lifecycle checks with run creation."""
        with self._lock:
            yield

    def has_active(self, session_id: str) -> bool:
        with self._lock:
            self.cleanup()
            return any(
                run.session_id == session_id and not run.terminal
                for run in self._runs.values()
            )

    def start(
        self,
        session_id: str,
        worker: Callable[[ManagedRun], None],
        *,
        provider: str | None = None,
        model: str | None = None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
        retry_of: str | None = None,
    ) -> ManagedRun:
        run = self.create(
            session_id,
            provider=provider,
            model=model,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            retry_of=retry_of,
        )
        try:
            self._executor.submit(worker, run)
        except Exception as exc:  # noqa: BLE001 - accepted runs must reach a terminal state
            run.publish("run_failed", {
                "code": "worker_error",
                "reason": "worker_submit_failed",
                "message": "Agent worker could not be started",
            })
            run.fail("worker_error", 503, "Agent worker could not be started", "worker_submit_failed")
            return run
        return run

    def get(self, run_id: str) -> ManagedRun | None:
        with self._lock:
            self.cleanup()
            return self._runs.get(run_id)

    def historical(self, session_id: str, run_id: str) -> HistoricalRun | None:
        if self.history_store is None:
            return None
        summary = self.history_store.get_run(session_id, run_id)
        return HistoricalRun(summary, self.history_store) if summary is not None else None

    def cleanup(self) -> None:
        expired = [run_id for run_id, run in self._runs.items() if run.expired]
        for run_id in expired:
            self._runs.pop(run_id, None)
        self.observations.cleanup()

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.observations.close()
        with self._lock:
            self._runs.clear()
