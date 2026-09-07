"""Thin MCP-shaped conversion for tools (reserved surface, not a server).

Maps a :class:`ToolRegistry` to the MCP tool-manifest shape (name / description
/ input schema) and to callable wrappers an MCP server could load. This is a
pure shape mapping with no IO and no running server — a skeleton kept for the
future MCP bridge.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from .registry import ToolRegistry


class McpToolManifest:
    """MCP-shaped tool manifest plus a callable wrapper."""

    def __init__(self, name: str, description: str, input_schema: Dict[str, Any],
                 abstract: Callable[..., Any]) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.abstract = abstract  # placeholder for an MCP server callable


def to_mcp_tools(registry: ToolRegistry) -> Dict[str, Any]:
    """Return MCP tool manifests and callables for every registered tool.

    Returns a dict ``{"manifests": [...], "callables": {name: wrapper}}``. The
    wrapper forwards to the underlying tool ``fn`` unchanged.
    """
    manifests: List[McpToolManifest] = []
    callables: Dict[str, Callable[..., Any]] = {}
    for tool in registry.list():
        manifests.append(McpToolManifest(
            name=tool.name,
            description=tool.description,
            input_schema=dict(tool.parameters),
            abstract=tool.fn,
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