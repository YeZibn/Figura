"""OpenAI function-tool schema projection."""

from __future__ import annotations

from typing import Any

from ..core.definition import canonical_tool_definition
from ..core.registry import ToolRegistry


def tool_to_openai_schema(tool: Any) -> dict[str, Any]:
    """Map a declarative tool to an OpenAI ``tools`` entry."""
    definition = canonical_tool_definition(tool)
    return {
        "type": "function",
        "function": {
            "name": definition["name"],
            "description": definition["description"],
            "parameters": definition["parameters"],
        },
    }


def registry_tools(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Return the OpenAI schema list for every registered tool."""
    return [tool_to_openai_schema(tool) for tool in registry.list()]


__all__ = ["registry_tools", "tool_to_openai_schema"]
