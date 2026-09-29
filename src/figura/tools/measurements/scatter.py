"""Visible point geometry and calibrated coordinates for scatter charts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from math import hypot, sqrt
from typing import Any

import numpy as np
from PIL import Image

from .cartesian import (
    associate_legend_labels,
    axis_scalar,
    calibrated_axis_value,
    observe_cartesian_axes,
)
from .colors import color_mask, hex_color, series_palette
from .ocr import recognize_text


def measure_scatter_image(image_bytes: bytes) -> dict[str, Any]:
    """Return visible color-coded point candidates without estimating hidden counts."""
    rgb = _decode_image(image_bytes)
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb)
    axes = observe_cartesian_axes(rgb, ocr.snippets, None)
    bounds = _plot_bounds(axes, width, height)
    left, top, right, bottom = bounds
    crop = rgb[top:bottom, left:right]
    palette = series_palette(crop)
    labels = associate_legend_labels(rgb, ocr.snippets, palette)
    series: list[dict[str, Any]] = []
    for index, color in enumerate(palette, start=1):
        detections = _point_components(color_mask(crop, color), left, top, width, height)
        if not detections:
            continue
        color_hex = hex_color(color)
        label, label_confidence = labels.get(color_hex, (None, None))
        series.append({
            "id": f"series_{index}",
            "color": color_hex,
            "label": label,
            "label_confidence": label_confidence,
            "points": [
                _point_observation(point, point_index, axes)
                for point_index, point in enumerate(detections, start=1)
            ],
        })
    overlap = _mark_overlaps(series)
    flags = [flag for item in series for point in item["points"] for flag in point["flags"]]
    for item in series:
        for point in item["points"]:
            point.pop("_bbox", None)
    calibration_confidence = _calibration_confidence(axes)
    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; axis and legend associations may be incomplete")
    if not series:
        status = "no_evidence"
        warnings.append("no scatter points were detected")
    else:
        status = "measured" if _axes_usable(axes) and not flags else "partial"
        if not _axes_usable(axes):
            warnings.append("one or more chart axes could not be calibrated")
        if any(flag in flags for flag in ("merged", "dense")):
            warnings.append("some visible marks may contain merged or dense points")
        if overlap:
            warnings.append("some visible point regions overlap or occlude one another")
    point_count = sum(len(item["points"]) for item in series)
    geometry_confidence = min(0.9, 0.5 + point_count * 0.01) if point_count else 0.0
    if flags:
        geometry_confidence *= 0.8
    association_confidence = 0.75 if len(series) > 1 else 0.6
    overall = _clamp(0.45 * geometry_confidence + 0.35 * calibration_confidence + 0.2 * association_confidence)
    return {
        "image_size": {"width": width, "height": height},
        "status": status,
        "plot_area_px": {"x": left, "y": top, "width": right - left, "height": bottom - top},
        "axes": axes,
        "series": series,
        "confidence": {
            "overall": overall,
            "geometry": geometry_confidence,
            "calibration": calibration_confidence,
            "association": association_confidence,
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def _decode_image(image_bytes: bytes) -> np.ndarray:
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("image bytes are required")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            return np.asarray(image.convert("RGB"))
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError("image cannot be decoded") from None


def _plot_bounds(axes: Mapping[str, object], width: int, height: int) -> tuple[int, int, int, int]:
    points: list[Sequence[float]] = []
    for name in ("x", "y"):
        axis = axes.get(name)
        value = axis.get("points_px") if isinstance(axis, Mapping) else None
        if isinstance(value, list):
            points.extend(point for point in value if isinstance(point, list) and len(point) == 2)
    if len(points) >= 4:
        left = max(0, min(width - 1, int(min(point[0] for point in points))))
        right = max(left + 1, min(width, int(max(point[0] for point in points)) + 1))
        top = max(0, min(height - 1, int(min(point[1] for point in points))))
        bottom = max(top + 1, min(height, int(max(point[1] for point in points)) + 1))
        if right - left >= width * 0.25 and bottom - top >= height * 0.2:
            return left, top, right, bottom
    return max(0, int(width * 0.1)), max(0, int(height * 0.1)), min(width, int(width * 0.92)), min(height, int(height * 0.88))


def _point_components(
    mask: np.ndarray,
    offset_x: int,
    offset_y: int,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    parents: list[int] = []
    runs: list[tuple[int, int, int, int]] = []
    previous: list[tuple[int, int, int]] = []
    for y in range(mask.shape[0]):
        x_values = np.flatnonzero(mask[y])
        if not len(x_values):
            previous = []
            continue
        breaks = np.flatnonzero(np.diff(x_values) > 1)
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, len(x_values) - 1]
        current: list[tuple[int, int, int]] = []
        previous_index = 0
        for first, last in zip(starts, ends, strict=True):
            run_left, run_right = int(x_values[first]), int(x_values[last])
            run_id = len(parents)
            parents.append(run_id)
            while previous_index < len(previous) and previous[previous_index][1] < run_left - 1:
                previous_index += 1
            scan = previous_index
            while scan < len(previous) and previous[scan][0] <= run_right + 1:
                prior_left, prior_right, prior_id = previous[scan]
                if prior_right >= run_left - 1:
                    _union(parents, run_id, prior_id)
                scan += 1
            current.append((run_left, run_right, run_id))
            runs.append((y, run_left, run_right, run_id))
        previous = current

    grouped: dict[int, dict[str, float]] = {}
    for y, left, right, run_id in runs:
        root = _find(parents, run_id)
        count = right - left + 1
        item = grouped.setdefault(root, {
            "area": 0.0, "sum_x": 0.0, "sum_y": 0.0,
            "left": float(left), "right": float(right), "top": float(y), "bottom": float(y),
        })
        item["area"] += count
        item["sum_x"] += (left + right) * count / 2.0
        item["sum_y"] += y * count
        item["left"] = min(item["left"], left)
        item["right"] = max(item["right"], right)
        item["top"] = min(item["top"], y)
        item["bottom"] = max(item["bottom"], y)

    detections: list[dict[str, Any]] = []
    minimum_area = max(3, int(image_width * image_height * 0.000001))
    for item in grouped.values():
        area = int(item["area"])
        box_width, box_height = int(item["right"] - item["left"] + 1), int(item["bottom"] - item["top"] + 1)
        if area < minimum_area or min(box_width, box_height) == 0:
            continue
        if max(box_width, box_height) > 15 and max(box_width, box_height) / min(box_width, box_height) > 3.5:
            continue
        flags: list[str] = []
        if area >= 420 or max(box_width, box_height) >= max(24, min(image_width, image_height) * 0.12):
            flags.extend(("merged", "dense"))
        detections.append({
            "position_px": [
                round(item["sum_x"] / item["area"] + offset_x, 2),
                round(item["sum_y"] / item["area"] + offset_y, 2),
            ],
            "radius_px": round(max(1.0, sqrt(area / np.pi)), 2),
            "confidence": 0.82 if not flags else 0.48,
            "flags": flags,
            "_bbox": [item["left"] + offset_x, item["top"] + offset_y, box_width, box_height],
        })
    detections.sort(key=lambda item: (item["position_px"][0], item["position_px"][1]))
    return detections


def _find(parents: list[int], item: int) -> int:
    while parents[item] != item:
        parents[item] = parents[parents[item]]
        item = parents[item]
    return item


def _union(parents: list[int], first: int, second: int) -> None:
    first_root, second_root = _find(parents, first), _find(parents, second)
    if first_root != second_root:
        parents[second_root] = first_root


def _point_observation(
    point: Mapping[str, Any],
    index: int,
    axes: Mapping[str, object],
) -> dict[str, object]:
    position = point["position_px"]
    x_axis, y_axis = axes.get("x"), axes.get("y")
    return {
        "id": f"point_{index}",
        "position_px": position,
        "x_value": calibrated_axis_value(position, x_axis) if isinstance(x_axis, Mapping) else None,
        "y_value": calibrated_axis_value(position, y_axis) if isinstance(y_axis, Mapping) else None,
        "x_tick_id": _nearest_tick_id(position, x_axis) if isinstance(x_axis, Mapping) else None,
        "y_tick_id": _nearest_tick_id(position, y_axis) if isinstance(y_axis, Mapping) else None,
        "radius_px": point["radius_px"],
        "confidence": point["confidence"],
        "flags": point["flags"],
        "_bbox": point["_bbox"],
    }


def _nearest_tick_id(position: Sequence[float], axis: Mapping[str, object]) -> str | None:
    points, ticks = axis.get("points_px"), axis.get("ticks")
    if not isinstance(points, list) or len(points) != 2 or not isinstance(ticks, list):
        return None
    target = axis_scalar(position, points)
    nearest: tuple[float, str] | None = None
    for tick in ticks:
        if not isinstance(tick, Mapping) or not isinstance(tick.get("id"), str) or not isinstance(tick.get("point_px"), list):
            continue
        distance = abs(axis_scalar(tick["point_px"], points) - target)
        if nearest is None or distance < nearest[0]:
            nearest = (distance, tick["id"])
    return nearest[1] if nearest is not None and nearest[0] <= 16 else None


def _mark_overlaps(series: list[dict[str, Any]]) -> bool:
    points = sorted(
        (point for item in series for point in item["points"]),
        key=lambda point: point["position_px"][0],
    )
    max_radius = max((float(point["radius_px"]) for point in points), default=0.0)
    overlap = False
    for first_index, first in enumerate(points):
        nearby_count = 0
        for second_index in range(first_index + 1, len(points)):
            second = points[second_index]
            first_position, second_position = first["position_px"], second["position_px"]
            delta_x = second_position[0] - first_position[0]
            if delta_x > float(first["radius_px"]) + max_radius + 1:
                break
            nearby_count += 1
            if nearby_count > 128:
                _add_flag(first, "dense")
                first["confidence"] = min(float(first["confidence"]), 0.45)
                break
            radius_sum = float(first["radius_px"]) + float(second["radius_px"])
            distance = hypot(first_position[0] - second_position[0], first_position[1] - second_position[1])
            if distance > radius_sum + 1:
                continue
            overlap = True
            for point in (first, second):
                _add_flag(point, "overlap")
                if distance <= min(float(first["radius_px"]), float(second["radius_px"])):
                    _add_flag(point, "occluded")
                point["confidence"] = min(float(point["confidence"]), 0.55)
    return overlap


def _add_flag(point: dict[str, Any], flag: str) -> None:
    if flag not in point["flags"]:
        point["flags"].append(flag)


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
    confidence = []
    for name in ("x", "y"):
        axis = axes.get(name)
        calibration = axis.get("calibration") if isinstance(axis, Mapping) else None
        confidence.append(float(calibration.get("confidence", 0.0)) if isinstance(calibration, Mapping) and calibration.get("calibrated") is True else 0.0)
    return sum(confidence) / len(confidence)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
