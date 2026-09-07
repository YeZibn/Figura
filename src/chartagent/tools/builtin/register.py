"""Batch registration entry point for the built-in basic tools."""

from __future__ import annotations

from ..registry import ToolRegistry
from .data import BUILTIN_DATA
from .files import BUILTIN_FILES

BUILTIN_TOOLS = BUILTIN_FILES + BUILTIN_DATA

TOOL_NAMES = [t.name for t in BUILTIN_TOOLS]


def register_builtins(registry: ToolRegistry) -> None:
    """Register all built-in basic tools into ``registry``."""
    for tool in BUILTIN_TOOLS:
        registry.register(tool)