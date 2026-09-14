"""Tool adapter for loading an authorized attachment."""

from __future__ import annotations

from pathlib import Path

from ...attachments import AttachmentRegistry
from ..core.definition import Tool
from ..core.result import GeneratedImage, ToolResult


def load_image_tool(attachments: AttachmentRegistry) -> Tool:
    """Build the model-facing ``load_image`` tool for one registry."""
    def load_image(attachment_id: str) -> ToolResult | dict:
        item, error = attachments.validate(attachment_id)
        if error or item is None:
            return {"error": error or "attachment is not authorized"}
        try:
            content = Path(item.canonical_path).read_bytes()
        except OSError:
            return {"error": "attachment file is unavailable"}
        return ToolResult(
            item.metadata() | {"status": "loaded"},
            (GeneratedImage(content, item.media_type, f"Loaded attachment {item.filename}"),),
        )

    return Tool(
        "load_image",
        "Load one authorized user image for visual inspection. Use when the model needs direct visual evidence that is not supplied by a chart sensor; do not provide a local filesystem path or an attachment ID not present in the current authorized context. The result contains bounded attachment metadata and image evidence, but loading does not prove that the image is a chart or that its contents are correct.",
        {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "Opaque authorized attachment ID from the user turn, such as att_<opaque-id>; never a local path or URL.",
                }
            },
            "required": ["attachment_id"],
            "additionalProperties": False,
        },
        load_image,
        group="attachment",
    )


__all__ = ["load_image_tool"]
