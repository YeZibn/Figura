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
from .observation_scope import decode_scoped_image


def measure_line_image(
    image_bytes: bytes,
    observation_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return source-coordinate line traces and only supported point samples."""
    rgb, observation_mask = decode_scoped_image(image_bytes, observation_scope)
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, observation_mask) if observation_mask is not None else recognize_text(rgb)
    axes = observe_cartesian_axes(rgb, ocr.snippets, None)
    bounds = _plot_bounds(axes, width, height)
    left, top, right, bottom = bounds
    crop = rgb[top:bottom, left:right]
    palette = series_palette(crop)
    legend_labels = associate_legend_labels(rgb, ocr.snippets, palette)
    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; axis and legend associations may be incomplete")
    series: list[dict[str, Any]] = []
    trace_count = 0
    geometry_confidences: list[float] = []
    for index, color in enumerate(palette, start=1):
        mask = color_mask(crop, color)
        traces = _trace_fragments(mask, left, top)
        if not traces:
            continue
        trace_count += len(traces)
        if len(traces) > 1:
            warnings.append(f"series_{index} contains {len(traces)} disconnected trace fragments")
        markers = _marker_centers(mask, left, top)
        points = _line_points(traces, axes, markers)
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


def _trace_fragments(mask: np.ndarray, offset_x: int, offset_y: int) -> list[list[list[int]]]:
    traces: list[list[list[int]]] = []
    active: list[int] = []
    for local_x in range(mask.shape[1]):
        ys = np.flatnonzero(mask[:, local_x])
        clusters = _clusters(ys)
        global_x = offset_x + local_x
        used: set[int] = set()
        next_active: list[int] = []
        for first, last in clusters:
            center_y = int(round((first + last) / 2.0)) + offset_y
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
    fragments = [_simplify(trace, 1.25) for trace in traces if len(trace) >= 3]
    return [fragment for fragment in fragments if len(fragment) >= 2]


def _clusters(values: np.ndarray) -> list[tuple[int, int]]:
    if not len(values):
        return []
    breaks = np.flatnonzero(np.diff(values) > 3)
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(values) - 1]
    return [(int(values[first]), int(values[last])) for first, last in zip(starts, ends, strict=True)]


def _simplify(points: list[list[int]], tolerance: float) -> list[list[int]]:
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


def _join(first: list[list[int]], second: list[list[int]]) -> list[list[int]]:
    return first[:-1] + second


def _line_points(
    traces: Sequence[Sequence[Sequence[int]]],
    axes: Mapping[str, object],
    markers: Sequence[Sequence[float]],
) -> list[dict[str, object]]:
    source = "marker" if markers else "axis_tick_sample"
    positions = markers if markers else _sample_ticks(traces, axes)
    points: list[dict[str, object]] = []
    x_axis, y_axis = axes.get("x"), axes.get("y")
    ticks = x_axis.get("ticks", []) if isinstance(x_axis, Mapping) else []
    x_kind = x_axis.get("kind") if isinstance(x_axis, Mapping) else "unknown"
    for index, position in enumerate(positions, start=1):
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


def _marker_centers(mask: np.ndarray, offset_x: int, offset_y: int) -> list[list[float]]:
    if min(mask.shape) < 7:
        return []
    integral = np.pad(mask.astype(np.uint32), ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    counts = integral[7:, 7:] - integral[:-7, 7:] - integral[7:, :-7] + integral[:-7, :-7]
    candidates = np.argwhere(counts >= 20)
    if not len(candidates):
        return []
    ranked = sorted(
        ((int(counts[y, x]), int(x + 3), int(y + 3)) for y, x in candidates),
        reverse=True,
    )
    selected: list[list[float]] = []
    for _count, x, y in ranked:
        center = [float(x + offset_x), float(y + offset_y)]
        if any(hypot(center[0] - prior[0], center[1] - prior[1]) < 7 for prior in selected):
            continue
        selected.append(center)
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


def _interpolate(trace: Sequence[Sequence[int]], x: float) -> float | None:
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
