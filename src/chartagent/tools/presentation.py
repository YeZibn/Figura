"""Stable local presentation metadata for tools and traces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .tool import Tool


@dataclass(frozen=True)
class ToolPresentation:
    """Human-facing names for one stable English tool identifier."""

    name: str
    display_name: str
    english_name: str | None
    group: str

    @property
    def label(self) -> str:
        if self.english_name and self.english_name != self.display_name:
            return f"{self.display_name} ({self.english_name})"
        return self.display_name


_PRESENTATIONS: dict[str, tuple[str, str | None, str]] = {
    "read_file": ("读取文件", "read_file", "file"),
    "list_dir": ("列出目录", "list_dir", "file"),
    "parse_json": ("解析 JSON", "parse_json", "data"),
    "read_json_file": ("读取 JSON 文件", "read_json_file", "data"),
    "load_image": ("加载图片", "load_image", "attachment"),
    "extract_text": ("提取图中文字", "extract_text", "chart-observation"),
    "measure_bars": ("测量柱状图", "measure_bars", "chart-observation"),
    "extract_line_series": ("提取折线系列", "extract_line_series", "chart-observation"),
    "extract_pie_slices": ("提取饼图扇区", "extract_pie_slices", "chart-observation"),
    "extract_scatter_points": ("提取散点", "extract_scatter_points", "chart-observation"),
    "assemble_spec": ("组装图表规格", "assemble_spec", "chart-spec"),
    "validate_spec": ("校验图表规格", "validate_spec", "chart-spec"),
    "render_chart": ("生成图表", "render_chart", "chart-generation"),
    "review_generated_chart": ("审核生成图表", "review_generated_chart", "chart-review"),
}


class ToolCatalog:
    """Lookup table with safe fallback for tools added after the catalog."""

    def __init__(self, entries: Mapping[str, tuple[str, str | None, str]] | None = None) -> None:
        self._entries = dict(entries or _PRESENTATIONS)

    def get(self, name: str, *, tool: Tool | None = None) -> ToolPresentation:
        entry = self._entries.get(name)
        if entry is not None:
            display_name, english_name, group = entry
            return ToolPresentation(name, display_name, english_name, group)
        display_name = tool.display_name if tool and tool.display_name else name
        group = tool.group if tool else "general"
        return ToolPresentation(name, display_name, name, group)

    def for_tool(self, tool: Tool) -> ToolPresentation:
        return self.get(tool.name, tool=tool)

    def complete_for(self, tools: Iterable[Tool]) -> dict[str, ToolPresentation]:
        return {tool.name: self.for_tool(tool) for tool in tools}


DEFAULT_TOOL_CATALOG = ToolCatalog()


def get_tool_presentation(name: str, *, tool: Tool | None = None) -> ToolPresentation:
    """Return known bilingual metadata or a stable English-name fallback."""
    return DEFAULT_TOOL_CATALOG.get(name, tool=tool)


__all__ = ["DEFAULT_TOOL_CATALOG", "ToolCatalog", "ToolPresentation", "get_tool_presentation"]
