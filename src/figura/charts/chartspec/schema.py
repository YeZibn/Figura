"""JSON Schema for ChartSpecData."""

from __future__ import annotations

from typing import Any

from ..limits import MAX_TEXT_LENGTH
from .limits import CHART_SPEC_SCHEMA_VERSION, MAX_DATA_POINTS, MAX_FINITE_NUMBER


_SERIES_SCHEMA: dict[str, Any] = {
    "description": "系列名称；bar/line/scatter 可使用，省略表示未命名系列；pie 不提供此字段。",
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_TEXT_LENGTH,
}

_CATEGORY_POINT_SCHEMA: dict[str, Any] = {
    "description": "bar/pie 数据点使用 category/value；类别名称必须非空。",
    "type": "object",
    "properties": {
        "category": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH},
        "value": {"description": "bar 可正可负；pie 必须非负且全图总和大于零，可用相对占比而不虚构绝对总量。", "type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "series": _SERIES_SCHEMA,
    },
    "required": ["category", "value"],
    "additionalProperties": False,
}

_COORDINATE_POINT_SCHEMA: dict[str, Any] = {
    "description": "line/scatter 数据点使用 x/y；line 同一系列的 x 按输入顺序严格递增且不重复。",
    "type": "object",
    "properties": {
        "x": {"description": "数值横坐标；类别折线则为 axes.x.categories 中的 0-based 整数位置。", "type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "y": {"type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "series": _SERIES_SCHEMA,
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}

_AXIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"description": "有依据的轴标签；可作描述性命名，不得补造原图单位或刻度。", "type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH},
        "categories": {
            "description": "仅 x 轴 bar/line 使用；bar 每个系列须覆盖全部类别且同系列同类别唯一，类别 line 每系列须覆盖所有位置；scatter 不支持。",
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH},
            "minItems": 1,
            "maxItems": MAX_DATA_POINTS,
            "uniqueItems": True,
        },
        "min_value": {"description": "可选数值下界，须涵盖数据并小于上界；类别横轴不得设置数值范围。", "type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
        "max_value": {"description": "可选数值上界，须涵盖数据并大于下界；类别横轴不得设置数值范围。", "type": "number", "minimum": -MAX_FINITE_NUMBER, "maximum": MAX_FINITE_NUMBER},
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
            "description": "bar/pie 使用 category/value，line/scatter 使用 x/y；pie 不提供 series、axes 为 null，多个饼图作为独立 Figure 子图。",
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
