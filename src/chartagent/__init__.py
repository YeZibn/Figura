"""chartagent - agentic foundation for ChartAgent.

Start here with the LLM client, a multi-turn conversation session, and a
declarative tool system. No agent loop, MCP server, or chart reading/generation
lives in this package yet.
"""

from .agent import Agent, registry_tools
from .conversation import Conversation
from .tools import Tool, ToolRegistry, dispatch, to_mcp_tools
from .tools.builtin import register_builtins

__all__ = ["Agent", "registry_tools", "Conversation", "Tool", "ToolRegistry",
           "dispatch", "to_mcp_tools", "register_builtins"]