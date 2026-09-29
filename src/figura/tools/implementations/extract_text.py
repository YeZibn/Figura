"""Authorized source adapter for bounded OCR observations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.sources.attachments import FiguraAttachmentService
from figura.sources.panels import FiguraPanelService

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from ..measurements.observation_scope import ObservationScopeError, decode_scoped_image
from ..measurements.ocr import recognize_text
from .measurement_schema import SOURCE_PARAMETERS
from .measurement_source import resolve_measurement_source


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
        "available": {"type": "boolean"},
        "truncated": {"type": "boolean"},
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "snippet_id": {"type": "string", "minLength": 1, "maxLength": 32},
                    "text": {"type": "string", "minLength": 1, "maxLength": 128},
                    "bbox_px": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 100000},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["snippet_id", "text", "bbox_px", "confidence"],
                "additionalProperties": False,
            },
            "maxItems": 512,
        },
    },
    "required": [
        "source_kind",
        "source_id",
        "image_size",
        "coordinate_system",
        "available",
        "truncated",
        "snippets",
    ],
    "additionalProperties": False,
}


def extract_text_definition(
    image_inventory: Callable[[str, str], Any],
    attachments: FiguraAttachmentService,
    panels: FiguraPanelService,
) -> ToolDefinition:
    def extract(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
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
            rgb, mask = decode_scoped_image(source.image_bytes, arguments.get("observation_scope"))
        except ObservationScopeError:
            raise ToolFailure(
                "invalid_observation_scope",
                "图像观察范围无效或不包含可观察像素。",
            ) from None
        except ValueError:
            raise ToolFailure("image_unavailable", "图像内容当前无法读取。", retryable=True) from None

        observation = recognize_text(rgb, mask) if mask is not None else recognize_text(rgb)
        height, width = rgb.shape[:2]
        return {
            "source_kind": kind,
            "source_id": source_id,
            "image_size": {"width": width, "height": height},
            "coordinate_system": source.coordinate_system,
            "available": observation.available,
            "truncated": observation.truncated,
            "snippets": [
                {
                    "snippet_id": snippet.snippet_id,
                    "text": snippet.text,
                    "bbox_px": list(snippet.bbox_px),
                    "confidence": snippet.confidence,
                }
                for snippet in observation.snippets
            ],
        }

    return ToolDefinition(
        name="extract_text",
        description=(
            "从指定 Attachment 或 Panel 提取有界 OCR 文字片段、像素框与置信度。"
            "可用 observation_scope 限定文字观察区域；OCR 可能为空或识别错误，"
            "应结合图像证据判断。"
        ),
        parameters_schema=SOURCE_PARAMETERS,
        result_schema=_RESULT,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=extract,
    )
