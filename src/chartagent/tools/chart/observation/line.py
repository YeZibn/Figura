"""Evidence-driven line-series sensor for clean Cartesian charts."""

from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

from ...core.definition import Tool
from ...core.result import GeneratedImage, ToolResult
from .cartesian import (
    apply_axis_transform as cartesian_apply_axis_transform,
    axis_output as cartesian_axis_output,
    color_mask,
    confidence_map,
    default_plot_area,
    detect_color_palette,
    evidence_envelope,
    fit_axis_transform as cartesian_fit_axis_transform,
    numeric_ticks as cartesian_numeric_ticks,
    numeric_text,
    rgb_to_hex,
    series_entry,
)
from .ocr import extract_text
from .overlays import render_line_overlay

_MAX_AXIS_SLOPE = 0.18
_AXIS_SLOPE_STEPS = 49
_DARK_PIXEL = 112
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


def _numeric_ticks(
    snippets: list[dict[str, Any]],
    plot_area: list[int],
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    """Classify numeric OCR snippets near the initial Cartesian frame.

    ``plot_area`` is intentionally only a search hint. The line sensor later
    projects the returned source-image points onto its inferred axis lines.
    The extra ``point_px`` field is ignored by the scatter sensor, which
    continues to consume the historical ``pixel`` field.
    """
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
        item = {
            "pixel": center_x,
            "value": value,
            "point_px": [center_x, center_y],
        }
        if center_x < x + 8 and y <= center_y <= y + height:
            y_item = dict(item)
            y_item["pixel"] = center_y
            y_ticks.append(y_item)
        elif y + height - 4 <= center_y and x - 4 <= center_x <= x + width:
            x_ticks.append(item)
    return _unique_ticks(x_ticks), _unique_ticks(y_ticks)


def _unique_ticks(ticks: list[dict[str, float]]) -> list[dict[str, float]]:
    unique: dict[tuple[int, float], dict[str, float]] = {}
    for tick in ticks:
        unique[(round(tick["pixel"]), tick["value"])] = tick
    return sorted(unique.values(), key=lambda tick: tick["pixel"])


def _fit_ticks(ticks: list[dict[str, float]]) -> Callable[[float], float] | None:
    """Keep the small compatibility helper used by the scatter sensor."""
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


def _axis_scalar(point: Sequence[float], axis_points: list[list[float]] | None) -> float:
    """Project a source-image point onto a fitted axis direction."""
    if not axis_points or len(axis_points) < 2:
        return float(point[0])
    origin = np.asarray(axis_points[0], dtype=float)
    direction = np.asarray(axis_points[1], dtype=float) - origin
    length = float(np.linalg.norm(direction))
    if length <= 1e-6:
        return float(point[0])
    return float(np.dot(np.asarray(point, dtype=float) - origin, direction / length))


def _fit_axis_transform(
    ticks: list[dict[str, float]],
    axis_points: list[list[float]] | None,
) -> dict[str, Any] | None:
    if len(ticks) < 2:
        return None
    pixels = np.asarray(
        [_axis_scalar(tick.get("point_px", [tick["pixel"], 0]), axis_points) for tick in ticks],
        dtype=float,
    )
    values = np.asarray([tick["value"] for tick in ticks], dtype=float)
    if len(np.unique(pixels)) < 2:
        return None
    slope, intercept = np.polyfit(pixels, values, 1)
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None
    residual = float(np.sqrt(np.mean((slope * pixels + intercept - values) ** 2)))
    value_span = max(1.0, float(np.ptp(values)))
    residual_limit = max(1.5, value_span * 0.08)
    calibrated = bool(residual <= residual_limit)
    confidence = min(1.0, len(ticks) / 4.0) * max(
        0.0,
        min(1.0, 1.0 - residual / max(residual_limit, 1e-6)),
    )
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "residual": round(residual, 4),
        "support": len(ticks),
        "confidence": round(confidence, 4),
        "calibrated": calibrated,
        "axis_points": axis_points,
    }


def _apply_axis_transform(model: dict[str, Any] | None, point: Sequence[float]) -> float | None:
    if not model or not model.get("calibrated"):
        return None
    scalar = _axis_scalar(point, model.get("axis_points"))
    return round(float(model["slope"] * scalar + model["intercept"]), 6)


def _dark_mask(rgb: np.ndarray) -> np.ndarray:
    return np.max(rgb, axis=2) <= _DARK_PIXEL


