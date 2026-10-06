"""Pixel geometry and calibrated quartile observations for box plots."""

from __future__ import annotations

from collections.abc import Mapping
from statistics import median

import numpy as np

from .cartesian import calibrated_axis_value, observe_cartesian_axes
from .contracts import MAX_MEASUREMENT_OBSERVATIONS, MeasurementSensorResult, PreparedMeasurementImage
from .ocr import recognize_text


def measure_box_plot(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    rgb = image.rgb
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, image.observation_mask) if image.observation_mask is not None else recognize_text(rgb)
    axes = observe_cartesian_axes(rgb, ocr.snippets, None)
    left, top, right, bottom = _plot_bounds(axes, width, height)
    gray = np.mean(rgb.astype(np.float32), axis=2)
    spread = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    dark = (gray <= 120) & (spread <= 72)
    colored = (spread >= 58) & (rgb.max(axis=2) <= 240) & (rgb.min(axis=2) <= 215)
    ink = (dark | colored)
    if image.observation_mask is not None:
        ink &= image.observation_mask
        dark &= image.observation_mask

    plot_width, plot_height = right - left, bottom - top
    horizontal = _horizontal_runs(dark, left, top, right, bottom, max_length=plot_width * 0.46)
    vertical = _vertical_runs(dark, left, top, right, bottom, max_length=plot_height * 0.68)
    rectangles: list[tuple[int, int, int, int]] = []
    for first in horizontal:
        y1, x1, x2 = first
        box_width = x2 - x1
        if box_width < max(8, int(plot_width * 0.025)):
            continue
        for second in horizontal:
            y2, other_x1, other_x2 = second
            box_height = y2 - y1
            if y2 <= y1:
                continue
            if box_height > plot_height * 0.62:
                break
            if box_height < 8:
                continue
            other_width = other_x2 - other_x1
            if max(box_width, other_width) / max(1, min(box_width, other_width)) > 1.35:
                continue
            overlap = max(0, min(x2, other_x2) - max(x1, other_x1))
            if overlap / max(1, max(box_width, other_width)) < 0.72:
                continue
            left_edge = int(round((x1 + other_x1) / 2))
            right_edge = int(round((x2 + other_x2) / 2))
            candidate_width = right_edge - left_edge
            if candidate_width < max(8, int(plot_width * 0.025)) or candidate_width > plot_width * 0.46:
                continue
            if not _has_vertical_edge(vertical, left_edge, y1, y2) or not _has_vertical_edge(vertical, right_edge, y1, y2):
                continue
            rectangles.append((left_edge, y1, right_edge, y2))

    candidates = _deduplicate_rectangles(rectangles)
    candidates.sort(key=lambda rect: (rect[0] + rect[2]) / 2)
    truncated = len(candidates) > MAX_MEASUREMENT_OBSERVATIONS
    candidates = candidates[:MAX_MEASUREMENT_OBSERVATIONS]
    groups = []
    y_axis = axes["y"]
    for index, (x1, y1, x2, y2) in enumerate(candidates, start=1):
        center_x = (x1 + x2) / 2.0
        median_y = _median_line_y(dark, x1, x2, y1, y2)
        upper_whisker_y = _whisker_endpoint(dark, center_x, y1, top, direction=-1)
        lower_whisker_y = _whisker_endpoint(dark, center_x, y2, bottom, direction=1)
        category_label = _nearest_category_label(axes.get("x"), center_x, (x1, x2))
        outliers = _visible_outliers(dark, center_x, x1, x2, y1, y2, upper_whisker_y, lower_whisker_y, bottom)
        groups.append(
            {
                "id": f"group_{index}",
                "label": category_label,
                "bounds_px": {"x": x1, "y": y1, "width": x2 - x1 + 1, "height": y2 - y1 + 1},
                "lower_whisker_px": [center_x, lower_whisker_y] if lower_whisker_y is not None else None,
                "q1_px": [center_x, y2],
                "median_px": [center_x, median_y] if median_y is not None else None,
                "q3_px": [center_x, y1],
                "upper_whisker_px": [center_x, upper_whisker_y] if upper_whisker_y is not None else None,
                "lower_whisker": calibrated_axis_value([center_x, lower_whisker_y], y_axis) if lower_whisker_y is not None else None,
                "q1": calibrated_axis_value([center_x, y2], y_axis),
                "median": calibrated_axis_value([center_x, median_y], y_axis) if median_y is not None else None,
                "q3": calibrated_axis_value([center_x, y1], y_axis),
                "upper_whisker": calibrated_axis_value([center_x, upper_whisker_y], y_axis) if upper_whisker_y is not None else None,
                "outliers": [
                    {"position_px": [x, y], "value": calibrated_axis_value([x, y], y_axis)}
                    for x, y in outliers
                ],
            }
        )

    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; category label associations may be incomplete")
    if truncated:
        warnings.append("box-plot group observation limit reached")
    if not groups:
        status = "no_evidence"
        warnings.append("no bounded box geometry was detected")
    else:
        calibration = y_axis.get("calibration") if isinstance(y_axis, Mapping) else None
        calibrated = isinstance(calibration, Mapping) and calibration.get("calibrated") is True
        status = "measured" if calibrated and all(group["median_px"] is not None for group in groups) else "partial"
        if status == "partial":
            warnings.append("box geometry is visible but median or numeric y-axis calibration is incomplete")
    if truncated:
        status = "partial"

    calibration = y_axis.get("calibration") if isinstance(y_axis, Mapping) else None
    calibration_confidence = float(calibration.get("confidence", 0.0)) if isinstance(calibration, Mapping) else 0.0
    geometry_confidence = min(0.95, 0.55 + len(groups) * 0.08) if groups else 0.0
    association_confidence = 0.75 if any(group["label"] for group in groups) else 0.5
    confidence = {
        "overall": _clamp(0.48 * geometry_confidence + 0.34 * calibration_confidence + 0.18 * association_confidence),
        "geometry": _clamp(geometry_confidence),
        "calibration": _clamp(calibration_confidence),
        "association": _clamp(association_confidence),
    }
    observations = {"axes": axes, "orientation": "vertical", "groups": groups}
    return MeasurementSensorResult(
        status=status,
        observations=observations,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        plot_area_px={"x": left, "y": top, "width": plot_width, "height": plot_height},
        warnings=tuple(dict.fromkeys(warnings)),
        truncated=truncated,
    )


