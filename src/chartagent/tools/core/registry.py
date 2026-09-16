"""Tool registry and dispatch.

The registry owns tools by name; ``dispatch`` turns a tool call (name + a JSON
string of arguments) into a structured result. Successful results are returned
as JSON strings ready to enter message history; failures never propagate to the
caller as exceptions but as ``{"error": ...}`` structures, so an agent loop can
feed them back to the model.
"""

from __future__ import annotations

import json
from typing import Dict, List

from .definition import Tool
from .result import DispatchedObservation, normalize_tool_result


class ToolRegistry:
    """Named collection of tools with dispatch-by-name."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool; reject duplicates of the same name."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Return the tool by name, or ``None`` if absent."""
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        """Return all registered tools (insertion order)."""
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def _error(message: str) -> str:
    """Structured, JSON-serializable error result."""
    return json.dumps({"error": message}, ensure_ascii=False)


def dispatch(registry: ToolRegistry, name: str, arguments_json: str) -> str:
    """Dispatch a tool call, returning a JSON string (success or ``{"error"}``).

    Unknown names, exceptions raised by the callable, and un-serializable
    results all yield a structured error string rather than an exception.
    """
    return dispatch_observation(registry, name, arguments_json).content


def dispatch_observation(
    registry: ToolRegistry,
    name: str,
    arguments_json: str,
) -> DispatchedObservation:
    """Dispatch a call with optional validated, in-memory image evidence."""
    tool = registry.get(name)
    if tool is None:
        return DispatchedObservation(_error(f"Unknown tool: {name!r}"))

    try:
        args = json.loads(arguments_json) if arguments_json.strip() else {}
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive boundary
        return DispatchedObservation(_error(f"Invalid arguments JSON for {name!r}: {exc}"))

    if not isinstance(args, dict):
        return DispatchedObservation(_error(f"Tool {name!r} expects an object of arguments."))

    try:
        result = tool.fn(**args)
    except Exception as exc:  # noqa: BLE001 - boundary; route to model
        return DispatchedObservation(_error(f"Tool {name!r} failed: {exc}"))

    try:
        return normalize_tool_result(
            result,
            source_tool=name,
            source_attachment_id=args.get("attachment_id")
            if isinstance(args.get("attachment_id"), str)
            else None,
        )
    except Exception:  # pragma: no cover - un-serializable result guard
        return DispatchedObservation(_error(f"Tool {name!r} result could not be serialized."))


__all__ = ["ToolRegistry", "dispatch", "dispatch_observation"]
