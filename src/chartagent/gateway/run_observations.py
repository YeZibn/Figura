"""Short-lived generated-image observations for Gateway runs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from ..tools.core.result import (
    DEFAULT_MAX_GENERATED_IMAGE_BYTES,
    DEFAULT_MAX_GENERATED_IMAGES,
    GeneratedImage,
    SUPPORTED_GENERATED_IMAGE_MIME_TYPES,
)
from .protocol import ObservationReference

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

__all__ = ["ObservationStore", "DEFAULT_OBSERVATION_RETENTION_SECONDS"]
