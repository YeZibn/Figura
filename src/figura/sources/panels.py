"""Private PNG persistence and polygon crop execution for Figura Panels."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from figura.providers.models import ImageBlock
from figura.shared.image_limits import MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES
from figura.runtime.errors import RunError, RunErrorCode

from .attachments import FiguraAttachmentService
from .models import PanelPoint, PanelRecord
from .imaging import crop_panel, read_panel_image
from .repository import SourcesRepository
from .storage import ensure_private_directory, sync_directory


_MAX_PANEL_COUNT = 32


class FiguraPanelService:
    __slots__ = ("_attachments", "_repository", "_root")

    def __init__(
        self,
        repository: SourcesRepository,
        data_root: str | os.PathLike[str],
        attachments: FiguraAttachmentService,
    ) -> None:
        if not isinstance(repository, SourcesRepository):
            raise TypeError("repository must be a SourcesRepository")
        if not isinstance(attachments, FiguraAttachmentService):
            raise TypeError("attachments must be a FiguraAttachmentService")
        root = Path(data_root).expanduser()
        self._attachments = attachments
        self._repository = repository
        self._root = root / "panels"
        try:
            ensure_private_directory(self._root, "Panel storage")
            self._repository.reconcile_panel_files(self._reconcile_files)
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def list(self, session_id: str) -> tuple[PanelRecord, ...]:
        return self._repository.list_panels(session_id)

    def decompose(
        self,
        session_id: str,
        run_id: str,
        attachment_id: str,
        proposals: Sequence[tuple[str, tuple[PanelPoint, ...]]],
        idempotency_key: str,
    ) -> tuple[PanelRecord, ...]:
        if not 1 <= len(proposals) <= _MAX_PANEL_COUNT:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        source = self._attachments.resolve(session_id, attachment_id)
        if len(idempotency_key) != 64:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        records = tuple(
            PanelRecord(
                panel_id=hashlib.sha256(f"{idempotency_key}:{index}".encode()).hexdigest(),
                session_id=session_id,
                run_id=run_id,
                source_attachment_id=attachment_id,
                name=name,
                points=points,
            )
            for index, (name, points) in enumerate(proposals)
        )
        existing = self._repository.list_panels(session_id)
        existing_by_id = {record.panel_id: record for record in existing}
        if any(record.panel_id in existing_by_id for record in records):
            if any(existing_by_id.get(record.panel_id) != record for record in records):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            for record in records:
                self._read_file(record.panel_id)
            return records

        try:
            crops = tuple(crop_panel(source.image_bytes, record.points) for record in records)
            if (
                any(len(content) > MAX_IMAGE_BYTES for content in crops)
                or sum(len(content) for content in crops) > MAX_TOTAL_IMAGE_BYTES
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            paths: list[Path] = []
            with tempfile.TemporaryDirectory(dir=self._root) as temporary:
                for record, content in zip(records, crops, strict=True):
                    staged_path = Path(temporary) / f"{record.panel_id}.png"
                    with staged_path.open("xb") as staged_file:
                        staged_file.write(content)
                        staged_file.flush()
                        os.fsync(staged_file.fileno())

                def install_files() -> None:
                    for record in records:
                        source_path = Path(temporary) / f"{record.panel_id}.png"
                        final_path = self._final_path(record.panel_id)
                        os.link(source_path, final_path)
                        paths.append(final_path)
                    descriptor = os.open(self._root, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)

                try:
                    self._repository.register_panels(records, install_files)
                except Exception:
                    for path in paths:
                        path.unlink(missing_ok=True)
                    raise
            return records
        except RunError:
            raise
        except (OSError, ValueError):
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def resolve(self, session_id: str, panel_id: str) -> tuple[PanelRecord, ImageBlock, int, int]:
        record = self._repository.get_panel(session_id, panel_id)
        content, width, height = self._read_file(panel_id)
        return record, ImageBlock("image/png", content), width, height

    def get(self, session_id: str, panel_id: str) -> PanelRecord:
        return self._repository.get_panel(session_id, panel_id)

    def _read_file(self, panel_id: str) -> tuple[bytes, int, int]:
        path = self._final_path(panel_id)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
                raise RunError(RunErrorCode.STORAGE_ERROR)
            content = path.read_bytes()
            width, height = read_panel_image(content, MAX_IMAGE_BYTES)
            return content, width, height
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None

    def _reconcile_files(self, panel_ids: frozenset[str]) -> None:
        for path in self._root.iterdir():
            if path.is_symlink():
                path.unlink()
                continue
            if path.is_dir():
                shutil.rmtree(path)
                continue
            panel_id = path.name.removesuffix(".png")
            if path.name.endswith(".png") and _is_panel_id(panel_id) and panel_id not in panel_ids:
                path.unlink()

    def stage_session_deletion(
        self, session_trash: Path, panel_ids: tuple[str, ...]
    ) -> None:
        stage = session_trash / "panels"
        ensure_private_directory(stage, "Session Panel staging")
        moved = False
        for panel_id in panel_ids:
            source = self._final_path(panel_id)
            target = stage / source.name
            if source.exists() or source.is_symlink():
                if target.exists() or target.is_symlink():
                    raise OSError("duplicate staged Panel")
                os.replace(source, target)
                moved = True
        if moved:
            sync_directory(self._root)
            sync_directory(stage)

    def restore_session_deletion(self, session_trash: Path) -> None:
        stage = session_trash / "panels"
        if not stage.exists() and not stage.is_symlink():
            return
        if stage.is_symlink() or not stage.is_dir():
            raise OSError("invalid Panel staging path")
        moved = False
        for staged in stage.iterdir():
            if not staged.name.endswith(".png"):
                raise OSError("invalid staged Panel")
            target = self._final_path(staged.name[:-4])
            if target.exists() or target.is_symlink():
                raise OSError("Panel restore collision")
            os.replace(staged, target)
            moved = True
        stage.rmdir()
        if moved:
            sync_directory(self._root)
            sync_directory(session_trash)

    def discard_session_deletion(self, session_trash: Path) -> None:
        stage = session_trash / "panels"
        if stage.is_symlink():
            raise OSError("invalid Panel staging path")
        if stage.exists():
            shutil.rmtree(stage)

    def validate_files(self) -> None:
        for record in self._repository.list_all_panels():
            self._read_file(record.panel_id)

    def _final_path(self, panel_id: str) -> Path:
        if not _is_panel_id(panel_id):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._root / f"{panel_id}.png"


def _is_panel_id(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
