"""Built-in read-only basic tools for the agent foundation."""

from .register import TOOL_NAMES, register_builtins

__all__ = ["register_builtins", "TOOL_NAMES"]