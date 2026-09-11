"""Shared construction for CLI and local gateway Agent runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, IO, Optional, Sequence

from .agent import Agent
from .attachments import AttachmentRegistry
from .client import LLMClient, load_environment, resolve_config
from .memory import SQLiteAgentMemory
from .trace import TraceSink
from .tools.result import GeneratedImage
from .tools import ToolRegistry
from .tools.builtin import register_builtins
from .tools.chart import register_chart_tools

AGENT_SYSTEM_PROMPT = """You are Figura Agent, a general-purpose assistant that can
inspect attached images visually and use tools when they are useful. For chart
work, extract_text can read visible labels and annotations, measure_bars can
measure bar geometry, assemble_spec can construct a ChartSpec, and validate_spec
can check one. Decide freely whether to call tools, which tools to call, and in
what order based on the user's request and the available evidence. Answer
naturally unless the user asks for structured output; a ChartSpec is optional.
User image references are registered as opaque attachment IDs. Use load_image
with an attachment_id when visual inspection is useful; chart sensors accept the
same authorized ID. Image loading is optional and under your control.
When a tool provides a generated visual observation, inspect it together with
the structured result when useful. You may accept it, retry with different
arguments, switch tools, ignore irrelevant evidence, or answer directly; no
fixed validation sequence or numeric acceptance threshold is required.
"""

VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]


def probe_agent_readiness(*, model: str | None = None) -> dict[str, str]:
    """Check local Agent configuration without making a provider request."""
    try:
        load_environment()
        config = resolve_config(model=model)
        if not config.api_key:
            return {"status": "unavailable", "reason": "missing_configuration"}
        LLMClient(config=config)
    except ValueError as exc:
        if "API key" in str(exc):
            return {"status": "unavailable", "reason": "missing_configuration"}
        return {"status": "unavailable", "reason": "invalid_configuration"}
    except Exception:
        return {"status": "unavailable", "reason": "initialization_failed"}
    return {"status": "ready"}


@dataclass
class AgentRuntime:
    """Constructed Agent and resources owned by one named runtime."""

    agent: Agent
    memory: SQLiteAgentMemory | None
    attachments: AttachmentRegistry

    def close(self) -> None:
        if self.memory is not None:
            self.memory.close()


def create_agent_runtime(
    *,
    model: str | None = None,
    system: str = AGENT_SYSTEM_PROMPT,
    trace_sink: Optional[TraceSink] = None,
    trace_reasoning: bool = False,
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
    actual_client = client if client is not None else llm_client_cls()
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
    register_builtins_fn(registry)
    if hasattr(registry, "register"):
        registry.register(attachments.load_tool())
        register_chart_tools_fn(registry, attachments=attachments)
    else:
        # Lightweight constructor stubs remain usable in offline callers/tests.
        register_chart_tools_fn(registry)

    agent_kwargs: dict[str, Any] = {"system": system, "model": model}
    if trace_sink is not None:
        agent_kwargs.update(trace=trace_sink, trace_reasoning=trace_reasoning)
    if visual_observation_sink is not None:
        agent_kwargs["visual_observation_sink"] = visual_observation_sink
    if memory is not None:
        agent_kwargs["memory"] = memory
    agent_kwargs["attachments"] = attachments
    try:
        agent = agent_cls(actual_client, registry, **agent_kwargs)
    except Exception:
        if memory is not None:
            memory.close()
        raise
    return AgentRuntime(agent, memory, attachments)