def _fit_dominant_axis_line(dark: np.ndarray, *, axis: str) -> dict[str, Any] | None:
    """Find a long near-horizontal or near-vertical dark line.

    This is a bounded Hough-like search implemented with NumPy. It favors long
    support spans, so chart axes win over short text strokes and labels.
    """
    height, width = dark.shape
    yy, xx = np.nonzero(dark)
    if axis == "x":
        keep = (
            (xx >= int(width * 0.08))
            & (xx <= int(width * 0.97))
            & (yy >= int(height * 0.52))
            & (yy <= int(height * 0.96))
        )
    else:
        keep = (
            (xx >= int(width * 0.04))
            & (xx <= int(width * 0.46))
            & (yy >= int(height * 0.06))
            & (yy <= int(height * 0.94))
        )
    xx, yy = xx[keep].astype(float), yy[keep].astype(float)
    if len(xx) < 20:
        return None

    best: dict[str, Any] | None = None
    slopes = np.linspace(-_MAX_AXIS_SLOPE, _MAX_AXIS_SLOPE, _AXIS_SLOPE_STEPS)
    for slope in slopes:
        coordinate = yy - slope * xx if axis == "x" else xx - slope * yy
        rounded = np.rint(coordinate).astype(int)
        minimum = int(rounded.min())
        counts = np.bincount(rounded - minimum)
        if len(counts) == 0:
            continue
        candidate_bins = np.argsort(counts)[-8:]
        for candidate_bin in candidate_bins:
            support_line = minimum + int(candidate_bin)
            inliers = np.abs(coordinate - support_line) <= 1.6
            support = int(inliers.sum())
            if support < 12:
                continue
            projected = xx[inliers] if axis == "x" else yy[inliers]
            span = float(np.ptp(projected)) if len(projected) else 0.0
            minimum_span = width * 0.38 if axis == "x" else height * 0.38
            if span < minimum_span:
                continue
            score = span + support * 0.35
            if best is not None and score <= best["score"]:
                continue
            if axis == "x":
                fit_slope, intercept = np.polyfit(xx[inliers], yy[inliers], 1)
                first = float(projected.min())
                last = float(projected.max())
                endpoints = [
                    [round(first, 2), round(fit_slope * first + intercept, 2)],
                    [round(last, 2), round(fit_slope * last + intercept, 2)],
                ]
                residual_values = yy[inliers] - (fit_slope * xx[inliers] + intercept)
            else:
                fit_slope, intercept = np.polyfit(yy[inliers], xx[inliers], 1)
                first = float(projected.min())
                last = float(projected.max())
                endpoints = [
                    [round(fit_slope * first + intercept, 2), round(first, 2)],
                    [round(fit_slope * last + intercept, 2), round(last, 2)],
                ]
                residual_values = xx[inliers] - (fit_slope * yy[inliers] + intercept)
            residual = float(np.sqrt(np.mean(residual_values**2)))
            best = {
                "points_px": endpoints,
                "slope": float(fit_slope),
                "intercept": float(intercept),
                "residual_px": round(residual, 4),
                "support": support,
                "score": score,
            }
    return best


def _bbox_from_points(points: list[Sequence[float]]) -> list[int] | None:
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    left = max(0, int(np.floor(min(xs))))
    top = max(0, int(np.floor(min(ys))))
    right = int(np.ceil(max(xs))) + 1
    bottom = int(np.ceil(max(ys))) + 1
    return [left, top, max(1, right - left), max(1, bottom - top)]


def _frame_from_evidence(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    search_area: list[int],
) -> tuple[dict[str, Any], str, list[np.ndarray]]:
    height, width = rgb.shape[:2]
    dark = _dark_mask(rgb)
    x_axis = _fit_dominant_axis_line(dark, axis="x")
    y_axis = _fit_dominant_axis_line(dark, axis="y")

    trace_points: list[list[float]] = []
    x, y, frame_width, frame_height = search_area
    for color in palette:
        mask = color_mask(rgb, color, tolerance=_TRACE_TOLERANCE)
        cropped = mask[max(0, y) : y + frame_height, max(0, x) : x + frame_width]
        for local_y, local_x in np.argwhere(cropped):
            trace_points.append([float(local_x + max(0, x)), float(local_y + max(0, y))])

    evidence_points = trace_points[:]
    for axis_line in (x_axis, y_axis):
        if axis_line:
            evidence_points.extend(axis_line["points_px"])
    bbox = _bbox_from_points(evidence_points) or list(search_area)
    left, top, box_width, box_height = bbox
    right = min(width, left + box_width)
    bottom = min(height, top + box_height)
    bbox = [left, top, max(1, right - left), max(1, bottom - top)]
    frame = {
        "bbox": bbox,
        "polygon_px": [
            [bbox[0], bbox[1]],
            [bbox[0] + bbox[2] - 1, bbox[1]],
            [bbox[0] + bbox[2] - 1, bbox[1] + bbox[3] - 1],
            [bbox[0], bbox[1] + bbox[3] - 1],
        ],
        "x_axis": {key: value for key, value in x_axis.items() if key != "score"}
        if x_axis
        else None,
        "y_axis": {key: value for key, value in y_axis.items() if key != "score"}
        if y_axis
        else None,
    }
    if x_axis is None and y_axis is None:
        orientation = "unknown"
    elif max(
        abs(float(x_axis["slope"])) if x_axis else 0.0,
        abs(float(y_axis["slope"])) if y_axis else 0.0,
    ) > 0.025:
        orientation = "oblique"
    else:
        orientation = "upright"
    return frame, orientation, palette


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


