"""Tool system: declarative tools, registry, dispatch, and an MCP-shaped
conversion surface reserved for a future MCP bridge (no server here)."""

from .mcp_converter import McpToolManifest, manifests_json, to_mcp_tools
from .registry import ToolRegistry, dispatch
from .tool import Tool

__all__ = [
    "Tool",
    "ToolRegistry",
    "dispatch",
    "McpToolManifest",
    "to_mcp_tools",
    "manifests_json",
]