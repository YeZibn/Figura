"""Authorized source adapter for bounded OCR observations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import RunExecutionState

from ..contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from ..measurements.observation_scope import ObservationScopeError, decode_scoped_image
from ..measurements.ocr import recognize_text
from .measurement_schema import SOURCE_PARAMETERS
from .measurement_source import resolve_measurement_source


EXTRACT_TEXT_RESULT_SCHEMA = {
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
    image_inventory: Callable[[str, str], RunExecutionState],
    image_reader: RunExecutionImageReader,
) -> ToolDefinition:
    def extract(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
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
            "从授权 Attachment 或 Panel 提取候选 OCR 文本、原来源像素框 [x,y,width,height] 与置信度。"
            "available 表示 OCR 是否可用，空 snippets 不证明无文字，truncated 表示可能不完整。可选 observation_scope；整框跨出有效范围的候选会被丢弃，成功批次提供标注图回看。"
        ),
        parameters_schema=SOURCE_PARAMETERS,
        result_schema=EXTRACT_TEXT_RESULT_SCHEMA,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=extract,
    )
