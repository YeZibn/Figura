"""Deterministic bar-geometry sensor for clean Cartesian charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...core.result import GeneratedImage, ToolResult
from ...core.definition import Tool
from .cartesian import (
    cluster_centers,
    color_mask,
    confidence_map,
    default_plot_area,
    detect_color_palette,
    evidence_envelope,
    series_entry,
)
from .overlays import render_bar_overlay


def _empty_result(chart_image: Image.Image) -> ToolResult:
    rgb = np.asarray(chart_image)
    data = {
        "bars": [],
        "baseline_y": None,
        **evidence_envelope(
            rgb,
            plot_area=None,
            confidence=confidence_map(
                overall=0.0,
                geometry=0.0,
                calibration=0.0,
                association=0.0,
            ),
        ),
        "warnings": ["no bar geometry or baseline detected"],
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_bar_overlay(chart_image, [], None),
                "image/png",
                "No bars or baseline detected",
            ),
        ),
        ("no bar geometry or baseline detected",),
    )


def _dominant_chart_color(rgb: np.ndarray) -> np.ndarray | None:
    """Keep the old helper available for callers that imported it directly."""
    palette = detect_color_palette(rgb, max_colors=1)
    return palette[0] if palette else None


def _contiguous_groups(indices: np.ndarray) -> list[tuple[int, int]]:
    if len(indices) == 0:
        return []
    breaks = np.where(np.diff(indices) > 1)[0]
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(indices) - 1]
    return [(int(indices[start]), int(indices[end])) for start, end in zip(starts, ends)]


def _bar_candidates(
    rgb: np.ndarray,
    color: np.ndarray,
    series_index: int,
    plot_area: list[int],
) -> list[dict[str, Any]]:
    mask = color_mask(rgb, color, tolerance=28)
    x, y, width, height = plot_area
    left = max(0, x)
    top = max(0, y)
    right = min(rgb.shape[1], x + width)
    bottom = min(rgb.shape[0], y + height)
    plot_mask = mask[top:bottom, left:right]
    if not plot_mask.size:
        return []

    min_column_pixels = max(4, int(rgb.shape[0] * 0.012))
    active_columns = np.flatnonzero(plot_mask.sum(axis=0) >= min_column_pixels)
    min_bar_width = max(4, int(rgb.shape[1] * 0.008))
    candidates: list[dict[str, Any]] = []
    for local_left, local_right in _contiguous_groups(active_columns):
        width_px = local_right - local_left + 1
        if width_px < min_bar_width:
            continue
        region = plot_mask[:, local_left : local_right + 1]
        active_rows = np.flatnonzero(
            region.sum(axis=1) >= max(2, int(width_px * 0.45))
        )
        if len(active_rows) == 0:
            continue
        local_top, local_bottom = int(active_rows[0]), int(active_rows[-1])
        height_px = local_bottom - local_top + 1
        if height_px < min_column_pixels:
            continue
        absolute_left = left + local_left
        absolute_top = top + local_top
        candidates.append(
            {
                "bbox": [absolute_left, absolute_top, width_px, height_px],
                "h_px": height_px,
                "_bottom": top + local_bottom,
                "_top": absolute_top,
                "_center_x": absolute_left + width_px / 2,
                "_series_index": series_index,
            }
        )
    return candidates


def _has_horizontal_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_left, _, first_width, _ = first["bbox"]
    second_left, _, second_width, _ = second["bbox"]
    overlap = min(first_left + first_width, second_left + second_width) - max(
        first_left, second_left
    )
    return overlap >= 0.5 * min(first_width, second_width)


def _assign_categories(candidates: list[dict[str, Any]], stacked: bool) -> None:
    centers = [candidate["_center_x"] for candidate in candidates]
    if not centers:
        return
    if stacked:
        category_centers = cluster_centers(centers, gap=12.0)
    elif len({candidate["_series_index"] for candidate in candidates}) > 1:
        category_centers = cluster_centers(centers)
    else:
        category_centers = sorted(centers)
    for candidate in candidates:
        candidate["category_index"] = min(
            range(len(category_centers)),
            key=lambda index: abs(category_centers[index] - candidate["_center_x"]),
        ) + 1


def _stack_totals(candidates: list[dict[str, Any]]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for category_index in sorted({candidate["category_index"] for candidate in candidates}):
        members = [
            candidate
            for candidate in candidates
            if candidate["category_index"] == category_index
        ]
        if members:
            totals[category_index] = max(candidate["_bottom"] for candidate in members) - min(
                candidate["_top"] for candidate in members
            ) + 1
    return totals


def _measure_chart(rgb: np.ndarray) -> tuple[list[dict[str, Any]], int | None, bool, list[np.ndarray]]:
    plot_area = default_plot_area(rgb)
    palette = detect_color_palette(rgb, max_colors=8)
    candidates: list[dict[str, Any]] = []
    for series_index, color in enumerate(palette, start=1):
        candidates.extend(_bar_candidates(rgb, color, series_index, plot_area))
    if not candidates:
        return [], None, False, palette

    stacked = any(
        first["_series_index"] != second["_series_index"]
        and _has_horizontal_overlap(first, second)
        for position, first in enumerate(candidates)
        for second in candidates[position + 1 :]
    )
    baseline = int(round(float(max(candidate["_bottom"] for candidate in candidates))))
    if not stacked:
        aligned = [candidate for candidate in candidates if abs(candidate["_bottom"] - baseline) <= 3]
        if aligned:
            candidates = aligned
        baseline = int(round(float(np.median([candidate["_bottom"] for candidate in candidates]))))
    _assign_categories(candidates, stacked)
    candidates.sort(key=lambda candidate: (candidate["_center_x"], candidate["_top"]))
    return candidates, baseline, stacked, palette


def measure_bars(image_path: str) -> ToolResult | dict:
    """Detect single, grouped, and clean stacked bars with visual evidence."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}

    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"measure_bars failed for {image_path}: {exc}"}

    candidates, baseline, stacked, palette = _measure_chart(rgb)
    if not candidates or baseline is None:
        return _empty_result(chart_image)

    shortest = min(candidate["h_px"] for candidate in candidates)
    stack_totals = _stack_totals(candidates) if stacked else {}
    palette_map = {index: color for index, color in enumerate(palette, start=1)}
    series = [
        series_entry(index, palette_map[index])
        for index in sorted({candidate["_series_index"] for candidate in candidates})
        if index in palette_map
    ]
    bars: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        series_id = f"series_{candidate['_series_index']}"
        bar = {
            "id": index,
            "bbox": candidate["bbox"],
            "h_px": candidate["h_px"],
            "ratio": candidate["h_px"] / shortest,
            "category_index": candidate["category_index"],
            "series": series_id,
        }
        if stacked:
            bar["stack_total_h_px"] = stack_totals[candidate["category_index"]]
        bars.append(bar)

    warnings: list[str] = []
    if len(series) > 1:
        warnings.append("series labels unresolved; using stable color-based identities")
    data = {
        "bars": bars,
        "baseline_y": baseline,
        "stacked": stacked,
        **evidence_envelope(
            rgb,
            plot_area=default_plot_area(rgb),
            axes=None,
            legend=series,
            series=series,
            confidence=confidence_map(
                overall=0.86 if not warnings else 0.72,
                geometry=0.92,
                calibration=0.0,
                association=0.82 if len(series) == 1 else 0.62,
            ),
        ),
        "warnings": warnings,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_bar_overlay(chart_image, bars, baseline),
                "image/png",
                "Detected bars with stable IDs, series identities, and baseline",
            ),
        ),
        tuple(warnings),
    )


MEASURE_BARS = Tool(
    name="measure_bars",
    description=(
        "Measure single-series, grouped, or clean stacked bars in an authorized "
        "chart image and return bar IDs, pixel bounds, heights, category and series "
        "evidence, normalized ratios, confidence, warnings, and an overlay. Use "
        "when bar geometry or relative magnitudes are required; do not use it for "
        "non-bar charts, 3D or heavily occluded bars, or as proof of exact source "
        "values without axis calibration. Colors and stable geometry can identify "
        "series, but labels and numeric values may remain unresolved."
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
    group="chart-observation",
)


__all__ = ["MEASURE_BARS", "measure_bars"]