def _trace_vertices(mask: np.ndarray, plot_area: list[int]) -> tuple[list[list[int]], list[list[list[int]]]]:
    x, y, width, height = plot_area
    left = max(0, x)
    top = max(0, y)
    right = min(mask.shape[1], x + width)
    bottom = min(mask.shape[0], y + height)
    if right <= left or bottom <= top:
        return [], []
    points: list[list[int]] = []
    for pixel_x in range(left, right):
        rows = np.flatnonzero(mask[top:bottom, pixel_x])
        if len(rows):
            points.append([pixel_x, top + int(round(float(np.median(rows))))])
    fragments: list[list[list[int]]] = []
    current: list[list[int]] = []
    for point in points:
        if current and point[0] - current[-1][0] > 4:
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


def _marker_candidates(mask: np.ndarray, plot_area: list[int], trace_points: list[list[int]]) -> list[list[int]]:
    x, y, width, height = plot_area
    left = max(0, x)
    top = max(0, y)
    right = min(mask.shape[1], x + width)
    bottom = min(mask.shape[0], y + height)
    if right <= left or bottom <= top or not trace_points:
        return []
    counts = mask[top:bottom, left:right].sum(axis=0).astype(float)
    if not len(counts) or float(counts.max()) < 5.0:
        return []
    active = counts[counts > 0]
    baseline = float(np.median(active)) if len(active) else 0.0
    threshold = max(8.0, float(np.percentile(active, 85)))
    candidates: list[int] = []
    for index in range(2, len(counts) - 2):
        window = counts[index - 2 : index + 3]
        if counts[index] < threshold or counts[index] != max(window):
            continue
        if counts[index] - baseline < 4.0:
            continue
        if candidates and index - candidates[-1] < 16:
            if counts[index] > counts[candidates[-1]]:
                candidates[-1] = index
            continue
        candidates.append(index)

    result: list[list[int]] = []
    for local_x in candidates:
        pixel_x = left + local_x
        nearby = [point for point in trace_points if abs(point[0] - pixel_x) <= 5]
        if not nearby:
            continue
        pixel_y = int(round(float(np.median([point[1] for point in nearby]))))
        result.append([pixel_x, pixel_y])
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


def _point_records(
    *,
    trace_points: list[list[int]],
    mask: np.ndarray,
    plot_area: list[int],
    x_ticks: list[dict[str, float]],
    x_model: dict[str, Any] | None,
    y_model: dict[str, Any] | None,
    series_id: str,
) -> list[dict[str, Any]]:
    markers = _marker_candidates(mask, plot_area, trace_points)
    sources: list[tuple[list[int], str, float]] = [
        (point, "marker", 0.88) for point in markers
    ]
    if not sources:
        sources = [
            (point, "tick_sample", 0.72)
            for point in _anchor_points(trace_points, x_ticks)
        ]
    records: list[dict[str, Any]] = []
    for index, (point, source, confidence) in enumerate(sources, start=1):
        record: dict[str, Any] = {
            "id": f"{series_id}_point_{index}",
            "x_px": int(point[0]),
            "y_px": int(point[1]),
            "source": source,
            "confidence": confidence,
        }
        calibrated_x = cartesian_apply_axis_transform(x_model, point)
        calibrated_y = cartesian_apply_axis_transform(y_model, point)
        if calibrated_x is not None and calibrated_y is not None:
            record["x"] = calibrated_x
            record["y"] = calibrated_y
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


