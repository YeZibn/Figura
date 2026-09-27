"""Session-scoped, private image attachment storage for the Figura runtime."""

from __future__ import annotations

import io
import os
import stat
import tempfile
import unicodedata
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from figura.providers.models import ImageBlock
from figura.providers.validation import MAX_IMAGE_BYTES
from figura.runtime import AttachmentMetadata, FiguraRunStore, RunError, RunErrorCode


_PIL_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_CHUNK_BYTES = 64 * 1024


class FiguraAttachmentService:
    """Persist Session-owned image metadata and resolve bytes for Agent calls."""

    __slots__ = ("_store", "_root", "_trash")

    def __init__(self, store: FiguraRunStore) -> None:
        if not isinstance(store, FiguraRunStore):
            raise TypeError("store must be a FiguraRunStore")
        self._store = store
        self._root = store.data_root / "attachments"
        self._trash = self._root / ".trash"
        try:
            self._ensure_private_directory(self._root)
            self._ensure_private_directory(self._trash)
            self._store.reconcile_attachment_files(self._reconcile_files)
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def upload(
        self,
        session_id: str,
        filename: str,
        content: bytes | bytearray | memoryview | BinaryIO,
    ) -> AttachmentMetadata:
        safe_filename = _sanitize_filename(filename)
        self._store.assert_session(session_id)
        attachment_id = uuid.uuid4().hex
        final_path = self._final_path(attachment_id)

        try:
            with tempfile.TemporaryFile(mode="w+b", dir=self._root) as staged:
                byte_count = _copy_bounded(content, staged)
                if byte_count == 0:
                    raise RunError(RunErrorCode.INVALID_REQUEST)
                media_type = _verify_image(staged)
                metadata = AttachmentMetadata(
                    attachment_id=attachment_id,
                    session_id=session_id,
                    filename=safe_filename,
                    media_type=media_type,
                    byte_count=byte_count,
                    created_at=_utc_now(),
                )

                def install_file() -> None:
                    staged.seek(0)
                    descriptor = os.open(
                        final_path,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                    with os.fdopen(descriptor, "wb") as destination:
                        while True:
                            chunk = staged.read(_CHUNK_BYTES)
                            if not chunk:
                                break
                            destination.write(chunk)
                        destination.flush()
                        os.fsync(destination.fileno())

                self._store.register_attachment(metadata, install_file)
                return metadata
        except RunError:
            self._remove_failed_upload(final_path)
            raise
        except (OSError, ValueError, TypeError):
            self._remove_failed_upload(final_path)
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def list(self, session_id: str) -> tuple[AttachmentMetadata, ...]:
        return self._store.list_attachments(session_id)

    def resolve(self, session_id: str, attachment_id: str) -> ImageBlock:
        metadata = self._store.get_attachment_metadata(session_id, attachment_id)
        path = self._final_path(metadata.attachment_id)
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != metadata.byte_count
            ):
                raise RunError(RunErrorCode.STORAGE_ERROR)
            content = path.read_bytes()
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None
        if len(content) != metadata.byte_count:
            raise RunError(RunErrorCode.STORAGE_ERROR)
        if _verify_image(io.BytesIO(content)) != metadata.media_type:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return ImageBlock(metadata.media_type, content)

    def delete(self, session_id: str, attachment_id: str) -> None:
        self._store.get_attachment_metadata(session_id, attachment_id)
        final_path = self._final_path(attachment_id)
        trash_path = self._trash / f"{attachment_id}.{uuid.uuid4().hex}.bin"
        try:
            with self._store.delete_attachment_transaction(session_id, attachment_id):
                if final_path.exists() or final_path.is_symlink():
                    os.replace(final_path, trash_path)
        except Exception as error:
            if trash_path.exists() or trash_path.is_symlink():
                try:
                    os.replace(trash_path, final_path)
                except OSError:
                    raise RunError(RunErrorCode.STORAGE_ERROR) from None
            if isinstance(error, RunError):
                raise
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

        try:
            if trash_path.exists() or trash_path.is_symlink():
                trash_path.unlink()
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def _reconcile_files(self, attachment_ids: frozenset[str]) -> None:
        for tombstone in self._trash.iterdir():
            attachment_id = tombstone.name.split(".", 1)[0]
            if not _is_attachment_id(attachment_id):
                continue
            final_path = self._final_path(attachment_id)
            if attachment_id in attachment_ids and not final_path.exists():
                os.replace(tombstone, final_path)
            else:
                tombstone.unlink()

        for path in self._root.iterdir():
            if path == self._trash or not path.name.endswith(".bin"):
                continue
            attachment_id = path.name[:-4]
            if _is_attachment_id(attachment_id) and attachment_id not in attachment_ids:
                path.unlink()

    def _final_path(self, attachment_id: str) -> Path:
        if not _is_attachment_id(attachment_id):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._root / f"{attachment_id}.bin"

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        if path.is_symlink():
            raise OSError("attachment directory cannot be a symlink")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir():
            raise OSError("attachment path is not a directory")
        path.chmod(0o700)

    @staticmethod
    def _remove_failed_upload(path: Path) -> None:
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None


def _copy_bounded(
    source: bytes | bytearray | memoryview | BinaryIO,
    destination: BinaryIO,
) -> int:
    if isinstance(source, (bytes, bytearray, memoryview)):
        reader: BinaryIO = io.BytesIO(bytes(source))
    elif callable(getattr(source, "read", None)):
        reader = source
    else:
        raise RunError(RunErrorCode.INVALID_REQUEST)

    total = 0
    while True:
        chunk = reader.read(min(_CHUNK_BYTES, MAX_IMAGE_BYTES - total + 1))
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not chunk:
            break
        if total + len(chunk) > MAX_IMAGE_BYTES:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        destination.write(chunk)
        total += len(chunk)
    return total


def _sanitize_filename(filename: str) -> str:
    if not isinstance(filename, str):
        raise RunError(RunErrorCode.INVALID_REQUEST)
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    safe = "".join(character for character in basename if not unicodedata.category(character).startswith("C"))
    safe = safe.strip()
    try:
        size = len(safe.encode("utf-8"))
    except UnicodeEncodeError:
        raise RunError(RunErrorCode.INVALID_REQUEST) from None
    if not safe or size > 255:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    return safe


def _verify_image(source: BinaryIO) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source.seek(0)
            with Image.open(source) as image:
                image_format = image.format
                image.verify()
            source.seek(0)
            with Image.open(source) as image:
                image.load()
                image_format = image.format
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    media_type = _PIL_FORMATS.get(image_format or "")
    if media_type is None:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return media_type


def _is_attachment_id(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return uuid.UUID(value).hex == value
    except ValueError:
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