def _runs(indices: np.ndarray) -> list[tuple[int, int]]:
    if not len(indices):
        return []
    breaks = np.flatnonzero(np.diff(indices) > 1)
    starts, ends = np.r_[0, breaks + 1], np.r_[breaks, len(indices) - 1]
    return [(int(indices[first]), int(indices[last])) for first, last in zip(starts, ends, strict=True)]


def _horizontal_runs(mask: np.ndarray, left: int, top: int, right: int, bottom: int, *, max_length: float):
    result = []
    for y in range(top, bottom):
        xs = np.flatnonzero(mask[y, left:right]) + left
        for x1, x2 in _runs(xs):
            length = x2 - x1 + 1
            if 8 <= length <= max_length:
                result.append((y, x1, x2 + 1))
    return result


def _vertical_runs(mask: np.ndarray, left: int, top: int, right: int, bottom: int, *, max_length: float):
    result = []
    for x in range(left, right):
        ys = np.flatnonzero(mask[top:bottom, x]) + top
        for y1, y2 in _runs(ys):
            length = y2 - y1 + 1
            if 8 <= length <= max_length:
                result.append((x, y1, y2 + 1))
    return result


def _has_vertical_edge(vertical_runs, x: int, y1: int, y2: int) -> bool:
    height = y2 - y1
    return any(
        abs(run_x - x) <= 2
        and max(0, min(y2, run_bottom) - max(y1, run_top)) >= height * 0.82
        for run_x, run_top, run_bottom in vertical_runs
    )


