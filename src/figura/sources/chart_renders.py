"""Private, idempotent storage for rendered ChartFigure PNGs."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.shared.json_schema import canonical_json_dumps

from .storage import ensure_private_directory, sync_directory


_MAX_IMAGE_PIXELS = 40_000_000


class FiguraChartRenderService:
    """Store and resolve immutable PNG bytes by their originating Run and call."""

    __slots__ = ("_root",)

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self._root = Path(data_root).expanduser() / "chart-renders"
        try:
            ensure_private_directory(self._root, "chart render storage")
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def store(self, run_id: str, call_id: str, content: bytes) -> tuple[bytes, int, int]:
        """Install once and return the canonical stored PNG and its dimensions."""
        final_path = self._final_path(run_id, call_id)
        try:
            if final_path.exists() or final_path.is_symlink():
                return self._read(final_path)
            self._validate_png(content)

            with tempfile.TemporaryDirectory(dir=self._root) as temporary:
                staged_path = Path(temporary) / "render.png"
                descriptor = os.open(
                    staged_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(descriptor, "wb") as staged:
                    staged.write(content)
                    staged.flush()
                    os.fchmod(staged.fileno(), 0o600)
                    os.fsync(staged.fileno())

                try:
                    os.link(staged_path, final_path)
                    directory_fd = os.open(self._root, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except FileExistsError:
                    pass
            return self._read(final_path)
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def resolve(self, run_id: str, call_id: str) -> tuple[bytes, int, int]:
        return self._read(self._final_path(run_id, call_id))

    def stage_session_deletion(
        self, session_trash: Path, render_calls: tuple[tuple[str, str], ...]
    ) -> None:
        stage = session_trash / "chart-renders"
        ensure_private_directory(stage, "Session ChartRender staging")
        moved = False
        for run_id, call_id in render_calls:
            source = self._final_path(run_id, call_id)
            target = stage / source.name
            if source.exists() or source.is_symlink():
                if target.exists() or target.is_symlink():
                    raise OSError("duplicate staged chart render")
                os.replace(source, target)
                moved = True
        if moved:
            sync_directory(self._root)
            sync_directory(stage)

    def restore_session_deletion(self, session_trash: Path) -> None:
        stage = session_trash / "chart-renders"
        if not stage.exists() and not stage.is_symlink():
            return
        if stage.is_symlink() or not stage.is_dir():
            raise OSError("invalid ChartRender staging path")
        moved = False
        for staged in stage.iterdir():
            if not _is_render_filename(staged.name):
                raise OSError("invalid staged chart render")
            target = self._root / staged.name
            if target.exists() or target.is_symlink():
                raise OSError("ChartRender restore collision")
            os.replace(staged, target)
            moved = True
        stage.rmdir()
        if moved:
            sync_directory(self._root)
            sync_directory(session_trash)

    def discard_session_deletion(self, session_trash: Path) -> None:
        stage = session_trash / "chart-renders"
        if stage.is_symlink():
            raise OSError("invalid ChartRender staging path")
        if stage.exists():
            shutil.rmtree(stage)

    def reconcile_files(self, render_calls: tuple[tuple[str, str], ...]) -> None:
        expected = {self._render_filename(run_id, call_id) for run_id, call_id in render_calls}
        for path in self._root.iterdir():
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.name.endswith(".png") and path.name not in expected:
                path.unlink()

    def _read(self, path: Path) -> tuple[bytes, int, int]:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            content = path.read_bytes()
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        try:
            width, height = self._validate_png(content)
        except RunError as error:
            if error.code is RunErrorCode.UNSUPPORTED_PAYLOAD:
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
            raise
        return content, width, height

    def _final_path(self, run_id: str, call_id: str) -> Path:
        return self._root / self._render_filename(run_id, call_id)

    @staticmethod
    def _render_filename(run_id: str, call_id: str) -> str:
        if not isinstance(run_id, str) or not run_id or not isinstance(call_id, str) or not call_id:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        identity = canonical_json_dumps([run_id, call_id]).encode("utf-8")
        filename = hashlib.sha256(identity).hexdigest()
        return f"{filename}.png"

    @staticmethod
    def _validate_png(content: bytes) -> tuple[int, int]:
        if not isinstance(content, bytes) or not content or len(content) > MAX_IMAGE_BYTES:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if (
                        image.format != "PNG"
                        or image.width * image.height > _MAX_IMAGE_PIXELS
                    ):
                        raise RunError(RunErrorCode.INTEGRITY_ERROR)
                    width, height = image.size
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
        except RunError:
            raise
        except (
            OSError,
            ValueError,
            SyntaxError,
            UnidentifiedImageError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        return width, height


def _is_render_filename(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 68
        and value.endswith(".png")
        and all(character in "0123456789abcdef" for character in value[:-4])
    )
