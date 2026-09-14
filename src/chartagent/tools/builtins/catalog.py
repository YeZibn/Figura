"""Catalog and registration for the built-in read-only tools."""

from __future__ import annotations

from ..core.registry import ToolRegistry
from .filesystem import BUILTIN_FILES
from .json import BUILTIN_DATA

BUILTIN_TOOLS = [*BUILTIN_FILES, *BUILTIN_DATA]
TOOL_NAMES = [tool.name for tool in BUILTIN_TOOLS]


def register_builtins(registry: ToolRegistry) -> None:
    """Register all built-in basic tools into ``registry``."""
    for tool in BUILTIN_TOOLS:
        registry.register(tool)


__all__ = ["BUILTIN_TOOLS", "TOOL_NAMES", "register_builtins"]
