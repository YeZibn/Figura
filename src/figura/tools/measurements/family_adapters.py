"""Adapters from family geometry sensors to the closed measurement v2 union."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from figura.charts.chartspec.models import ChartType

from .bars import measure_bar_pixels
from .contracts import (
    MAX_MEASUREMENT_OBSERVATIONS,
    MAX_MEASUREMENT_WARNINGS,
    MAX_MEASUREMENT_WARNING_LENGTH,
    MeasurementSensorResult,
    PreparedMeasurementImage,
)
from .areas import measure_area
from .boxplots import measure_box_plot
from .histograms import measure_histogram
from .heatmap import measure_heatmap
from .radar import measure_radar
from .treemap import measure_treemap
from .lines import measure_line_pixels
from .pie import _estimate_inner_radius_px, measure_pie_pixels
from .scatter import measure_scatter_pixels


def current_chart_family_adapters() -> dict[ChartType, Any]:
    """Return all family sensors implemented at this migration step."""
    return {
        ChartType.BAR: measure_bar,
        ChartType.LINE: measure_line,
        ChartType.SCATTER: measure_scatter,
        ChartType.PIE: measure_pie,
        ChartType.AREA: measure_area,
        ChartType.HISTOGRAM: measure_histogram,
        ChartType.BOX_PLOT: measure_box_plot,
        ChartType.RADAR: measure_radar,
        ChartType.HEATMAP: measure_heatmap,
        ChartType.TREEMAP: measure_treemap,
    }


def measure_bar(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    raw = measure_bar_pixels(image.rgb, image.observation_mask)
    raw, truncated = _bounded(raw)
    bars = []
    for item in raw["bars"]:
        geometry = item["geometry"]
        left, top, width, height = geometry["bbox_px"]
        observation = {
            "id": str(item["id"]),
            "bounds_px": {"x": left, "y": top, "width": width, "height": height},
            "polygon_px": geometry["polygon_px"],
            "category_id": item["category_tick_id"],
            "category_label": item["category_label"],
            "series_id": item["series_id"],
            "pixel_length_px": item["measure"]["value_length_px"]
            if item["measure"]["value_length_px"] is not None
            else float(height if raw["orientation"] == "vertical" else width),
            "value": item["measure"]["value"],
        }
        bars.append(observation)
    observations = {
        "orientation": raw["orientation"] if raw["orientation"] in {"vertical", "horizontal"} else "unknown",
        "mode": raw["bar_mode"],
        "axes": raw["axes"],
        "baseline_px": raw["baseline"]["points_px"] if raw["baseline"] is not None else None,
        "baseline_value": None,
        "series": raw["series"],
        "bars": bars,
    }
    return _sensor_result(raw, observations, truncated)


def measure_line(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    raw = measure_line_pixels(image.rgb, image.observation_mask)
    raw, truncated = _bounded(raw)
    series = []
    for item in raw["series"]:
        points = [
            {
                "position_px": point["position_px"],
                "x_value": point["x_value"],
                "y_value": point["y_value"],
                "point_source": point["source"],
            }
            for point in item["points"]
        ]
        series.append(
            {
                "id": item["id"],
                "color": item["color"],
                "label": item["label"],
                "label_confidence": item["label_confidence"],
                "segments_px": item["trace"],
                "points": points,
            }
        )
    observations = {"axes": raw["axes"], "series": series}
    return _sensor_result(raw, observations, truncated)


def measure_scatter(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    raw = measure_scatter_pixels(image.rgb, image.observation_mask)
    raw, truncated = _bounded(raw)
    series = []
    for item in raw["series"]:
        points = [
            {
                "center_px": point["position_px"],
                "radius_px": point["radius_px"],
                "x_value": point["x_value"],
                "y_value": point["y_value"],
                "series_id": item["id"],
                "flags": point["flags"],
            }
            for point in item["points"]
        ]
        series.append(
            {
                "id": item["id"],
                "color": item["color"],
                "label": item["label"],
                "label_confidence": item["label_confidence"],
                "points": points,
            }
        )
    observations = {"axes": raw["axes"], "series": series}
    return _sensor_result(raw, observations, truncated)


def measure_pie(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    raw = measure_pie_pixels(image.rgb, image.observation_mask)
    raw, truncated = _bounded(raw)
    region = raw["plot_region"]
    if isinstance(region, Mapping):
        center = region["center_px"]
        radius = region["radius_px"]
        inner_radius = _estimate_inner_radius_px(image.rgb, center, radius, image.observation_mask)
    else:
        center = None
        radius = None
        inner_radius = None
    observations = {
        "center_px": center,
        "outer_radius_px": radius,
        "inner_radius_px": inner_radius,
        "sectors": [
            {
                "start_angle_deg": item["start_angle_deg"],
                "sweep_angle_deg": item["sweep_angle_deg"],
                "ratio": item["ratio"],
                "label": item["label_text"],
                "color": item["color"],
            }
            for item in raw["sectors"]
        ],
    }
    return _sensor_result(raw, observations, truncated, pie_confidence=True)


def _sensor_result(
    raw: Mapping[str, Any],
    observations: Mapping[str, object],
    truncated: bool,
    *,
    pie_confidence: bool = False,
) -> MeasurementSensorResult:
    warnings = [str(message)[:MAX_MEASUREMENT_WARNING_LENGTH] for message in raw.get("warnings", ())]
    if truncated and not any("truncated" in warning.lower() or "limit reached" in warning.lower() for warning in warnings):
        warnings.append("measurement observations reached a shared result bound")
    if len(warnings) > MAX_MEASUREMENT_WARNINGS:
        truncated = True
        warnings = warnings[: MAX_MEASUREMENT_WARNINGS - 1]
        warnings.append("additional measurement warnings were omitted")
    status = raw["status"]
    if truncated and status in {"measured", "no_evidence"}:
        status = "partial"
    confidence = raw["confidence"]
    return MeasurementSensorResult(
        status=status,
        observations=observations,  # type: ignore[arg-type]
        confidence={
            "overall": confidence["overall"],
            "geometry": confidence["geometry"],
            "calibration": confidence["segmentation"] if pie_confidence else confidence["calibration"],
            "association": confidence["association"],
        },
        plot_area_px=raw.get("plot_area_px"),
        warnings=tuple(dict.fromkeys(warnings)),
        truncated=truncated,
    )


def _bounded(value: Any) -> tuple[Any, bool]:
    """Copy detector output while capping every observation list at its shared bound."""
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        truncated = False
        for key, item in value.items():
            copied_item, item_truncated = _bounded(item)
            copied[key] = copied_item
            truncated = truncated or item_truncated
        return copied, truncated
    if isinstance(value, (tuple, list)):
        truncated = len(value) > MAX_MEASUREMENT_OBSERVATIONS
        selected = value[:MAX_MEASUREMENT_OBSERVATIONS]
        copied_items = []
        for item in selected:
            copied_item, item_truncated = _bounded(item)
            copied_items.append(copied_item)
            truncated = truncated or item_truncated
        return copied_items, truncated
    return value, False
