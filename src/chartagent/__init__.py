"""Public package exports for Figura's chart-analysis Agent runtime.

The package exposes the LLM client-facing conversation API, the tool system,
the Agent loop, chart observation and generation helpers, and verification records.
Lower-level modules remain organized by domain under ``chartagent``.
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
from .spec import chart_spec_digest
from .tools import (
    DispatchedObservation,
    GeneratedImage,
    Tool,
    ToolCatalog,
    ToolPresentation,
    ToolRegistry,
    ToolResult,
    get_tool_presentation,
    dispatch,
    dispatch_observation,
    to_mcp_tools,
)
from .tools.builtins import register_builtins

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
    "chart_spec_digest",
    "TextTraceRenderer",
    "JsonlTraceRenderer",
    "Tool",
    "ToolCatalog",
    "ToolPresentation",
    "ToolRegistry",
    "GeneratedImage",
    "ToolResult",
    "DispatchedObservation",
    "dispatch",
    "dispatch_observation",
    "to_mcp_tools",
    "get_tool_presentation",
    "register_builtins",
]
