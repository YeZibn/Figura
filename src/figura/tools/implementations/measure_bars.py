"""Authorized source adapter for the JSON-only bar measurement sensor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.sources.attachments import FiguraAttachmentService
from figura.sources.panels import FiguraPanelService

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from ..measurements.bars import measure_bar_image
from ..measurements.observation_scope import ObservationScopeError
from .measurement_schema import COMMON_REQUIRED, MEASUREMENT_PROPERTIES, SOURCE_PARAMETERS
from .measurement_source import resolve_measurement_source


_PIXEL_POINT = {
    "type": "array",
    "items": {"type": "integer", "minimum": 0, "maximum": 100000},
    "minItems": 2,
    "maxItems": 2,
}
_GEOMETRY = {
    "type": "object",
    "properties": {
        "bbox_px": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 100000},
            "minItems": 4,
            "maxItems": 4,
        },
        "polygon_px": {"type": "array", "items": _PIXEL_POINT, "minItems": 4, "maxItems": 4},
    },
    "required": ["bbox_px", "polygon_px"],
    "additionalProperties": False,
}
_BASELINE = {
    "type": "object",
    "properties": {
        "points_px": {"type": "array", "items": _PIXEL_POINT, "minItems": 2, "maxItems": 2},
        "axis": {"type": "string", "enum": ["x", "y"]},
        "slope": {"type": "number"},
        "intercept": {"type": "number"},
        "residual_px": {"type": "number", "minimum": 0},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["points_px", "axis", "slope", "intercept", "residual_px", "confidence"],
    "additionalProperties": False,
}
_SERIES = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 32},
        "color": {"type": "string", "pattern": "^#[0-9a-f]{6}$"},
        "label": {"anyOf": [{"type": "string", "maxLength": 128}, {"type": "null"}]},
        "label_confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
    },
    "required": ["id", "color", "label", "label_confidence"],
    "additionalProperties": False,
}
_STACK = {
    "type": "object",
    "properties": {
        "segment_index": {"type": "integer", "minimum": 1},
        "total_length_px": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]},
        "total_geometry": _GEOMETRY,
        "total_value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    },
    "required": ["segment_index", "total_length_px", "total_geometry", "total_value"],
    "additionalProperties": False,
}
_BAR = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "minimum": 1},
        "category_index": {"type": "integer", "minimum": 1},
        "category_label": {"anyOf": [{"type": "string", "maxLength": 128}, {"type": "null"}]},
        "category_tick_id": {"anyOf": [{"type": "string", "maxLength": 64}, {"type": "null"}]},
        "series_id": {"type": "string", "minLength": 1, "maxLength": 32},
        "geometry": _GEOMETRY,
        "measure": {
            "type": "object",
            "properties": {
                "value_length_px": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "ratio_to_shortest": {"anyOf": [{"type": "number", "minimum": 1}, {"type": "null"}]},
                "value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            },
            "required": ["value_length_px", "ratio_to_shortest", "value"],
            "additionalProperties": False,
        },
        "stack": {"anyOf": [_STACK, {"type": "null"}]},
    },
    "required": ["id", "category_index", "category_label", "category_tick_id", "series_id", "geometry", "measure"],
    "additionalProperties": False,
}
_RESULT = {
    "type": "object",
    "properties": {
        **MEASUREMENT_PROPERTIES,
        "orientation": {"type": "string", "enum": ["vertical", "horizontal", "oblique", "unknown"]},
        "bar_mode": {"type": "string", "enum": ["single", "grouped", "stacked", "unknown"]},
        "baseline": {"anyOf": [_BASELINE, {"type": "null"}]},
        "series": {"type": "array", "items": _SERIES},
        "bars": {"type": "array", "items": _BAR},
    },
    "required": [*COMMON_REQUIRED, "orientation", "bar_mode", "baseline", "series", "bars"],
    "additionalProperties": False,
}


def measure_bars_definition(
    image_inventory: Callable[[str, str], _RunImageInventory],
    attachments: FiguraAttachmentService,
    panels: FiguraPanelService,
) -> ToolDefinition:
    def measure(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        kind, source_id = arguments["source_kind"], arguments["source_id"]
        source = resolve_measurement_source(
            context.session_id,
            kind,
            source_id,
            image_inventory,
            attachments,
            panels,
            context.run_id,
        )

        try:
            scope = arguments.get("observation_scope")
            result = measure_bar_image(source.image_bytes, scope) if scope is not None else measure_bar_image(source.image_bytes)
        except ObservationScopeError:
            raise ToolFailure("invalid_observation_scope", "图像观察范围无效或不包含可观察像素。") from None
        except ValueError:
            raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True) from None
        result.update({
            "source_kind": kind,
            "source_id": source_id,
            "coordinate_system": source.coordinate_system,
        })
        return result

    return ToolDefinition(
        name="measure_bars",
        description=(
            "测量指定附件或 Panel 中的二维柱状图，返回图像像素坐标下的柱体几何、基线、相对长度和置信度。"
            "使用 observation_scope 包含或排除图像区域；省略时分析完整来源。警告和不确定结果由你判断，不会自动重试。"
        ),
        parameters_schema=SOURCE_PARAMETERS,
        result_schema=_RESULT,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=measure,
    )
