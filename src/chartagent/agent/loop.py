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
from typing import Any, Callable, List, Optional, Sequence

from ..client.client import LLMClient
from ..client.models import NormalizedResult, ToolCall
from ..multimodal import ToolVisualEvidence, build_tool_observation_content
from ..trace import (
    TraceEmitter,
    TraceSink,
    bounded_reasoning,
    summarize_arguments,
    summarize_images,
    summarize_result,
)
from ..tools.core import ToolRegistry, dispatch_observation, canonical_tool_definition
from ..tools.core.presentation import get_tool_presentation
from ..memory import AgentMemory, InMemoryAgentMemory, RunStatus
from ..review import ChartReviewManager, CandidateStatus, PublicationStatus
from ..tools.core.result import GeneratedImage
from .tool_schema import registry_tools, tool_to_openai_schema
from ..tools.adapters.review import review_generated_chart_tool
from .messages import assistant_entry, tool_entry
from .review_gate import (
    _BUDGET_MSG,
    _REVIEW_REQUIRED_MSG,
    REVIEW_INCOMPLETE_MESSAGE,
    review_gate_context,
)
from .observations import observation_status

# Sentinel returned when the step budget is exhausted.
VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]


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
        review_manager: Optional[ChartReviewManager] = None,
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
        self._review_manager = review_manager or ChartReviewManager(attachments=attachments)
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
        run = self.memory.begin_run(self._run_id) if self._run_id is not None else self.memory.begin_run()
        self._messages = []
        self._current_messages = []
        user_message = {"role": "user", "content": user_input}
        self.memory.append(run, "user", {"message": user_message, "text": user_input if isinstance(user_input, str) else "[image attachment turn]"})
        if isinstance(user_input, str):
            run_attachment_ids = tuple(re.findall(r"\batt_[A-Za-z0-9]+\b", user_input))
            for ordinal, attachment_id in enumerate(run_attachment_ids, start=1):
                self.memory.append(run, "attachment", {"attachment_id": attachment_id, "ordinal": ordinal})
                if self.attachments is not None:
                    self.attachments.bind_run(attachment_id, run.id)
        else:
            run_attachment_ids = ()
        self._current_messages.append(user_message)  # type: ignore[arg-type]
        tools = registry_tools(self.registry)
        emitter = (
            TraceEmitter(self._trace_sink, run_id=self._trace_run_id or run.id)
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
                self.memory.append(run, "error", {"error_code": "agent_call_failed", "error_type": type(exc).__name__[:64]})
                self.memory.finish(run, RunStatus.FAILED, "error")
                if emitter is not None and not isinstance(self.client, LLMClient):
                    emitter.emit(
                        "model_completed",
                        turn=turn,
                        status="error",
                        error_code="agent_call_failed",
                        error_type=type(exc).__name__[:64],
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
                assistant_message = assistant_entry(result)
                gate = self._review_manager.gate(run.id)
                if gate["pending"]:
                    # Preserve the attempted answer as model context, but do
                    # not turn it into a terminal record or trace event.
                    self._current_messages.append(assistant_message)
                    self._messages.append(assistant_message)
                    self.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {"role": "user", "content": review_gate_context(gate)}
                    self._current_messages.append(gate_message)  # type: ignore[arg-type]
                    self._messages.append(gate_message)  # type: ignore[arg-type]
                    self.memory.append(run, "review_gate", {"state": gate})
                    if emitter is not None:
                        emitter.emit("chart_review_required", turn=turn, state=gate)
                    continue
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

            assistant_message = assistant_entry(result)
            self._current_messages.append(assistant_message)
            self._messages.append(assistant_message)
            self.memory.append(run, "assistant", {"message": assistant_message})
            visual_evidence: list[ToolVisualEvidence] = []
            for call in result.tool_calls:
                if emitter is not None:
                    presentation = get_tool_presentation(call.name, tool=self.registry.get(call.name))
                    emitter.emit(
                        "tool_call",
                        turn=turn,
                        tool_name=call.name,
                        tool_display_name=presentation.display_name,
                        tool_label=presentation.label,
                        call_id=call.id,
                        arguments=summarize_arguments(call.arguments),
                    )
                observation = dispatch_observation(
                    self.registry, call.name, call.arguments
                )
                observation = self._apply_generation_review(
                    observation,
                    run_id=run.id,
                    call_id=call.id,
                    arguments=call.arguments,
                    source_attachment_ids=run_attachment_ids,
                )
                if self.registry.get("review_generated_chart") is not None:
                    tools = registry_tools(self.registry)
                review_transition = self._review_transition_image(call.name, observation.content)
                tool_message = tool_entry(call, observation.content)
                self._current_messages.append(tool_message)
                self._messages.append(tool_message)
                self.memory.append(run, "tool", {"message": tool_message, "tool_name": call.name, "status": observation_status(observation.content)})
                observation_refs: Sequence[dict[str, Any]] = ()
                sink_images = observation.images or review_transition
                if self._visual_observation_sink is not None and sink_images:
                    try:
                        observation_refs = self._visual_observation_sink(
                            call.name,
                            call.id,
                            sink_images,
                        )
                    except Exception:  # noqa: BLE001 - observation diagnostics cannot abort the Agent
                        observation_refs = ()
                if emitter is not None:
                    image_payload = {"images": summarize_images(observation.images)}
                    if observation_refs:
                        generated_refs = [
                            reference
                            for reference in observation_refs
                            if reference.get("artifactKind") == "generated_chart"
                        ]
                        regular_refs = [
                            reference
                            for reference in observation_refs
                            if reference.get("artifactKind") != "generated_chart"
                        ]
                        if regular_refs:
                            image_payload["observations"] = regular_refs
                        if generated_refs:
                            image_payload["artifacts"] = generated_refs
                    emitter.emit(
                        "tool_result",
                        turn=turn,
                        tool_name=call.name,
                        tool_display_name=presentation.display_name,
                        tool_label=presentation.label,
                        call_id=call.id,
                        status=observation_status(observation.content),
                        tool_status=observation_status(observation.content),
                        result=summarize_result(observation.content),
                        image_count=len(observation.images),
                    )
                    review_items = self._review_items(observation.content)
                    for item in review_items:
                        review_status = item.get("reviewStatus")
                        candidate_status = item.get("candidateStatus")
                        publication_status = item.get("publicationStatus")
                        common_review_fields = {
                            "tool_name": call.name,
                            "tool_display_name": presentation.display_name,
                            "tool_label": presentation.label,
                            "call_id": call.id,
                            "candidate_id": item.get("candidateId"),
                            "review_id": item.get("reviewId"),
                            "candidate_status": candidate_status,
                            "review_status": review_status,
                            "publication_status": publication_status,
                        }
                        if candidate_status == "review_pending" and review_status in {"pending", "requires_model_decision"}:
                            emitter.emit(
                                "chart_review_started",
                                turn=turn,
                                **common_review_fields,
                            )
                        if item.get("reviewStatus") == "completed":
                            emitter.emit(
                                "chart_review_completed",
                                turn=turn,
                                **common_review_fields,
                            )
                            if item.get("publicationStatus") in {"published", "published_with_warning"}:
                                emitter.emit(
                                    "generated_chart_published",
                                    turn=turn,
                                    **common_review_fields,
                                )
                            if item.get("publicationStatus") == "rejected":
                                emitter.emit(
                                    "generated_chart_rejected",
                                    turn=turn,
                                    **common_review_fields,
                                    reason="review_failed",
                                )
                    if observation.images:
                        emitter.emit(
                            "generated_chart" if any(
                                image.metadata.get("kind") == "generated_chart"
                                for image in observation.images
                                if hasattr(image.metadata, "get")
                            ) else "visual_observation",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            **image_payload,
                        )
                    if review_transition and observation_refs:
                        emitter.emit(
                            "generated_chart",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            artifacts=[
                                reference for reference in observation_refs
                                if reference.get("artifactKind") == "generated_chart"
                            ],
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

        terminal_answer = _BUDGET_MSG
        terminal_gate = self._review_manager.gate(run.id)
        if terminal_gate["pending"]:
            terminal_answer = _REVIEW_REQUIRED_MSG
        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=self.max_steps,
                max_steps=self.max_steps,
                answer=terminal_answer,
                review_gate=terminal_gate,
            )
        self.memory.append(run, "terminal", {"answer": terminal_answer, "max_steps": self.max_steps, "review_gate": terminal_gate})
        self.memory.finish(run, RunStatus.COMPLETED, "budget")
        return terminal_answer

    @staticmethod
    def _review_items(content: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(content)
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data.get("review") if isinstance(data, dict) else None
            if not isinstance(items, list):
                items = payload.get("review") if isinstance(payload, dict) else None
            if not isinstance(items, list) and isinstance(payload, dict) and isinstance(payload.get("candidate"), dict):
                items = [payload["candidate"]]
            return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    def _ensure_review_tool(self) -> None:
        if self.registry.get("review_generated_chart") is None:
            self.registry.register(review_generated_chart_tool(self._review_manager))

    def _review_transition_image(self, tool_name: str, content: str) -> tuple[GeneratedImage, ...]:
        """Expose a reviewed candidate to the Gateway promotion boundary."""
        if tool_name != "review_generated_chart":
            return ()
        try:
            payload = json.loads(content)
            candidate_payload = payload.get("candidate") if isinstance(payload, dict) else None
            if not isinstance(candidate_payload, dict):
                return ()
            candidate_id = candidate_payload.get("candidateId")
            review_id = candidate_payload.get("reviewId")
            candidate = self._review_manager.get(candidate_id, review_id)
            if candidate is None:
                return ()
            metadata = candidate.safe_metadata()
            metadata["kind"] = "generated_chart"
            return (GeneratedImage(candidate.content, candidate.media_type, f"生成图表：{candidate.title}", metadata),)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ()

    def _apply_generation_review(
        self,
        observation: Any,
        *,
        run_id: str,
        call_id: str,
        arguments: str,
        source_attachment_ids: Sequence[str],
    ) -> Any:
        """Run the post-generation hook before tool evidence reaches the model."""
        if not observation.images:
            return observation
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except (TypeError, json.JSONDecodeError):
            return observation
        spec_payload = args.get("spec") if isinstance(args, dict) else None
        if not isinstance(spec_payload, dict):
            return observation
        try:
            from ..spec import ChartSpec

            spec = ChartSpec.from_dict(spec_payload)
        except (TypeError, ValueError, KeyError):
            return observation
        generated: list[GeneratedImage] = []
        review_payloads: list[dict[str, Any]] = []
        changed = False
        for image in observation.images:
            metadata = image.metadata if hasattr(image.metadata, "get") else {}
            if metadata.get("kind") != "generated_chart":
                generated.append(image)
                continue
            # Legacy custom tools without a ChartSpec digest remain readable;
            # renderer-produced images always carry the digest and enter this
            # mandatory lifecycle.
            if not metadata.get("chart_spec_digest"):
                generated.append(image)
                continue
            candidate = self._review_manager.create_candidate(
                run_id,
                call_id,
                image,
                spec,
                source_attachment_ids=source_attachment_ids,
            )
            self._ensure_review_tool()
            if candidate.policy.semantic_required is False:
                candidate = self._review_manager.process(candidate)
            generated.append(self._review_manager.decorate_image(image, candidate))
            review_payloads.append(candidate.safe_metadata())
            changed = True
        if not changed:
            return observation
        content = observation.content
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, dict):
                    data = dict(data)
                    data["review"] = review_payloads
                    payload["data"] = data
                payload["review"] = review_payloads
                content = json.dumps(payload, ensure_ascii=False)
        except (TypeError, json.JSONDecodeError):
            pass
        from ..tools.core.result import DispatchedObservation

        return DispatchedObservation(content=content, images=tuple(generated))


_assistant_entry = assistant_entry
_tool_entry = tool_entry
_observation_status = observation_status
