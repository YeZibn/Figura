"""Thin MCP-shaped conversion for tools (reserved surface, not a server).

Maps a :class:`ToolRegistry` to the MCP tool-manifest shape (name / description
/ input schema) and to callable wrappers an MCP server could load. This is a
pure shape mapping with no IO and no running server — a skeleton kept for the
future MCP bridge.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..core.definition import canonical_tool_definition
from ..core.registry import ToolRegistry


class McpToolManifest:
    """MCP-shaped tool manifest plus a callable wrapper."""

    def __init__(self, name: str, description: str, input_schema: Dict[str, Any],
                 abstract: Callable[..., Any], *, display_name: str | None = None,
                 group: str = "general") -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.abstract = abstract  # placeholder for an MCP server callable
        self.display_name = display_name
        self.group = group


def to_mcp_tools(registry: ToolRegistry) -> Dict[str, Any]:
    """Return MCP tool manifests and callables for every registered tool.

    Returns a dict ``{"manifests": [...], "callables": {name: wrapper}}``. The
    wrapper forwards to the underlying tool ``fn`` unchanged.
    """
    manifests: List[McpToolManifest] = []
    callables: Dict[str, Callable[..., Any]] = {}
    for tool in registry.list():
        definition = canonical_tool_definition(tool)
        manifests.append(McpToolManifest(
            name=definition["name"],
            description=definition["description"],
            input_schema=definition["parameters"],
            abstract=tool.fn,
            display_name=tool.display_name,
            group=tool.group,
        ))
        callables[tool.name] = tool.fn
    return {"manifests": manifests, "callables": callables}


def manifests_json(registry: ToolRegistry) -> str:
    """Return the MCP tool-manifest list as JSON (for inspection/fixtures)."""
    data = to_mcp_tools(registry)
    return str([{
        "name": m.name,
        "description": m.description,
        "inputSchema": m.input_schema,
    } for m in data["manifests"]])


__all__ = ["McpToolManifest", "to_mcp_tools", "manifests_json"]
