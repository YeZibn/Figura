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
    "description": "实际用于此子图的已成功提交测量调用；引用核验不保证数值或语义正确。",
    "type": "object",
    "properties": {
        "run_id": {"description": "真实测量调用所属 Run ID。", "type": "string", "minLength": 1},
        "call_id": {"description": "真实测量工具 call_id，不是装配、OCR 或渲染调用。", "type": "string", "minLength": 1},
    },
    "required": ["run_id", "call_id"],
    "additionalProperties": False,
}

_CHART_FIGURE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "description": "本 Figure 内唯一的子图标识。",
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_CHART_ID_LENGTH,
            "pattern": "^[A-Za-z0-9_-]{1,64}$",
        },
        "chart_spec": CHART_SPEC_DATA_SCHEMA,
        "measurement_refs": {
            "description": "仅列实际采用的测量证据；未采用测量可省略或为空，不得虚构引用。",
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
    "description": "完整新 Figure；修改旧图先读取完整内容再重新提交全部子图，不支持 patch。",
    "type": "object",
    "properties": {
        "schema_version": {
            "description": "当前 Figure schema 版本，必须匹配 const。",
            "type": "integer",
            "const": CHART_FIGURE_SCHEMA_VERSION,
        },
        "title": {"description": "可选整体标题；可拟定有依据的描述性新标题，勿伪称原图文字。", "type": "string", "maxLength": MAX_TEXT_LENGTH},
        "layout": {
            "type": "object",
            "properties": {
                "columns": {
                    "description": "布局列数：1 或 2。",
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_FIGURE_COLUMNS,
                }
            },
            "required": ["columns"],
            "additionalProperties": False,
        },
        "charts": {
            "description": "完整子图列表（1–4 项），按列表顺序排版。",
            "type": "array",
            "items": _CHART_FIGURE_ITEM_SCHEMA,
            "minItems": 1,
            "maxItems": MAX_CHART_FIGURE_ITEMS,
        },
    },
    "required": ["schema_version", "layout", "charts"],
    "additionalProperties": False,
}
