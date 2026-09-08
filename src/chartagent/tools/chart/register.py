"""Batch registration entry point for chart-understanding tools."""

from __future__ import annotations

from ..registry import ToolRegistry
from .geometry import MEASURE_BARS
from .ocr import EXTRACT_TEXT
from .spec_tools import ASSEMBLE_SPEC, VALIDATE_SPEC

CHART_TOOLS = [EXTRACT_TEXT, MEASURE_BARS, ASSEMBLE_SPEC, VALIDATE_SPEC]
CHART_TOOL_NAMES = [tool.name for tool in CHART_TOOLS]


def register_chart_tools(registry: ToolRegistry) -> None:
    """Register all available chart-understanding tools."""
    for tool in CHART_TOOLS:
        registry.register(tool)
