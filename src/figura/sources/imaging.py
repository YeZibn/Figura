"""Image validation and polygon extraction for Figura Sources."""

from __future__ import annotations

import io
import warnings
from typing import BinaryIO

from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from figura.runtime.errors import RunError, RunErrorCode
from figura.sources.models import PanelPoint


PIL_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


MAX_PANEL_PIXELS = 40_000_000


def verify_attachment_image(source: BinaryIO) -> str:
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
    media_type = PIL_FORMATS.get(image_format or "")
    if media_type is None:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return media_type


def crop_panel(source: bytes, points: tuple[PanelPoint, ...]) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source)) as image:
                if image.width * image.height > MAX_PANEL_PIXELS:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                image.load()
                rgba = image.convert("RGBA")
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
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

    pixel_points = tuple(
        (round(point.x * (rgba.width - 1) / 1000), round(point.y * (rgba.height - 1) / 1000))
        for point in points
    )
    area_twice = abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(
                pixel_points, (*pixel_points[1:], pixel_points[0]), strict=True
            )
        )
    )
    if area_twice == 0:
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


def read_panel_image(content: bytes, max_bytes: int) -> tuple[int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if (
                    image.format != "PNG"
                    or len(content) > max_bytes
                    or image.width * image.height > MAX_PANEL_PIXELS
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                image.load()
                return image.size
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
