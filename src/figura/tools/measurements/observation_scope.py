"""Normalized polygon scopes for image observation sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


class ObservationScopeError(ValueError):
    """The supplied observation scope cannot select source pixels."""


def decode_scoped_image(
    image_bytes: bytes,
    observation_scope: Mapping[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Decode an image and neutralize source pixels outside its optional scope."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("image bytes are required")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            rgba = image.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"))
            visible = alpha > 0
            if bool(np.all(alpha == 255)):
                rgb = np.asarray(image.convert("RGB"))
            else:
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                rgb = np.asarray(Image.alpha_composite(background, rgba).convert("RGB"))
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        raise ValueError("image cannot be decoded") from None

    if observation_scope is None:
        if not bool(np.any(visible)):
            raise ValueError("image contains no visible source pixels")
        if bool(np.all(visible)):
            return rgb, None
        mask = visible
    else:
        mask = build_observation_mask(observation_scope, rgb.shape[1], rgb.shape[0]) & visible
        if not bool(np.any(mask)):
            raise ObservationScopeError("observation_scope selects no visible source pixels")
    scoped_rgb = rgb.copy()
    scoped_rgb[~mask] = (255, 255, 255)
    return scoped_rgb, mask


def build_observation_mask(
    observation_scope: Mapping[str, Any],
    width: int,
    height: int,
) -> np.ndarray:
    """Rasterize the include union minus the exclude union in source pixels."""
    if not isinstance(observation_scope, Mapping):
        raise ObservationScopeError("observation_scope must be an object")
    if set(observation_scope) - {"include", "exclude"}:
        raise ObservationScopeError("observation_scope contains unsupported fields")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("source image dimensions must be positive integers")

    include = _polygons(observation_scope, "include")
    exclude = _polygons(observation_scope, "exclude")
    if include is None and exclude is None:
        raise ObservationScopeError("observation_scope requires include or exclude polygons")

    include_mask = _rasterize(include, width, height) if include is not None else np.ones((height, width), dtype=bool)
    if exclude is not None:
        include_mask &= ~_rasterize(exclude, width, height)
    if not bool(np.any(include_mask)):
        raise ObservationScopeError("observation_scope selects no source pixels")
    return include_mask


def contains_observed_box(
    bbox_px: tuple[int, int, int, int],
    observation_mask: np.ndarray | None,
) -> bool:
    """Keep an OCR detection only when its complete box is inside the scope."""
    if observation_mask is None:
        return True
    x, y, width, height = bbox_px
    image_height, image_width = observation_mask.shape
    right, bottom = x + width, y + height
    if x < 0 or y < 0 or right > image_width or bottom > image_height:
        return False
    return bool(np.all(observation_mask[y:bottom, x:right]))


def _polygons(
    scope: Mapping[str, Any],
    name: str,
) -> tuple[tuple[tuple[int, int], ...], ...] | None:
    if name not in scope:
        return None
    polygons = scope[name]
    if not isinstance(polygons, Sequence) or isinstance(polygons, str | bytes) or not 1 <= len(polygons) <= 4:
        raise ObservationScopeError(f"{name} must contain 1 through 4 polygons")
    normalized: list[tuple[tuple[int, int], ...]] = []
    for polygon in polygons:
        if not isinstance(polygon, Sequence) or isinstance(polygon, str | bytes) or not 3 <= len(polygon) <= 32:
            raise ObservationScopeError("each observation polygon must contain 3 through 32 points")
        points: list[tuple[int, int]] = []
        for point in polygon:
            if not isinstance(point, Sequence) or isinstance(point, str | bytes) or len(point) != 2:
                raise ObservationScopeError("each observation point must be an [x, y] pair")
            x, y = point
            if type(x) is not int or type(y) is not int or not 0 <= x <= 1000 or not 0 <= y <= 1000:
                raise ObservationScopeError("observation coordinates must be integers from 0 through 1000")
            points.append((x, y))
        normalized.append(tuple(points))
    return tuple(normalized)


def _rasterize(
    polygons: tuple[tuple[tuple[int, int], ...], ...],
    width: int,
    height: int,
) -> np.ndarray:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    for polygon in polygons:
        points = [
            (round(x * width / 1000), round(y * height / 1000))
            for x, y in polygon
        ]
        draw.polygon(points, fill=1)
    return np.asarray(image, dtype=np.uint8).astype(bool)
