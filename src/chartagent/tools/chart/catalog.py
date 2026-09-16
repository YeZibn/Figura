"""Single registration catalog for chart-understanding tools."""

from __future__ import annotations

from ..adapters.chart import authorized_chart_tool
from ...attachments import AttachmentRegistry
from ..core.definition import Tool
from ..core.registry import ToolRegistry
from .observation.bars import MEASURE_BARS
from .observation.line import EXTRACT_LINE_SERIES
from .observation.layout_tool import INSPECT_CHART_LAYOUT
from .observation.ocr import EXTRACT_TEXT
from .observation.pie import EXTRACT_PIE_SLICES
from .observation.scatter import EXTRACT_SCATTER_POINTS
from .rendering import RENDER_CHART
from .specification import ASSEMBLE_SPEC, VALIDATE_SPEC

CHART_TOOLS = [
    EXTRACT_TEXT,
    INSPECT_CHART_LAYOUT,
    MEASURE_BARS,
    EXTRACT_LINE_SERIES,
    EXTRACT_PIE_SLICES,
    EXTRACT_SCATTER_POINTS,
    ASSEMBLE_SPEC,
    VALIDATE_SPEC,
    RENDER_CHART,
]
CHART_TOOL_NAMES = [tool.name for tool in CHART_TOOLS]


def register_chart_tools(
    registry: ToolRegistry,
    *,
    attachments: AttachmentRegistry | None = None,
) -> None:
    """Register all chart tools exactly once in their stable order."""
    for tool in CHART_TOOLS:
        if attachments is not None and tool.name in {
            "extract_text",
            "inspect_chart_layout",
            "measure_bars",
            "extract_line_series",
            "extract_pie_slices",
            "extract_scatter_points",
        }:
            tool = authorized_chart_tool(tool, attachments)
        registry.register(tool)


__all__ = [
    "CHART_TOOLS",
    "CHART_TOOL_NAMES",
    "register_chart_tools",
]
