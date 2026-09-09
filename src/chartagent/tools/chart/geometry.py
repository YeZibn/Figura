"""Deterministic bar-geometry sensor for clean single-series charts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..result import GeneratedImage, ToolResult
from ..tool import Tool
from .overlays import render_bar_overlay


def _empty_result(chart_image: Image.Image) -> ToolResult:
    return ToolResult(
        {"bars": [], "baseline_y": None},
        (
            GeneratedImage(
                render_bar_overlay(chart_image, [], None),
                "image/png",
                "No bars or baseline detected",
            ),
        ),
    )


def _dominant_chart_color(rgb: np.ndarray) -> np.ndarray | None:
    flat = rgb.reshape(-1, 3).astype(np.int16)
    spread = flat.max(axis=1) - flat.min(axis=1)
    colored = flat[(spread >= 24) & (flat.max(axis=1) <= 245)]
    if len(colored) < 25:
        return None

    quantized = ((colored // 8) * 8).astype(np.uint8)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    return colors[int(np.argmax(counts))].astype(np.int16) + 4


def _contiguous_groups(indices: np.ndarray) -> list[tuple[int, int]]:
    if len(indices) == 0:
        return []
    breaks = np.where(np.diff(indices) > 1)[0]
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(indices) - 1]
    return [(int(indices[start]), int(indices[end])) for start, end in zip(starts, ends)]


def measure_bars(image_path: str) -> ToolResult | dict:
    """Detect bars and return measurements plus a model-readable overlay."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}

    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"measure_bars failed for {image_path}: {exc}"}

    dominant = _dominant_chart_color(rgb)
    if dominant is None:
        return _empty_result(chart_image)

    distance = np.max(np.abs(rgb.astype(np.int16) - dominant), axis=2)
    mask = distance <= 16
    min_column_pixels = max(4, int(rgb.shape[0] * 0.015))
    active_columns = np.flatnonzero(mask.sum(axis=0) >= min_column_pixels)
    min_bar_width = max(4, int(rgb.shape[1] * 0.01))

    candidates: list[dict] = []
    for left, right in _contiguous_groups(active_columns):
        width = right - left + 1
        if width < min_bar_width:
            continue
        region = mask[:, left : right + 1]
        active_rows = np.flatnonzero(region.sum(axis=1) >= max(2, int(width * 0.6)))
        if len(active_rows) == 0:
            continue
        top, bottom = int(active_rows[0]), int(active_rows[-1])
        height = bottom - top + 1
        if height < min_column_pixels:
            continue
        candidates.append(
            {
                "bbox": [left, top, width, height],
                "h_px": height,
                "_bottom": bottom,
            }
        )

    if not candidates:
        return _empty_result(chart_image)

    baseline = int(round(float(np.median([bar["_bottom"] for bar in candidates]))))
    aligned = [bar for bar in candidates if abs(bar["_bottom"] - baseline) <= 2]
    if not aligned:
        return _empty_result(chart_image)

    heights = [bar["h_px"] for bar in aligned]
    shortest = min(heights)
    bars = [
        {
            "id": index,
            "bbox": bar["bbox"],
            "h_px": bar["h_px"],
            "ratio": bar["h_px"] / shortest,
        }
        for index, bar in enumerate(aligned, start=1)
    ]
    data = {"bars": bars, "baseline_y": baseline}
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_bar_overlay(chart_image, bars, baseline),
                "image/png",
                "Detected bars with stable IDs, top edges, and baseline",
            ),
        ),
    )


MEASURE_BARS = Tool(
    name="measure_bars",
    description=(
        "Measure bars in a clean single-series bar chart, returning pixel "
        "bounds, heights, and ratios normalized to the shortest bar."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local chart image.",
            }
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=measure_bars,
)
