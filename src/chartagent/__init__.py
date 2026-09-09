"""chartagent - agentic foundation for ChartAgent.

Start here with the LLM client, a multi-turn conversation session, and a
declarative tool system. No agent loop, MCP server, or chart reading/generation
lives in this package yet.
"""

from .agent import Agent, registry_tools
from .conversation import Conversation
from .attachments import AttachmentRegistry
from .multimodal import (
    ToolVisualEvidence,
    build_attachment_turn,
    build_registered_attachment_turn,
    build_tool_observation_content,
    build_user_content,
)
from .trace import (
    JsonlTraceRenderer,
    TextTraceRenderer,
    TraceEmitter,
    TraceEvent,
    TraceLimits,
)
from .tools import (
    DispatchedObservation,
    GeneratedImage,
    Tool,
    ToolRegistry,
    ToolResult,
    dispatch,
    dispatch_observation,
    to_mcp_tools,
)
from .tools.builtin import register_builtins

__all__ = [
    "Agent",
    "registry_tools",
    "Conversation",
    "AttachmentRegistry",
    "build_attachment_turn",
    "build_registered_attachment_turn",
    "build_tool_observation_content",
    "build_user_content",
    "ToolVisualEvidence",
    "TraceEvent",
    "TraceEmitter",
    "TraceLimits",
    "TextTraceRenderer",
    "JsonlTraceRenderer",
    "Tool",
    "ToolRegistry",
    "GeneratedImage",
    "ToolResult",
    "DispatchedObservation",
    "dispatch",
    "dispatch_observation",
    "to_mcp_tools",
    "register_builtins",
]
