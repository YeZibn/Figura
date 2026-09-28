"""Private PNG persistence and polygon crop execution for Figura Panels."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import warnings
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from figura.attachments import FiguraAttachmentService
from figura.providers.models import ImageBlock
from figura.providers.validation import MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES
from figura.runtime import RunError, RunErrorCode

from .models import PanelPoint, PanelRecord
from .repository import PanelRepository


_MAX_PANEL_COUNT = 32
_MAX_PANEL_PIXELS = 40_000_000


class FiguraPanelService:
    __slots__ = ("_attachments", "_repository", "_root")

    def __init__(self, data_root: str | os.PathLike[str], attachments: FiguraAttachmentService) -> None:
        if not isinstance(attachments, FiguraAttachmentService):
            raise TypeError("attachments must be a FiguraAttachmentService")
        root = Path(data_root).expanduser()
        self._attachments = attachments
        self._repository = PanelRepository(str(root))
        self._root = root / "panels"
        try:
            self._ensure_private_directory(self._root)
            self._repository.reconcile_files(self._reconcile_files)
            for record in self._repository.list_all():
                self._read_file(record.panel_id)
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def list(self, session_id: str) -> tuple[PanelRecord, ...]:
        return self._repository.list(session_id)

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
        existing = self._repository.list(session_id)
        existing_by_id = {record.panel_id: record for record in existing}
        if any(record.panel_id in existing_by_id for record in records):
            if any(existing_by_id.get(record.panel_id) != record for record in records):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            for record in records:
                self._read_file(record.panel_id)
            return records

        try:
            crops = tuple(_crop_panel(source.image_bytes, record.points) for record in records)
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
                    self._repository.register(records, install_files)
                except Exception:
                    for path in paths:
                        path.unlink(missing_ok=True)
                    raise
            return records
        except RunError:
            raise
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def resolve(self, session_id: str, panel_id: str) -> tuple[PanelRecord, ImageBlock, int, int]:
        record = self._repository.get(session_id, panel_id)
        content, width, height = self._read_file(panel_id)
        return record, ImageBlock("image/png", content), width, height

    def get(self, session_id: str, panel_id: str) -> PanelRecord:
        return self._repository.get(session_id, panel_id)

    def _read_file(self, panel_id: str) -> tuple[bytes, int, int]:
        path = self._final_path(panel_id)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
                raise RunError(RunErrorCode.STORAGE_ERROR)
            content = path.read_bytes()
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != "PNG" or image.width * image.height > _MAX_PANEL_PIXELS:
                        raise RunError(RunErrorCode.INTEGRITY_ERROR)
                    image.load()
                    width, height = image.size
            return content, width, height
        except RunError:
            raise
        except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
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

    def _final_path(self, panel_id: str) -> Path:
        if not _is_panel_id(panel_id):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        return self._root / f"{panel_id}.png"

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        if path.is_symlink():
            raise OSError("Panel storage directory cannot be a symlink")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir():
            raise OSError("Panel storage path is not a directory")
        path.chmod(0o700)


def _crop_panel(source: bytes, points: tuple[PanelPoint, ...]) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source)) as image:
                if image.width * image.height > _MAX_PANEL_PIXELS:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                image.load()
                rgba = image.convert("RGBA")
    except RunError:
        raise
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

    pixel_points = tuple(
        (round(point.x * (rgba.width - 1) / 1000), round(point.y * (rgba.height - 1) / 1000))
        for point in points
    )
    if abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(pixel_points, (*pixel_points[1:], pixel_points[0]), strict=True)
    )) == 0:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    left = min(x for x, _ in pixel_points)
    top = min(y for _, y in pixel_points)
    right = max(x for x, _ in pixel_points)
    bottom = max(y for _, y in pixel_points)
    if right <= left or bottom <= top:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    mask = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(mask).polygon(pixel_points, fill=255)
    if mask.getbbox() is None:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    crop = rgba.crop((left, top, right + 1, bottom + 1))
    crop_mask = mask.crop((left, top, right + 1, bottom + 1))
    crop.putalpha(ImageChops.multiply(crop.getchannel("A"), crop_mask))
    output = io.BytesIO()
    crop.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _is_panel_id(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
