"""Authorized source adapter for the JSON-only bar measurement sensor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from figura.runtime.errors import RunError
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.models import PanelRecord
from figura.sources.panels import FiguraPanelService

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from ..measurements.bars import measure_bar_image


class _AvailableAttachment(Protocol):
    attachment_id: str


class _RunImageInventory(Protocol):
    available_attachments: tuple[_AvailableAttachment, ...]
    panels: tuple[PanelRecord, ...]


_SOURCE_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["source_kind", "source_id"],
    "additionalProperties": False,
}

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
    },
    "required": ["id", "color"],
    "additionalProperties": False,
}
_STACK = {
    "type": "object",
    "properties": {
        "segment_index": {"type": "integer", "minimum": 1},
        "total_length_px": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]},
        "total_geometry": _GEOMETRY,
    },
    "required": ["segment_index", "total_length_px", "total_geometry"],
    "additionalProperties": False,
}
_BAR = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "minimum": 1},
        "category_index": {"type": "integer", "minimum": 1},
        "series_id": {"type": "string", "minLength": 1, "maxLength": 32},
        "geometry": _GEOMETRY,
        "measure": {
            "type": "object",
            "properties": {
                "value_length_px": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "ratio_to_shortest": {"anyOf": [{"type": "number", "minimum": 1}, {"type": "null"}]},
            },
            "required": ["value_length_px", "ratio_to_shortest"],
            "additionalProperties": False,
        },
        "stack": {"anyOf": [_STACK, {"type": "null"}]},
    },
    "required": ["id", "category_index", "series_id", "geometry", "measure"],
    "additionalProperties": False,
}
_RESULT = {
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
        "orientation": {"type": "string", "enum": ["vertical", "horizontal", "oblique", "unknown"]},
        "bar_mode": {"type": "string", "enum": ["single", "grouped", "stacked", "unknown"]},
        "plot_area_px": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "minimum": 0},
                        "y": {"type": "integer", "minimum": 0},
                        "width": {"type": "integer", "minimum": 1},
                        "height": {"type": "integer", "minimum": 1},
                    },
                    "required": ["x", "y", "width", "height"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
        "baseline": {"anyOf": [_BASELINE, {"type": "null"}]},
        "series": {"type": "array", "items": _SERIES},
        "bars": {"type": "array", "items": _BAR},
        "confidence": {
            "type": "object",
            "properties": {
                "overall": {"type": "number", "minimum": 0, "maximum": 1},
                "geometry": {"type": "number", "minimum": 0, "maximum": 1},
                "baseline": {"type": "number", "minimum": 0, "maximum": 1},
                "association": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["overall", "geometry", "baseline", "association"],
            "additionalProperties": False,
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "source_kind", "source_id", "image_size", "coordinate_system", "status", "orientation",
        "bar_mode", "plot_area_px", "baseline", "series", "bars", "confidence", "warnings",
    ],
    "additionalProperties": False,
}


def measure_bars_definition(
    image_inventory: Callable[[str, str], _RunImageInventory],
    attachments: FiguraAttachmentService,
    panels: FiguraPanelService,
) -> ToolDefinition:
    def measure(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        kind, source_id = arguments["source_kind"], arguments["source_id"]
        state = image_inventory(context.session_id, context.run_id)
        if kind == "attachment":
            if not any(item.attachment_id == source_id for item in state.available_attachments):
                raise ToolFailure("image_not_available", "请求的附件不在当前 Session 的可用清单中。")
            try:
                image = attachments.resolve(context.session_id, source_id)
            except RunError:
                raise ToolFailure("image_unavailable", "附件图像当前无法读取。", retryable=True) from None
            image_bytes = image.image_bytes
            coordinate_system = "attachment_px"
        else:
            if not any(item.panel_id == source_id for item in state.panels):
                raise ToolFailure("image_not_available", "请求的 Panel 不在当前 Session 的可用清单中。")
            try:
                _record, image, _width, _height = panels.resolve(context.session_id, source_id)
            except RunError:
                raise ToolFailure("image_unavailable", "Panel 图像当前无法读取。", retryable=True) from None
            image_bytes = image.image_bytes
            coordinate_system = "panel_px"

        try:
            result = measure_bar_image(image_bytes)
        except ValueError:
            raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True) from None
        result.update({
            "source_kind": kind,
            "source_id": source_id,
            "coordinate_system": coordinate_system,
        })
        return result

    return ToolDefinition(
        name="measure_bars",
        description=(
            "测量指定附件或 Panel 中的二维柱状图，返回图像像素坐标下的柱体几何、基线、相对长度和置信度。"
            "只能使用 source_kind 与 source_id 选择图像；警告和不确定结果由你判断，不会自动重试。"
        ),
        parameters_schema=_SOURCE_PARAMETERS,
        result_schema=_RESULT,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=measure,
    )
