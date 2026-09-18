"""Evidence-driven scatter-point sensor for clean Cartesian charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...core.definition import Tool
from ...core.result import GeneratedImage, ToolResult
from .foundation import (
    build_common_evidence,
    color_mask,
    confidence_map,
    default_plot_area,
    detect_color_palette,
    image_size,
    numeric_ticks,
    rgb_to_hex,
    series_entry,
    stable_evidence_id,
)
from .coordinates import (
    apply_axis_transform,
    axis_output,
    detect_cartesian_frame,
    fit_axis_transform,
    inside_polygon,
)
from .ocr import extract_text
from .overlays import render_scatter_overlay
from .layout import context_for_evidence, context_scope, filter_snippets_to_scope

_COLOR_TOLERANCE = 34
_MAX_MARKER_SIDE_RATIO = 0.12
_MAX_MARKER_AREA_RATIO = 0.025
_MAX_ROTATION_SLOPE = 0.16


def _connected_components(mask: np.ndarray, *, min_area: int = 6) -> list[dict[str, Any]]:
    """Return bounded 8-connected components in source-image coordinates."""
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
        if area < min_area:
            continue
        box_width = right - left + 1
        box_height = bottom - top + 1
        components.append(
            {
                "area": area,
                "bbox": [left, top, box_width, box_height],
                "center": [
                    sum(pixel[1] for pixel in pixels) / area,
                    sum(pixel[0] for pixel in pixels) / area,
                ],
                "fill_ratio": area / max(1, box_width * box_height),
            }
        )
    return components


def _component_points(
    rgb: np.ndarray,
    color: np.ndarray,
    *,
    frame: dict[str, Any] | None,
    search_area: list[int],
) -> list[dict[str, Any]]:
    """Extract marker components, filtering legend/fill geometry by frame."""
    mask = color_mask(rgb, color, tolerance=_COLOR_TOLERANCE)
    components = _connected_components(mask)
    if not components:
        return []
    polygon = frame.get("polygon_px") if frame else None
    frame_bbox = frame.get("bbox") if frame else search_area
    _, _, frame_width, frame_height = map(int, frame_bbox)
    max_side = max(18.0, min(frame_width, frame_height) * _MAX_MARKER_SIDE_RATIO)
    max_area = max(250.0, frame_width * frame_height * _MAX_MARKER_AREA_RATIO)
    filtered: list[dict[str, Any]] = []
    for component in components:
        center = component["center"]
        left, top, box_width, box_height = component["bbox"]
        if not inside_polygon(center, polygon):
            continue
        if not (
            frame_bbox[0] - 3 <= center[0] <= frame_bbox[0] + frame_bbox[2] + 3
            and frame_bbox[1] - 3 <= center[1] <= frame_bbox[1] + frame_bbox[3] + 3
        ):
            continue
        if max(box_width, box_height) > max_side or component["area"] > max_area:
            continue
        component["geometry"] = {
            "center_px": [round(float(center[0]), 3), round(float(center[1]), 3)],
            "bbox_px": list(map(int, component["bbox"])),
        }
        component["appearance"] = {
            "area_px": int(component["area"]),
            "bbox": list(map(int, component["bbox"])),
            "radius_px": round(max(box_width, box_height) / 2.0, 2),
            "fill_ratio": round(float(component["fill_ratio"]), 4),
            "opacity": None,
        }
        filtered.append(component)
    if not filtered:
        return []
    median_area = float(np.median([item["area"] for item in filtered]))
    median_size = float(
        np.median([max(item["bbox"][2], item["bbox"][3]) for item in filtered])
    )
    for component in filtered:
        box_width, box_height = component["bbox"][2:]
        component["merged_candidate"] = bool(
            len(filtered) > 1
            and (
                component["area"] > median_area * 1.1
                or max(box_width, box_height) > median_size * 1.1
            )
        )
        component["occluded_candidate"] = bool(component["merged_candidate"])
        component["dense_candidate"] = False
    return filtered


def _legend_entries(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    frame: dict[str, Any] | None,
    snippets: list[dict[str, Any]],
    search_area: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Associate small color swatches outside the frame with nearby OCR."""
    polygon = frame.get("polygon_px") if frame else None
    entries: list[dict[str, Any]] = []
    for index, color in enumerate(palette, start=1):
        label: str | None = None
        best: tuple[float, float, str] | None = None
        for swatch in _connected_components(color_mask(rgb, color, tolerance=32), min_area=4):
            left, top, box_width, box_height = swatch["bbox"]
            if max(box_width, box_height) > 100 or swatch["area"] > 2500:
                continue
            if search_area is not None and not (
                left < search_area[0] + search_area[2]
                and left + box_width > search_area[0]
                and top < search_area[1] + search_area[3]
                and top + box_height > search_area[1]
            ):
                continue
            if inside_polygon(swatch["center"], polygon):
                continue
            swatch_right = left + box_width
            for snippet in snippets:
                bbox = snippet.get("bbox")
                text = str(snippet.get("text", "")).strip()
                if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                text_left, text_top, text_width, text_height = map(float, bbox)
                gap = text_left - swatch_right
                vertical_distance = abs(text_top + text_height / 2.0 - swatch["center"][1])
                if -4 <= gap <= 140 and vertical_distance <= 24:
                    candidate = (vertical_distance, max(0.0, gap), text)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
        if best is not None:
            label = best[2]
        entries.append(series_entry(index, color, label))
    return entries


