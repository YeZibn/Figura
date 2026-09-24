"""Transient state owned by one Agent run invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..client.models import ToolCall
from ..measurement import MEASUREMENT_TOOLS, MeasurementSession
from .panel_routing import MAX_LAYOUT_CONTEXTS


LAYOUT_TOOL_NAME = "inspect_chart_layout"
DECOMPOSE_TOOL_NAME = "decompose_chart_image"
RENDER_TOOL_NAMES = frozenset({"render_chart", "generate_chart"})


def tool_trace_identity(tool_name: str, call_id: str) -> tuple[str, str]:
    """Return the explicit timeline unit shared by one tool call and result."""
    if tool_name in MEASUREMENT_TOOLS:
        unit_type = "measurement"
    elif tool_name == "assemble_spec" or tool_name in RENDER_TOOL_NAMES:
        unit_type = "generation"
    else:
        unit_type = "observation"
    return f"{unit_type}:{str(call_id)[:128]}", unit_type


@dataclass
class RunExecutionContext:
    """Mutable state derived for one Agent invocation."""

    run: Any
    user_input: str | list[dict[str, Any]]
    recovery: dict[str, Any] | None
    layout_contexts: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifact_records: list[dict[str, Any]] = field(default_factory=list)
    visual_references: list[dict[str, Any]] = field(default_factory=list)
    measurement_sessions: dict[str, MeasurementSession] = field(default_factory=dict)
    max_layout_contexts: int = MAX_LAYOUT_CONTEXTS
    attachment_ids: tuple[str, ...] = ()
    selected_panel_id: str | None = None
    current_tool_name: str | None = None
    pending_action: str = "检查当前请求并选择所需证据"
    messages: list[dict[str, Any]] = field(default_factory=list)
    current_messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    emitter: Any = None
    pending_recovery_calls: list[ToolCall] = field(default_factory=list)
    model_entry_id: str | None = None
