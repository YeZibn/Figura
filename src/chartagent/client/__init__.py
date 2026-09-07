"""LLM client module scope.

This package provides a thin, controllable LLM invocation layer over
OpenAI-compatible endpoints. It owns config layering, output normalization,
reasoning isolation, history construction, retry/timeout knobs, and
per-call observation logging. It does NOT implement an agent loop, tool
dispatch, MCP, or chart capabilities - those arrive in later changes and
consume this layer.
"""

from .client import LLMClient, append_to_history, assistant_history_entry
from .config import ClientConfig, load_environment, resolve_config
from .models import NormalizedResult, ToolCall

__all__ = [
    "LLMClient",
    "ClientConfig",
    "resolve_config",
    "load_environment",
    "NormalizedResult",
    "ToolCall",
    "append_to_history",
    "assistant_history_entry",
]