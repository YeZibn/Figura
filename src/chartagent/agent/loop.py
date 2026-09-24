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

Reasoning is never echoed into ordinary records or user-visible history. The
DeepSeek thinking + tools path retains its provider-required reasoning field
only in the internal model message immediately preceding a tool result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, List, Optional, Sequence

from openai.types.chat import ChatCompletionMessageParam

from ..client.client import LLMClient
from ..trace import TraceSink
from ..tools.core import ToolRegistry
from ..memory import AgentMemory, InMemoryAgentMemory
from ..tools.core.result import GeneratedImage
from ..verification.flow import GeneratedChartVerificationFlow

# Sentinel returned when the step budget is exhausted.
VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]
StageChartSink = Callable[[GeneratedImage, Any], Any]


class Agent:
    """Minimal ReAct agent loop owning its history in memory.

    Args:
        client: ``LLMClient`` used for every model turn.
        registry: ``ToolRegistry`` whose registered tools are exposed to the model.
        system: optional system prompt, kept first in the history.
        max_steps: maximum number of tool-calling turns before stopping.
        **chat_kwargs: forwarded to every ``client.chat(...)`` call (e.g. model,
            reasoning_effort, temperature).
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
        run_id: Optional[str] = None,
        visual_observation_sink: Optional[VisualObservationSink] = None,
        memory: Optional[AgentMemory] = None,
        attachments: Any = None,
        context_budget: int = 24000,
        stage_chart_sink: StageChartSink | None = None,
        verification_sink: Callable[[Any], Any] | None = None,
        promotion_sink: Callable[[str, str, str, str], Any] | None = None,
        execution_result_resolver: Callable[[str], Any] | None = None,
        staged_chart_resolver: Callable[[str, str], Any] | None = None,
        staged_work_resolver: Callable[[str, str], Any] | None = None,
        interruption_event: Any = None,
        recovery_context: Optional[dict[str, Any]] = None,
        execution_commit: Optional[Callable[..., Any]] = None,
        **chat_kwargs: Any,
    ) -> None:
        self.client = client
        self.registry = registry
        self._system = system
        self.max_steps = max_steps
        self._chat_kwargs = chat_kwargs
        self._trace_sink = trace if trace is not None else trace_sink
        self._trace_reasoning = trace_reasoning
        if run_id is not None and trace_run_id is not None and run_id != trace_run_id:
            raise ValueError("run_id and trace_run_id must identify the same run")
        self._run_id = run_id
        self._trace_run_id = trace_run_id or run_id
        self._visual_observation_sink = visual_observation_sink
        self.memory = memory or InMemoryAgentMemory(context_budget=context_budget)
        self.attachments = attachments
        self._interruption_event = interruption_event
        self._recovery_context = recovery_context
        self._execution_commit = execution_commit
        session_id = self.memory.session.id if self.memory.session is not None else "local"
        self._verification_flow = GeneratedChartVerificationFlow(
            client=self.client,
            chat_kwargs=self._chat_kwargs,
            attachments=self.attachments,
            session_id=session_id,
            stage_sink=stage_chart_sink,
            verification_sink=verification_sink,
            promotion_sink=promotion_sink,
            execution_result_resolver=execution_result_resolver,
            staged_chart_resolver=staged_chart_resolver,
            staged_work_resolver=staged_work_resolver,
            execution_commit=self._execution_commit,
        )
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

    def run(self, user_input: str | list[dict], *, recovery_context: Optional[dict[str, Any]] = None) -> str:
        """Drive one user turn through the per-run orchestrator."""
        from .orchestrator import AgentRunOrchestrator

        return AgentRunOrchestrator(self).run(user_input, recovery_context=recovery_context)
