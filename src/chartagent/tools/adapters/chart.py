"""Attachment-authorized wrappers for chart observation tools."""

from __future__ import annotations

from ...attachments import AttachmentRegistry
from ..core.definition import Tool


def authorized_chart_tool(tool: Tool, attachments: AttachmentRegistry) -> Tool:
    """Replace an internal image path with an authorized attachment ID."""
    original = tool.fn

    def call(attachment_id: str, **kwargs):
        item, error = attachments.validate(attachment_id)
        if error or item is None:
            return {"error": error or "attachment is not authorized"}
        return original(image_path=item.canonical_path, **kwargs)

    schema = dict(tool.parameters)
    schema["properties"] = dict(schema.get("properties", {}))
    schema["properties"].pop("image_path", None)
    schema["properties"]["attachment_id"] = {
        "type": "string",
        "description": "Opaque authorized attachment ID from the user turn; never a local filesystem path or URL.",
    }
    schema["required"] = [
        field for field in schema.get("required", []) if field != "image_path"
    ]
    if "attachment_id" not in schema["required"]:
        schema["required"].append("attachment_id")
    return Tool(
        tool.name,
        tool.description,
        schema,
        call,
        display_name=tool.display_name,
        group=tool.group,
    )


__all__ = ["authorized_chart_tool"]
