"""Pixel-boundary observations for filled Cartesian area charts."""

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
from .contracts import (
    MAX_MEASUREMENT_OBSERVATIONS,
    MeasurementSensorResult,
    PreparedMeasurementImage,
)
from .lines import measure_line_pixels
from .ocr import recognize_text


def measure_area(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    rgb = image.rgb
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, image.observation_mask) if image.observation_mask is not None else recognize_text(rgb)
    axes = observe_cartesian_axes(rgb, ocr.snippets, None)
    bounds = _plot_bounds(axes, width, height)
    left, top, right, bottom = bounds
    crop = rgb[top:bottom, left:right]
    palette = series_palette(crop)
    labels = associate_legend_labels(rgb, ocr.snippets, palette)
    series: list[dict[str, object]] = []
    candidate_pixel_count = 0
    color_limit_reached = len(palette) >= 8
    truncated = color_limit_reached
    for index, color in enumerate(palette, start=1):
        mask = color_mask(crop, color)
        if image.observation_mask is not None:
            mask &= image.observation_mask[top:bottom, left:right]
        pixel_count = int(np.count_nonzero(mask))
        candidate_pixel_count += pixel_count
        if pixel_count < max(24, int((right - left) * (bottom - top) * 0.001)):
            continue
        boundaries = _area_segments(mask, left, top)
        if not boundaries:
            continue
        if len(boundaries) > MAX_MEASUREMENT_OBSERVATIONS:
            boundaries = boundaries[:MAX_MEASUREMENT_OBSERVATIONS]
            truncated = True
        color_hex = hex_color(color)
        label, label_confidence = labels.get(color_hex, (None, None))
        segments = []
        for upper, lower in boundaries:
            if len(upper) > MAX_MEASUREMENT_OBSERVATIONS or len(lower) > MAX_MEASUREMENT_OBSERVATIONS:
                upper = upper[:MAX_MEASUREMENT_OBSERVATIONS]
                lower = lower[:MAX_MEASUREMENT_OBSERVATIONS]
                truncated = True
            upper_values = [
                calibrated_axis_value(point, axes["y"])
                for point in upper
            ]
            lower_values = [
                calibrated_axis_value(point, axes["y"])
                for point in lower
            ]
            segments.append(
                {
                    "upper_boundary_px": upper,
                    "lower_boundary_px": lower,
                    "upper_values": upper_values,
                    "lower_values": lower_values,
                }
            )
        series.append(
            {
                "id": f"series_{index}",
                "color": color_hex,
                "label": label,
                "label_confidence": label_confidence,
                "segments": segments,
            }
        )

    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; axis and legend associations may be incomplete")
    if color_limit_reached:
        warnings.append("area series color limit reached; additional colors may be omitted")
    elif truncated:
        warnings.append("area boundary observation limit reached")
    if not series and palette:
        line_result = measure_line_pixels(rgb, image.observation_mask)
        if line_result["series"]:
            status = "unsupported"
            warnings.append("visible traces do not provide a supported filled-area region")
        else:
            status = "no_evidence"
            warnings.append("no filled area geometry was detected")
    elif not series:
        status = "no_evidence"
        warnings.append("no filled area geometry was detected")
    else:
        status = "measured" if _axes_calibrated(axes) else "partial"
        if status == "partial":
            warnings.append("one or more area-chart axes could not be calibrated")
        if any(
            value is None
            for item in series
            for segment in item["segments"]
            for value in segment["upper_values"]
        ):
            status = "partial"
            warnings.append("area boundary values are unavailable without axis calibration")

    if truncated and status in {"measured", "no_evidence"}:
        status = "partial"
    geometry_confidence = min(0.96, 0.45 + candidate_pixel_count / max(1, (right - left) * (bottom - top)))
    calibration_confidence = _axis_calibration_confidence(axes)
    association_confidence = 0.72 if any(item["label"] for item in series) else 0.52
    confidence = {
        "overall": _clamp(0.48 * geometry_confidence + 0.34 * calibration_confidence + 0.18 * association_confidence),
        "geometry": _clamp(geometry_confidence),
        "calibration": _clamp(calibration_confidence),
        "association": _clamp(association_confidence),
    }
    observations = {"axes": axes, "stacking": "unknown", "series": series[:MAX_MEASUREMENT_OBSERVATIONS]}
    if len(series) > MAX_MEASUREMENT_OBSERVATIONS:
        truncated = True
        status = "partial"
        warnings.append("area observation limit reached")
    return MeasurementSensorResult(
        status=status,
        observations=observations,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        plot_area_px={"x": left, "y": top, "width": right - left, "height": bottom - top},
        warnings=tuple(warnings),
        truncated=truncated,
    )


def _area_segments(
    mask: np.ndarray,
    offset_x: int,
    offset_y: int,
) -> list[tuple[list[list[int]], list[list[int]]]]:
    columns: list[tuple[int, int] | None] = []
    for x in range(mask.shape[1]):
        ys = np.flatnonzero(mask[:, x])
        if not len(ys):
            columns.append(None)
            continue
        breaks = np.flatnonzero(np.diff(ys) > 2)
        starts, ends = np.r_[0, breaks + 1], np.r_[breaks, len(ys) - 1]
        runs = [
            (int(ys[first]), int(ys[last]))
            for first, last in zip(starts, ends, strict=True)
            if int(ys[last]) - int(ys[first]) >= 6
        ]
        columns.append(max(runs, key=lambda run: run[1] - run[0]) if runs else None)

    result: list[tuple[list[list[int]], list[list[int]]]] = []
    active_x: list[int] = []
    active_runs: list[tuple[int, int]] = []
    for x, run in enumerate(columns):
        if run is None:
            if active_x:
                _append_area_segment(result, active_x, active_runs, offset_x, offset_y)
                active_x, active_runs = [], []
            continue
        active_x.append(x)
        active_runs.append(run)
    if active_x:
        _append_area_segment(result, active_x, active_runs, offset_x, offset_y)
    return result


def _append_area_segment(
    output: list[tuple[list[list[int]], list[list[int]]]],
    xs: Sequence[int],
    runs: Sequence[tuple[int, int]],
    offset_x: int,
    offset_y: int,
) -> None:
    if len(xs) < 6 or float(np.median([bottom - top for top, bottom in runs])) < 8:
        return
    upper = [[offset_x + x, offset_y + top] for x, (top, _bottom) in zip(xs, runs, strict=True)]
    lower = [[offset_x + x, offset_y + bottom] for x, (_top, bottom) in zip(xs, runs, strict=True)]
    output.append((upper, lower))


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


def _axes_calibrated(axes: Mapping[str, object]) -> bool:
    for name in ("x", "y"):
        axis = axes.get(name)
        calibration = axis.get("calibration") if isinstance(axis, Mapping) else None
        if not isinstance(calibration, Mapping) or calibration.get("calibrated") is not True:
            return False
    return True


def _axis_calibration_confidence(axes: Mapping[str, object]) -> float:
    values = []
    for name in ("x", "y"):
        axis = axes.get(name)
        calibration = axis.get("calibration") if isinstance(axis, Mapping) else None
        values.append(float(calibration.get("confidence", 0.0)) if isinstance(calibration, Mapping) else 0.0)
    return sum(values) / len(values)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
