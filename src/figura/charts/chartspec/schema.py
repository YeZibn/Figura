"""Closed JSON Schema for the ChartSpec v2 content contract."""

from __future__ import annotations

from typing import Any

from ..limits import MAX_TEXT_LENGTH
from .limits import CHART_SPEC_SCHEMA_VERSION, MAX_DATA_POINTS, MAX_FINITE_NUMBER

MAX_ID_LENGTH = 64


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _array(items: dict[str, Any], *, minimum: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": MAX_DATA_POINTS}


_ID = {"type": "string", "minLength": 1, "maxLength": MAX_ID_LENGTH}
_LABEL = {"type": "string", "maxLength": MAX_TEXT_LENGTH}
_NUMBER = {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER}
_NONNEGATIVE = {"type": "number", "minimum": 0, "maximum": MAX_FINITE_NUMBER}
_POSITIVE = {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_FINITE_NUMBER}
_NULLABLE_NUMBER = {"anyOf": [_NUMBER, {"type": "null"}]}

_CATEGORY = _object({"id": _ID, "label": _LABEL}, ["id", "label"])
_VALUE_SERIES = _object(
    {"id": _ID, "label": _LABEL, "values": _array(_NUMBER, minimum=1)},
    ["id", "label", "values"],
)
_BAR_DATASET = _object(
    {
        "orientation": {"type": "string", "enum": ["vertical", "horizontal"]},
        "mode": {"type": "string", "enum": ["grouped", "stacked"]},
        "categories": _array(_CATEGORY, minimum=1),
        "series": _array(_VALUE_SERIES, minimum=1),
    },
    ["orientation", "mode", "categories", "series"],
)

_XY_POINT = _object(
    {"x": {"anyOf": [_NUMBER, {"type": "string", "maxLength": MAX_TEXT_LENGTH}]}, "y": _NULLABLE_NUMBER},
    ["x", "y"],
)
_XY_SERIES = _object(
    {"id": _ID, "label": _LABEL, "points": _array(_XY_POINT, minimum=1)},
    ["id", "label", "points"],
)
_LINE_DATASET = _object({"series": _array(_XY_SERIES, minimum=1)}, ["series"])
_AREA_DATASET = _object(
    {"stacking": {"type": "string", "enum": ["none", "stacked"]}, "series": _array(_XY_SERIES, minimum=1)},
    ["stacking", "series"],
)

_SCATTER_POINT = _object(
    {"x": _NUMBER, "y": _NUMBER, "size": _POSITIVE},
    ["x", "y"],
)
_SCATTER_SERIES = _object(
    {"id": _ID, "label": _LABEL, "points": _array(_SCATTER_POINT, minimum=1)},
    ["id", "label", "points"],
)
_SCATTER_DATASET = _object({"series": _array(_SCATTER_SERIES, minimum=1)}, ["series"])

_PIE_SLICE = _object({"id": _ID, "label": _LABEL, "value": _NONNEGATIVE}, ["id", "label", "value"])
_PIE_DATASET = _object(
    {
        "slices": _array(_PIE_SLICE, minimum=1),
        "inner_radius_ratio": {"type": "number", "minimum": 0, "maximum": 0.75},
    },
    ["slices"],
)

_HISTOGRAM_BIN = _object({"start": _NUMBER, "end": _NUMBER, "value": _NONNEGATIVE}, ["start", "end", "value"])
_HISTOGRAM_DATASET = _object(
    {
        "measure": {"type": "string", "enum": ["count", "frequency", "probability", "density", "unknown"]},
        "bins": _array(_HISTOGRAM_BIN, minimum=1),
    },
    ["measure", "bins"],
)

_BOX_GROUP = _object(
    {
        "id": _ID,
        "label": _LABEL,
        "lower_whisker": _NUMBER,
        "q1": _NUMBER,
        "median": _NUMBER,
        "q3": _NUMBER,
        "upper_whisker": _NUMBER,
        "outliers": _array(_NUMBER),
    },
    ["id", "label", "lower_whisker", "q1", "median", "q3", "upper_whisker"],
)
_BOX_PLOT_DATASET = _object(
    {"orientation": {"type": "string", "enum": ["vertical", "horizontal"]}, "groups": _array(_BOX_GROUP, minimum=1)},
    ["orientation", "groups"],
)

_RADAR_DIMENSION = _CATEGORY
_RADAR_DATASET = _object(
    {"dimensions": _array(_RADAR_DIMENSION, minimum=3), "series": _array(_VALUE_SERIES, minimum=1)},
    ["dimensions", "series"],
)

_MATRIX_ROW = _array(_NULLABLE_NUMBER, minimum=1)
_HEATMAP_DATASET = _object(
    {
        "x_categories": _array(_CATEGORY, minimum=1),
        "y_categories": _array(_CATEGORY, minimum=1),
        "values": _array(_MATRIX_ROW, minimum=1),
    },
    ["x_categories", "y_categories", "values"],
)

_TREEMAP_NODE = _object(
    {
        "id": _ID,
        "parent_id": {"anyOf": [_ID, {"type": "null"}]},
        "label": _LABEL,
        "value": _NONNEGATIVE,
    },
    ["id", "parent_id", "label"],
)
_TREEMAP_DATASET = _object(
    {"root_id": _ID, "nodes": _array(_TREEMAP_NODE, minimum=1)},
    ["root_id", "nodes"],
)

ChartTypeName = str
CHART_DATASET_SCHEMAS: dict[ChartTypeName, dict[str, Any]]
CHART_TYPE_VALUES = (
    "bar",
    "line",
    "scatter",
    "pie",
    "area",
    "histogram",
    "box_plot",
    "radar",
    "heatmap",
    "treemap",
)
CHART_DATASET_SCHEMAS = {
    "bar": _BAR_DATASET,
    "line": _LINE_DATASET,
    "scatter": _SCATTER_DATASET,
    "pie": _PIE_DATASET,
    "area": _AREA_DATASET,
    "histogram": _HISTOGRAM_DATASET,
    "box_plot": _BOX_PLOT_DATASET,
    "radar": _RADAR_DATASET,
    "heatmap": _HEATMAP_DATASET,
    "treemap": _TREEMAP_DATASET,
}

_AXIS = _object(
    {
        "kind": {"type": "string", "enum": ["categorical", "numeric", "time"]},
        "label": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
    },
    ["kind"],
)
_CARTESIAN_COORDINATE_SYSTEM = _object(
    {"kind": {"type": "string", "const": "cartesian"}, "x_axis": _AXIS, "y_axis": _AXIS},
    ["kind", "x_axis", "y_axis"],
)
_POLAR_COORDINATE_SYSTEM = _object(
    {
        "kind": {"type": "string", "const": "polar"},
        "value_range": _object({"min": _NUMBER, "max": _NUMBER}, ["min", "max"]),
    },
    ["kind", "value_range"],
)
_SIMPLE_COORDINATE_SYSTEMS = [
    _object({"kind": {"type": "string", "const": kind}}, ["kind"])
    for kind in ("matrix", "hierarchical", "none")
]
_COORDINATE_SYSTEM = {
    "anyOf": [_CARTESIAN_COORDINATE_SYSTEM, _POLAR_COORDINATE_SYSTEM, *_SIMPLE_COORDINATE_SYSTEMS]
}

_METADATA_SCHEMA = _object(
    {
        "chart_type": {"type": "string", "enum": list(CHART_TYPE_VALUES)},
        "title": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
        "source": {"anyOf": [{"type": "string", "maxLength": MAX_TEXT_LENGTH}, {"type": "null"}]},
        "note": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
    },
    ["chart_type"],
)

CHART_SPEC_DATA_SCHEMA: dict[str, Any] = _object(
    {
        "schema_version": {"type": "integer", "const": CHART_SPEC_SCHEMA_VERSION},
        "metadata": _METADATA_SCHEMA,
        "coordinate_system": _COORDINATE_SYSTEM,
        "dataset": {"anyOf": list(CHART_DATASET_SCHEMAS.values())},
    },
    ["schema_version", "metadata", "coordinate_system", "dataset"],
)
