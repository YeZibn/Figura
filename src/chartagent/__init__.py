"""chartagent - agentic foundation for ChartAgent.

Start here with the LLM client, a multi-turn conversation session, and a
declarative tool system. No agent loop, MCP server, or chart reading/generation
lives in this package yet.
"""

from .conversation import Conversation
from .tools import Tool, ToolRegistry, dispatch, to_mcp_tools

__all__ = ["Conversation", "Tool", "ToolRegistry", "dispatch", "to_mcp_tools"]