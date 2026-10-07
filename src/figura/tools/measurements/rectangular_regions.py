"""Bounded color-region candidates shared by matrix and hierarchy sensors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .colors import color_mask, hex_color, series_palette
from .contracts import MAX_MEASUREMENT_OBSERVATIONS, PreparedMeasurementImage
from .pie import _components


@dataclass(frozen=True)
class ColorRegion:
    left: int
    top: int
    width: int
    height: int
    pixels: int
    color: str
    rectangularity: float

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2.0

    @property
    def bounds_px(self) -> dict[str, int]:
        return {"x": self.left, "y": self.top, "width": self.width, "height": self.height}


def visible_color_regions(image: PreparedMeasurementImage) -> tuple[list[ColorRegion], bool]:
    """Find bounded near-rectangular color components without assigning data values."""
    rgb = image.rgb
    height, width = rgb.shape[:2]
    palette = series_palette(rgb, limit=MAX_MEASUREMENT_OBSERVATIONS)
    if not palette:
        return [], False
    mask_limit = image.observation_mask
    min_area = max(8, int(width * height * 0.00012))
    candidates: list[ColorRegion] = []
    for color in palette:
        mask = color_mask(rgb, color, tolerance=3)
        if mask_limit is not None:
            mask &= mask_limit
        for component in _components(mask, min_area):
            left, top, box_width, box_height = component["bbox"]
            if box_width < 3 or box_height < 3:
                continue
            box_area = box_width * box_height
            rectangularity = min(1.0, float(component["area"]) / max(1, box_area))
            aspect_ratio = max(box_width, box_height) / max(1, min(box_width, box_height))
            if rectangularity < 0.42 or aspect_ratio > 12 or box_area >= width * height * 0.92:
                continue
            selected = mask[top : top + box_height, left : left + box_width]
            pixels = rgb[top : top + box_height, left : left + box_width][selected]
            if not len(pixels):
                continue
            representative = np.median(pixels, axis=0).astype(np.uint8)
            candidates.append(
                ColorRegion(
                    left=left,
                    top=top,
                    width=box_width,
                    height=box_height,
                    pixels=int(component["area"]),
                    color=hex_color(representative),
                    rectangularity=rectangularity,
                )
            )

    candidates.sort(key=lambda item: (item.pixels, item.rectangularity), reverse=True)
    unique: list[ColorRegion] = []
    for candidate in candidates:
        if any(_overlap_ratio(candidate, known) >= 0.82 for known in unique):
            continue
        unique.append(candidate)
    truncated = len(unique) > MAX_MEASUREMENT_OBSERVATIONS or len(palette) >= MAX_MEASUREMENT_OBSERVATIONS
    unique = unique[:MAX_MEASUREMENT_OBSERVATIONS]
    unique.sort(key=lambda item: (item.top, item.left, item.height, item.width))
    return unique, truncated


def _overlap_ratio(left: ColorRegion, right: ColorRegion) -> float:
    intersection = max(0, min(left.right, right.right) - max(left.left, right.left)) * max(
        0,
        min(left.bottom, right.bottom) - max(left.top, right.top),
    )
    smaller_area = min(left.width * left.height, right.width * right.height)
    return intersection / max(1, smaller_area)


def enclosing_plot_area(regions: list[ColorRegion], width: int, height: int) -> dict[str, int] | None:
    if not regions:
        return None
    left = max(0, min(item.left for item in regions))
    top = max(0, min(item.top for item in regions))
    right = min(width, max(item.right for item in regions))
    bottom = min(height, max(item.bottom for item in regions))
    return {"x": left, "y": top, "width": max(1, right - left), "height": max(1, bottom - top)}


def matched_label(region: ColorRegion, snippets: tuple[object, ...]) -> tuple[str | None, float | None]:
    """Return the clearest OCR label whose center is visibly inside a region."""
    candidates: list[tuple[float, float, str]] = []
    for snippet in snippets:
        bbox = getattr(snippet, "bbox_px", None)
        text = getattr(snippet, "text", None)
        confidence = getattr(snippet, "confidence", None)
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4 or not isinstance(text, str):
            continue
        x, y, box_width, box_height = bbox
        center_x, center_y = x + box_width / 2.0, y + box_height / 2.0
        if region.left <= center_x < region.right and region.top <= center_y < region.bottom:
            distance = ((center_x - region.center_x) ** 2 + (center_y - region.center_y) ** 2) ** 0.5
            candidates.append((distance, -float(confidence or 0.0), text[:160]))
    if not candidates:
        return None, None
    selected = min(candidates)
    return selected[2], max(0.0, min(1.0, -selected[1]))
