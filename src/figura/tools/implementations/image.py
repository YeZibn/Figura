"""Figura image inventory and polygon decomposition tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from io import BytesIO
from PIL import Image
from figura.runtime.errors import RunError, RunErrorCode
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.models import PanelPoint, PanelRecord
from figura.sources.panels import FiguraPanelService

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure


class _AvailableAttachment(Protocol):
    attachment_id: str


class _RunImageInventory(Protocol):
    available_attachments: tuple[_AvailableAttachment, ...]
    panels: tuple[PanelRecord, ...]


_LOAD_IMAGE_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["source_kind", "source_id"],
    "additionalProperties": False,
}
_LOAD_IMAGE_RESULT = {
    "type": "object",
    "properties": {
        "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "name": {"type": "string", "minLength": 1, "maxLength": 256},
        "width": {"type": "integer", "minimum": 1, "maximum": 100000},
        "height": {"type": "integer", "minimum": 1, "maximum": 100000},
    },
    "required": ["source_kind", "source_id", "name", "width", "height"],
    "additionalProperties": False,
}
_POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "integer", "minimum": 0, "maximum": 1000},
        "y": {"type": "integer", "minimum": 0, "maximum": 1000},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}
_PANEL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 256},
        "points": {"type": "array", "items": _POINT_SCHEMA, "minItems": 3, "maxItems": 64},
    },
    "required": ["name", "points"],
    "additionalProperties": False,
}
_DECOMPOSE_PARAMETERS = {
    "type": "object",
    "properties": {
        "attachment_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "panels": {"type": "array", "items": _PANEL_INPUT_SCHEMA, "minItems": 1, "maxItems": 32},
    },
    "required": ["attachment_id", "panels"],
    "additionalProperties": False,
}
_DECOMPOSE_RESULT = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "panel_id": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 256},
                    "source_attachment_id": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "required": ["panel_id", "name", "source_attachment_id"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 32,
        },
    },
    "required": ["panels"],
    "additionalProperties": False,
}


def image_tool_definitions(
    image_inventory: Callable[[str, str], _RunImageInventory],
    attachments: FiguraAttachmentService,
    panels: FiguraPanelService,
) -> tuple[ToolDefinition, ToolDefinition]:
    def load_image(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        state = image_inventory(_context.session_id, _context.run_id)
        kind, source_id = arguments["source_kind"], arguments["source_id"]
        if kind == "attachment":
            item = next((item for item in state.available_attachments if item.attachment_id == source_id), None)
            if item is None:
                raise ToolFailure("image_not_available", "请求的图像不在当前 Session 的可用清单中。")
            try:
                image = attachments.resolve(_context.session_id, source_id)
            except RunError:
                raise ToolFailure("image_unavailable", "图像文件当前无法读取。", retryable=True) from None
            name = item.filename
            width, height = _image_dimensions(image.image_bytes)
        else:
            record = next((item for item in state.panels if item.panel_id == source_id), None)
            if record is None:
                raise ToolFailure("image_not_available", "请求的 Panel 不在当前 Session 的可用清单中。")
            try:
                _record, image, width, height = panels.resolve(_context.session_id, source_id)
            except RunError:
                raise ToolFailure("image_unavailable", "Panel 图像当前无法读取。", retryable=True) from None
            name = record.name
        return {
            "source_kind": kind,
            "source_id": source_id,
            "name": name,
            "width": width,
            "height": height,
        }

    def decompose_chart_image(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        state = image_inventory(context.session_id, context.run_id)
        attachment_id = arguments["attachment_id"]
        if not any(item.attachment_id == attachment_id for item in state.available_attachments):
            raise ToolFailure("image_not_available", "待分割图像不在当前 Session 的可用清单中。")
        proposals: list[tuple[str, tuple[PanelPoint, ...]]] = []
        for panel in arguments["panels"]:
            try:
                proposals.append((panel["name"], tuple(PanelPoint(point["x"], point["y"]) for point in panel["points"])))
            except (KeyError, TypeError, RunError):
                raise ToolFailure("invalid_region", "Panel 区域结构无效。", field_path="/panels") from None
        try:
            records = panels.decompose(
                context.session_id,
                context.run_id,
                attachment_id,
                tuple(proposals),
                context.idempotency_key or "",
            )
        except RunError as error:
            if error.code in {RunErrorCode.INVALID_REQUEST, RunErrorCode.UNSUPPORTED_PAYLOAD}:
                raise ToolFailure("invalid_region", "Panel 区域结构或资源范围不符合要求。") from None
            raise ToolFailure("image_unavailable", "源图像当前无法读取。", retryable=True) from None
        return {
            "panels": [
                {
                    "panel_id": record.panel_id,
                    "name": record.name,
                    "source_attachment_id": record.source_attachment_id,
                }
                for record in records
            ]
        }

    return (
        ToolDefinition(
            name="load_image",
            description="按附件或 Panel ID 读取图像。结果只返回名称和尺寸；图像内容会附加到下一次模型请求。",
            parameters_schema=_LOAD_IMAGE_PARAMETERS,
            result_schema=_LOAD_IMAGE_RESULT,
            replay_effect=ReplayEffect.REPLAY_SAFE,
            handler=load_image,
        ),
        ToolDefinition(
            name="decompose_chart_image",
            description="将附件图像按模型提供的多边形区域切成独立 Panel PNG。坐标按原图宽高归一化到 0–1000。",
            parameters_schema=_DECOMPOSE_PARAMETERS,
            result_schema=_DECOMPOSE_RESULT,
            replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE,
            handler=decompose_chart_image,
        ),
    )


def _image_dimensions(content: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            return image.size
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ToolFailure("image_unavailable", "图像尺寸当前无法读取。", retryable=True) from None
