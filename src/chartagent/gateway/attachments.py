"""Ephemeral, bounded storage for images uploaded through the local gateway."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from ..attachments import DEFAULT_MAX_ATTACHMENT_BYTES, SUPPORTED_IMAGE_TYPES

DEFAULT_ATTACHMENT_ROOT = Path(tempfile.gettempdir()) / "chartagent-attachments"
DEFAULT_MAX_SESSION_ATTACHMENT_BYTES = 80 * 1024 * 1024
MAX_ATTACHMENT_FILENAME = 255

_MEDIA_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class AttachmentStoreError(Exception):
    """A bounded, user-safe upload failure."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class EphemeralAttachmentStore:
    """Store uploaded bytes below a private process-managed temporary root."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES,
        max_session_bytes: int = DEFAULT_MAX_SESSION_ATTACHMENT_BYTES,
    ) -> None:
        self.root = Path(root) if root is not None else Path(os.environ.get("CHARTAGENT_ATTACHMENT_DIR", DEFAULT_ATTACHMENT_ROOT))
        self.max_bytes = max_bytes
        self.max_session_bytes = max_session_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._clean_startup_root()

    def _clean_startup_root(self) -> None:
        for child in self.root.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError:
                # A stale file that cannot be removed will never be selected by
                # the generated paths below, so startup remains usable.
                continue

    def stage(self, session_id: str, filename: str, media_type: str, content: bytes) -> Path:
        self._validate_session_id(session_id)
        suffix = self._validate_upload(filename, media_type, content)
        session_root = self.root / session_id
        session_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        current_size = sum(
            item.stat().st_size
            for item in session_root.iterdir()
            if item.is_file()
        )
        if current_size + len(content) > self.max_session_bytes:
            raise AttachmentStoreError(
                "attachment_storage_limit",
                413,
                "Session attachment storage limit exceeded",
            )
        path = session_root / f"upload_{uuid4().hex}{suffix}"
        try:
            path.write_bytes(content)
            path.chmod(0o600)
        except OSError as exc:
            self.remove(path)
            raise AttachmentStoreError(
                "attachment_storage_error",
                500,
                "Attachment could not be stored",
            ) from exc
        return path

    def remove(self, path: str | Path) -> None:
        candidate = Path(path)
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass

    def _validate_upload(self, filename: str, media_type: str, content: bytes) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise AttachmentStoreError("invalid_filename", 400, "Attachment filename is required")
        if len(filename) > MAX_ATTACHMENT_FILENAME or filename in {".", ".."}:
            raise AttachmentStoreError("invalid_filename", 400, "Attachment filename is invalid")
        if Path(filename).name != filename or any(ord(char) < 32 for char in filename):
            raise AttachmentStoreError("invalid_filename", 400, "Attachment filename is invalid")
        if media_type not in SUPPORTED_IMAGE_TYPES:
            raise AttachmentStoreError("unsupported_media_type", 415, "Unsupported image type")
        if not isinstance(content, bytes):
            raise AttachmentStoreError("invalid_request", 400, "Attachment body is invalid")
        if len(content) == 0:
            raise AttachmentStoreError("invalid_request", 400, "Attachment body is empty")
        if len(content) > self.max_bytes:
            raise AttachmentStoreError("attachment_too_large", 413, "Attachment exceeds the size limit")
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AttachmentStoreError("invalid_image", 400, "Attachment is not a valid image") from exc
        return _MEDIA_SUFFIXES[media_type]

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not _SAFE_SESSION_ID.fullmatch(session_id):
            raise AttachmentStoreError("invalid_request", 400, "Session ID is invalid")
