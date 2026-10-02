"""JSON Schema for ChartSpecData."""

from __future__ import annotations

from typing import Any

from ..limits import MAX_TEXT_LENGTH
from .limits import CHART_SPEC_SCHEMA_VERSION, MAX_DATA_POINTS, MAX_FINITE_NUMBER


_SERIES_SCHEMA: dict[str, Any] = {
    "description": "系列名称；pie 不提供此字段。",
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_TEXT_LENGTH,
}

_CATEGORY_POINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH},
        "value": {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "series": _SERIES_SCHEMA,
    },
    "required": ["category", "value"],
    "additionalProperties": False,
}

_COORDINATE_POINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "x": {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "y": {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "series": _SERIES_SCHEMA,
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}

_AXIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH},
        "categories": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH},
            "minItems": 1,
            "maxItems": MAX_DATA_POINTS,
            "uniqueItems": True,
        },
        "min_value": {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "max_value": {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
    },
    "required": ["label"],
    "additionalProperties": False,
}

_METADATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_type": {
            "type": "string",
            "enum": ["bar", "line", "pie", "scatter"],
        },
        "title": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
        "source": {
            "anyOf": [
                {"type": "string", "maxLength": MAX_TEXT_LENGTH},
                {"type": "null"},
            ]
        },
        "note": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
    },
    "required": ["chart_type"],
    "additionalProperties": False,
}


CHART_SPEC_DATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {
            "type": "integer",
            "const": CHART_SPEC_SCHEMA_VERSION,
        },
        "metadata": _METADATA_SCHEMA,
        "axes": {
            "description": "bar/line/scatter 需要坐标轴；pie 使用 null。",
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "x": _AXIS_SCHEMA,
                        "y": _AXIS_SCHEMA,
                    },
                    "required": ["x", "y"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
        "dataset": {
            "description": "pie 使用 category/value，不提供 series；多个系列作为独立 ChartFigure 子图。",
            "type": "array",
            "items": {
                "anyOf": [
                    _CATEGORY_POINT_SCHEMA,
                    _COORDINATE_POINT_SCHEMA,
                ]
            },
            "minItems": 1,
            "maxItems": MAX_DATA_POINTS,
        },
    },
    "required": ["schema_version", "metadata", "axes", "dataset"],
    "additionalProperties": False,
}
