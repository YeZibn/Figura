"""chartagent - agentic foundation for ChartAgent.

Start here with the LLM client and a multi-turn conversation session. No agent
loop, tool dispatch, MCP, or chart reading/generation lives in this package
yet.
"""

from .conversation import Conversation

__all__ = ["Conversation"]