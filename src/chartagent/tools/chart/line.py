"""Deterministic line-series sensor for clean Cartesian charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from ..result import GeneratedImage, ToolResult
from ..tool import Tool
from .cartesian import (
    color_mask,
    confidence_map,
    default_plot_area,
    detect_color_palette,
    evidence_envelope,
    numeric_text,
    series_entry,
)
from .ocr import extract_text
from .overlays import render_line_overlay


def _numeric_ticks(
    snippets: list[dict[str, Any]],
    plot_area: list[int],
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    x, y, width, height = plot_area
    x_ticks: list[dict[str, float]] = []
    y_ticks: list[dict[str, float]] = []
    for snippet in snippets:
        value = numeric_text(str(snippet.get("text", "")))
        bbox = snippet.get("bbox")
        if value is None or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        left, top, box_width, box_height = map(float, bbox)
        center_x = left + box_width / 2
        center_y = top + box_height / 2
        if center_x < x + 8 and y <= center_y <= y + height:
            y_ticks.append({"pixel": center_y, "value": value})
        elif y + height - 4 <= center_y and x - 4 <= center_x <= x + width:
            x_ticks.append({"pixel": center_x, "value": value})
    return _unique_ticks(x_ticks), _unique_ticks(y_ticks)


def _unique_ticks(ticks: list[dict[str, float]]) -> list[dict[str, float]]:
    unique: dict[tuple[int, float], dict[str, float]] = {}
    for tick in ticks:
        unique[(round(tick["pixel"]), tick["value"])] = tick
    return sorted(unique.values(), key=lambda tick: tick["pixel"])


def _fit_ticks(ticks: list[dict[str, float]]) -> Callable[[float], float] | None:
    if len(ticks) < 2:
        return None
    pixels = np.asarray([tick["pixel"] for tick in ticks], dtype=float)
    values = np.asarray([tick["value"] for tick in ticks], dtype=float)
    if len(np.unique(pixels)) < 2:
        return None
    slope, intercept = np.polyfit(pixels, values, 1)
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None
    return lambda pixel: float(slope * pixel + intercept)


def _peak_positions(mask: np.ndarray, plot_area: list[int]) -> list[int]:
    x, y, width, height = plot_area
    cropped = mask[max(0, y) : y + height, max(0, x) : x + width]
    if not cropped.size:
        return []
    counts = cropped.sum(axis=0).astype(float)
    active = np.flatnonzero(counts > 0)
    if len(active) == 0:
        return []
    smooth = np.convolve(counts, np.ones(5) / 5.0, mode="same")
    threshold = max(3.0, float(np.percentile(counts[active], 72)))
    candidate = np.flatnonzero(
        (smooth >= threshold)
        & (smooth >= np.r_[smooth[0], smooth[:-1]])
        & (smooth >= np.r_[smooth[1:], smooth[-1]])
    )
    candidate = candidate[counts[candidate] > 0]
    # Clean generated charts use a marker at each x position. A larger
    # suppression window removes the many local maxima introduced by a sloped
    # anti-aliased line between two markers.
    min_distance = max(12, int(width * 0.12))
    positions: list[int] = []
    for local_x in candidate:
        absolute_x = max(0, x) + int(local_x)
        if not positions or absolute_x - positions[-1] >= min_distance:
            positions.append(absolute_x)
        elif counts[local_x] > counts[positions[-1] - max(0, x)]:
            positions[-1] = absolute_x
    first = max(0, x) + int(active[0])
    last = max(0, x) + int(active[-1])
    if not positions or first - positions[0] >= min_distance // 2:
        positions.insert(0, first)
    if positions[-1] - last < -min_distance // 2:
        positions.append(last)
    return sorted(set(positions))


def _point_rows(mask: np.ndarray, x: int, plot_area: list[int]) -> int | None:
    _, top, _, height = plot_area
    left = max(0, x - 4)
    right = min(mask.shape[1], x + 5)
    rows = np.flatnonzero(mask[top : top + height, left:right].any(axis=1))
    if len(rows) == 0:
        return None
    return top + int(round(float(np.median(rows))))


def _legend_entries(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    plot_area: list[int],
    snippets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    x, y, width, _ = plot_area
    entries: list[dict[str, Any]] = []
    for index, color in enumerate(palette, start=1):
        mask = color_mask(rgb, color, tolerance=28)
        yy, xx = np.indices(mask.shape)
        legend_pixels = np.argwhere(
            mask
            & (yy >= max(0, y - 4))
            & (yy < y + 100)
            & (xx > x + width * 0.05)
            & (xx < x + width * 0.45)
        )
        label: str | None = None
        if len(legend_pixels):
            center_y = float(np.median(legend_pixels[:, 0]))
            center_x = float(np.median(legend_pixels[:, 1]))
            candidates = []
            for snippet in snippets:
                bbox = snippet.get("bbox")
                text = str(snippet.get("text", "")).strip()
                if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                left, top, box_width, box_height = map(float, bbox)
                snippet_x = left + box_width / 2
                snippet_y = top + box_height / 2
                if snippet_x >= center_x and abs(snippet_y - center_y) <= 22:
                    candidates.append((snippet_x - center_x, text))
            if candidates:
                label = min(candidates, key=lambda item: item[0])[1]
        entries.append(series_entry(index, color, label))
    return entries


def _ocr_snippets(image_path: Path) -> list[dict[str, Any]]:
    result = extract_text(str(image_path))
    if isinstance(result, ToolResult) and isinstance(result.data, list):
        return [snippet for snippet in result.data if isinstance(snippet, dict)]
    return []


def extract_line_series(image_path: str) -> ToolResult | dict:
    """Extract colored line geometry and calibrated points from a chart image."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}
    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"extract_line_series failed for {image_path}: {exc}"}

    plot_area = default_plot_area(rgb)
    snippets = _ocr_snippets(path)
    x_ticks, y_ticks = _numeric_ticks(snippets, plot_area)
    x_fit = _fit_ticks(x_ticks)
    y_fit = _fit_ticks(y_ticks)
    palette = detect_color_palette(rgb, max_colors=8)
    legend = _legend_entries(rgb, palette, plot_area, snippets)
    series: list[dict[str, Any]] = []
    for index, color in enumerate(palette):
        mask = color_mask(rgb, color, tolerance=28)
        positions = _peak_positions(mask, plot_area)
        points: list[dict[str, Any]] = []
        for point_index, pixel_x in enumerate(positions, start=1):
            pixel_y = _point_rows(mask, pixel_x, plot_area)
            if pixel_y is None:
                continue
            point: dict[str, Any] = {
                "id": point_index,
                "x_px": int(pixel_x),
                "y_px": int(pixel_y),
            }
            if x_fit is not None and y_fit is not None:
                point["x"] = round(x_fit(pixel_x), 6)
                point["y"] = round(y_fit(pixel_y), 6)
            points.append(point)
        if points:
            entry = dict(legend[index]) if index < len(legend) else series_entry(index + 1, color)
            entry["points"] = points
            series.append(entry)

    warnings: list[str] = []
    if not x_fit:
        warnings.append("x-axis calibration unavailable; preserving pixel x coordinates")
    if not y_fit:
        warnings.append("y-axis calibration unavailable; preserving pixel y coordinates")
    if len(series) > 1 and not any(entry.get("label") for entry in series):
        warnings.append("series labels unresolved; using stable color-based identities")
    calibration_confidence = 0.92 if x_fit and y_fit else 0.25
    geometry_confidence = 0.9 if series else 0.0
    association_confidence = 0.85 if series and any(entry.get("label") for entry in series) else 0.62
    axes = {
        "x": {"label": None, "ticks": x_ticks, "calibrated": x_fit is not None},
        "y": {"label": None, "ticks": y_ticks, "calibrated": y_fit is not None},
    }
    confidence = confidence_map(
        overall=geometry_confidence * 0.55 + calibration_confidence * 0.3 + association_confidence * 0.15,
        geometry=geometry_confidence,
        calibration=calibration_confidence,
        association=association_confidence,
    )
    data = {
        **evidence_envelope(
            rgb,
            plot_area=plot_area,
            axes=axes,
            legend=[{key: value for key, value in entry.items() if key != "points"} for entry in legend],
            series=series,
            confidence=confidence,
        ),
        "series": series,
        "warnings": warnings,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_line_overlay(chart_image, plot_area=plot_area, series=series),
                "image/png",
                "Detected line series and point geometry",
            ),
        ),
        tuple(warnings),
    )


EXTRACT_LINE_SERIES = Tool(
    name="extract_line_series",
    description=(
        "Extract ordered points from clean single- or multi-series line "
        "charts, including pixel geometry, axis calibration, and series IDs."
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
    fn=extract_line_series,
)
