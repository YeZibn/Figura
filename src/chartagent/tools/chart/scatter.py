"""Deterministic scatter-point sensor for clean Cartesian charts."""

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
    rgb_to_hex,
    series_entry,
)
from .line import _fit_ticks, _legend_entries, _numeric_ticks
from .ocr import extract_text
from .overlays import render_scatter_overlay

_COLOR_TOLERANCE = 34


def _connected_components(
    mask: np.ndarray,
    *,
    offset_x: int = 0,
    offset_y: int = 0,
    min_area: int = 6,
) -> list[dict[str, Any]]:
    """Return bounded 8-connected colored components with marker evidence."""
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, Any]] = []
    for start_y, start_x in np.argwhere(mask):
        start_y, start_x = int(start_y), int(start_x)
        if visited[start_y, start_x]:
            continue
        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        pixels: list[tuple[int, int]] = []
        left = right = start_x
        top = bottom = start_y
        while stack:
            y, x = stack.pop()
            pixels.append((y, x))
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for next_y in range(y - 1, y + 2):
                for next_x in range(x - 1, x + 2):
                    if (
                        0 <= next_y < height
                        and 0 <= next_x < width
                        and mask[next_y, next_x]
                        and not visited[next_y, next_x]
                    ):
                        visited[next_y, next_x] = True
                        stack.append((next_y, next_x))
        area = len(pixels)
        box_width = right - left + 1
        box_height = bottom - top + 1
        if area < min_area:
            continue
        center_x = sum(x for _, x in pixels) / area + offset_x
        center_y = sum(y for y, _ in pixels) / area + offset_y
        components.append(
            {
                "area": area,
                "bbox": [left + offset_x, top + offset_y, box_width, box_height],
                "center": [center_x, center_y],
                "fill_ratio": area / max(1, box_width * box_height),
            }
        )
    return components


def _component_points(
    rgb: np.ndarray,
    color: np.ndarray,
    plot_area: list[int],
) -> list[dict[str, Any]]:
    x, y, width, height = plot_area
    mask = color_mask(rgb, color, tolerance=_COLOR_TOLERANCE)
    left = max(0, x)
    top = max(0, y)
    right = min(rgb.shape[1], x + width)
    bottom = min(rgb.shape[0], y + height)
    cropped = mask[top:bottom, left:right]
    if not cropped.size:
        return []

    minimum_area = max(6, int(rgb.shape[0] * rgb.shape[1] * 0.000015))
    components = _connected_components(
        cropped,
        offset_x=left,
        offset_y=top,
        min_area=minimum_area,
    )
    if not components:
        return []

    median_area = float(np.median([item["area"] for item in components]))
    median_size = float(
        np.median([max(item["bbox"][2], item["bbox"][3]) for item in components])
    )
    for component in components:
        _, _, box_width, box_height = component["bbox"]
        largest_side = max(box_width, box_height)
        component["merged_candidate"] = bool(
            len(components) > 1
            and (
                component["area"] > median_area * 1.15
                or largest_side > median_size * 1.15
            )
        )
        component["appearance"] = {
            "area_px": int(component["area"]),
            "bbox": list(map(int, component["bbox"])),
            "radius_px": round(max(box_width, box_height) / 2.0, 2),
            "fill_ratio": round(float(component["fill_ratio"]), 4),
            "opacity": None,
        }
    return components


def _ocr_snippets(path: Path) -> list[dict[str, Any]]:
    result = extract_text(str(path))
    if isinstance(result, ToolResult) and isinstance(result.data, list):
        return [item for item in result.data if isinstance(item, dict)]
    return []


def _outlier_candidates(points: list[dict[str, Any]]) -> None:
    """Mark only strong spatial outliers, retaining every point."""
    if len(points) < 4:
        return
    centers = np.asarray([point["center"] for point in points], dtype=float)
    outlier_flags = np.zeros(len(points), dtype=bool)
    for axis in range(2):
        values = centers[:, axis]
        median = float(np.median(values))
        deviations = np.abs(values - median)
        median_deviation = float(np.median(deviations))
        deviation_mad = float(np.median(np.abs(deviations - median_deviation)))
        spread = max(median_deviation * 0.75, deviation_mad, 3.0)
        threshold = median_deviation + 4.0 * spread
        outlier_flags |= deviations > threshold
    for point, is_outlier in zip(points, outlier_flags):
        point["outlier_candidate"] = bool(is_outlier)


