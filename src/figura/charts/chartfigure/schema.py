"""JSON Schema for ChartFigure and its children."""

from __future__ import annotations

from typing import Any

from ..chartspec.schema import CHART_SPEC_DATA_SCHEMA
from ..limits import MAX_TEXT_LENGTH
from .limits import (
    CHART_FIGURE_SCHEMA_VERSION,
    MAX_CHART_FIGURE_ITEMS,
    MAX_CHART_ID_LENGTH,
    MAX_FIGURE_COLUMNS,
    MAX_MEASUREMENT_REFS_PER_CHART,
)


_MEASUREMENT_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "minLength": 1},
        "call_id": {"type": "string", "minLength": 1},
    },
    "required": ["run_id", "call_id"],
    "additionalProperties": False,
}

_CHART_FIGURE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_CHART_ID_LENGTH,
            "pattern": "^[A-Za-z0-9_-]{1,64}$",
        },
        "chart_spec": CHART_SPEC_DATA_SCHEMA,
        "measurement_refs": {
            "type": "array",
            "items": _MEASUREMENT_REF_SCHEMA,
            "maxItems": MAX_MEASUREMENT_REFS_PER_CHART,
            "uniqueItems": True,
        },
    },
    "required": ["chart_id", "chart_spec"],
    "additionalProperties": False,
}

CHART_FIGURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {
            "type": "integer",
            "const": CHART_FIGURE_SCHEMA_VERSION,
        },
        "title": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
        "layout": {
            "type": "object",
            "properties": {
                "columns": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_FIGURE_COLUMNS,
                }
            },
            "required": ["columns"],
            "additionalProperties": False,
        },
        "charts": {
            "type": "array",
            "items": _CHART_FIGURE_ITEM_SCHEMA,
            "minItems": 1,
            "maxItems": MAX_CHART_FIGURE_ITEMS,
        },
    },
    "required": ["schema_version", "layout", "charts"],
    "additionalProperties": False,
}
