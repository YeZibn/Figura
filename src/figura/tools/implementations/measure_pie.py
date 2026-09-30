"""Authorized source adapter for polar pie-chart observations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import RunExecutionState

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from ..measurements.observation_scope import ObservationScopeError
from ..measurements.pie import measure_pie_image
from .measurement_schema import SOURCE_PARAMETERS
from .measurement_source import resolve_measurement_source

_PIXEL_POINT = {
    "type": "array",
    "items": {"type": "number", "minimum": 0, "maximum": 100000},
    "minItems": 2,
    "maxItems": 2,
}
_PLOT_REGION = {
    "type": "object",
    "properties": {
        "center_px": _PIXEL_POINT,
        "radius_px": {"type": "number", "exclusiveMinimum": 0, "maximum": 100000},
    },
    "required": ["center_px", "radius_px"],
    "additionalProperties": False,
}
_SECTOR = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "minimum": 1, "maximum": 512},
        "start_angle_deg": {"type": "number", "minimum": 0, "exclusiveMaximum": 360},
        "sweep_angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
        "ratio": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
        "color": {"anyOf": [{"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}, {"type": "null"}]},
        "label_text": {"anyOf": [{"type": "string", "maxLength": 128}, {"type": "null"}]},
        "label_confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "id",
        "start_angle_deg",
        "sweep_angle_deg",
        "ratio",
        "color",
        "label_text",
        "label_confidence",
        "confidence",
    ],
    "additionalProperties": False,
}
_CONFIDENCE = {
    "type": "object",
    "properties": {
        name: {"type": "number", "minimum": 0, "maximum": 1}
        for name in ("overall", "geometry", "segmentation", "association")
    },
    "required": ["overall", "geometry", "segmentation", "association"],
    "additionalProperties": False,
}
MEASURE_PIE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "image_size": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "minimum": 1, "maximum": 100000},
                "height": {"type": "integer", "minimum": 1, "maximum": 100000},
            },
            "required": ["width", "height"],
            "additionalProperties": False,
        },
        "coordinate_system": {"type": "string", "enum": ["attachment_px", "panel_px"]},
        "status": {"type": "string", "enum": ["measured", "partial", "no_evidence", "unsupported"]},
        "plot_region": {"anyOf": [_PLOT_REGION, {"type": "null"}]},
        "sectors": {"type": "array", "items": _SECTOR, "maxItems": 512},
        "confidence": _CONFIDENCE,
        "warnings": {"type": "array", "items": {"type": "string", "maxLength": 256}, "maxItems": 32},
    },
    "required": [
        "source_kind",
        "source_id",
        "image_size",
        "coordinate_system",
        "status",
        "plot_region",
        "sectors",
        "confidence",
        "warnings",
    ],
    "additionalProperties": False,
}


def measure_pie_definition(
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
            result = (
                measure_pie_image(source.image_bytes, scope)
                if scope is not None
                else measure_pie_image(source.image_bytes)
            )
        except ObservationScopeError:
            raise ToolFailure(
                "invalid_observation_scope",
                "图像观察范围无效或不包含可观察像素。",
            ) from None
        except ValueError:
            raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True) from None
        result.update({
            "source_kind": kind,
            "source_id": source_id,
            "coordinate_system": source.coordinate_system,
        })
        return result

    return ToolDefinition(
        name="measure_pie",
        description=(
            "测量指定附件或 Panel 中的二维圆形饼图，返回像素坐标下的圆心、半径、扇区角度、"
            "有证据支持的比例、颜色、OCR 标签及置信度。使用 observation_scope 限定观察区域。"
            "不支持甜甜圈、爆炸、椭圆、透视或 3D 饼图；警告不会自动触发重试。"
        ),
        parameters_schema=SOURCE_PARAMETERS,
        result_schema=MEASURE_PIE_RESULT_SCHEMA,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=measure,
    )
