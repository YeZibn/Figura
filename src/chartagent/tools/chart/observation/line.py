"""Evidence-driven line-series sensor for clean Cartesian charts."""

from __future__ import annotations

import colorsys
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
    evidence_envelope,
    numeric_ticks,
    ordered_text_anchors,
    rgb_to_hex,
    series_entry,
)
from .coordinates import apply_axis_transform, axis_output, detect_cartesian_frame, fit_axis_transform
from .ocr import extract_text
from .overlays import render_line_overlay
from .layout import context_for_evidence, context_region

_TRACE_TOLERANCE = 30


def _line_palette(rgb: np.ndarray, region: list[int]) -> list[np.ndarray]:
    """Collapse anti-aliased shades while retaining distinct trace hues."""
    candidates = detect_color_palette(rgb, region=region, max_colors=8)
    selected: list[tuple[float, np.ndarray]] = []
    for candidate in candidates:
        red, green, blue = (float(value) / 255.0 for value in candidate[:3])
        hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
        match_index = next(
            (
                index
                for index, (existing_hue, _) in enumerate(selected)
                if min(abs(hue - existing_hue), 1.0 - abs(hue - existing_hue)) <= 0.045
            ),
            None,
        )
        if match_index is None:
            selected.append((hue, candidate))
        else:
            existing = selected[match_index][1]
            existing_saturation = colorsys.rgb_to_hsv(
                *(float(value) / 255.0 for value in existing[:3])
            )[1]
            if saturation > existing_saturation:
                selected[match_index] = (hue, candidate)
    return [color for _, color in selected]


def _components(mask: np.ndarray, *, min_area: int = 4) -> list[dict[str, Any]]:
    """Return small colored components for legend and marker evidence."""
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
            current_y, current_x = stack.pop()
            pixels.append((current_y, current_x))
            left = min(left, current_x)
            right = max(right, current_x)
            top = min(top, current_y)
            bottom = max(bottom, current_y)
            for next_y in range(current_y - 1, current_y + 2):
                for next_x in range(current_x - 1, current_x + 2):
                    if (
                        0 <= next_y < height
                        and 0 <= next_x < width
                        and mask[next_y, next_x]
                        and not visited[next_y, next_x]
                    ):
                        visited[next_y, next_x] = True
                        stack.append((next_y, next_x))
        if len(pixels) < min_area:
            continue
        area = len(pixels)
        components.append(
            {
                "area": area,
                "bbox": [left, top, right - left + 1, bottom - top + 1],
                "center": [
                    sum(pixel[1] for pixel in pixels) / area,
                    sum(pixel[0] for pixel in pixels) / area,
                ],
            }
        )
    return components


