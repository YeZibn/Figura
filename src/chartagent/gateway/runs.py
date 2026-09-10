"""Bounded in-memory runs and temporary visual observations for the Gateway."""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Callable, Iterable
from uuid import uuid4

from ..tools.result import (
    DEFAULT_MAX_GENERATED_IMAGE_BYTES,
    DEFAULT_MAX_GENERATED_IMAGES,
    GeneratedImage,
    SUPPORTED_GENERATED_IMAGE_MIME_TYPES,
)
from ..trace import TraceEvent
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
        max_events: int = DEFAULT_MAX_RUN_EVENTS,
        retention_seconds: float = DEFAULT_RUN_RETENTION_SECONDS,
    ) -> None:
        self.run_id = f"run_{uuid4().hex}"
        self.session_id = session_id
        self.status = RunStatus.RUNNING
        self.answer: str | None = None
        self.error_code: str | None = None
        self.error_status: int = 502
        self.error_message: str | None = None
        self.error_reason: str | None = None
        self.created_at = utc_timestamp()
        self.finished_at: float | None = None
        self.retention_seconds = retention_seconds
        self._events: deque[RunEvent] = deque(maxlen=max_events)
        self._next_sequence = 0
        self._condition = Condition(RLock())

    @property
    def accepted(self) -> RunAccepted:
        return RunAccepted(self.run_id, self.session_id, self.status)

    @property
    def terminal(self) -> bool:
        return self.status is not RunStatus.RUNNING

    @property
    def expired(self) -> bool:
        return self.finished_at is not None and time.monotonic() - self.finished_at > self.retention_seconds

    def publish(self, kind: str, payload: dict | None = None) -> RunEvent:
        with self._condition:
            self._next_sequence += 1
            event = RunEvent(
                run_id=self.run_id,
                sequence=self._next_sequence,
                kind=kind,
                payload=sanitize_payload(payload or {}),
            )
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
            self.answer = str(answer)
            self.status = RunStatus.COMPLETED
            self.finished_at = time.monotonic()
            self._condition.notify_all()

    def fail(self, code: str, status: int, message: str, reason: str | None = None) -> None:
        with self._condition:
            if self.terminal:
                return
            self.error_code = code
            self.error_status = status
            self.error_message = message
            self.error_reason = reason
            self.status = RunStatus.FAILED
            self.finished_at = time.monotonic()
            self._condition.notify_all()

    def wait_terminal(self, timeout: float | None = None) -> bool:
        with self._condition:
            if not self.terminal:
                self._condition.wait_for(lambda: self.terminal, timeout=timeout)
            return self.terminal

    def iter_events(self, after_sequence: int = 0, *, heartbeat_seconds: float = 15.0) -> Iterable[RunEvent | None]:
        cursor = max(0, after_sequence)
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


class RunManager:
    """Own active and recently completed runs without durable trace state."""

    def __init__(
        self,
        *,
        max_runs: int = DEFAULT_MAX_RUNS,
        max_events: int = DEFAULT_MAX_RUN_EVENTS,
        retention_seconds: float = DEFAULT_RUN_RETENTION_SECONDS,
        observation_store: ObservationStore | None = None,
    ) -> None:
        self.max_runs = max_runs
        self.max_events = max_events
        self.retention_seconds = retention_seconds
        self.observations = observation_store or ObservationStore(retention_seconds=retention_seconds)
        self._runs: dict[str, ManagedRun] = {}
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chartagent-run")

    def create(self, session_id: str) -> ManagedRun:
        with self._lock:
            self.cleanup()
            active_count = sum(not run.terminal for run in self._runs.values())
            if active_count >= self.max_runs:
                raise RuntimeError("active run limit exceeded")
            run = ManagedRun(
                session_id,
                max_events=self.max_events,
                retention_seconds=self.retention_seconds,
            )
            self._runs[run.run_id] = run
            run.publish("run_started", {"status": RunStatus.RUNNING.value})
            return run

    def start(self, session_id: str, worker: Callable[[ManagedRun], None]) -> ManagedRun:
        run = self.create(session_id)
        self._executor.submit(worker, run)
        return run

    def get(self, run_id: str) -> ManagedRun | None:
        with self._lock:
            self.cleanup()
            return self._runs.get(run_id)

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