def _deduplicate_rectangles(rectangles: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    ranked = sorted(rectangles, key=lambda rect: (rect[2] - rect[0]) * (rect[3] - rect[1]), reverse=True)
    result: list[tuple[int, int, int, int]] = []
    for candidate in ranked:
        x1, _, x2, _ = candidate
        center_x = (x1 + x2) / 2
        width = x2 - x1
        same_category = False
        for known in result:
            known_center_x = (known[0] + known[2]) / 2
            known_width = known[2] - known[0]
            overlap = max(0, min(x2, known[2]) - max(x1, known[0]))
            if (
                abs(center_x - known_center_x) <= max(5, min(width, known_width) * 0.3)
                and overlap / max(1, min(width, known_width)) >= 0.55
            ):
                same_category = True
                break
        if same_category:
            continue
        result.append(candidate)
    return result


def _median_line_y(dark: np.ndarray, x1: int, x2: int, y1: int, y2: int) -> int | None:
    rows = []
    minimum = max(5, int((x2 - x1) * 0.58))
    for y in range(y1 + 2, y2 - 1):
        if int(np.count_nonzero(dark[y, x1 + 2 : x2 - 2])) >= minimum:
            rows.append(y)
    if not rows:
        return None
    return int(median(rows))


def _whisker_endpoint(dark: np.ndarray, center_x: float, box_edge: int, plot_edge: int, *, direction: int) -> int | None:
    x = int(round(center_x))
    if direction < 0:
        start, stop = box_edge - 2, max(0, plot_edge)
        ys = range(start, stop - 1, -1)
    else:
        start, stop = box_edge + 2, min(dark.shape[0], plot_edge)
        ys = range(start, stop)
    selected: list[int] = []
    missing = 0
    for y in ys:
        y_int = int(y)
        visible = bool(np.any(dark[max(0, y_int - 1) : min(dark.shape[0], y_int + 2), max(0, x - 1) : min(dark.shape[1], x + 2)]))
        if visible:
            selected.append(y_int)
            missing = 0
        elif selected:
            missing += 1
            if missing > 1:
                break
    if len(selected) < 3:
        return None
    return min(selected) if direction < 0 else max(selected)


def _nearest_category_label(axis: object, center_x: float, bounds: tuple[int, int]) -> str | None:
    if not isinstance(axis, Mapping):
        return None
    ticks = axis.get("ticks")
    if not isinstance(ticks, (list, tuple)):
        return None
    candidates = []
    for tick in ticks:
        if not isinstance(tick, Mapping) or not isinstance(tick.get("point_px"), (list, tuple)):
            continue
        point = tick["point_px"]
        if len(point) != 2 or not isinstance(tick.get("text"), str):
            continue
        distance = abs(float(point[0]) - center_x)
        if distance <= max(24, (bounds[1] - bounds[0]) * 1.5):
            candidates.append((distance, tick["text"]))
    return min(candidates)[1] if candidates else None


def _visible_outliers(
    dark: np.ndarray,
    center_x: float,
    x1: int,
    x2: int,
    y1: int,
    y2: int,
    upper_whisker_y: int | None,
    lower_whisker_y: int | None,
    plot_bottom: int,
) -> list[tuple[float, float]]:
    upper_limit = upper_whisker_y if upper_whisker_y is not None else y1
    lower_limit = lower_whisker_y if lower_whisker_y is not None else y2
    x_radius = max(4, int((x2 - x1) * 0.28))
    local_left, local_right = max(0, int(center_x) - x_radius), min(dark.shape[1], int(center_x) + x_radius + 1)
    local_top, local_bottom = max(0, upper_limit - 18), min(plot_bottom, lower_limit + 18)
    local = dark[local_top:local_bottom, local_left:local_right]
    padded = np.pad(local.astype(np.uint8), 1)
    neighbor_count = np.zeros(local.shape, dtype=np.uint8)
    for dy in range(3):
        for dx in range(3):
            neighbor_count += padded[dy : dy + local.shape[0], dx : dx + local.shape[1]]
    candidates = np.argwhere((local) & (neighbor_count >= 3) & (neighbor_count <= 15))
    points: list[tuple[float, float]] = []
    for row, column in candidates:
        x, y = local_left + int(column), local_top + int(row)
        if upper_limit + 3 < y < lower_limit - 3:
            continue
        if any(abs(x - known_x) <= 3 and abs(y - known_y) <= 3 for known_x, known_y in points):
            continue
        points.append((float(x), float(y)))
        if len(points) >= 32:
            break
    return points


def _plot_bounds(axes: Mapping[str, object], width: int, height: int) -> tuple[int, int, int, int]:
    points = []
    for name in ("x", "y"):
        axis = axes.get(name)
        axis_points = axis.get("points_px") if isinstance(axis, Mapping) else None
        if isinstance(axis_points, list):
            points.extend(point for point in axis_points if isinstance(point, list) and len(point) == 2)
    if len(points) >= 4:
        left = max(0, min(width - 1, int(min(point[0] for point in points))))
        right = max(left + 1, min(width, int(max(point[0] for point in points)) + 1))
        top = max(0, min(height - 1, int(min(point[1] for point in points))))
        bottom = max(top + 1, min(height, int(max(point[1] for point in points)) + 1))
        if right - left >= width * 0.25 and bottom - top >= height * 0.2:
            return left, top, right, bottom
    return int(width * 0.1), int(height * 0.1), int(width * 0.92), int(height * 0.88)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
