"""Session-scoped, private image attachment storage for the Figura runtime."""

from __future__ import annotations

import io
import os
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import BinaryIO

from figura.providers.models import ImageBlock
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.runtime.errors import RunError, RunErrorCode
from figura.sources.imaging import verify_attachment_image
from figura.sources.models import AttachmentMetadata
from figura.sources.repository import SourcesRepository
from figura.sources.storage import ensure_private_directory
from figura.storage.database import _utc_now


_CHUNK_BYTES = 64 * 1024


class FiguraAttachmentService:
    """Persist Session-owned image metadata and resolve bytes for Agent calls."""

    __slots__ = ("_repository", "_root", "_trash")

    def __init__(self, repository: SourcesRepository, data_root: str | os.PathLike[str]) -> None:
        if not isinstance(repository, SourcesRepository):
            raise TypeError("repository must be a SourcesRepository")
        self._repository = repository
        self._root = Path(data_root).expanduser() / "attachments"
        self._trash = self._root / ".trash"
        try:
            ensure_private_directory(self._root, "attachment storage")
            ensure_private_directory(self._trash, "attachment trash")
            self._repository.reconcile_attachment_files(self._reconcile_files)
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
        self._repository.assert_session(session_id)
        attachment_id = uuid.uuid4().hex
        final_path = self._final_path(attachment_id)

        try:
            with tempfile.TemporaryFile(mode="w+b", dir=self._root) as staged:
                byte_count = _copy_bounded(content, staged)
                if byte_count == 0:
                    raise RunError(RunErrorCode.INVALID_REQUEST)
                media_type = verify_attachment_image(staged)
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

                self._repository.register_attachment(metadata, install_file)
                return metadata
        except RunError:
            self._remove_failed_upload(final_path)
            raise
        except (OSError, ValueError, TypeError):
            self._remove_failed_upload(final_path)
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def list(self, session_id: str) -> tuple[AttachmentMetadata, ...]:
        return self._repository.list_attachments(session_id)

    def resolve(self, session_id: str, attachment_id: str) -> ImageBlock:
        metadata = self._repository.get_attachment_metadata(session_id, attachment_id)
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
        if verify_attachment_image(io.BytesIO(content)) != metadata.media_type:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return ImageBlock(metadata.media_type, content)

    def delete(self, session_id: str, attachment_id: str) -> None:
        self._repository.get_attachment_metadata(session_id, attachment_id)
        final_path = self._final_path(attachment_id)
        trash_path = self._trash / f"{attachment_id}.{uuid.uuid4().hex}.bin"
        try:
            with self._repository.delete_attachment_transaction(session_id, attachment_id):
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


def _is_attachment_id(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return uuid.UUID(value).hex == value
    except ValueError:
        return False
