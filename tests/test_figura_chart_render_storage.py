from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.json_schema import canonical_json_dumps
from figura.sources.chart_renders import FiguraChartRenderService


def _png(color: str = "red", size: tuple[int, int] = (13, 7)) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _service(tmp_path) -> FiguraChartRenderService:
    return FiguraChartRenderService(tmp_path)


def test_render_storage_is_private_and_uses_safe_identity_filename(tmp_path) -> None:
    service = _service(tmp_path)
    content = _png()

    stored, width, height = service.store("run/unsafe", "call?unsafe", content)

    identity = canonical_json_dumps(["run/unsafe", "call?unsafe"]).encode("utf-8")
    expected_name = hashlib.sha256(identity).hexdigest() + ".png"
    render_root = tmp_path / "chart-renders"
    path = render_root / expected_name
    assert stored == content
    assert (width, height) == (13, 7)
    assert render_root.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert service.resolve("run/unsafe", "call?unsafe") == (content, 13, 7)
    assert len(list(render_root.glob("*.png"))) == 1


def test_render_storage_replay_returns_existing_png_without_overwriting(tmp_path) -> None:
    service = _service(tmp_path)
    original = _png("red")
    replacement = _png("blue")

    assert service.store("run-1", "call-1", original) == (original, 13, 7)
    assert service.store("run-1", "call-1", replacement) == (original, 13, 7)
    assert service.resolve("run-1", "call-1")[0] == original


def test_existing_valid_file_from_interrupted_commit_is_reused(tmp_path) -> None:
    service = _service(tmp_path)
    original = _png()
    identity = canonical_json_dumps(["run-1", "call-1"]).encode("utf-8")
    path = tmp_path / "chart-renders" / f"{hashlib.sha256(identity).hexdigest()}.png"
    path.write_bytes(original)
    path.chmod(0o600)

    assert service.store("run-1", "call-1", _png("blue")) == (original, 13, 7)


def test_render_storage_rejects_invalid_and_oversized_png(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    with pytest.raises(RunError) as invalid:
        service.store("run-1", "call-1", b"not a png")
    assert invalid.value.code is RunErrorCode.INTEGRITY_ERROR

    monkeypatch.setattr("figura.sources.chart_renders.MAX_IMAGE_BYTES", 1)
    with pytest.raises(RunError) as oversized:
        service.store("run-1", "call-2", _png())
    assert oversized.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_render_storage_enforces_pixel_dimension_limit(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr("figura.sources.chart_renders._MAX_IMAGE_PIXELS", 10)

    with pytest.raises(RunError) as error:
        service.store("run-1", "call-dimensions", _png(size=(4, 3)))

    assert error.value.code is RunErrorCode.INTEGRITY_ERROR


@pytest.mark.parametrize("content", [b"broken", b""])
def test_render_storage_missing_or_corrupted_file_fails_closed(tmp_path, content: bytes) -> None:
    service = _service(tmp_path)
    with pytest.raises(RunError) as missing:
        service.resolve("run-1", "missing")
    assert missing.value.code is RunErrorCode.INTEGRITY_ERROR

    identity = canonical_json_dumps(["run-1", "corrupted"]).encode("utf-8")
    path = tmp_path / "chart-renders" / f"{hashlib.sha256(identity).hexdigest()}.png"
    path.write_bytes(content)
    with pytest.raises(RunError) as corrupted:
        service.resolve("run-1", "corrupted")
    assert corrupted.value.code is RunErrorCode.INTEGRITY_ERROR