def _outlier_candidates(points: list[dict[str, Any]]) -> None:
    """Mark strong spatial outliers but retain every visible point."""
    for point in points:
        point["outlier_candidate"] = False
    if len(points) < 4:
        return
    centers = np.asarray([point["center"] for point in points], dtype=float)
    flags = np.zeros(len(points), dtype=bool)
    for axis in range(2):
        values = centers[:, axis]
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        threshold = max(12.0, mad * 4.5, float(np.ptp(values)) * 0.34)
        flags |= np.abs(values - median) > threshold
    for point, flag in zip(points, flags):
        point["outlier_candidate"] = bool(flag)


def _mark_dense_candidates(points: list[dict[str, Any]]) -> None:
    if len(points) < 3:
        return
    centers = np.asarray([point["center"] for point in points], dtype=float)
    radii = np.asarray([point["appearance"]["radius_px"] for point in points], dtype=float)
    for index, point in enumerate(points):
        distances = np.sqrt(((centers - centers[index]) ** 2).sum(axis=1))
        close_count = int(
            np.sum((distances > 0) & (distances <= max(8.0, radii[index] * 3.0)))
        )
        point["dense_candidate"] = close_count >= 2


def _build_series(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    *,
    frame: dict[str, Any] | None,
    search_area: list[int],
    snippets: list[dict[str, Any]],
    x_model: dict[str, Any] | None,
    y_model: dict[str, Any] | None,
    legend_scope: list[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    legend = _legend_entries(
        rgb,
        palette,
        frame,
        snippets,
        legend_scope,
    )
    series: list[dict[str, Any]] = []
    warnings: list[str] = []
    for palette_index, color in enumerate(palette):
        components = _component_points(
            rgb,
            color,
            frame=frame,
            search_area=search_area,
        )
        if not components:
            continue
        _outlier_candidates(components)
        _mark_dense_candidates(components)
        source_entry = legend[palette_index] if palette_index < len(legend) else None
        entry = dict(source_entry or series_entry(palette_index + 1, color))
        entry["id"] = f"series_{palette_index + 1}"
        entry["color"] = rgb_to_hex(color)
        points: list[dict[str, Any]] = []
        for point_index, component in enumerate(
            sorted(components, key=lambda item: (item["center"][0], item["center"][1])),
            start=1,
        ):
            center_x, center_y = component["center"]
            point: dict[str, Any] = {
                "id": stable_evidence_id(f'{entry["id"]}_point', point_index),
                "series_id": entry["id"],
                "x_px": int(round(center_x)),
                "y_px": int(round(center_y)),
                "geometry": component["geometry"],
                "appearance": component["appearance"],
                "merged_candidate": bool(component["merged_candidate"]),
                "occluded_candidate": bool(component["occluded_candidate"]),
                "dense_candidate": bool(component["dense_candidate"]),
                "overlap_candidate": False,
                "outlier_candidate": bool(component["outlier_candidate"]),
                "evidence": {
                    "source": "colored_component",
                    "complete_visible_marker": not bool(component["merged_candidate"]),
                },
            }
            calibrated_x = apply_axis_transform(x_model, [center_x, center_y])
            calibrated_y = apply_axis_transform(y_model, [center_x, center_y])
            if calibrated_x is not None and calibrated_y is not None:
                point["x"] = calibrated_x
                point["y"] = calibrated_y
                point["calibration"] = "both_axes"
            else:
                point["calibration"] = "pixel_only"
            points.append(point)
        entry["points"] = points
        entry["point_count"] = len(points)
        entry["point_count_complete"] = not any(
            point["merged_candidate"] or point["occluded_candidate"] or point["dense_candidate"]
            for point in points
        )
        series.append(entry)
        if entry.get("label") is None:
            warnings.append(f'{entry["id"]} label unresolved; using color-based identity')
        if any(point["merged_candidate"] for point in points):
            warnings.append(f'{entry["id"]} contains a possible merged or oversized marker')
        if any(point["dense_candidate"] for point in points):
            warnings.append(f'{entry["id"]} contains a dense marker region')
        if any(point["outlier_candidate"] for point in points):
            warnings.append(f'{entry["id"]} contains a potential outlier')

    overlaps: list[dict[str, Any]] = []
    point_records = [(entry["id"], point) for entry in series for point in entry["points"]]
    for index, (first_series, first) in enumerate(point_records):
        for second_series, second in point_records[index + 1 :]:
            distance = float(
                np.hypot(
                    first["x_px"] - second["x_px"],
                    first["y_px"] - second["y_px"],
                )
            )
            radius_sum = float(first["appearance"]["radius_px"]) + float(
                second["appearance"]["radius_px"]
            )
            if distance <= max(2.0, radius_sum * 0.8):
                first["overlap_candidate"] = True
                second["overlap_candidate"] = True
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
    return series, overlaps, warnings, legend


def _empty_result(
    image: Image.Image,
    warning: str,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult:
    data = {
        "image_size": image_size(np.asarray(image.convert("RGB"))),
        "evidence": build_common_evidence(
            np.asarray(image.convert("RGB")),
            coordinate_system="cartesian_2d",
            frame=None,
            confidence=confidence_map(overall=0.0, geometry=0.0, calibration=0.0, association=0.0),
            warnings=[warning],
            layout_context=context_for_evidence(layout_context),
        ),
        "orientation": "unknown",
        "plot_frame": None,
        "axes": {
            "x": {"label": None, "ticks": [], "calibrated": False},
            "y": {"label": None, "ticks": [], "calibrated": False},
        },
        "legend": [],
        "series": [],
        "points": [],
        "overlaps": [],
        "confidence": confidence_map(overall=0.0, geometry=0.0, calibration=0.0, association=0.0),
        "warnings": [warning],
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_scatter_overlay(image, plot_area=None, series=[], warnings=[warning]),
                "image/png",
                "No reliable scatter evidence detected",
            ),
        ),
        (warning,),
    )


def _ocr_snippets(
    path: Path,
    scope: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = extract_text(str(path))
    if isinstance(result, ToolResult) and isinstance(result.data, list):
        snippets = [item for item in result.data if isinstance(item, dict)]
        return filter_snippets_to_scope(snippets, scope)
    return []


def _error(reason: str) -> dict[str, str]:
    return {"error": f"extract_scatter_points: {reason}"}


def extract_scatter_points(
    image_path: str,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult | dict:
    """Extract source-image marker evidence and optionally calibrated points."""
    path = Path(image_path)
    if not path.is_file():
        return _error("image could not be resolved")
    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return _error(f"input is not a readable image ({type(exc).__name__})")

    scope = context_scope(layout_context)
    search_area = scope.get("bbox_px") if scope else default_plot_area(rgb)
    palette = detect_color_palette(rgb, region=search_area, max_colors=8)
    snippets = _ocr_snippets(path, scope) if scope else _ocr_snippets(path)
    x_ticks, y_ticks = numeric_ticks(snippets, search_area)
    frame, orientation, detection_area = detect_cartesian_frame(
        rgb,
        search_area,
        palette,
        snippets,
        layout_context=layout_context,
        strict_search_area=scope is not None,
    )
    x_axis_points = frame.get("x_axis", {}).get("points_px") if frame and frame.get("x_axis") else None
    y_axis_points = frame.get("y_axis", {}).get("points_px") if frame and frame.get("y_axis") else None
    x_model = fit_axis_transform(x_ticks, x_axis_points) if x_axis_points else None
    y_model = fit_axis_transform(y_ticks, y_axis_points) if y_axis_points else None
    if not palette:
        return _empty_result(chart_image, "no reliable scatter point population detected", layout_context)

    series, overlaps, warnings, legend = _build_series(
        rgb,
        palette,
        frame=frame,
        search_area=detection_area,
        snippets=snippets,
        x_model=x_model,
        y_model=y_model,
        legend_scope=scope.get("bbox_px") if scope else None,
    )
    if not series:
        return _empty_result(chart_image, "no reliable scatter point population detected", layout_context)

    conflicts: list[dict[str, Any]] = []
    for axis_name, ticks, model in (("x", x_ticks, x_model), ("y", y_ticks, y_model)):
        if len(ticks) >= 2 and model is not None and not model.get("calibrated"):
            conflicts.append(
                {
                    "field": f"{axis_name}_axis_calibration",
                    "sources": ["ocr", "pixel_geometry"],
                    "message": f"OCR {axis_name}-axis tick candidates do not fit a reliable pixel calibration",
                }
            )
            warnings.append(f"OCR {axis_name}-axis tick candidates conflict with pixel calibration")
    if frame is None:
        warnings.append("scatter plot frame unresolved; preserving source pixel geometry")
    if isinstance(layout_context, dict):
        validation = layout_context.get("validation") if isinstance(layout_context.get("validation"), dict) else {}
        if validation.get("status") == "rejected":
            warnings.append("layout context rejected; using scatter pixel evidence fallback")
        elif validation.get("status") == "partial":
            warnings.append("layout context partially validated; scatter geometry remains partial")
    if orientation == "unknown":
        warnings.append("scatter orientation unresolved or unsupported")
    if x_model is None or not x_model.get("calibrated"):
        warnings.append("x-axis calibration unavailable; preserving pixel x coordinates")
    if y_model is None or not y_model.get("calibrated"):
        warnings.append("y-axis calibration unavailable; preserving pixel y coordinates")
    if len(series) > 1 and not any(entry.get("label") for entry in series):
        warnings.append("series labels unresolved; using stable color-based identities")
    if frame and frame.get("confidence", 0.0) < 0.5:
        warnings.append("scatter frame evidence is low confidence")

    points = [point for entry in series for point in entry["points"]]
    axis_confidences = [
        float(model["confidence"])
        for model in (x_model, y_model)
        if model and model.get("calibrated")
    ]
    calibration_confidence = float(np.mean(axis_confidences)) if axis_confidences else 0.25
    geometry_confidence = 0.9 if points else 0.0
    if frame is None:
        geometry_confidence *= 0.55
    elif frame.get("confidence", 0.0) < 0.5:
        geometry_confidence *= 0.75
    if overlaps:
        geometry_confidence *= 0.75
    association_confidence = 0.88 if all(entry.get("label") for entry in series) else 0.62
    frame_confidence = float(frame.get("confidence", 0.0)) if frame else 0.0
    confidence = confidence_map(
        overall=(
            geometry_confidence * 0.45
            + frame_confidence * 0.2
            + calibration_confidence * 0.25
            + association_confidence * 0.1
        ),
        geometry=geometry_confidence,
        calibration=calibration_confidence,
        association=association_confidence,
    )
    layout_evidence = context_for_evidence(layout_context)
    data = {
        "image_size": image_size(rgb),
        "evidence": build_common_evidence(
            rgb,
            coordinate_system="cartesian_2d",
            frame=frame,
            legend=legend,
            series=series,
            confidence=confidence,
            warnings=warnings,
            layout_context=layout_evidence,
            conflicts=conflicts,
        ),
        "orientation": orientation,
        "plot_frame": frame,
        "layout_context": layout_evidence,
        "axes": {
            "x": axis_output(x_ticks, x_model),
            "y": axis_output(y_ticks, y_model),
        },
        "legend": legend,
        "series": series,
        "points": points,
        "overlaps": overlaps,
        "ocr": snippets,
        "confidence": confidence,
        "warnings": warnings,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_scatter_overlay(
                    chart_image,
                    plot_frame=frame,
                    axes=data["axes"],
                    series=series,
                    warnings=warnings,
                ),
                "image/png",
                "Detected scatter frame, points, series, and calibration evidence",
            ),
        ),
        tuple(warnings),
    )


EXTRACT_SCATTER_POINTS = Tool(
    name="extract_scatter_points",
    description=(
        "Use for clean authorized two-dimensional scatter charts: extract "
        "source-image evidence, infer its frame and orientation, and return stable series "
        "and point IDs, marker geometry, optional evidence-backed x/y calibration, "
        "overlap/density/outlier evidence, confidence, warnings, and a source-sized "
        "overlay. Pixel-only points remain available when calibration is incomplete. "
        "Use it only with corroboration; do not use for strong perspective, 3D, dense unresolved, or non-scatter "
        "graphics as exact semantic truth."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local scatter-chart image.",
            },
            "layout_context": {
                "type": "object",
                "description": "Optional validated chart layout context; model hints remain advisory.",
                "additionalProperties": True,
            },
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=extract_scatter_points,
    group="chart-observation",
)


__all__ = ["EXTRACT_SCATTER_POINTS", "extract_scatter_points"]
