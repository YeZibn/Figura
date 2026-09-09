"""ReAct-style agent loop over the LLM client + tool registry.

Unlike ``Conversation`` (pure dialogue, strips ``tool_calls`` from history),
``Agent`` keeps a model's ``tool_calls`` in the assistant entry and appends a
``tool`` observation message per call, so the model can see its own actions and
observations turn after turn. This is the key difference from the dialogue loop.

Loop semantics (native function calling, not text ReAct):
- model returns ``tool_calls`` -> the Actions; run each serially via
  ``dispatch``; observations feed back; continue.
- model returns no ``tool_calls`` -> Final Answer; stop and return ``content``.
- step budget reached -> bounded stop, no unbounded loop.

Reasoning is never echoed into history (deep-thinking providers 400 otherwise),
matching the client's ``append_to_history`` contract.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from openai.types.chat import ChatCompletionMessageParam

from .client.client import LLMClient
from .client.models import NormalizedResult, ToolCall
from .multimodal import ToolVisualEvidence, build_tool_observation_content
from .trace import (
    TraceEmitter,
    TraceSink,
    bounded_reasoning,
    new_run_id,
    summarize_arguments,
    summarize_images,
    summarize_result,
)
from .tools.registry import ToolRegistry, dispatch_observation
from .memory import AgentMemory, InMemoryAgentMemory, RunStatus

# Sentinel returned when the step budget is exhausted.
_BUDGET_MSG = "*stopped: max_steps reached*"


def tool_to_openai_schema(tool: Any) -> dict:
    """Map a ``Tool`` to an OpenAI ``tools`` entry."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def registry_tools(registry: ToolRegistry) -> List[dict]:
    """Return the OpenAI ``tools`` schema list for every registered tool."""
    return [tool_to_openai_schema(t) for t in registry.list()]


def _assistant_entry(result: NormalizedResult) -> ChatCompletionMessageParam:
    """Assistant history entry keeping content + tool_calls, never reasoning."""
    entry: dict = {"role": "assistant", "content": result.content}
    if result.tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in result.tool_calls
        ]
    return entry  # type: ignore[return-value]


def _tool_entry(call: ToolCall, observation: str) -> ChatCompletionMessageParam:
    return {"role": "tool", "tool_call_id": call.id, "content": observation}  # type: ignore[return-value]