def _legend_entries(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    plot_area: list[int],
    snippets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Associate color swatches outside the plot frame with OCR labels."""
    x, y, width, height = plot_area
    right, bottom = x + width, y + height
    entries: list[dict[str, Any]] = []
    for index, color in enumerate(palette, start=1):
        mask = color_mask(rgb, color, tolerance=32)
        # Legend swatches can sit inside the broad proportional search hint
        # (for example, Matplotlib's upper-left legend).  Do not use that
        # hint as a hard exclusion boundary: associate small color components
        # with nearby OCR labels first, then keep trace extraction scoped to
        # the inferred frame.
        components = _components(mask, min_area=4)
        candidates = [
            component
            for component in components
            if max(component["bbox"][2:]) <= 100
            and component["area"] <= 2500
            and (
                component["center"][0] >= right - 2
                or component["center"][1] <= y + 6
                or component["center"][1] >= bottom - 6
                or component["bbox"][0] < x + max(32, int(width * 0.12))
            )
        ]
        label: str | None = None
        labeled_candidates: list[tuple[float, float, dict[str, Any], str]] = []
        for swatch in candidates:
            swatch_left, swatch_top, swatch_width, swatch_height = swatch["bbox"]
            swatch_right = swatch_left + swatch_width
            center_y = swatch["center"][1]
            for snippet in snippets:
                bbox = snippet.get("bbox")
                text = str(snippet.get("text", "")).strip()
                if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                left, top, box_width, box_height = map(float, bbox)
                snippet_y = top + box_height / 2
                gap = left - swatch_right
                if -2 <= gap <= 120 and abs(snippet_y - center_y) <= 24:
                    labeled_candidates.append((abs(snippet_y - center_y), gap, swatch, text))
        if labeled_candidates:
            _, _, swatch, label = min(
                labeled_candidates,
                key=lambda item: (item[0], item[1], -item[2]["area"]),
            )
        entries.append(series_entry(index, color, label))
    return entries


def _trace_vertices(
    mask: np.ndarray,
    plot_area: list[int],
    *,
    orientation: str = "upright",
) -> tuple[list[list[int]], list[list[list[int]]]]:
    x, y, width, height = plot_area
    left = max(0, x)
    top = max(0, y)
    right = min(mask.shape[1], x + width)
    bottom = min(mask.shape[0], y + height)
    if right <= left or bottom <= top:
        return [], []
    points: list[list[int]] = []
    if orientation == "horizontal":
        for pixel_y in range(top, bottom):
            columns = np.flatnonzero(mask[pixel_y, left:right])
            if len(columns):
                points.append([left + int(round(float(np.median(columns)))), pixel_y])
    else:
        for pixel_x in range(left, right):
            rows = np.flatnonzero(mask[top:bottom, pixel_x])
            if len(rows):
                points.append([pixel_x, top + int(round(float(np.median(rows))))])
    fragments: list[list[list[int]]] = []
    current: list[list[int]] = []
    coordinate_index = 1 if orientation == "horizontal" else 0
    for point in points:
        if current and point[coordinate_index] - current[-1][coordinate_index] > 4:
            if len(current) >= 2:
                fragments.append(current)
            current = []
        current.append(point)
    if len(current) >= 2:
        fragments.append(current)
    return points, fragments


def _is_filled_region(mask: np.ndarray, plot_area: list[int]) -> bool:
    """Reject solid bar/area fills that are not line traces."""
    x, y, width, height = plot_area
    left = max(0, x)
    top = max(0, y)
    right = min(mask.shape[1], x + width)
    bottom = min(mask.shape[0], y + height)
    if right <= left or bottom <= top:
        return False
    counts = mask[top:bottom, left:right].sum(axis=0).astype(float)
    active = counts[counts > 0]
    if len(active) < max(8, int(width * 0.04)):
        return False
    filled_columns = float(np.mean(active >= max(10.0, height * 0.04)))
    return float(np.median(active)) >= max(10.0, height * 0.08) or filled_columns >= 0.28


def _marker_candidates(
    mask: np.ndarray,
    plot_area: list[int],
    trace_points: list[list[int]],
    *,
    orientation: str = "upright",
) -> list[list[int]]:
    x, y, width, height = plot_area
    left = max(0, x)
    top = max(0, y)
    right = min(mask.shape[1], x + width)
    bottom = min(mask.shape[0], y + height)
    if right <= left or bottom <= top or not trace_points:
        return []
    horizontal = orientation == "horizontal"
    counts = mask[top:bottom, left:right].sum(axis=1 if horizontal else 0).astype(float)
    if not len(counts) or float(counts.max()) < 5.0:
        return []
    active = counts[counts > 0]
    baseline = float(np.median(active)) if len(active) else 0.0
    threshold = max(10.0, float(np.percentile(active, 92)), baseline * 2.0)
    candidates: list[int] = []
    for index in range(2, len(counts) - 2):
        window = counts[index - 2 : index + 3]
        if counts[index] < threshold or counts[index] != max(window):
            continue
        if counts[index] - baseline < 6.0:
            continue
        left_peak = index
        while left_peak > 0 and counts[left_peak - 1] >= threshold * 0.72:
            left_peak -= 1
        right_peak = index
        while right_peak + 1 < len(counts) and counts[right_peak + 1] >= threshold * 0.72:
            right_peak += 1
        if right_peak - left_peak + 1 > 13:
            continue
        if candidates and index - candidates[-1] < 16:
            if counts[index] > counts[candidates[-1]]:
                candidates[-1] = index
            continue
        candidates.append(index)

    result: list[list[int]] = []
    for local_x in candidates:
        coordinate = top + local_x if horizontal else left + local_x
        nearby = [
            point
            for point in trace_points
            if abs(point[1 if horizontal else 0] - coordinate) <= 5
        ]
        if not nearby:
            continue
        if horizontal:
            pixel_x = int(round(float(np.median([point[0] for point in nearby]))))
            result.append([pixel_x, coordinate])
        else:
            pixel_y = int(round(float(np.median([point[1] for point in nearby]))))
            result.append([coordinate, pixel_y])
    return result


def _anchor_points(trace_points: list[list[int]], x_ticks: list[dict[str, float]]) -> list[list[int]]:
    if len(x_ticks) < 2 or not trace_points:
        return []
    result: list[list[int]] = []
    trace_array = np.asarray(trace_points, dtype=float)
    for tick in x_ticks:
        point = tick.get("point_px")
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        pixel_x = int(round(float(point[0])))
        nearby = trace_array[np.abs(trace_array[:, 0] - pixel_x) <= 20]
        if len(nearby) == 0:
            continue
        pixel_y = int(round(float(np.median(nearby[:, 1]))))
        result.append([pixel_x, pixel_y])
    return result


def _anchor_records(
    trace_points: list[list[int]],
    anchors: list[dict[str, Any]],
    *,
    axis: str = "x",
) -> list[tuple[list[int], dict[str, Any]]]:
    """Project ordered date/category anchors onto a continuous trace."""
    if not anchors or not trace_points:
        return []
    trace_array = np.asarray(trace_points, dtype=float)
    result: list[tuple[list[int], dict[str, Any]]] = []
    for anchor in anchors:
        point = anchor.get("point_px")
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        coordinate_index = 1 if axis == "y" else 0
        coordinate = int(round(float(point[coordinate_index])))
        nearby = trace_array[np.abs(trace_array[:, coordinate_index] - coordinate) <= 20]
        if len(nearby) == 0:
            continue
        if coordinate_index == 1:
            pixel_x = int(round(float(np.median(nearby[:, 0]))))
            result.append(([pixel_x, coordinate], anchor))
        else:
            pixel_y = int(round(float(np.median(nearby[:, 1]))))
            result.append(([coordinate, pixel_y], anchor))
    return result


def _point_records(
    *,
    trace_points: list[list[int]],
    mask: np.ndarray,
    plot_area: list[int],
    x_ticks: list[dict[str, float]],
    x_anchors: list[dict[str, Any]],
    x_model: dict[str, Any] | None,
    y_model: dict[str, Any] | None,
    series_id: str,
    trace_axis: str = "x",
) -> list[dict[str, Any]]:
    markers = _marker_candidates(
        mask,
        plot_area,
        trace_points,
        orientation="horizontal" if trace_axis == "y" else "upright",
    )
    sources: list[tuple[list[int], str, float]] = [
        (point, "marker", 0.88) for point in markers
    ]
    anchor_metadata: dict[tuple[int, int], dict[str, Any]] = {}
    if not sources:
        anchored = _anchor_records(trace_points, x_anchors, axis=trace_axis)
        sources = [(point, "tick_sample", 0.72) for point, _ in anchored]
        anchor_metadata = {tuple(point): anchor for point, anchor in anchored}
    records: list[dict[str, Any]] = []
    for index, (point, source, confidence) in enumerate(sources, start=1):
        record: dict[str, Any] = {
            "id": f"{series_id}_point_{index}",
            "x_px": int(point[0]),
            "y_px": int(point[1]),
            "source": source,
            "confidence": confidence,
        }
        calibrated_x = apply_axis_transform(x_model, point)
        calibrated_y = apply_axis_transform(y_model, point)
        if calibrated_x is not None and calibrated_y is not None:
            record["x"] = calibrated_x
            record["y"] = calibrated_y
        anchor = anchor_metadata.get((int(point[0]), int(point[1])))
        if anchor is not None:
            record["x_label"] = anchor.get("text")
            record["x_order"] = anchor.get("order")
            record["x_anchor"] = anchor.get("point_px")
        records.append(record)
    return records


def _traces_overlap(series: list[dict[str, Any]], tolerance_px: float = 2.5) -> bool:
    """Detect source-pixel proximity between otherwise separate color traces."""
    traces: list[np.ndarray] = []
    for entry in series:
        points = entry.get("trace", {}).get("polyline_px") if isinstance(entry, dict) else None
        if isinstance(points, list) and points:
            traces.append(np.asarray(points, dtype=float))
    for index, first in enumerate(traces):
        if not len(first):
            continue
        sampled_first = first[:: max(1, len(first) // 240)]
        for second in traces[index + 1 :]:
            if not len(second):
                continue
            sampled_second = second[:: max(1, len(second) // 240)]
            distance = np.sqrt(
                ((sampled_first[:, None, :] - sampled_second[None, :, :]) ** 2).sum(axis=2)
            )
            if distance.size and float(distance.min()) <= tolerance_px:
                return True
    return False


def _empty_result(
    image: Image.Image,
    warning: str,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult:
    rgb = np.asarray(image.convert("RGB"))
    confidence = confidence_map(
        overall=0.0,
        geometry=0.0,
        calibration=0.0,
        association=0.0,
    )
    data = {
        "image_size": [image.width, image.height],
        "evidence": build_common_evidence(
            rgb,
            coordinate_system="cartesian_2d",
            frame=None,
            confidence=confidence,
            warnings=[warning],
            layout_context=context_for_evidence(layout_context),
        ),
        "orientation": "unknown",
        "plot_area": None,
        "plot_frame": None,
        "axes": {
            "x": {"label": None, "ticks": [], "calibrated": False},
            "y": {"label": None, "ticks": [], "calibrated": False},
        },
        "legend": [],
        "series": [],
        "confidence": confidence,
        "warnings": [warning],
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_line_overlay(image, plot_frame=None, axes=None, series=[], warnings=[warning]),
                "image/png",
                "No reliable line series detected",
            ),
        ),
        (warning,),
    )


def extract_line_series(
    image_path: str,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult | dict:
    """Extract source-image line traces and evidence-backed data points."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": "line image could not be resolved"}
    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"extract_line_series failed: {type(exc).__name__}"}

    search_area = default_plot_area(rgb)
    preliminary_palette = _line_palette(rgb, search_area)
    frame, orientation, detection_area = detect_cartesian_frame(
        rgb,
        search_area,
        preliminary_palette,
        layout_context=layout_context,
    )
    plot_area = list(frame.get("bbox") if frame else detection_area)
    if frame is None:
        frame = {
            "coordinate_system": "cartesian_2d",
            "bbox": plot_area,
            "bbox_px": plot_area,
            "polygon_px": [],
            "x_axis": None,
            "y_axis": None,
            "confidence": 0.0,
            "evidence": [],
        }
    palette = _line_palette(rgb, plot_area)
    snippets = _ocr_snippets(path)
    x_ticks, y_ticks = numeric_ticks(snippets, plot_area)
    x_tick_region = context_region(layout_context, "x_ticks")
    x_anchors = ordered_text_anchors(
        snippets,
        plot_area,
        region=x_tick_region.get("bbox_px") if x_tick_region else None,
        axis="y" if orientation == "horizontal" else "x",
    )
    trace_axis = "y" if orientation == "horizontal" else "x"
    x_axis_points = frame.get("x_axis", {}).get("points_px") if frame.get("x_axis") else None
    y_axis_points = frame.get("y_axis", {}).get("points_px") if frame.get("y_axis") else None
    x_model = fit_axis_transform(x_ticks, x_axis_points)
    y_model = fit_axis_transform(y_ticks, y_axis_points)
    legend = _legend_entries(rgb, palette, plot_area, snippets)

    series: list[dict[str, Any]] = []
    filled_region_detected = False
    for index, color in enumerate(palette, start=1):
        mask = color_mask(rgb, color, tolerance=_TRACE_TOLERANCE)
        if _is_filled_region(mask, plot_area):
            filled_region_detected = True
            continue
        trace_points, fragments = _trace_vertices(
            mask,
            plot_area,
            orientation="horizontal" if trace_axis == "y" else "upright",
        )
        if not trace_points:
            continue
        series_id = f"series_{index}"
        entry = dict(legend[index - 1]) if index - 1 < len(legend) else series_entry(index, color)
        entry["id"] = series_id
        entry["color"] = rgb_to_hex(color)
        points = _point_records(
            trace_points=trace_points,
            mask=mask,
            plot_area=plot_area,
            x_ticks=x_ticks,
            x_anchors=x_anchors,
            x_model=x_model,
            y_model=y_model,
            series_id=series_id,
            trace_axis=trace_axis,
        )
        entry["trace"] = {
            "polyline_px": trace_points,
            "fragments": [{"polyline_px": fragment} for fragment in fragments],
        }
        entry["points"] = points
        entry["point_count"] = len(points)
        series.append(entry)

    warnings: list[str] = []
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
    if isinstance(layout_context, dict):
        validation = layout_context.get("validation") if isinstance(layout_context.get("validation"), dict) else {}
        if validation.get("status") == "rejected":
            warnings.append("layout context rejected; using pixel evidence fallback")
        elif validation.get("status") == "partial":
            warnings.append("layout context partially validated; preserving uncertainty")
    if filled_region_detected:
        warnings.append("filled or bar-like color regions were excluded from line traces")
    if frame.get("x_axis") is None or frame.get("y_axis") is None:
        warnings.append("line chart frame or axes unresolved; preserving pixel geometry")
    if not x_model or not x_model.get("calibrated"):
        warnings.append("x-axis calibration unavailable; preserving pixel x coordinates")
    if not y_model or not y_model.get("calibrated"):
        warnings.append("y-axis calibration unavailable; preserving pixel y coordinates")
    if not x_ticks and not x_anchors and series:
        warnings.append("x-axis anchors unavailable; confirmed sampling positions may be incomplete")
    if len(series) > 1 and not any(entry.get("label") for entry in series):
        warnings.append("series labels unresolved; using stable color-based identities")
    if len(series) > 1 and _traces_overlap(series):
        warnings.append("series traces cross or overlap; identity is retained by color evidence")
    if any(len(entry.get("trace", {}).get("fragments", [])) > 1 for entry in series):
        warnings.append("one or more series contain fragmented trace evidence")
    if not series:
        return _empty_result(chart_image, "no reliable line series detected", layout_context)

    geometry_confidence = 0.9 if all(entry.get("trace", {}).get("polyline_px") for entry in series) else 0.35
    frame_confidence = 0.9 if frame.get("x_axis") and frame.get("y_axis") else 0.35
    calibration_values = [
        float(model["confidence"])
        for model in (x_model, y_model)
        if model and model.get("calibrated")
    ]
    calibration_confidence = float(np.mean(calibration_values)) if len(calibration_values) == 2 else 0.25
    association_confidence = 0.85 if any(entry.get("label") for entry in series) else 0.62
    if any(not entry.get("points") for entry in series):
        geometry_confidence *= 0.9
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
    x_axis_output = axis_output(x_ticks, x_model)
    x_axis_output["anchors"] = x_anchors
    layout_evidence = context_for_evidence(layout_context)
    data = {
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
        **evidence_envelope(
            rgb,
            plot_area=plot_area,
            axes={
                "x": x_axis_output,
                "y": axis_output(y_ticks, y_model),
            },
            legend=[
                {key: value for key, value in entry.items() if key != "points"}
                for entry in legend
            ],
            series=series,
            confidence=confidence,
            layout_context=layout_evidence,
        ),
        "orientation": orientation,
        "plot_frame": frame,
        "x_anchors": x_anchors,
        "layout_context": layout_evidence,
        "series": series,
        "warnings": warnings,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_line_overlay(
                    chart_image,
                    plot_frame=frame,
                    axes=data["axes"],
                    series=series,
                    warnings=warnings,
                ),
                "image/png",
                "Detected line traces, points, frame, and calibration evidence",
            ),
        ),
        tuple(warnings),
    )


def _ocr_snippets(image_path: Path) -> list[dict[str, Any]]:
    result = extract_text(str(image_path))
    if isinstance(result, ToolResult) and isinstance(result.data, list):
        return [snippet for snippet in result.data if isinstance(snippet, dict)]
    return []


EXTRACT_LINE_SERIES = Tool(
    name="extract_line_series",
    description=(
        "Use for clean two-dimensional line charts: extract source-image "
        "traces and evidence-backed points from an authorized "
        "single- or multi-series line chart. Return the inferred "
        "frame, axis calibration, stable series IDs, trace geometry, marker or "
        "tick-sampled points, confidence, warnings, and a source-sized overlay. "
        "The result keeps pixel evidence when semantic calibration is missing. "
        "Do not use for filled areas, strong perspective, 3D, or exact semantic "
        "values when axes or sampling anchors cannot be calibrated; do not "
        "use it for unsupported geometry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local chart image.",
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
    fn=extract_line_series,
    group="chart-observation",
)


__all__ = ["EXTRACT_LINE_SERIES", "extract_line_series"]
