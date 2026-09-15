"""Shared construction for CLI and local gateway Agent runtimes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from ..agent import Agent
from ..attachments import AttachmentRegistry
from ..client import LLMClient, load_environment
from ..memory import SQLiteAgentMemory
from ..review import ChartReviewManager
from ..trace import TraceSink
from ..tools.adapters.attachment import load_image_tool
from ..tools.adapters.review import review_generated_chart_tool
from ..tools.builtins import register_builtins
from ..tools.chart import register_chart_tools
from ..tools.core import GeneratedImage, ToolRegistry
from .models import AgentRuntime
from .prompts import AGENT_SYSTEM_PROMPT

VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]


def create_agent_runtime(
    *,
    provider: str | None = None,
    model: str | None = None,
    system: str = AGENT_SYSTEM_PROMPT,
    trace_sink: Optional[TraceSink] = None,
    trace_reasoning: bool = False,
    run_id: str | None = None,
    visual_observation_sink: Optional[VisualObservationSink] = None,
    session_name: str | None = None,
    database: str | Path | None = None,
    client: Any = None,
    load_env: Callable[..., None] = load_environment,
    llm_client_cls: Callable[..., Any] = LLMClient,
    agent_cls: Callable[..., Any] = Agent,
    registry_cls: Callable[..., Any] = ToolRegistry,
    register_builtins_fn: Callable[..., None] = register_builtins,
    register_chart_tools_fn: Callable[..., None] = register_chart_tools,
) -> AgentRuntime:
    """Build one runtime while allowing CLI tests to inject constructors."""
    load_env()
    actual_client = client if client is not None else llm_client_cls(provider=provider) if provider is not None else llm_client_cls()
    memory = (
        SQLiteAgentMemory(session_name, database=database)
        if session_name is not None
        else None
    )
    attachments = AttachmentRegistry(
        session_id=memory.session.id if memory else None,
        save=memory.save_attachment if memory else None,
        load=memory.get_attachment if memory else None,
    )
    registry = registry_cls()
    review_manager = ChartReviewManager(attachments=attachments)
    register_builtins_fn(registry)
    if hasattr(registry, "register"):
        registry.register(load_image_tool(attachments))
        register_chart_tools_fn(registry, attachments=attachments)
        if registry.get("review_generated_chart") is None:
            registry.register(review_generated_chart_tool(review_manager))
    else:
        register_chart_tools_fn(registry)

    agent_kwargs: dict[str, Any] = {"system": system, "model": model}
    if trace_sink is not None:
        agent_kwargs.update(trace=trace_sink, trace_reasoning=trace_reasoning)
    if run_id is not None:
        agent_kwargs["run_id"] = run_id
        agent_kwargs["trace_run_id"] = run_id
    if visual_observation_sink is not None:
        agent_kwargs["visual_observation_sink"] = visual_observation_sink
    if memory is not None:
        agent_kwargs["memory"] = memory
    agent_kwargs["attachments"] = attachments
    agent_kwargs["review_manager"] = review_manager
    try:
        agent = agent_cls(actual_client, registry, **agent_kwargs)
    except Exception:
        if memory is not None:
            memory.close()
        raise
    return AgentRuntime(agent, memory, attachments)


__all__ = ["AgentRuntime", "VisualObservationSink", "create_agent_runtime"]
