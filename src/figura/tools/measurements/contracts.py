"""Versioned, closed contracts shared by all chart-family measurement sensors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias, TypedDict

import numpy as np

from figura.charts.chartspec.models import ChartType
from figura.shared.json_schema import JsonValueError, normalize_json_value, validate_instance


MEASUREMENT_RESULT_SCHEMA_VERSION = 2
MAX_MEASUREMENT_OBSERVATIONS = 512
MAX_MEASUREMENT_WARNINGS = 32
MAX_MEASUREMENT_WARNING_LENGTH = 256
MAX_MEASUREMENT_TEXT_LENGTH = 160
MAX_MEASUREMENT_ID_LENGTH = 64
MAX_PIXEL_DIMENSION = 100000

SourceKind = Literal["attachment", "panel"]
CoordinateFrame = Literal["attachment_px", "panel_px"]
MeasurementStatus = Literal["measured", "partial", "no_evidence", "unsupported"]
PixelPoint: TypeAlias = tuple[int | float, int | float]


class PixelRect(TypedDict):
    x: int
    y: int
    width: int
    height: int


class MeasurementConfidence(TypedDict):
    overall: float
    geometry: float
    calibration: float
    association: float


@dataclass(frozen=True)
class PreparedMeasurementImage:
    """Authorized, scope-masked pixels with the source coordinate frame intact."""

    source_kind: SourceKind
    source_id: str
    coordinate_system: CoordinateFrame
    width: int
    height: int
    rgb: np.ndarray
    observation_mask: np.ndarray | None


class AxisTick(TypedDict):
    id: str
    text: str
    value: float | None
    bbox_px: tuple[int, int, int, int]
    point_px: PixelPoint
    confidence: float


class AxisCalibration(TypedDict):
    slope: float
    intercept: float
    residual_value: float
    support_count: int
    support_span_px: float
    confidence: float
    calibrated: bool


class AxisObservation(TypedDict):
    kind: Literal["numeric", "categorical", "unknown"]
    label_text: str | None
    label_confidence: float | None
    points_px: tuple[PixelPoint, PixelPoint] | None
    ticks: list[AxisTick]
    calibration: AxisCalibration | None


class CartesianAxes(TypedDict):
    x: AxisObservation
    y: AxisObservation


class MeasurementSeries(TypedDict):
    id: str
    color: str | None
    label: str | None
    label_confidence: float | None


class BarObservation(TypedDict):
    id: str
    bounds_px: PixelRect
    polygon_px: list[PixelPoint]
    category_id: str | None
    category_label: str | None
    series_id: str | None
    pixel_length_px: float
    value: float | None


class BarObservations(TypedDict):
    orientation: Literal["vertical", "horizontal", "unknown"]
    mode: Literal["single", "grouped", "stacked", "unknown"]
    axes: CartesianAxes
    baseline_px: tuple[PixelPoint, PixelPoint] | None
    baseline_value: float | None
    series: list[MeasurementSeries]
    bars: list[BarObservation]


class LinePoint(TypedDict):
    position_px: PixelPoint
    x_value: float | None
    y_value: float | None
    point_source: Literal["marker", "axis_tick_sample"]


class LineSeries(MeasurementSeries):
    segments_px: list[list[PixelPoint]]
    points: list[LinePoint]


class LineObservations(TypedDict):
    axes: CartesianAxes
    series: list[LineSeries]


class ScatterPoint(TypedDict):
    center_px: PixelPoint
    radius_px: float | None
    x_value: float | None
    y_value: float | None
    series_id: str | None
    flags: list[Literal["merged", "occluded", "dense", "overlap"]]


class ScatterSeries(MeasurementSeries):
    points: list[ScatterPoint]


class ScatterObservations(TypedDict):
    axes: CartesianAxes
    series: list[ScatterSeries]


class PieSector(TypedDict):
    start_angle_deg: float
    sweep_angle_deg: float
    ratio: float | None
    label: str | None
    color: str | None


class PieObservations(TypedDict):
    center_px: PixelPoint | None
    outer_radius_px: float | None
    inner_radius_px: float | None
    sectors: list[PieSector]


class AreaBoundary(TypedDict):
    upper_boundary_px: list[PixelPoint]
    lower_boundary_px: list[PixelPoint] | None
    upper_values: list[float | None]
    lower_values: list[float | None] | None


class AreaSeries(MeasurementSeries):
    segments: list[AreaBoundary]


class AreaObservations(TypedDict):
    axes: CartesianAxes
    stacking: Literal["none", "stacked", "unknown"]
    series: list[AreaSeries]


class HistogramBin(TypedDict):
    bounds_px: PixelRect
    interval_start: float | None
    interval_end: float | None
    value: float | None


class HistogramObservations(TypedDict):
    axes: CartesianAxes
    y_measure: Literal["count", "frequency", "probability", "density", "unknown"]
    bins: list[HistogramBin]


class BoxPlotOutlier(TypedDict):
    position_px: PixelPoint
    value: float | None


class BoxPlotGroup(TypedDict):
    id: str
    label: str | None
    bounds_px: PixelRect | None
    lower_whisker_px: PixelPoint | None
    q1_px: PixelPoint | None
    median_px: PixelPoint | None
    q3_px: PixelPoint | None
    upper_whisker_px: PixelPoint | None
    lower_whisker: float | None
    q1: float | None
    median: float | None
    q3: float | None
    upper_whisker: float | None
    outliers: list[BoxPlotOutlier]


class BoxPlotObservations(TypedDict):
    axes: CartesianAxes
    orientation: Literal["vertical", "horizontal", "unknown"]
    groups: list[BoxPlotGroup]


class RadarSpoke(TypedDict):
    dimension_id: str | None
    label: str | None
    angle_deg: float
    endpoint_px: PixelPoint


class RadarGrid(TypedDict):
    value: float | None
    radius_px: float


class RadarVertex(TypedDict):
    dimension_id: str | None
    position_px: PixelPoint
    value: float | None


class RadarSeries(MeasurementSeries):
    vertices: list[RadarVertex]


class RadarObservations(TypedDict):
    center_px: PixelPoint | None
    spokes: list[RadarSpoke]
    radial_grid: list[RadarGrid]
    series: list[RadarSeries]


class HeatmapCell(TypedDict):
    row_id: str | None
    column_id: str | None
    bounds_px: PixelRect
    color: str | None
    value: float | None


class HeatmapObservations(TypedDict):
    row_labels: list[str | None]
    column_labels: list[str | None]
    cells: list[HeatmapCell]


class TreemapNodeObservation(TypedDict):
    id: str
    parent_id: str | None
    label: str | None
    bounds_px: PixelRect
    value: float | None
    area_ratio: float | None


class TreemapObservations(TypedDict):
    nodes: list[TreemapNodeObservation]


MeasurementObservations: TypeAlias = (
    BarObservations
    | LineObservations
    | ScatterObservations
    | PieObservations
    | AreaObservations
    | HistogramObservations
    | BoxPlotObservations
    | RadarObservations
    | HeatmapObservations
    | TreemapObservations
)


@dataclass(frozen=True)
class MeasurementSensorResult:
    """Family-local evidence before source identity is added by the shared router."""

    status: MeasurementStatus
    observations: MeasurementObservations
    confidence: MeasurementConfidence
    plot_area_px: PixelRect | None = None
    warnings: tuple[str, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.warnings, list):
            object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class MeasurementResultV2:
    chart_type: ChartType
    source_kind: SourceKind
    source_id: str
    image_size: tuple[int, int]
    coordinate_system: CoordinateFrame
    status: MeasurementStatus
    observations: MeasurementObservations
    confidence: MeasurementConfidence
    plot_area_px: PixelRect | None = None
    warnings: tuple[str, ...] = ()
    truncated: bool = False
    schema_version: int = MEASUREMENT_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        width, height = self.image_size
        chart_type = self.chart_type.value if isinstance(self.chart_type, ChartType) else self.chart_type
        return {
            "schema_version": self.schema_version,
            "chart_type": chart_type,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "image_size": {"width": width, "height": height},
            "coordinate_system": self.coordinate_system,
            "status": self.status,
            "plot_area_px": self.plot_area_px,
            "observations": self.observations,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class MeasurementResultIssue:
    code: str
    field_path: str
    message: str


class MeasurementContractError(ValueError):
    def __init__(self, issue: MeasurementResultIssue) -> None:
        self.issue = issue
        super().__init__(issue.message)


def _object(properties: dict[str, object], required: list[str] | None = None) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required is not None:
        schema["required"] = required
    return schema


def _array(items: dict[str, object], *, max_items: int = MAX_MEASUREMENT_OBSERVATIONS, min_items: int = 0) -> dict[str, object]:
    return {"type": "array", "items": items, "minItems": min_items, "maxItems": max_items}


def _nullable(schema: dict[str, object]) -> dict[str, object]:
    return {"anyOf": [schema, {"type": "null"}]}


_NUMBER = {"type": "number"}
_NULLABLE_NUMBER = _nullable(_NUMBER)
_TEXT = {"type": "string", "maxLength": MAX_MEASUREMENT_TEXT_LENGTH}
_NULLABLE_TEXT = _nullable(_TEXT)
_PIXEL_POINT_SCHEMA = {
    "type": "array",
    "items": {"type": "number", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION},
    "minItems": 2,
    "maxItems": 2,
}
_PIXEL_POLYLINE_SCHEMA = _array(_PIXEL_POINT_SCHEMA, min_items=2)
_PIXEL_RECT_SCHEMA = _object(
    {
        "x": {"type": "integer", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION},
        "y": {"type": "integer", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION},
        "width": {"type": "integer", "minimum": 1, "maximum": MAX_PIXEL_DIMENSION},
        "height": {"type": "integer", "minimum": 1, "maximum": MAX_PIXEL_DIMENSION},
    },
    ["x", "y", "width", "height"],
)
_CALIBRATION_SCHEMA = _object(
    {
        "slope": _NUMBER,
        "intercept": _NUMBER,
        "residual_value": {"type": "number", "minimum": 0},
        "support_count": {"type": "integer", "minimum": 2, "maximum": MAX_MEASUREMENT_OBSERVATIONS},
        "support_span_px": {"type": "number", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "calibrated": {"type": "boolean"},
    },
    ["slope", "intercept", "residual_value", "support_count", "support_span_px", "confidence", "calibrated"],
)
_TICK_SCHEMA = _object(
    {
        "id": {"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH},
        "text": {"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_TEXT_LENGTH},
        "value": _NULLABLE_NUMBER,
        "bbox_px": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION},
            "minItems": 4,
            "maxItems": 4,
        },
        "point_px": _PIXEL_POINT_SCHEMA,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    ["id", "text", "value", "bbox_px", "point_px", "confidence"],
)
_AXIS_SCHEMA = _object(
    {
        "kind": {"type": "string", "enum": ["numeric", "categorical", "unknown"]},
        "label_text": _NULLABLE_TEXT,
        "label_confidence": _nullable({"type": "number", "minimum": 0, "maximum": 1}),
        "points_px": _nullable({"type": "array", "items": _PIXEL_POINT_SCHEMA, "minItems": 2, "maxItems": 2}),
        "ticks": _array(_TICK_SCHEMA),
        "calibration": _nullable(_CALIBRATION_SCHEMA),
    },
    ["kind", "label_text", "label_confidence", "points_px", "ticks", "calibration"],
)
_AXES_SCHEMA = _object({"x": _AXIS_SCHEMA, "y": _AXIS_SCHEMA}, ["x", "y"])
_SERIES_SCHEMA = _object(
    {
        "id": {"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH},
        "color": _nullable({"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}),
        "label": _NULLABLE_TEXT,
        "label_confidence": _nullable({"type": "number", "minimum": 0, "maximum": 1}),
    },
    ["id", "color", "label", "label_confidence"],
)

_BAR_SCHEMA = _object(
    {
        "id": {"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH},
        "bounds_px": _PIXEL_RECT_SCHEMA,
        "polygon_px": _array(_PIXEL_POINT_SCHEMA, min_items=3, max_items=8),
        "category_id": _NULLABLE_TEXT,
        "category_label": _NULLABLE_TEXT,
        "series_id": _nullable({"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH}),
        "pixel_length_px": {"type": "number", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION},
        "value": _NULLABLE_NUMBER,
    },
    ["id", "bounds_px", "polygon_px", "category_id", "category_label", "series_id", "pixel_length_px", "value"],
)
_BAR_OBSERVATIONS_SCHEMA = _object(
    {
        "orientation": {"type": "string", "enum": ["vertical", "horizontal", "unknown"]},
        "mode": {"type": "string", "enum": ["single", "grouped", "stacked", "unknown"]},
        "axes": _AXES_SCHEMA,
        "baseline_px": _nullable({"type": "array", "items": _PIXEL_POINT_SCHEMA, "minItems": 2, "maxItems": 2}),
        "baseline_value": _NULLABLE_NUMBER,
        "series": _array(_SERIES_SCHEMA),
        "bars": _array(_BAR_SCHEMA),
    },
    ["orientation", "mode", "axes", "baseline_px", "baseline_value", "series", "bars"],
)

_LINE_POINT_SCHEMA = _object(
    {
        "position_px": _PIXEL_POINT_SCHEMA,
        "x_value": _NULLABLE_NUMBER,
        "y_value": _NULLABLE_NUMBER,
        "point_source": {"type": "string", "enum": ["marker", "axis_tick_sample"]},
    },
    ["position_px", "x_value", "y_value", "point_source"],
)
_LINE_SERIES_SCHEMA = _object(
    {
        **_SERIES_SCHEMA["properties"],
        "segments_px": _array(_PIXEL_POLYLINE_SCHEMA),
        "points": _array(_LINE_POINT_SCHEMA),
    },
    ["id", "color", "label", "label_confidence", "segments_px", "points"],
)
_LINE_OBSERVATIONS_SCHEMA = _object({"axes": _AXES_SCHEMA, "series": _array(_LINE_SERIES_SCHEMA)}, ["axes", "series"])

_SCATTER_POINT_SCHEMA = _object(
    {
        "center_px": _PIXEL_POINT_SCHEMA,
        "radius_px": _nullable({"type": "number", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION}),
        "x_value": _NULLABLE_NUMBER,
        "y_value": _NULLABLE_NUMBER,
        "series_id": _nullable({"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH}),
        "flags": _array({"type": "string", "enum": ["merged", "occluded", "dense", "overlap"]}, max_items=4),
    },
    ["center_px", "radius_px", "x_value", "y_value", "series_id", "flags"],
)
_SCATTER_SERIES_SCHEMA = _object({**_SERIES_SCHEMA["properties"], "points": _array(_SCATTER_POINT_SCHEMA)}, ["id", "color", "label", "label_confidence", "points"])
_SCATTER_OBSERVATIONS_SCHEMA = _object({"axes": _AXES_SCHEMA, "series": _array(_SCATTER_SERIES_SCHEMA)}, ["axes", "series"])

_PIE_SECTOR_SCHEMA = _object(
    {
        "start_angle_deg": {"type": "number", "minimum": 0, "exclusiveMaximum": 360},
        "sweep_angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
        "ratio": _nullable({"type": "number", "minimum": 0, "maximum": 1}),
        "label": _NULLABLE_TEXT,
        "color": _nullable({"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}),
    },
    ["start_angle_deg", "sweep_angle_deg", "ratio", "label", "color"],
)
_PIE_OBSERVATIONS_SCHEMA = _object(
    {
        "center_px": _nullable(_PIXEL_POINT_SCHEMA),
        "outer_radius_px": _nullable({"type": "number", "exclusiveMinimum": 0, "maximum": MAX_PIXEL_DIMENSION}),
        "inner_radius_px": _nullable({"type": "number", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION}),
        "sectors": _array(_PIE_SECTOR_SCHEMA),
    },
    ["center_px", "outer_radius_px", "inner_radius_px", "sectors"],
)

_AREA_BOUNDARY_SCHEMA = _object(
    {
        "upper_boundary_px": _PIXEL_POLYLINE_SCHEMA,
        "lower_boundary_px": _nullable(_PIXEL_POLYLINE_SCHEMA),
        "upper_values": _array(_NULLABLE_NUMBER),
        "lower_values": _nullable(_array(_NULLABLE_NUMBER)),
    },
    ["upper_boundary_px", "lower_boundary_px", "upper_values", "lower_values"],
)
_AREA_SERIES_SCHEMA = _object(
    {**_SERIES_SCHEMA["properties"], "segments": _array(_AREA_BOUNDARY_SCHEMA)},
    ["id", "color", "label", "label_confidence", "segments"],
)
_AREA_OBSERVATIONS_SCHEMA = _object(
    {
        "axes": _AXES_SCHEMA,
        "stacking": {"type": "string", "enum": ["none", "stacked", "unknown"]},
        "series": _array(_AREA_SERIES_SCHEMA),
    },
    ["axes", "stacking", "series"],
)

_HISTOGRAM_BIN_SCHEMA = _object(
    {
        "bounds_px": _PIXEL_RECT_SCHEMA,
        "interval_start": _NULLABLE_NUMBER,
        "interval_end": _NULLABLE_NUMBER,
        "value": _NULLABLE_NUMBER,
    },
    ["bounds_px", "interval_start", "interval_end", "value"],
)
_HISTOGRAM_OBSERVATIONS_SCHEMA = _object(
    {
        "axes": _AXES_SCHEMA,
        "y_measure": {"type": "string", "enum": ["count", "frequency", "probability", "density", "unknown"]},
        "bins": _array(_HISTOGRAM_BIN_SCHEMA),
    },
    ["axes", "y_measure", "bins"],
)

_BOX_OUTLIER_SCHEMA = _object({"position_px": _PIXEL_POINT_SCHEMA, "value": _NULLABLE_NUMBER}, ["position_px", "value"])
_BOX_GROUP_SCHEMA = _object(
    {
        "id": {"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH},
        "label": _NULLABLE_TEXT,
        "bounds_px": _nullable(_PIXEL_RECT_SCHEMA),
        "lower_whisker_px": _nullable(_PIXEL_POINT_SCHEMA),
        "q1_px": _nullable(_PIXEL_POINT_SCHEMA),
        "median_px": _nullable(_PIXEL_POINT_SCHEMA),
        "q3_px": _nullable(_PIXEL_POINT_SCHEMA),
        "upper_whisker_px": _nullable(_PIXEL_POINT_SCHEMA),
        "lower_whisker": _NULLABLE_NUMBER,
        "q1": _NULLABLE_NUMBER,
        "median": _NULLABLE_NUMBER,
        "q3": _NULLABLE_NUMBER,
        "upper_whisker": _NULLABLE_NUMBER,
        "outliers": _array(_BOX_OUTLIER_SCHEMA),
    },
    [
        "id", "label", "bounds_px", "lower_whisker_px", "q1_px", "median_px", "q3_px", "upper_whisker_px",
        "lower_whisker", "q1", "median", "q3", "upper_whisker", "outliers",
    ],
)
_BOX_PLOT_OBSERVATIONS_SCHEMA = _object(
    {
        "axes": _AXES_SCHEMA,
        "orientation": {"type": "string", "enum": ["vertical", "horizontal", "unknown"]},
        "groups": _array(_BOX_GROUP_SCHEMA),
    },
    ["axes", "orientation", "groups"],
)

_RADAR_SPOKE_SCHEMA = _object(
    {
        "dimension_id": _NULLABLE_TEXT,
        "label": _NULLABLE_TEXT,
        "angle_deg": _NUMBER,
        "endpoint_px": _PIXEL_POINT_SCHEMA,
    },
    ["dimension_id", "label", "angle_deg", "endpoint_px"],
)
_RADAR_GRID_SCHEMA = _object({"value": _NULLABLE_NUMBER, "radius_px": {"type": "number", "minimum": 0, "maximum": MAX_PIXEL_DIMENSION}}, ["value", "radius_px"])
_RADAR_VERTEX_SCHEMA = _object({"dimension_id": _NULLABLE_TEXT, "position_px": _PIXEL_POINT_SCHEMA, "value": _NULLABLE_NUMBER}, ["dimension_id", "position_px", "value"])
_RADAR_SERIES_SCHEMA = _object({**_SERIES_SCHEMA["properties"], "vertices": _array(_RADAR_VERTEX_SCHEMA)}, ["id", "color", "label", "label_confidence", "vertices"])
_RADAR_OBSERVATIONS_SCHEMA = _object(
    {
        "center_px": _nullable(_PIXEL_POINT_SCHEMA),
        "spokes": _array(_RADAR_SPOKE_SCHEMA),
        "radial_grid": _array(_RADAR_GRID_SCHEMA),
        "series": _array(_RADAR_SERIES_SCHEMA),
    },
    ["center_px", "spokes", "radial_grid", "series"],
)

_HEATMAP_CELL_SCHEMA = _object(
    {
        "row_id": _NULLABLE_TEXT,
        "column_id": _NULLABLE_TEXT,
        "bounds_px": _PIXEL_RECT_SCHEMA,
        "color": _nullable({"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}),
        "value": _NULLABLE_NUMBER,
    },
    ["row_id", "column_id", "bounds_px", "color", "value"],
)
_HEATMAP_OBSERVATIONS_SCHEMA = _object(
    {
        "row_labels": _array(_NULLABLE_TEXT),
        "column_labels": _array(_NULLABLE_TEXT),
        "cells": _array(_HEATMAP_CELL_SCHEMA),
    },
    ["row_labels", "column_labels", "cells"],
)

_TREEMAP_NODE_SCHEMA = _object(
    {
        "id": {"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH},
        "parent_id": _nullable({"type": "string", "minLength": 1, "maxLength": MAX_MEASUREMENT_ID_LENGTH}),
        "label": _NULLABLE_TEXT,
        "bounds_px": _PIXEL_RECT_SCHEMA,
        "value": _NULLABLE_NUMBER,
        "area_ratio": _nullable({"type": "number", "minimum": 0, "maximum": 1}),
    },
    ["id", "parent_id", "label", "bounds_px", "value", "area_ratio"],
)
_TREEMAP_OBSERVATIONS_SCHEMA = _object({"nodes": _array(_TREEMAP_NODE_SCHEMA)}, ["nodes"])

OBSERVATION_SCHEMAS: dict[str, dict[str, object]] = {
    "bar": _BAR_OBSERVATIONS_SCHEMA,
    "line": _LINE_OBSERVATIONS_SCHEMA,
    "scatter": _SCATTER_OBSERVATIONS_SCHEMA,
    "pie": _PIE_OBSERVATIONS_SCHEMA,
    "area": _AREA_OBSERVATIONS_SCHEMA,
    "histogram": _HISTOGRAM_OBSERVATIONS_SCHEMA,
    "box_plot": _BOX_PLOT_OBSERVATIONS_SCHEMA,
    "radar": _RADAR_OBSERVATIONS_SCHEMA,
    "heatmap": _HEATMAP_OBSERVATIONS_SCHEMA,
    "treemap": _TREEMAP_OBSERVATIONS_SCHEMA,
}

_COMMON_RESULT_PROPERTIES: dict[str, object] = {
    "schema_version": {"type": "integer", "const": MEASUREMENT_RESULT_SCHEMA_VERSION},
    "chart_type": {"type": "string", "enum": [chart_type.value for chart_type in ChartType]},
    "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
    "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "image_size": _object(
        {
            "width": {"type": "integer", "minimum": 1, "maximum": MAX_PIXEL_DIMENSION},
            "height": {"type": "integer", "minimum": 1, "maximum": MAX_PIXEL_DIMENSION},
        },
        ["width", "height"],
    ),
    "coordinate_system": {"type": "string", "enum": ["attachment_px", "panel_px"]},
    "status": {"type": "string", "enum": ["measured", "partial", "no_evidence", "unsupported"]},
    "plot_area_px": _nullable(_PIXEL_RECT_SCHEMA),
    "confidence": _object(
        {
            name: {"type": "number", "minimum": 0, "maximum": 1}
            for name in ("overall", "geometry", "calibration", "association")
        },
        ["overall", "geometry", "calibration", "association"],
    ),
    "warnings": _array({"type": "string", "maxLength": MAX_MEASUREMENT_WARNING_LENGTH}, max_items=MAX_MEASUREMENT_WARNINGS),
    "truncated": {"type": "boolean"},
}
_COMMON_RESULT_REQUIRED = [
    "schema_version", "chart_type", "source_kind", "source_id", "image_size", "coordinate_system", "status",
    "plot_area_px", "observations", "confidence", "warnings", "truncated",
]

_RESULT_VARIANTS = [
    _object(
        {
            **_COMMON_RESULT_PROPERTIES,
            "chart_type": {"type": "string", "const": chart_type},
            "observations": observation_schema,
        },
        _COMMON_RESULT_REQUIRED,
    )
    for chart_type, observation_schema in OBSERVATION_SCHEMAS.items()
]
MEASUREMENT_RESULT_V2_SCHEMA: dict[str, object] = {"type": "object", "anyOf": _RESULT_VARIANTS}


def _issue(code: str, path: str, message: str) -> MeasurementResultIssue:
    return MeasurementResultIssue(code, path[:256], message[:240])


def validate_measurement_result(value: MeasurementResultV2 | Mapping[str, object]) -> MeasurementResultIssue | None:
    """Validate the family discriminator, closed observations, and source-frame pixels."""
    if isinstance(value, MeasurementResultV2):
        try:
            normalized = normalize_json_value(value.to_dict())
        except (JsonValueError, UnicodeEncodeError, RecursionError, OverflowError):
            return _issue("invalid_result", "", "测量结果不是有效的有界 JSON。")
    elif isinstance(value, Mapping):
        try:
            normalized = normalize_json_value(value)
        except (JsonValueError, UnicodeEncodeError, RecursionError, OverflowError):
            return _issue("invalid_result", "", "测量结果不是有效的有界 JSON。")
    else:
        return _issue("invalid_result", "", "测量结果必须是对象。")

    if not isinstance(normalized, dict):
        return _issue("invalid_result", "", "测量结果必须是对象。")
    schema_issue = validate_instance(normalized, MEASUREMENT_RESULT_V2_SCHEMA)
    if schema_issue is not None:
        return _issue(schema_issue.code, schema_issue.pointer, "测量结果字段结构无效。")

    size = normalized["image_size"]
    width, height = size["width"], size["height"]
    if normalized["coordinate_system"] != f"{normalized['source_kind']}_px":
        return _issue("coordinate_frame_mismatch", "/coordinate_system", "测量坐标系必须匹配所选来源。")
    if normalized["truncated"] and normalized["status"] != "partial":
        return _issue("truncation_status_mismatch", "/status", "截断结果必须标记为 partial。")

    pixel_issue = _validate_pixel_coordinates(normalized, width, height)
    if pixel_issue is not None:
        return pixel_issue
    return None


def _validate_pixel_coordinates(value: object, width: int, height: int, path: str = "") -> MeasurementResultIssue | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}/{key}"
            if key in {"center_px", "position_px", "point_px", "endpoint_px"}:
                if not isinstance(item, (tuple, list)) or len(item) != 2:
                    return _issue("invalid_pixel_point", child_path, "像素坐标必须是 [x, y]。")
                x, y = item
                if type(x) not in (int, float) or type(y) not in (int, float) or not 0 <= x <= width or not 0 <= y <= height:
                    return _issue("pixel_out_of_bounds", child_path, "像素坐标超出来源图像边界。")
            elif key == "bounds_px" or key == "plot_area_px":
                if item is not None:
                    if not isinstance(item, Mapping):
                        return _issue("invalid_pixel_bounds", child_path, "像素矩形结构无效。")
                    x, y, rect_width, rect_height = (item.get(field) for field in ("x", "y", "width", "height"))
                    if x < 0 or y < 0 or rect_width < 1 or rect_height < 1 or x + rect_width > width or y + rect_height > height:
                        return _issue("pixel_out_of_bounds", child_path, "像素矩形超出来源图像边界。")
            elif key == "bbox_px":
                if not isinstance(item, (tuple, list)) or len(item) != 4:
                    return _issue("invalid_pixel_bounds", child_path, "像素框必须包含四个整数。")
                x, y, rect_width, rect_height = item
                if x < 0 or y < 0 or rect_width < 1 or rect_height < 1 or x + rect_width > width or y + rect_height > height:
                    return _issue("pixel_out_of_bounds", child_path, "像素框超出来源图像边界。")
            elif key in {"points_px", "polygon_px", "segments_px", "upper_boundary_px", "lower_boundary_px", "baseline_px"}:
                point_issue = _validate_pixel_point_collection(item, width, height, child_path)
                if point_issue is not None:
                    return point_issue
                continue
            elif key.endswith("_px") and type(item) in (int, float):
                if item < 0 or item > max(width, height):
                    return _issue("pixel_out_of_bounds", child_path, "像素长度超出来源图像边界。")
            nested_issue = _validate_pixel_coordinates(item, width, height, child_path)
            if nested_issue is not None:
                return nested_issue
        return None
    if isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            nested_issue = _validate_pixel_coordinates(item, width, height, f"{path}/{index}")
            if nested_issue is not None:
                return nested_issue
    return None


def _validate_pixel_point_collection(value: object, width: int, height: int, path: str) -> MeasurementResultIssue | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)):
        return _issue("invalid_pixel_point", path, "像素点集合结构无效。")
    if len(value) == 2 and all(type(item) in (int, float) for item in value):
        x, y = value
        if not 0 <= x <= width or not 0 <= y <= height:
            return _issue("pixel_out_of_bounds", path, "像素坐标超出来源图像边界。")
        return None
    for index, point in enumerate(value):
        point_issue = _validate_pixel_point_collection(point, width, height, f"{path}/{index}")
        if point_issue is not None:
            return point_issue
    return None
