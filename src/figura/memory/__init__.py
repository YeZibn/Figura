"""Provider-neutral projections of durable Figura conversation history."""

from .models import (
    AssistantMessage,
    RunHistoryOutcome,
    IncompleteBatchContext,
    IncompleteCallContext,
    MemoryMessage,
    MemoryToolCall,
    SessionHistory,
    ToolMessage,
    UserMessage,
)
from .projector import project_run_messages, project_session_history, tool_observation
from .references import HistorySourceRef, MessageSourceRef, ToolResultSourceRef, source_ref_from_dict

__all__ = [
    "AssistantMessage",
    "RunHistoryOutcome",
    "IncompleteBatchContext",
    "IncompleteCallContext",
    "HistorySourceRef",
    "MessageSourceRef",
    "MemoryMessage",
    "MemoryToolCall",
    "SessionHistory",
    "ToolMessage",
    "ToolResultSourceRef",
    "UserMessage",
    "project_run_messages",
    "project_session_history",
    "source_ref_from_dict",
    "tool_observation",
]