class Agent:
    """Minimal ReAct agent loop owning its history in memory.

    Args:
        client: ``LLMClient`` used for every model turn.
        registry: ``ToolRegistry`` whose registered tools are exposed to the model.
        system: optional system prompt, kept first in the history.
        max_steps: maximum number of tool-calling turns before stopping.
        **chat_kwargs: forwarded to every ``client.chat(...)`` call (e.g. model,
            enable_thinking, temperature).
    """

    def __init__(
        self,
        client: LLMClient,
        registry: ToolRegistry,
        *,
        system: Optional[str] = None,
        max_steps: int = 10,
        trace: Optional[TraceSink] = None,
        trace_sink: Optional[TraceSink] = None,
        trace_reasoning: bool = False,
        trace_run_id: Optional[str] = None,
        memory: Optional[AgentMemory] = None,
        attachments: Any = None,
        context_budget: int = 24000,
        **chat_kwargs: Any,
    ) -> None:
        self.client = client
        self.registry = registry
        self._system = system
        self.max_steps = max_steps
        self._chat_kwargs = chat_kwargs
        self._trace_sink = trace if trace is not None else trace_sink
        self._trace_reasoning = trace_reasoning
        self._trace_run_id = trace_run_id
        self.memory = memory or InMemoryAgentMemory(context_budget=context_budget)
        self.attachments = attachments
        self.context_budget = context_budget
        self._messages: List[ChatCompletionMessageParam] = []
        self._current_messages: List[ChatCompletionMessageParam] = []
        if system is not None:
            self._messages.append({"role": "system", "content": system})  # type: ignore[arg-type]

    @property
    def messages(self) -> List[ChatCompletionMessageParam]:
        """Read-only view of the running history (for inspection/tests)."""
        return list(self._messages)

    def reset(self) -> None:
        """Clear history, keeping only the system prompt."""
        self._messages = []
        self._current_messages = []
        reset = getattr(self.memory, "reset", None)
        if callable(reset):
            reset()

    def close(self) -> None:
        """Release retained conversation content, including generated images."""
        self.reset()
        close = getattr(self.memory, "close", None)
        if callable(close):
            close()

    def run(self, user_input: str | list[dict]) -> str:
        """Drive one user turn to completion (final answer or budget cap).

        ``user_input`` is a plain string or an OpenAI multimodal content list
        (e.g. from ``build_user_content``); it is appended to history and
        forwarded to the client unchanged.
        """
        run = self.memory.begin_run()
        self._messages = []
        self._current_messages = []
        user_message = {"role": "user", "content": user_input}
        self.memory.append(run, "user", {"message": user_message, "text": user_input if isinstance(user_input, str) else "[image attachment turn]"})
        if isinstance(user_input, str):
            for ordinal, attachment_id in enumerate(re.findall(r"\batt_[A-Za-z0-9]+\b", user_input), start=1):
                self.memory.append(run, "attachment", {"attachment_id": attachment_id, "ordinal": ordinal})
                if self.attachments is not None:
                    self.attachments.bind_run(attachment_id, run.id)
        self._current_messages.append(user_message)  # type: ignore[arg-type]
        tools = registry_tools(self.registry)
        emitter = (
            TraceEmitter(self._trace_sink, run_id=self._trace_run_id or new_run_id())
            if self._trace_sink is not None
            else None
        )

        for step in range(self.max_steps):
            turn = step + 1
            system_message = {"role": "system", "content": self._system} if self._system else None
            self._messages = self.memory.context(run, system_message, self.context_budget, current_messages=self._current_messages)
            if emitter is not None and not isinstance(self.client, LLMClient):
                emitter.emit(
                    "model_started",
                    turn=turn,
                    model=self._chat_kwargs.get("model"),
                    message_count=len(self._messages),
                    tool_count=len(tools),
                )
            chat_kwargs = dict(self._chat_kwargs)
            if emitter is not None and isinstance(self.client, LLMClient):
                chat_kwargs.update(
                    trace_sink=emitter,
                    trace_run_id=emitter.run_id,
                    trace_turn=turn,
                )
            try:
                result = self.client.chat(self._messages, tools=tools, **chat_kwargs)
            except Exception as exc:
                self.memory.append(run, "error", {"text": str(exc)})
                self.memory.finish(run, RunStatus.FAILED, "error")
                if emitter is not None and not isinstance(self.client, LLMClient):
                    emitter.emit(
                        "model_completed",
                        turn=turn,
                        status="error",
                        error=str(exc),
                    )
                raise

            if emitter is not None and not isinstance(self.client, LLMClient):
                emitter.emit(
                    "model_completed",
                    turn=turn,
                    status="ok",
                    content_length=len(result.content),
                    reasoning_available=bool(result.reasoning),
                    tool_calls=len(result.tool_calls),
                    finish_reason=result.finish_reason,
                )
            if emitter is not None and self._trace_reasoning:
                emitter.emit(
                    "reasoning",
                    turn=turn,
                    status="available" if result.reasoning else "unavailable",
                    reasoning=bounded_reasoning(result.reasoning),
                )

            if not result.tool_calls:
                assistant_message = _assistant_entry(result)
                self._current_messages.append(assistant_message)
                self._messages.append(assistant_message)
                self.memory.append(run, "assistant", {"message": assistant_message})
                self.memory.append(run, "final", {"answer": result.content, "finish_reason": result.finish_reason})
                self.memory.finish(run, RunStatus.COMPLETED, "final")
                if emitter is not None:
                    emitter.emit(
                        "final_answer",
                        turn=turn,
                        answer=result.content,
                        finish_reason=result.finish_reason,
                    )
                return result.content

            assistant_message = _assistant_entry(result)
            self._current_messages.append(assistant_message)
            self._messages.append(assistant_message)
            self.memory.append(run, "assistant", {"message": assistant_message})
            visual_evidence: list[ToolVisualEvidence] = []
            for call in result.tool_calls:
                if emitter is not None:
                    emitter.emit(
                        "tool_call",
                        turn=turn,
                        tool_name=call.name,
                        call_id=call.id,
                        arguments=summarize_arguments(call.arguments),
                    )
                observation = dispatch_observation(
                    self.registry, call.name, call.arguments
                )
                tool_message = _tool_entry(call, observation.content)
                self._current_messages.append(tool_message)
                self._messages.append(tool_message)
                self.memory.append(run, "tool", {"message": tool_message, "tool_name": call.name, "status": _observation_status(observation.content)})
                if emitter is not None:
                    emitter.emit(
                        "tool_result",
                        turn=turn,
                        tool_name=call.name,
                        call_id=call.id,
                        status=_observation_status(observation.content),
                        result=summarize_result(observation.content),
                        image_count=len(observation.images),
                    )
                    if observation.images:
                        emitter.emit(
                            "visual_observation",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            images=summarize_images(observation.images),
                        )
                visual_evidence.extend(
                    ToolVisualEvidence(call.name, call.id, generated)
                    for generated in observation.images
                )
            if visual_evidence:
                visual_message = {
                    "role": "user",
                    "content": build_tool_observation_content(visual_evidence),
                }
                self._current_messages.append(visual_message)  # type: ignore[arg-type]
                self._messages.append(visual_message)  # type: ignore[arg-type]
                self.memory.append(
                    run,
                    "visual_metadata",
                    {
                        "tool_count": len(visual_evidence),
                        "tools": [item.tool_name for item in visual_evidence],
                        "call_ids": [item.tool_call_id for item in visual_evidence],
                        "image_count": len(visual_evidence),
                    },
                )

        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=self.max_steps,
                max_steps=self.max_steps,
                answer=_BUDGET_MSG,
            )
        self.memory.append(run, "terminal", {"answer": _BUDGET_MSG, "max_steps": self.max_steps})
        self.memory.finish(run, RunStatus.COMPLETED, "budget")
        return _BUDGET_MSG


def _observation_status(content: str) -> str:
    """Classify the registry's structured success/error boundary for tracing."""
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return "success"
    return "error" if isinstance(parsed, dict) and "error" in parsed else "success"
