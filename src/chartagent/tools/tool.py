"""Tool definition for the agent foundation.

A ``Tool`` is metadata (name / description / parameters schema) plus a plain
callable. The metadata is decoupled from the callable so the same tool can be
described to an LLM or mapped to an external protocol (e.g. MCP) without
touching the callable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping


@dataclass
class Tool:
    """A declarative tool: metadata + a Python callable.

    Attributes:
        name: stable identifier used by the model / external host.
        description: human-readable guidance for choosing this tool.
        parameters: JSON-Schema object describing accepted arguments.
        fn: callable that executes the tool when dispatched.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    fn: Callable[..., Any]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not callable(self.fn):
            raise TypeError("Tool.fn must be callable.")
        # Normalise the schema for downstream equality/use.
        self.parameters: Dict[str, Any] = dict(self.parameters)