def _build_series(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    plot_area: list[int],
    snippets: list[dict[str, Any]],
    x_fit: Callable[[float], float] | None,
    y_fit: Callable[[float], float] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    legend = _legend_entries(rgb, palette, plot_area, snippets)
    series: list[dict[str, Any]] = []
    warnings: list[str] = []
    for palette_index, color in enumerate(palette):
        components = _component_points(rgb, color, plot_area)
        if not components:
            continue
        _outlier_candidates(components)
        source_entry = legend[palette_index] if palette_index < len(legend) else None
        entry = dict(source_entry or series_entry(palette_index + 1, color))
        entry["id"] = f"series_{palette_index + 1}"
        entry["color"] = rgb_to_hex(color)
        points: list[dict[str, Any]] = []
        for component in sorted(
            components,
            key=lambda item: (item["center"][0], item["center"][1]),
        ):
            point_index = len(points) + 1
            center_x, center_y = component["center"]
            point: dict[str, Any] = {
                "id": f'{entry["id"]}_point_{point_index}',
                "x_px": int(round(center_x)),
                "y_px": int(round(center_y)),
                "bbox": component["bbox"],
                "appearance": component["appearance"],
                "merged_candidate": bool(component["merged_candidate"]),
                "outlier_candidate": bool(component.get("outlier_candidate", False)),
            }
            if x_fit is not None and y_fit is not None:
                point["x"] = round(x_fit(center_x), 6)
                point["y"] = round(y_fit(center_y), 6)
            points.append(point)
        entry["points"] = points
        entry["point_count"] = len(points)
        series.append(entry)

        if entry.get("label") is None:
            warnings.append(f'{entry["id"]} label unresolved; using color-based identity')
        if any(point["merged_candidate"] for point in points):
            warnings.append(f'{entry["id"]} contains a possible merged or oversized marker')
        if any(point["outlier_candidate"] for point in points):
            warnings.append(f'{entry["id"]} contains a potential outlier')

    overlaps: list[dict[str, Any]] = []
    point_records = [
        (entry["id"], point)
        for entry in series
        for point in entry["points"]
    ]
    for index, (first_series, first) in enumerate(point_records):
        for second_series, second in point_records[index + 1 :]:
            distance = float(
                np.hypot(
                    first["x_px"] - second["x_px"],
                    first["y_px"] - second["y_px"],
                )
            )
            radius = max(
                float(first["appearance"]["radius_px"]),
                float(second["appearance"]["radius_px"]),
            )
            if distance <= max(2.0, radius * 1.25):
                overlaps.append(
                    {
                        "point_ids": [first["id"], second["id"]],
                        "series_ids": [first_series, second_series],
                        "distance_px": round(distance, 2),
                        "uncertain": True,
                    }
                )
    if overlaps:
        warnings.append("nearby markers may overlap and have an uncertain count")
    return series, overlaps, warnings


def _empty_result(image: Image.Image, warning: str) -> ToolResult:
    data = {
        "image_size": [image.width, image.height],
        "plot_area": None,
        "axes": {
            "x": {"label": None, "ticks": [], "calibrated": False},
            "y": {"label": None, "ticks": [], "calibrated": False},
        },
        "legend": [],
        "series": [],
        "points": [],
        "overlaps": [],
        "confidence": confidence_map(
            overall=0.0,
            geometry=0.0,
            calibration=0.0,
            association=0.0,
        ),
        "warnings": [warning],
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_scatter_overlay(image, None, []),
                "image/png",
                "No reliable scatter evidence detected",
            ),
        ),
        (warning,),
    )


def extract_scatter_points(image_path: str) -> ToolResult | dict:
    """Extract colored marker geometry and calibrated points from a scatter chart."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}
    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"extract_scatter_points failed for {image_path}: {exc}"}

    plot_area = default_plot_area(rgb)
    snippets = _ocr_snippets(path)
    x_ticks, y_ticks = _numeric_ticks(snippets, plot_area)
    x_fit = _fit_ticks(x_ticks)
    y_fit = _fit_ticks(y_ticks)
    palette = detect_color_palette(rgb, region=plot_area, max_colors=8)
    if not palette:
        return _empty_result(chart_image, "no reliable scatter point population detected")

    series, overlaps, warnings = _build_series(
        rgb,
        palette,
        plot_area,
        snippets,
        x_fit,
        y_fit,
    )
    if not series:
        return _empty_result(chart_image, "no reliable scatter point population detected")

    if x_fit is None:
        warnings.append("x-axis calibration unavailable; preserving pixel x coordinates")
    if y_fit is None:
        warnings.append("y-axis calibration unavailable; preserving pixel y coordinates")
    if len(series) > 1 and not any(entry.get("label") for entry in series):
        warnings.append("series labels unresolved; using stable color-based identities")

    points = [point for entry in series for point in entry["points"]]
    calibration_confidence = (
        0.94 if x_fit and y_fit else 0.25 if not x_fit and not y_fit else 0.55
    )
    geometry_confidence = 0.9 if points else 0.0
    association_confidence = 0.88 if all(entry.get("label") for entry in series) else 0.62
    if overlaps:
        geometry_confidence *= 0.75
    data = {
        **evidence_envelope(
            rgb,
            plot_area=plot_area,
            axes={
                "x": {
                    "label": None,
                    "ticks": x_ticks,
                    "calibrated": x_fit is not None,
                },
                "y": {
                    "label": None,
                    "ticks": y_ticks,
                    "calibrated": y_fit is not None,
                },
            },
            legend=[
                entry
                for entry in _legend_entries(rgb, palette, plot_area, snippets)
                if entry.get("label") or entry.get("color")
            ],
            series=series,
            confidence=confidence_map(
                overall=(
                    geometry_confidence * 0.55
                    + calibration_confidence * 0.3
                    + association_confidence * 0.15
                ),
                geometry=geometry_confidence,
                calibration=calibration_confidence,
                association=association_confidence,
            ),
        ),
        "points": points,
        "overlaps": overlaps,
        "ocr": snippets,
        "warnings": warnings,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_scatter_overlay(chart_image, plot_area, series),
                "image/png",
                "Detected scatter points, series, and calibration evidence",
            ),
        ),
        tuple(warnings),
    )


EXTRACT_SCATTER_POINTS = Tool(
    name="extract_scatter_points",
    description=(
        "Extract points from a clean authorized two-dimensional scatter chart and "
        "return series colors and IDs, pixel geometry, optional axis calibration, "
        "overlap evidence, confidence, warnings, and an overlay. Use when plotted "
        "markers and trends are needed; do not use for dense, overlapping, 3D, or "
        "non-scatter graphics, or as exact numeric truth when axes are not "
        "calibrated. Treat missed overlaps, unresolved series labels, and pixel-only "
        "coordinates as limitations requiring corroboration."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local scatter-chart image.",
            }
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=extract_scatter_points,
    group="chart-observation",
)