def _empty_result(image: Image.Image, warning: str) -> ToolResult:
    data = {
        "image_size": [image.width, image.height],
        "orientation": "unknown",
        "plot_area": None,
        "plot_frame": None,
        "axes": {
            "x": {"label": None, "ticks": [], "calibrated": False},
            "y": {"label": None, "ticks": [], "calibrated": False},
        },
        "legend": [],
        "series": [],
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
                render_line_overlay(image, plot_frame=None, axes=None, series=[], warnings=[warning]),
                "image/png",
                "No reliable line series detected",
            ),
        ),
        (warning,),
    )


def _axis_output(ticks: list[dict[str, float]], model: dict[str, Any] | None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "label": None,
        "ticks": [
            {
                "pixel": round(float(tick["pixel"]), 3),
                "value": round(float(tick["value"]), 6),
                "point_px": [
                    round(float(tick["point_px"][0]), 3),
                    round(float(tick["point_px"][1]), 3),
                ],
            }
            for tick in ticks
        ],
        "calibrated": bool(model and model.get("calibrated")),
    }
    if model:
        output["transform"] = {
            "slope": round(float(model["slope"]), 8),
            "intercept": round(float(model["intercept"]), 8),
            "residual": model["residual"],
            "support": model["support"],
            "confidence": model["confidence"],
        }
    return output


def extract_line_series(image_path: str) -> ToolResult | dict:
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
    frame, orientation, palette = _frame_from_evidence(rgb, preliminary_palette, search_area)
    plot_area = list(frame["bbox"])
    snippets = _ocr_snippets(path)
    x_ticks, y_ticks = cartesian_numeric_ticks(snippets, search_area)
    x_axis_points = frame.get("x_axis", {}).get("points_px") if frame.get("x_axis") else None
    y_axis_points = frame.get("y_axis", {}).get("points_px") if frame.get("y_axis") else None
    x_model = cartesian_fit_axis_transform(x_ticks, x_axis_points)
    y_model = cartesian_fit_axis_transform(y_ticks, y_axis_points)
    legend = _legend_entries(rgb, palette, plot_area, snippets)

    series: list[dict[str, Any]] = []
    filled_region_detected = False
    for index, color in enumerate(palette, start=1):
        mask = color_mask(rgb, color, tolerance=_TRACE_TOLERANCE)
        if _is_filled_region(mask, plot_area):
            filled_region_detected = True
            continue
        trace_points, fragments = _trace_vertices(mask, plot_area)
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
            x_model=x_model,
            y_model=y_model,
            series_id=series_id,
        )
        entry["trace"] = {
            "polyline_px": trace_points,
            "fragments": [{"polyline_px": fragment} for fragment in fragments],
        }
        entry["points"] = points
        entry["point_count"] = len(points)
        series.append(entry)

    warnings: list[str] = []
    if filled_region_detected:
        warnings.append("filled or bar-like color regions were excluded from line traces")
    if frame.get("x_axis") is None or frame.get("y_axis") is None:
        warnings.append("line chart frame or axes unresolved; preserving pixel geometry")
    if not x_model or not x_model.get("calibrated"):
        warnings.append("x-axis calibration unavailable; preserving pixel x coordinates")
    if not y_model or not y_model.get("calibrated"):
        warnings.append("y-axis calibration unavailable; preserving pixel y coordinates")
    if not x_ticks and series:
        warnings.append("x-axis anchors unavailable; confirmed sampling positions may be incomplete")
    if len(series) > 1 and not any(entry.get("label") for entry in series):
        warnings.append("series labels unresolved; using stable color-based identities")
    if len(series) > 1 and _traces_overlap(series):
        warnings.append("series traces cross or overlap; identity is retained by color evidence")
    if any(len(entry.get("trace", {}).get("fragments", [])) > 1 for entry in series):
        warnings.append("one or more series contain fragmented trace evidence")
    if not series:
        return _empty_result(chart_image, "no reliable line series detected")

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
    data = {
        **evidence_envelope(
            rgb,
            plot_area=plot_area,
            axes={
                "x": cartesian_axis_output(x_ticks, x_model),
                "y": cartesian_axis_output(y_ticks, y_model),
            },
            legend=[
                {key: value for key, value in entry.items() if key != "points"}
                for entry in legend
            ],
            series=series,
            confidence=confidence,
        ),
        "orientation": orientation,
        "plot_frame": frame,
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
            }
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=extract_line_series,
    group="chart-observation",
)


__all__ = ["EXTRACT_LINE_SERIES", "extract_line_series"]
