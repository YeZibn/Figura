"""Batch registration entry point for chart-understanding tools."""

from __future__ import annotations

from ..registry import ToolRegistry
from .geometry import MEASURE_BARS
from .line import EXTRACT_LINE_SERIES
from .ocr import EXTRACT_TEXT
from .pie import EXTRACT_PIE_SLICES
from .scatter import EXTRACT_SCATTER_POINTS
from .spec_tools import ASSEMBLE_SPEC, VALIDATE_SPEC
from .generation import RENDER_CHART
from ...attachments import AttachmentRegistry
from ..tool import Tool

CHART_TOOLS = [
    EXTRACT_TEXT,
    MEASURE_BARS,
    EXTRACT_LINE_SERIES,
    EXTRACT_PIE_SLICES,
    EXTRACT_SCATTER_POINTS,
    ASSEMBLE_SPEC,
    VALIDATE_SPEC,
    RENDER_CHART,
]
CHART_TOOL_NAMES = [tool.name for tool in CHART_TOOLS]


def _authorized_tool(tool: Tool, attachments: AttachmentRegistry) -> Tool:
    original = tool.fn

    def call(attachment_id: str, **kwargs):
        item, error = attachments.validate(attachment_id)
        if error or item is None:
            return {"error": error or "attachment is not authorized"}
        return original(image_path=item.canonical_path, **kwargs)

    schema = dict(tool.parameters)
    schema["properties"] = dict(schema.get("properties", {}))
    schema["properties"].pop("image_path", None)
    schema["properties"]["attachment_id"] = {"type": "string", "description": "Opaque authorized attachment ID from the user turn."}
    schema["required"] = ["attachment_id"]
    return Tool(tool.name, tool.description + " Accepts an authorized attachment ID.", schema, call)


def register_chart_tools(registry: ToolRegistry, *, attachments: AttachmentRegistry | None = None) -> None:
    """Register all available chart-understanding tools."""
    for tool in CHART_TOOLS:
        if attachments is not None and tool.name in {
            "extract_text",
            "measure_bars",
            "extract_line_series",
            "extract_pie_slices",
            "extract_scatter_points",
        }:
            tool = _authorized_tool(tool, attachments)
        registry.register(tool)
