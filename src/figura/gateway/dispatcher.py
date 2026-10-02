"""Bounded asynchronous scheduling for durable Figura Runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock, Event, Thread
import logging

from figura.agent import AgentExecutor
from figura.runtime.models import Run


class DispatcherFull(RuntimeError):
    """The local Run queue has reached its configured capacity."""


class RunDispatcher:
    def __init__(
        self,
        executor: AgentExecutor,
        *,
        max_workers: int = 3,
        max_queued: int = 8,
        scan_interval: float = 2.0,
    ) -> None:
        if max_workers < 1 or max_queued < 0 or scan_interval <= 0:
            raise ValueError("dispatcher capacity is invalid")
        self._executor = executor
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="figura-run",
        )
        self._capacity = BoundedSemaphore(max_workers + max_queued)
        self._lock = Lock()
        self._scheduled: set[str] = set()
        self._closed = False
        self._activity: dict[str, str] = {}
        self._stop_scan = Event()
        self._scan_interval = scan_interval
        self._scanner = Thread(target=self._scan, name="figura-run-recovery", daemon=True)
        self._scanner.start()

    def activity(self, run_id: str) -> str | None:
        with self._lock:
            return self._activity.get(run_id)

    def _scan(self) -> None:
        while not self._stop_scan.wait(self._scan_interval):
            try:
                coordinator = getattr(self._executor, "coordinator", None)
                if coordinator is None:
                    continue
                for run in coordinator.list_running_runs():
                    try:
                        self.ensure_scheduled(run)
                    except DispatcherFull:
                        break
            except Exception:
                logging.getLogger(__name__).warning("Figura recovery scan unavailable")

    def ensure_scheduled(self, run: Run, *, wait_for_capacity: bool = False) -> bool:
        with self._lock:
            if self._closed:
                raise DispatcherFull
            if run.run_id in self._scheduled:
                return False

        acquired = self._capacity.acquire(blocking=wait_for_capacity)
        if not acquired:
            raise DispatcherFull

        with self._lock:
            if self._closed:
                self._capacity.release()
                raise DispatcherFull
            if run.run_id in self._scheduled:
                self._capacity.release()
                return False
            self._scheduled.add(run.run_id)
            self._activity[run.run_id] = "queued"

        try:
            self._pool.submit(self._execute, run)
        except RuntimeError:
            self._capacity.release()
            with self._lock:
                self._scheduled.discard(run.run_id)
                self._activity.pop(run.run_id, None)
            raise DispatcherFull from None
        return True

    def owns(self, run_id: str) -> bool:
        """Return whether this Gateway currently owns the Run's executor task."""
        with self._lock:
            return run_id in self._scheduled

    def _execute(self, run: Run) -> None:
        try:
            with self._lock:
                self._activity[run.run_id] = "executing"
            coordinator = getattr(self._executor, "coordinator", None)
            state = coordinator.read_run_state(run.session_id, run.run_id) if coordinator else None
            if state and state.checkpoint.next_action and state.checkpoint.next_action.action_kind.value == "tool_attempt":
                with self._lock:
                    self._activity[run.run_id] = "recovering"
            self._executor.execute(run.session_id, run.run_id)
        except Exception:
            # The bounded scanner retries from durable state after ownership release.
            logging.getLogger(__name__).warning("Figura execution unavailable; awaiting checkpoint assessment")
        finally:
            with self._lock:
                self._scheduled.discard(run.run_id)
                self._activity.pop(run.run_id, None)
            self._capacity.release()

    def close(self, *, wait: bool = True) -> None:
        self._stop_scan.set()
        self._scanner.join()
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=wait, cancel_futures=False)
