"""Authorized source adapter for the scatter-chart measurement sensor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import RunExecutionState

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from ..measurements.scatter import measure_scatter_image
from ..measurements.observation_scope import ObservationScopeError
from .measurement_schema import COMMON_REQUIRED, MEASUREMENT_PROPERTIES, PIXEL_POINT, SOURCE_PARAMETERS
from .measurement_source import resolve_measurement_source


_POINT = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 64},
        "position_px": PIXEL_POINT,
        "x_value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "y_value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "x_tick_id": {"anyOf": [{"type": "string", "maxLength": 64}, {"type": "null"}]},
        "y_tick_id": {"anyOf": [{"type": "string", "maxLength": 64}, {"type": "null"}]},
        "radius_px": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "flags": {"type": "array", "items": {"type": "string", "enum": ["merged", "occluded", "dense", "overlap"]}},
    },
    "required": [
        "id", "position_px", "x_value", "y_value", "x_tick_id", "y_tick_id", "radius_px", "confidence", "flags",
    ],
    "additionalProperties": False,
}

_SERIES = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 32},
        "color": {"type": "string", "pattern": "^#[0-9a-f]{6}$"},
        "label": {"anyOf": [{"type": "string", "maxLength": 128}, {"type": "null"}]},
        "label_confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
        "points": {"type": "array", "items": _POINT},
    },
    "required": ["id", "color", "label", "label_confidence", "points"],
    "additionalProperties": False,
}

MEASURE_SCATTER_RESULT_SCHEMA = {
    "type": "object",
    "properties": {**MEASUREMENT_PROPERTIES, "series": {"type": "array", "items": _SERIES}},
    "required": [*COMMON_REQUIRED, "series"],
    "additionalProperties": False,
}


def measure_scatter_definition(
    image_inventory: Callable[[str, str], RunExecutionState],
    image_reader: RunExecutionImageReader,
) -> ToolDefinition:
    def measure(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        kind, source_id = arguments["source_kind"], arguments["source_id"]
        source = resolve_measurement_source(
            context.session_id,
            kind,
            source_id,
            image_inventory,
            image_reader,
            context.run_id,
        )
        try:
            scope = arguments.get("observation_scope")
            result = measure_scatter_image(source.image_bytes, scope) if scope is not None else measure_scatter_image(source.image_bytes)
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
        name="measure_scatter",
        description=(
            "测量指定附件或 Panel 中的二维散点图，返回源图像像素坐标下的可见点、系列及坐标轴观察。"
            "使用 observation_scope 包含或排除图像区域；省略时分析完整来源。重叠、遮挡或密集标记会作为不确定标记。"
        ),
        parameters_schema=SOURCE_PARAMETERS,
        result_schema=MEASURE_SCATTER_RESULT_SCHEMA,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=measure,
    )
