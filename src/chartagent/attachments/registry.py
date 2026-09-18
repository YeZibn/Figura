"""Authorized local image references and attachment lifecycle service."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..memory.models import Attachment
from .policy import DEFAULT_MAX_ATTACHMENT_BYTES, SUPPORTED_IMAGE_TYPES



class AttachmentRegistry:
    def __init__(self, *, session_id: str | None = None, max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES, save: Callable[[Attachment], None] | None = None, load: Callable[[str], Attachment | None] | None = None, panel_store: Any = None) -> None:
        self.session_id = session_id
        self.max_bytes = max_bytes
        self._save = save
        self._load = load
        self.panel_store = panel_store
        self._items: dict[str, Attachment] = {}

    def register(
        self,
        raw_path: str,
        *,
        run_id: str | None = None,
        ordinal: int = 1,
        filename: str | None = None,
    ) -> Attachment:
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("attachment is not a file")
        media_type = mimetypes.guess_type(path.name)[0] or ""
        if media_type not in SUPPORTED_IMAGE_TYPES:
            raise ValueError("unsupported image type")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ValueError(f"image exceeds limit of {self.max_bytes} bytes")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        item = Attachment(
            f"att_{uuid4().hex}",
            self.session_id,
            run_id,
            ordinal,
            str(path),
            filename or path.name,
            media_type,
            size,
            digest.hexdigest(),
        )
        self._items[item.id] = item
        if self._save:
            self._save(item)
        return item

    def bind_run(self, attachment_id: str, run_id: str) -> Attachment | None:
        """Associate a registered attachment with the current durable run."""
        item = self._items.get(attachment_id)
        if item is None:
            item = self._load(attachment_id) if self._load else None
        if item is None:
            return None
        if item.run_id == run_id:
            return item
        rebound = Attachment(item.id, item.session_id, run_id, item.ordinal, item.canonical_path,
                          item.filename, item.media_type, item.byte_count, item.sha256,
                          item.created_at)
        self._items[attachment_id] = rebound
        updater = getattr(self._save, "__self__", None)
        update = getattr(updater, "update_attachment_run", None)
        if callable(update):
            update(attachment_id, run_id)
        return rebound

    def get(self, attachment_id: str) -> Attachment | None:
        item = self._items.get(attachment_id)
        return item if item is not None else self._load(attachment_id) if self._load else None

    def validate(self, attachment_id: str) -> tuple[Attachment | None, str | None]:
        item = self.get(attachment_id)
        if item is None or (self.session_id is not None and item.session_id != self.session_id):
            return None, "attachment is not authorized for this session"
        path = Path(item.canonical_path)
        try:
            if not path.is_file() or not os.access(path, os.R_OK):
                return None, "attachment file is missing or unreadable"
            if (mimetypes.guess_type(path.name)[0] or "") not in SUPPORTED_IMAGE_TYPES:
                return None, "attachment media type is no longer supported"
            if path.stat().st_size > self.max_bytes:
                return None, "attachment exceeds the configured size limit"
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item.sha256:
                return None, "attachment changed; attach the file again"
        except OSError:
            return None, "attachment file is unavailable"
        return item, None

    def metadata(self, attachment_id: str) -> dict:
        item = self.get(attachment_id)
        authorized = item is not None and (self.session_id is None or item.session_id == self.session_id)
        return item.metadata() if authorized else {"attachment_id": attachment_id, "error": "attachment is not authorized"}

    def load_tool(self):
        """Compatibility facade; the canonical factory lives in tools.adapters."""
        from ..tools.adapters.attachment import load_image_tool

        return load_image_tool(self)


__all__ = ["AttachmentRegistry"]
