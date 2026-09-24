"""Active Gateway run manager and worker lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import RLock
from typing import Callable

from .history import GatewayHistoryStore
from .run_lifecycle import HistoricalRun, ManagedRun
from .run_observations import ObservationStore
from .protocol import ContinuationKind, RunStatus

DEFAULT_MAX_RUNS = 64
DEFAULT_MAX_RUN_EVENTS = 256
DEFAULT_RUN_RETENTION_SECONDS = 120.0

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
        parent_run_id: str | None = None,
        root_run_id: str | None = None,
        continuation_kind: ContinuationKind | str | None = None,
        idempotency_continuation_kind: str | None = None,
        idempotency_parent_run_id: str | None = None,
        idempotency_cursor_id: str | None = None,
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
                parent_run_id=parent_run_id,
                root_run_id=root_run_id,
                continuation_kind=continuation_kind,
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
                        parent_run_id=parent_run_id,
                        root_run_id=root_run_id,
                        continuation_kind=continuation_kind,
                        idempotency_continuation_kind=idempotency_continuation_kind,
                        idempotency_parent_run_id=idempotency_parent_run_id,
                        idempotency_cursor_id=idempotency_cursor_id,
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
        parent_run_id: str | None = None,
        root_run_id: str | None = None,
        continuation_kind: ContinuationKind | str | None = None,
        idempotency_continuation_kind: str | None = None,
        idempotency_parent_run_id: str | None = None,
        idempotency_cursor_id: str | None = None,
    ) -> ManagedRun:
        run = self.create(
            session_id,
            provider=provider,
            model=model,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            retry_of=retry_of,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id,
            continuation_kind=continuation_kind,
            idempotency_continuation_kind=idempotency_continuation_kind,
            idempotency_parent_run_id=idempotency_parent_run_id,
            idempotency_cursor_id=idempotency_cursor_id,
        )
        try:
            self._executor.submit(worker, run)
        except Exception as exc:  # noqa: BLE001 - accepted runs must reach a terminal state
            run.publish("run_failed", {
                "code": "worker_error",
                "reason": "worker_submit_failed",
                "message": "Agent worker could not be started",
                "failure_category": "worker_startup",
                "failure_code": "worker_error",
                "safe_message": "Agent worker could not be started",
                "retryable": True,
                "outcome_known": True,
                "first_failure_ref": {"kind": "run_failed", "stage": "startup"},
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

__all__ = ["RunManager", "DEFAULT_MAX_RUNS", "DEFAULT_MAX_RUN_EVENTS", "DEFAULT_RUN_RETENTION_SECONDS"]
