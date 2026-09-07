"""Normalized result model shared across calls and providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """A single model-requested tool call, normalized across providers."""

    id: str
    name: str
    arguments: str  # JSON-encoded arguments string as given by the provider


@dataclass
class NormalizedResult:
    """Single normalized shape returned by every client invocation.

    Non-applicable fields are empty/absent, never ambiguous. `raw` always
    preserves the untouched provider response as a fallback.
    """

    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Any] = None
    raw: Any = None