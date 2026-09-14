"""External protocol projections for the tool registry."""

from .mcp import McpToolManifest, manifests_json, to_mcp_tools
from .openai import registry_tools, tool_to_openai_schema

__all__ = [
    "McpToolManifest",
    "manifests_json",
    "to_mcp_tools",
    "registry_tools",
    "tool_to_openai_schema",
]
