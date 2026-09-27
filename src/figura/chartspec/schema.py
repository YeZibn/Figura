"""JSON Schema for the local shape of version 1 ChartSpecData."""

from __future__ import annotations

from typing import Any

from .limits import (
    CHART_SPEC_SCHEMA_VERSION,
    MAX_DATA_POINTS,
    MAX_FINITE_NUMBER,
    MAX_TEXT_LENGTH,
)


_SERIES_SCHEMA: dict[str, Any] = {
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
