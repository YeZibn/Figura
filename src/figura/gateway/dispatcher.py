"""Bounded asynchronous scheduling for durable Figura Runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock

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
    ) -> None:
        if max_workers < 1 or max_queued < 0:
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

        try:
            self._pool.submit(self._execute, run)
        except RuntimeError:
            self._capacity.release()
            with self._lock:
                self._scheduled.discard(run.run_id)
            raise DispatcherFull from None
        return True

    def _execute(self, run: Run) -> None:
        try:
            self._executor.execute(run.session_id, run.run_id)
        except Exception:
            # Durable state remains the source of truth; a later Gateway start
            # can safely inspect the checkpoint again.
            pass
        finally:
            with self._lock:
                self._scheduled.discard(run.run_id)
            self._capacity.release()

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=wait, cancel_futures=False)
