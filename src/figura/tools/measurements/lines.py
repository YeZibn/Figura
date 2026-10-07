"""Pixel traces and calibrated point observations for Cartesian line charts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import hypot
from typing import Any

import numpy as np

from .cartesian import (
    associate_legend_labels,
    calibrated_axis_value,
    observe_cartesian_axes,
)
from .colors import color_mask, hex_color, series_palette
from .ocr import OCRSnippet, recognize_text


def measure_line_pixels(rgb: np.ndarray, observation_mask: np.ndarray | None = None) -> dict[str, Any]:
    """Measure an already decoded, scope-masked RGB source without shifting its coordinates."""
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, observation_mask) if observation_mask is not None else recognize_text(rgb)
    axes = observe_cartesian_axes(rgb, ocr.snippets, None)
    bounds = _plot_bounds(axes, width, height)
    left, top, right, bottom = bounds
    crop = rgb[top:bottom, left:right]
    palette = series_palette(crop)
    from .layout import legend_regions, exclude_legend
    legend_bounds = legend_regions(rgb, ocr.snippets, palette)
    legend_labels = associate_legend_labels(rgb, ocr.snippets, palette)
    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; axis and legend associations may be incomplete")
    series: list[dict[str, Any]] = []
    trace_count = 0
    geometry_confidences: list[float] = []
    masks = [
        exclude_legend(color_mask(crop, color, palette=palette), legend_bounds, (left, top))
        for color in palette
    ]
    if observation_mask is not None:
        for mask in masks:
            mask &= observation_mask[top:bottom, left:right]
    markers_by_series = [_marker_centers(mask, left, top) for mask in masks]
    for index, (color, mask, markers) in enumerate(zip(palette, masks, markers_by_series, strict=True), start=1):
        traces = _trace_fragments(mask, left, top)
        if not traces:
            continue
        trace_count += len(traces)
        if len(traces) > 1:
            warnings.append(f"series_{index} contains {len(traces)} disconnected trace fragments")
        other_markers = [
            marker
            for other_index, other_series in enumerate(markers_by_series)
            if other_index != index - 1
            for marker in other_series
        ]
        points = _line_points(traces, axes, markers, other_markers, mask, left, top)
        geometry_confidences.append(min(1.0, sum(len(fragment) for fragment in traces) / max(10.0, (right - left) * 0.25)))
        color_hex = hex_color(color)
        label, label_confidence = legend_labels.get(color_hex, (None, None))
        series.append({
            "id": f"series_{index}",
            "color": color_hex,
            "label": label,
            "label_confidence": label_confidence,
            "trace": [fragment for fragment in traces],
            "points": points,
        })

    calibration_confidence = _calibration_confidence(axes)
    if not series:
        status = "no_evidence"
        warnings.append("no line traces were detected")
    else:
        status = "measured" if _axes_usable(axes) else "partial"
        if status == "partial":
            warnings.append("one or more chart axes could not be calibrated or associated")
        if trace_count > len(series):
            warnings.append("line traces contain disconnected fragments")
    geometry_confidence = float(np.mean(geometry_confidences)) if geometry_confidences else 0.0
    association_confidence = 0.75 if any(item["points"] for item in series) else 0.45
    overall = _clamp(0.45 * geometry_confidence + 0.35 * calibration_confidence + 0.2 * association_confidence)
    return {
        "image_size": {"width": width, "height": height},
        "status": status,
        "plot_area_px": _public_plot_area(bounds),
        "axes": axes,
        "series": series,
        "confidence": {
            "overall": overall,
            "geometry": geometry_confidence,
            "calibration": calibration_confidence,
            "association": association_confidence,
        },
        "warnings": _unique(warnings),
    }


def _plot_bounds(axes: Mapping[str, object], width: int, height: int) -> tuple[int, int, int, int]:
    points: list[Sequence[float]] = []
    for axis_name in ("x", "y"):
        axis = axes.get(axis_name)
        axis_points = axis.get("points_px") if isinstance(axis, Mapping) else None
        if isinstance(axis_points, list):
            points.extend(point for point in axis_points if isinstance(point, list) and len(point) == 2)
    if len(points) >= 4:
        left = max(0, min(width - 1, int(min(point[0] for point in points))))
        right = max(left + 1, min(width, int(max(point[0] for point in points)) + 1))
        top = max(0, min(height - 1, int(min(point[1] for point in points))))
        bottom = max(top + 1, min(height, int(max(point[1] for point in points)) + 1))
        if (right - left) >= width * 0.25 and (bottom - top) >= height * 0.2:
            return left, top, right, bottom
    return max(0, int(width * 0.1)), max(0, int(height * 0.1)), min(width, int(width * 0.92)), min(height, int(height * 0.88))


def _public_plot_area(bounds: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = bounds
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _trace_fragments(
    mask: np.ndarray,
    offset_x: int,
    offset_y: int,
    *,
    simplify: bool = True,
    x_range: tuple[int, int] | None = None,
) -> list[list[list[float]]]:
    traces: list[list[list[float]]] = []
    active: list[int] = []
    start_x, end_x = x_range or (0, mask.shape[1])
    start_x = max(0, min(mask.shape[1], start_x))
    end_x = max(start_x, min(mask.shape[1], end_x))
    for local_x in range(start_x, end_x):
        ys = np.flatnonzero(mask[:, local_x])
        clusters = _clusters(ys)
        global_x = offset_x + local_x
        used: set[int] = set()
        next_active: list[int] = []
        for first, last in clusters:
            # Keep half-pixel centers for even-width strokes; rounding each
            # column accumulates visible bias when a trace is interpolated.
            center_y = (first + last) / 2.0 + offset_y
            candidates = [
                (abs(traces[index][-1][1] - center_y) + (global_x - traces[index][-1][0]) * 1.5, index)
                for index in active
                if index not in used and global_x - traces[index][-1][0] <= 2
                and abs(traces[index][-1][1] - center_y) <= 7
            ]
            if candidates:
                _distance, trace_index = min(candidates)
                traces[trace_index].append([global_x, center_y])
            else:
                trace_index = len(traces)
                traces.append([[global_x, center_y]])
            used.add(trace_index)
            next_active.append(trace_index)
        active = next_active
    fragments = [(_simplify(trace, 1.25) if simplify else trace) for trace in traces if len(trace) >= 3]
    return [fragment for fragment in fragments if len(fragment) >= 2]


def _clusters(values: np.ndarray) -> list[tuple[int, int]]:
    if not len(values):
        return []
    breaks = np.flatnonzero(np.diff(values) > 3)
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(values) - 1]
    return [(int(values[first]), int(values[last])) for first, last in zip(starts, ends, strict=True)]


def _simplify(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 2:
        return points
    first, last = np.asarray(points[0], dtype=float), np.asarray(points[-1], dtype=float)
    segment = last - first
    length = float(np.linalg.norm(segment))
    if length <= 1e-9:
        distances = np.linalg.norm(np.asarray(points[1:-1], dtype=float) - first, axis=1)
    else:
        offsets = np.asarray(points[1:-1], dtype=float) - first
        distances = np.abs(segment[0] * offsets[:, 1] - segment[1] * offsets[:, 0]) / length
    if not len(distances) or float(np.max(distances)) <= tolerance:
        return [points[0], points[-1]]
    split = int(np.argmax(distances)) + 1
    return _join(_simplify(points[: split + 1], tolerance), _simplify(points[split:], tolerance))


def _join(first: list[list[float]], second: list[list[float]]) -> list[list[float]]:
    return first[:-1] + second


def _line_points(
    traces: Sequence[Sequence[Sequence[float]]],
    axes: Mapping[str, object],
    markers: Sequence[Sequence[float]],
    other_markers: Sequence[Sequence[float]] = (),
    mask: np.ndarray | None = None,
    offset_x: int = 0,
    offset_y: int = 0,
) -> list[dict[str, object]]:
    positions: list[tuple[Sequence[float], str]] = [(point, "marker") for point in markers]
    for sample in _sample_ticks(traces, axes):
        if any(abs(sample[0] - marker[0]) < 10 for marker in markers):
            continue
        y = sample[1]
        occluded = any(
            abs(sample[0] - marker[0]) <= 10 and abs(y - marker[1]) <= 12
            for marker in other_markers
        )
        if occluded:
            estimated = None
            if mask is not None:
                local_x = sample[0] - offset_x
                window = (int(np.floor(local_x - 27)), int(np.ceil(local_x + 28)))
                local_traces = _trace_fragments(mask, offset_x, offset_y, simplify=False, x_range=window)
                estimated = _interpolate_across_marker_gap(local_traces, sample[0])
            if estimated is not None:
                y = estimated
        positions.append(([sample[0], y], "axis_tick_sample"))
    points: list[dict[str, object]] = []
    x_axis, y_axis = axes.get("x"), axes.get("y")
    ticks = x_axis.get("ticks", []) if isinstance(x_axis, Mapping) else []
    x_kind = x_axis.get("kind") if isinstance(x_axis, Mapping) else "unknown"
    for index, (position, source) in enumerate(positions, start=1):
        tick = _nearest_tick(position[0], ticks) if isinstance(ticks, list) else None
        points.append({
            "id": f"point_{index}",
            "position_px": [round(float(position[0]), 2), round(float(position[1]), 2)],
            "x_value": calibrated_axis_value(position, x_axis) if isinstance(x_axis, Mapping) else None,
            "y_value": calibrated_axis_value(position, y_axis) if isinstance(y_axis, Mapping) else None,
            "x_tick_id": tick.get("id") if tick is not None else None,
            "x_category_label": tick.get("text") if tick is not None and x_kind == "categorical" else None,
            "source": source,
            "confidence": 0.65 if source == "marker" else 0.5,
        })
    return points


def _interpolate_across_marker_gap(
    traces: Sequence[Sequence[Sequence[float]]],
    x: float,
) -> float | None:
    """Estimate an occluded vertex from the visible line segments on both sides."""
    left_values = []
    right_values = []
    for trace in traces:
        left = [point for point in trace if x - 26 <= point[0] <= x - 8]
        right = [point for point in trace if x + 8 <= point[0] <= x + 26]
        left_value = _fit_local_line(left, x)
        right_value = _fit_local_line(right, x)
        if left_value is not None:
            left_values.append(left_value)
        if right_value is not None:
            right_values.append(right_value)
    pairs = [
        (left, right)
        for left in left_values
        for right in right_values
        if abs(left - right) <= 5
    ]
    if not pairs:
        return None
    left, right = min(pairs, key=lambda pair: abs(pair[0] - pair[1]))
    return float((left + right) / 2)


def _fit_local_line(points: Sequence[Sequence[float]], x: float) -> float | None:
    if len(points) < 4:
        return None
    coordinates = np.asarray(points, dtype=float)
    center_x = float(np.mean(coordinates[:, 0]))
    center_y = float(np.mean(coordinates[:, 1]))
    spread = coordinates[:, 0] - center_x
    denominator = float(np.dot(spread, spread))
    if denominator <= 1e-9:
        return None
    slope = float(np.dot(spread, coordinates[:, 1] - center_y) / denominator)
    intercept = center_y - slope * center_x
    residual = coordinates[:, 1] - (slope * coordinates[:, 0] + intercept)
    if float(np.sqrt(np.mean(residual**2))) > 1.5:
        return None
    return float(slope * x + intercept)


def _marker_centers(mask: np.ndarray, offset_x: int, offset_y: int) -> list[list[float]]:
    from scipy.ndimage import distance_transform_edt, maximum_filter, label, center_of_mass
    distance = distance_transform_edt(mask)
    maxima = (distance >= 2.8) & (distance == maximum_filter(distance, size=11))
    components, count = label(maxima)
    if not count:
        return []
    centers = center_of_mass(maxima, components, range(1, count+1))
    selected = []
    for y, x in sorted(centers, key=lambda p: -distance[int(round(p[0])),int(round(p[1]))]):
        if any(hypot(x + offset_x-p[0],y + offset_y-p[1]) < 10 for p in selected):
            continue
        selected.append([float(x + offset_x),float(y + offset_y)])
    return sorted(selected, key=lambda point: (point[0], point[1]))


def _sample_ticks(traces: Sequence[Sequence[Sequence[int]]], axes: Mapping[str, object]) -> list[list[float]]:
    axis = axes.get("x")
    ticks = axis.get("ticks", []) if isinstance(axis, Mapping) else []
    if not isinstance(ticks, list):
        return []
    positions: list[list[float]] = []
    for tick in ticks:
        point = tick.get("point_px") if isinstance(tick, Mapping) else None
        if not isinstance(point, list) or len(point) != 2:
            continue
        x = float(point[0])
        y = next((sample for trace in traces if (sample := _interpolate(trace, x)) is not None), None)
        if y is not None:
            positions.append([x, y])
    return positions


def _interpolate(trace: Sequence[Sequence[float]], x: float) -> float | None:
    for first, second in zip(trace, trace[1:]):
        if first[0] <= x <= second[0] and second[0] > first[0]:
            fraction = (x - first[0]) / (second[0] - first[0])
            return float(first[1] + fraction * (second[1] - first[1]))
    return None


def _nearest_tick(x: float, ticks: Sequence[object]) -> Mapping[str, object] | None:
    valid = [tick for tick in ticks if isinstance(tick, Mapping) and isinstance(tick.get("point_px"), list)]
    if not valid:
        return None
    tick = min(valid, key=lambda item: abs(float(item["point_px"][0]) - x))
    return tick if abs(float(tick["point_px"][0]) - x) <= 16 else None


def _axes_usable(axes: Mapping[str, object]) -> bool:
    for name in ("x", "y"):
        axis = axes.get(name)
        if not isinstance(axis, Mapping):
            return False
        if axis.get("kind") == "categorical":
            continue
        calibration = axis.get("calibration")
        if not isinstance(calibration, Mapping) or calibration.get("calibrated") is not True:
            return False
    return True


def _calibration_confidence(axes: Mapping[str, object]) -> float:
    values = []
    for name in ("x", "y"):
        axis = axes.get(name)
        calibration = axis.get("calibration") if isinstance(axis, Mapping) else None
        values.append(float(calibration.get("confidence", 0.0)) if isinstance(calibration, Mapping) and calibration.get("calibrated") is True else 0.0)
    return sum(values) / len(values)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))
