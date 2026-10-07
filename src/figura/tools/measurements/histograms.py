"""Bin geometry and visible numeric intervals for histograms."""

from __future__ import annotations

from collections.abc import Mapping
from statistics import median
from typing import Any

from figura.tools.measurements.cartesian import calibrated_axis_value

from .bars import measure_bar_pixels
from .contracts import MAX_MEASUREMENT_OBSERVATIONS, MeasurementSensorResult, PreparedMeasurementImage


def measure_histogram(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    raw = measure_bar_pixels(image.rgb, image.observation_mask)
    axes = raw["axes"]
    bars = raw["bars"]
    y_measure = _classify_y_measure(axes)
    warnings = list(raw["warnings"])
    if not bars:
        return MeasurementSensorResult(
            status=raw["status"],
            observations={"axes": axes, "y_measure": y_measure, "bins": []},  # type: ignore[arg-type]
            confidence=raw["confidence"],  # type: ignore[arg-type]
            plot_area_px=raw["plot_area_px"],
            warnings=tuple(warnings),
        )

    if raw["orientation"] != "vertical":
        return MeasurementSensorResult(
            status="unsupported",
            observations={"axes": axes, "y_measure": y_measure, "bins": []},  # type: ignore[arg-type]
            confidence=raw["confidence"],  # type: ignore[arg-type]
            plot_area_px=raw["plot_area_px"],
            warnings=tuple([*warnings, "histogram bins must have a vertical numeric interval axis"]),
        )

    ordered_all = sorted(bars, key=lambda item: item["geometry"]["bbox_px"][0])
    truncated = len(ordered_all) > MAX_MEASUREMENT_OBSERVATIONS
    ordered = ordered_all[:MAX_MEASUREMENT_OBSERVATIONS]
    if truncated:
        warnings.append("histogram bin observation limit reached")
    widths = [int(item["geometry"]["bbox_px"][2]) for item in ordered]
    typical_width = max(1.0, float(median(widths)))
    gaps = []
    for first, second in zip(ordered, ordered[1:]):
        first_box, second_box = first["geometry"]["bbox_px"], second["geometry"]["bbox_px"]
        gaps.append(int(second_box[0]) - (int(first_box[0]) + int(first_box[2])))
    if len(ordered) > 1 and any(gap > max(5.0, typical_width * 0.4) for gap in gaps):
        return MeasurementSensorResult(
            status="unsupported",
            observations={"axes": axes, "y_measure": y_measure, "bins": []},  # type: ignore[arg-type]
            confidence=raw["confidence"],  # type: ignore[arg-type]
            plot_area_px=raw["plot_area_px"],
            warnings=tuple([*warnings, "detected bars are separated like categories rather than histogram bins"]),
        )

    x_axis = axes["x"]
    y_axis = axes["y"]
    bins: list[dict[str, object]] = []
    rects = [item["geometry"]["bbox_px"] for item in ordered]
    observed_gaps = [max(0, int(second[0]) - (int(first[0]) + int(first[2])))
                     for first, second in zip(rects, rects[1:])]
    edge_inset = float(median(observed_gaps)) / 2.0 if observed_gaps else 0.0
    interval_edges = [float(rects[0][0]) - edge_inset]
    interval_edges.extend(
        (float(first[0] + first[2]) + float(second[0])) / 2.0
        for first, second in zip(rects, rects[1:])
    )
    interval_edges.append(float(rects[-1][0] + rects[-1][2]) + edge_inset)
    for index, item in enumerate(ordered):
        left, top, width, height = item["geometry"]["bbox_px"]
        baseline = raw["baseline"]["points_px"] if raw["baseline"] is not None else None
        baseline_y = (
            float(baseline[0][1]) + (float(left) - float(baseline[0][0]))
            * (float(baseline[1][1]) - float(baseline[0][1]))
            / max(1e-6, float(baseline[1][0]) - float(baseline[0][0]))
            if baseline is not None and abs(float(baseline[1][0]) - float(baseline[0][0])) > 1e-6
            else float(top + height)
        )
        start_px, end_px = interval_edges[index], interval_edges[index + 1]
        left_edge, right_edge = min(start_px, end_px), max(start_px, end_px)
        baseline_y = float(baseline_y)
        raw_lower = float(top + height)
        raw_upper = float(top)
        # Histogram bars have an antialiased outline; estimate the visible
        # rectangle edge from adjacent bins and move the far edge to the
        # center of its stroke before applying the value-axis fit.
        value_y = raw_upper - 2.25 if abs(raw_upper - baseline_y) >= abs(raw_lower - baseline_y) else raw_lower + 2.25
        value_x = (left_edge + right_edge) / 2.0
        interval_start = calibrated_axis_value([left_edge, baseline_y], x_axis)
        interval_end = calibrated_axis_value([right_edge, baseline_y], x_axis)
        value = calibrated_axis_value([value_x, value_y], y_axis)
        bins.append(
            {
                "bounds_px": {"x": round(left_edge), "y": round(min(value_y, baseline_y)),
                              "width": max(1, round(right_edge - left_edge)),
                              "height": max(1, round(abs(baseline_y - value_y)))},
                "interval_start": interval_start,
                "interval_end": interval_end,
                "value": value,
            }
        )

    values_calibrated = all(item["value"] is not None for item in bins)
    intervals_calibrated = all(item["interval_start"] is not None and item["interval_end"] is not None for item in bins)
    status = "measured" if values_calibrated and intervals_calibrated and y_measure != "unknown" else "partial"
    if truncated:
        status = "partial"
    if not intervals_calibrated:
        warnings.append("histogram numeric intervals are unavailable without x-axis calibration")
    if not values_calibrated:
        warnings.append("histogram values are unavailable without supported y-axis calibration")
    if y_measure == "unknown":
        warnings.append("the visible y-axis does not identify a histogram measure")
    return MeasurementSensorResult(
        status=status,
        observations={"axes": axes, "y_measure": y_measure, "bins": bins},  # type: ignore[arg-type]
        confidence=raw["confidence"],  # type: ignore[arg-type]
        plot_area_px=raw["plot_area_px"],
        warnings=tuple(dict.fromkeys(warnings)),
        truncated=truncated,
    )


def _classify_y_measure(axes: Mapping[str, Any]) -> str:
    axis = axes.get("y")
    if not isinstance(axis, Mapping):
        return "unknown"
    text_values = [axis.get("label_text", "")]
    ticks = axis.get("ticks", ())
    if isinstance(ticks, (tuple, list)):
        text_values.extend(item.get("text", "") for item in ticks if isinstance(item, Mapping))
    text = " ".join(value.lower() for value in text_values if isinstance(value, str))
    if any(token in text for token in ("density", "密度")):
        return "density"
    if any(token in text for token in ("probability", "prob.", "percent", "%", "概率", "百分比")):
        return "probability"
    if any(token in text for token in ("frequency", "频率")):
        return "frequency"
    if any(token in text for token in ("count", "number", "数量", "个数", "计数", "频数")):
        return "count"
    return "unknown"
