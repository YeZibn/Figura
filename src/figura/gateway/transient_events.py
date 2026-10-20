"""Session-scoped, non-durable assistant stream events for Gateway SSE."""

from __future__ import annotations

from queue import Empty, Full, Queue
from threading import RLock
from uuid import uuid4


_QUEUE_CAPACITY = 128
_MAX_DELTA_BYTES = 65536


class TransientRunEventHub:
    """Fan out bounded provisional text without writing it to Runtime history."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[tuple[str, str], dict[str, Queue[dict[str, object]]]] = {}

    def subscribe(self, session_id: str, run_id: str) -> tuple[str, Queue[dict[str, object]]]:
        key = (session_id, run_id)
        token = uuid4().hex
        channel: Queue[dict[str, object]] = Queue(maxsize=_QUEUE_CAPACITY)
        with self._lock:
            self._subscribers.setdefault(key, {})[token] = channel
        return token, channel

    def unsubscribe(self, session_id: str, run_id: str, token: str) -> None:
        key = (session_id, run_id)
        with self._lock:
            subscribers = self._subscribers.get(key)
            if subscribers is None:
                return
            subscribers.pop(token, None)
            if not subscribers:
                self._subscribers.pop(key, None)

    def publish(
        self,
        session_id: str,
        run_id: str,
        attempt_id: str,
        sequence: int,
        text: str,
    ) -> None:
        if (
            not isinstance(session_id, str) or not session_id
            or not isinstance(run_id, str) or not run_id
            or not isinstance(attempt_id, str) or not attempt_id
            or type(sequence) is not int or sequence < 1
            or not isinstance(text, str) or not text
            or len(text.encode("utf-8")) > _MAX_DELTA_BYTES
        ):
            return
        event = {
            "runId": run_id,
            "attemptId": attempt_id,
            "deltaSequence": sequence,
            "text": text,
        }
        with self._lock:
            channels = tuple(self._subscribers.get((session_id, run_id), {}).values())
        for channel in channels:
            try:
                channel.put_nowait(event)
            except Full:
                try:
                    channel.get_nowait()
                except Empty:
                    pass
                try:
                    channel.put_nowait(event)
                except Full:
                    pass
