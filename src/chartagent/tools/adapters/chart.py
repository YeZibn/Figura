"""Attachment-authorized wrappers for chart observation tools."""

from __future__ import annotations

from ...attachments import AttachmentRegistry
from ..core.definition import Tool


def authorized_chart_tool(tool: Tool, attachments: AttachmentRegistry) -> Tool:
    """Replace an internal image path with an authorized attachment ID."""
    original = tool.fn

    def call(attachment_id: str, **kwargs):
        # ``panel_id`` is a model-facing routing hint. The Agent resolves it
        # to an internal layout context before dispatch.
        kwargs.pop("panel_id", None)
        item, error = attachments.validate(attachment_id)
        if error or item is None:
            return {"error": error or "attachment is not authorized"}
        if tool.name in {"inspect_chart_layout", "decompose_chart_image"}:
            kwargs.setdefault("attachment_id", attachment_id)
        return original(image_path=item.canonical_path, **kwargs)

    schema = dict(tool.parameters)
    schema["properties"] = dict(schema.get("properties", {}))
    schema["properties"].pop("image_path", None)
    # Layout context is an internal, run-scoped evidence injection. It is not
    # exposed as a model argument on the attachment-authorized wrapper.
    schema["properties"].pop("layout_context", None)
    if tool.name in {
        "measure_bars",
        "extract_line_series",
        "extract_pie_slices",
        "extract_scatter_points",
    }:
        schema["properties"]["panel_id"] = {
            "type": "string",
            "description": "Optional stable panel ID returned by decompose_chart_image; selects the scoped panel measurement context.",
        }
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
