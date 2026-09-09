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

from typing import Any, List, Optional

from openai.types.chat import ChatCompletionMessageParam

from .client.client import LLMClient
from .client.models import NormalizedResult, ToolCall
from .multimodal import ToolVisualEvidence, build_tool_observation_content
from .tools.registry import ToolRegistry, dispatch_observation

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
        **chat_kwargs: Any,
    ) -> None:
        self.client = client
        self.registry = registry
        self._system = system
        self.max_steps = max_steps
        self._chat_kwargs = chat_kwargs
        self._messages: List[ChatCompletionMessageParam] = []
        if system is not None:
            self._messages.append({"role": "system", "content": system})  # type: ignore[arg-type]

    @property
    def messages(self) -> List[ChatCompletionMessageParam]:
        """Read-only view of the running history (for inspection/tests)."""
        return list(self._messages)

    def reset(self) -> None:
        """Clear history, keeping only the system prompt."""
        self._messages = []
        if self._system is not None:
            self._messages.append({"role": "system", "content": self._system})  # type: ignore[arg-type]

    def close(self) -> None:
        """Release retained conversation content, including generated images."""
        self.reset()

    def run(self, user_input: str | list[dict]) -> str:
        """Drive one user turn to completion (final answer or budget cap).

        ``user_input`` is a plain string or an OpenAI multimodal content list
        (e.g. from ``build_user_content``); it is appended to history and
        forwarded to the client unchanged.
        """
        self._messages.append({"role": "user", "content": user_input})  # type: ignore[arg-type]
        tools = registry_tools(self.registry)

        for _ in range(self.max_steps):
            result = self.client.chat(
                self._messages,
                tools=tools,
                **self._chat_kwargs,
            )

            if not result.tool_calls:
                self._messages.append(_assistant_entry(result))
                return result.content

            self._messages.append(_assistant_entry(result))
            visual_evidence: list[ToolVisualEvidence] = []
            for call in result.tool_calls:
                observation = dispatch_observation(
                    self.registry, call.name, call.arguments
                )
                self._messages.append(_tool_entry(call, observation.content))
                visual_evidence.extend(
                    ToolVisualEvidence(call.name, call.id, generated)
                    for generated in observation.images
                )
            if visual_evidence:
                self._messages.append(
                    {
                        "role": "user",
                        "content": build_tool_observation_content(visual_evidence),
                    }  # type: ignore[arg-type]
                )

        return _BUDGET_MSG
