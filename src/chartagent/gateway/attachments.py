"""Bounded, persistent storage for images uploaded through the local gateway."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from ..attachments import DEFAULT_MAX_ATTACHMENT_BYTES, SUPPORTED_IMAGE_TYPES
from ..storage import project_root, resolve_storage_paths

DEFAULT_ATTACHMENT_ROOT = project_root() / ".chartagent" / "attachments"
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
    """Store uploaded bytes below a private application-owned root.

    The historical class name is kept for compatibility with existing callers.
    New instances are persistent and never clear the root during startup.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        database: str | Path | None = None,
        max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES,
        max_session_bytes: int = DEFAULT_MAX_SESSION_ATTACHMENT_BYTES,
    ) -> None:
        self.root = self._resolve_root(root, database)
        self.max_bytes = max_bytes
        self.max_session_bytes = max_session_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._restrict_permissions(self.root, 0o700)

    @staticmethod
    def _resolve_root(root: str | Path | None, database: str | Path | None) -> Path:
        return resolve_storage_paths(
            database=database,
            attachment_root=root,
        ).attachments

    @staticmethod
    def _restrict_permissions(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except OSError:
            pass

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
        self._restrict_permissions(session_root, 0o700)
        path = session_root / f"upload_{uuid4().hex}{suffix}"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=session_root,
                prefix=".upload_",
                suffix=suffix,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._restrict_permissions(temporary, 0o600)
            os.replace(temporary, path)
            self._restrict_permissions(path, 0o600)
        except OSError as exc:
            if temporary is not None:
                self.remove(temporary)
            self.remove(path)
            raise AttachmentStoreError(
                "attachment_storage_error",
                500,
                "Attachment could not be stored",
            ) from exc
        return path

    def remove(self, path: str | Path) -> bool:
        candidate = Path(path)
        try:
            candidate.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def is_managed_path(self, session_id: str, path: str | Path) -> bool:
        self._validate_session_id(session_id)
        candidate = Path(path).expanduser().resolve(strict=False)
        session_root = (self.root / session_id).resolve(strict=False)
        try:
            candidate.relative_to(session_root)
        except ValueError:
            return False
        return candidate != session_root

    def remove_managed(self, session_id: str, path: str | Path) -> bool:
        if not self.is_managed_path(session_id, path):
            raise AttachmentStoreError("attachment_storage_error", 500, "Attachment storage path is invalid")
        candidate = Path(path).expanduser().resolve(strict=False)
        try:
            candidate.unlink(missing_ok=True)
            return True
        except OSError as exc:
            raise AttachmentStoreError("attachment_storage_error", 500, "Attachment could not be removed") from exc

    def remove_session(self, session_id: str) -> bool:
        self._validate_session_id(session_id)
        session_root = (self.root / session_id).resolve(strict=False)
        try:
            session_root.relative_to(self.root.resolve(strict=False))
        except ValueError as exc:
            raise AttachmentStoreError("attachment_storage_error", 500, "Attachment storage path is invalid") from exc
        try:
            shutil.rmtree(session_root, ignore_errors=False)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise AttachmentStoreError("attachment_storage_error", 500, "Attachment directory could not be removed") from exc

    def migrate_legacy(self, session_id: str, filename: str, media_type: str, source: str | Path, expected_sha256: str) -> Path | None:
        """Copy a valid legacy source into managed storage without trusting its path."""
        candidate = Path(source).expanduser()
        if self.is_managed_path(session_id, candidate) or not candidate.is_file():
            return None
        try:
            content = candidate.read_bytes()
        except OSError:
            return None
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            return None
        try:
            return self.stage(session_id, filename, media_type, content)
        except AttachmentStoreError:
            return None

    def cleanup_orphans(self, referenced_paths: set[str]) -> int:
        """Remove only opaque files below managed session directories."""
        removed = 0
        if not self.root.exists():
            return removed
        root = self.root.resolve(strict=False)
        for session_root in self.root.iterdir():
            if not session_root.is_dir():
                continue
            try:
                session_root.resolve(strict=False).relative_to(root)
            except ValueError:
                continue
            for item in session_root.iterdir():
                if not item.is_file() or str(item.resolve(strict=False)) in referenced_paths:
                    continue
                if item.name.startswith("upload_") or item.name.startswith(".upload_"):
                    removed += int(self.remove(item))
        return removed

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
