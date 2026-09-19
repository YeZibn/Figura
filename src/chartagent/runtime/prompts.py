"""Compatibility export for Figura's static Markdown prompt."""

from ..prompting import build_static_agent_prompt

AGENT_SYSTEM_PROMPT = build_static_agent_prompt()

__all__ = ["AGENT_SYSTEM_PROMPT"]
