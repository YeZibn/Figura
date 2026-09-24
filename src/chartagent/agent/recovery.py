"""Small helpers for explicit execution continuation and interruption."""

from __future__ import annotations

from typing import Any, Optional

from ..client.models import ToolCall
from ..memory import RunStatus


class AgentInterrupted(RuntimeError):
    """Raised when a cooperative run interruption is observed."""


class AgentRecoveryBlocked(RuntimeError):
    """Raised when a continuation reaches an operation with an unknown outcome."""


def recovery_tool_calls(recovery: Optional[dict[str, Any]]) -> list[ToolCall]:
    """Read pending calls derived from the committed model/tool prefix."""
    if not isinstance(recovery, dict) or recovery.get("nextAction") != "tool":
        return []
    raw = recovery.get("pendingToolCalls")
    if not isinstance(raw, list):
        return []
    calls: list[ToolCall] = []
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        if not all(isinstance(item.get(key), str) and item.get(key) for key in ("id", "name", "arguments")):
            continue
        calls.append(ToolCall(item["id"], item["name"], item["arguments"]))
    return calls


def interruption_requested(event: Any) -> bool:
    """Read a cooperative interruption source without propagating its errors."""
    if event is None:
        return False
    if callable(event):
        try:
            return bool(event())
        except Exception:  # noqa: BLE001 - cancellation must remain best effort
            return False
    is_set = getattr(event, "is_set", None)
    return bool(is_set()) if callable(is_set) else bool(event)


def raise_if_interrupted(event: Any, memory: Any, run: Any) -> None:
    """Finish the run as interrupted and raise the public interruption error."""
    if not interruption_requested(event):
        return
    try:
        memory.finish(run, RunStatus.INTERRUPTED, "interrupted")
    finally:
        raise AgentInterrupted("Agent run was interrupted")
