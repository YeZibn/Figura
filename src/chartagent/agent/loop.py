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
from ..tools.core import ToolRegistry, dispatch_observation
from ..tools.core.presentation import get_tool_presentation
from ..memory import AgentMemory, InMemoryAgentMemory, RunStatus
from ..review import ChartReviewManager, ReviewIssue, ReviewResult, ReviewStatus, review_candidate_with_vlm
from ..tools.core.result import DispatchedObservation, GeneratedImage
from .tool_schema import registry_tools, tool_to_openai_schema
from .messages import assistant_entry, tool_entry
from .review_gate import (
    _BUDGET_MSG,
    _REVIEW_FAILED_MSG,
    _REVIEW_REQUIRED_MSG,
    review_gate_context,
)
from .observations import observation_status

# Sentinel returned when the step budget is exhausted.
VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]
_LAYOUT_TOOL_NAME = "inspect_chart_layout"
_DECOMPOSE_TOOL_NAME = "decompose_chart_image"
_MAX_LAYOUT_CONTEXTS = 32
_GEOMETRY_TOOL_NAMES = frozenset(
    {"measure_bars", "extract_line_series", "extract_scatter_points", "extract_pie_slices"}
)
_SCOPED_TOOL_NAMES = _GEOMETRY_TOOL_NAMES | {"extract_text"}
_RENDER_TOOL_NAMES = frozenset({"render_chart", "generate_chart"})


def _attach_visual_observation_refs(
    observation: DispatchedObservation,
    references: Sequence[dict[str, Any]],
) -> DispatchedObservation:
    """Attach managed visual-resource refs to decomposition crop records."""
    if not references or not observation.images:
        return observation
    try:
        payload = json.loads(observation.content)
    except (TypeError, json.JSONDecodeError):
        return observation
    if not isinstance(payload, dict):
        return observation
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("panels"), list):
        return observation
    by_key = {
        str(reference.get("resourceKey")): reference
        for reference in references
        if isinstance(reference, dict) and isinstance(reference.get("resourceKey"), str)
    }
    ordered_refs = [reference for reference in references if isinstance(reference, dict)]
    for image_index, image in enumerate(observation.images):
        metadata = image.metadata if hasattr(image.metadata, "get") else {}
        panel_id = metadata.get("panel_id") if isinstance(metadata, dict) else None
        resource_key = metadata.get("resource_key") if isinstance(metadata, dict) else None
        if not isinstance(panel_id, str):
            continue
        panel = next(
            (item for item in data["panels"] if isinstance(item, dict) and item.get("id") == panel_id),
            None,
        )
        if panel is None or not isinstance(panel.get("crop"), dict):
            continue
        reference = by_key.get(resource_key) if isinstance(resource_key, str) else None
        if reference is None and len(ordered_refs) == len(observation.images):
            reference = ordered_refs[image_index]
        crop = dict(panel["crop"])
        crop["resource_ref"] = dict(reference) if isinstance(reference, dict) else None
        crop["status"] = "persisted" if reference is not None else "unavailable"
        panel["crop"] = crop
        layout_context = panel.get("layout_context")
        if isinstance(layout_context, dict):
            panel_context = dict(layout_context.get("panel") or {})
            panel_context["crop_ref"] = crop["resource_ref"]
            layout_context["panel"] = panel_context
    payload["data"] = data
    return DispatchedObservation(
        content=json.dumps(payload, ensure_ascii=False),
        images=observation.images,
    )


class AgentInterrupted(RuntimeError):
    """Raised when a cooperative run interruption is observed."""


class AgentRecoveryBlocked(RuntimeError):
    """Raised when a continuation reaches an operation with an unknown outcome."""


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
        interruption_event: Any = None,
        recovery_context: Optional[dict[str, Any]] = None,
        checkpoint_sink: Optional[Callable[..., bool]] = None,
        operation_begin: Optional[Callable[..., dict[str, Any]]] = None,
        operation_complete: Optional[Callable[..., dict[str, Any] | None]] = None,
        operation_uncertain: Optional[Callable[..., dict[str, Any] | None]] = None,
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
        self._interruption_event = interruption_event
        self._recovery_context = recovery_context
        self._checkpoint_sink = checkpoint_sink
        self._operation_begin = operation_begin
        self._operation_complete = operation_complete
        self._operation_uncertain = operation_uncertain
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
        """Drive one user turn to completion (final answer or budget cap).

        ``user_input`` is a plain string or an OpenAI multimodal content list
        (e.g. from ``build_user_content``); it is appended to history and
        forwarded to the client unchanged.
        """
        if self._interruption_requested():
            raise AgentInterrupted("Agent run was interrupted before it started")
        recovery = recovery_context if recovery_context is not None else self._recovery_context
        run = self.memory.begin_run(self._run_id) if self._run_id is not None else self.memory.begin_run()
        self._messages = []
        self._current_messages = []
        layout_contexts: dict[str, dict[str, Any]] = {}
        checkpoint_references: list[dict[str, Any]] = []
        if isinstance(recovery, dict):
            loader = getattr(self.memory, "recovery_context", None)
            hydrated = loader(recovery, budget=self.context_budget) if callable(loader) else []
            if hydrated:
                self._current_messages.extend(hydrated)  # type: ignore[arg-type]
            raw_layouts = recovery.get("layoutContexts")
            if isinstance(raw_layouts, dict):
                layout_contexts = {
                    str(key): value for key, value in list(raw_layouts.items())[:_MAX_LAYOUT_CONTEXTS]
                    if isinstance(value, dict)
                }
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
        self._hydrate_persisted_panel_contexts(layout_contexts, run_attachment_ids)
        if not self._current_messages or self._current_messages[-1].get("role") != "user":
            self._current_messages.append(user_message)  # type: ignore[arg-type]
        tools = registry_tools(self.registry)
        emitter = (
            TraceEmitter(self._trace_sink, run_id=self._trace_run_id or run.id)
            if self._trace_sink is not None
            else None
        )

        pending_recovery_calls = self._recovery_tool_calls(recovery)
        if isinstance(recovery, dict) and recovery.get("nextAction") == "final" and isinstance(recovery.get("pendingAnswer"), str):
            answer = str(recovery["pendingAnswer"])
            self.memory.append(run, "final", {"answer": answer, "recovered": True})
            self.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
            return answer
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
            self._raise_if_interrupted(run)
            operation_id = f"model:{turn}"
            if pending_recovery_calls:
                result = NormalizedResult(tool_calls=pending_recovery_calls, finish_reason="tool_calls")
                pending_recovery_calls = []
            else:
                self._begin_work_unit(operation_id, "model")
                try:
                    result = self.client.chat(self._messages, tools=tools, **chat_kwargs)
                except Exception as exc:
                    self._uncertain_work_unit(operation_id, "model_response_outcome_uncertain")
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
                self._complete_work_unit(operation_id, "model", self._model_result_payload(result))

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
                self._raise_if_interrupted(run)
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
                if gate["failed"]:
                    self._current_messages.append(assistant_message)
                    self._messages.append(assistant_message)
                    self.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {"role": "user", "content": review_gate_context(gate)}
                    self.memory.append(run, "review_gate", {"state": gate})
                    if gate.get("retryable") and turn < self.max_steps:
                        self._current_messages.append(gate_message)  # type: ignore[arg-type]
                        self._messages.append(gate_message)  # type: ignore[arg-type]
                        self._checkpoint(
                            run,
                            phase="review",
                            next_action=str((gate.get("recoveryActions") or [{}])[0].get("action", "correct_chart_spec")),
                            state=self._checkpoint_state(
                                user_input,
                                self._current_messages,
                                layout_contexts,
                                run_attachment_ids,
                                turn,
                                pending_tool_calls=(),
                                visual_references=checkpoint_references,
                            ),
                        )
                        if emitter is not None:
                            emitter.emit("chart_review_repair_required", turn=turn, state=gate)
                        continue
                    if emitter is not None:
                        emitter.emit("generated_chart_rejected", turn=turn, state=gate, reason="review_failed")
                    self.memory.append(run, "terminal", {"answer": _REVIEW_FAILED_MSG, "review_gate": gate})
                    self.memory.finish(run, RunStatus.COMPLETED, "review_failed")
                    return _REVIEW_FAILED_MSG
                self._current_messages.append(assistant_message)
                self._messages.append(assistant_message)
                self.memory.append(run, "assistant", {"message": assistant_message})
                self._checkpoint(
                    run,
                    phase="model",
                    next_action="final",
                    state=self._checkpoint_state(
                        user_input,
                        self._current_messages,
                        layout_contexts,
                        run_attachment_ids,
                        turn,
                        pending_tool_calls=(),
                        pending_answer=result.content,
                        visual_references=checkpoint_references,
                    ),
                )
                if isinstance(recovery, dict) and recovery.get("nextAction") == "final" and isinstance(recovery.get("pendingAnswer"), str):
                    answer = str(recovery["pendingAnswer"])
                    self.memory.append(run, "final", {"answer": answer, "recovered": True})
                    self.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
                    return answer
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

            assistant_message = assistant_entry(
                result,
                include_reasoning=(
                    getattr(getattr(self.client, "config", None), "provider", None) == "deepseek"
                    and getattr(getattr(self.client, "config", None), "enable_thinking", False)
                    and bool(result.reasoning)
                ),
            )
            # ``assistant_message`` is the model-facing message. The memory
            # record stays sanitized and content/tool-call-only so provider
            # reasoning cannot leak into transcripts or ordinary records.
            assistant_record = assistant_entry(result)
            self._current_messages.append(assistant_message)
            self._messages.append(assistant_message)
            self.memory.append(run, "assistant", {"message": assistant_record})
            self._checkpoint(
                run,
                phase="model",
                next_action="tool",
                state=self._checkpoint_state(
                    user_input,
                    self._current_messages,
                    layout_contexts,
                    run_attachment_ids,
                    turn,
                    pending_tool_calls=result.tool_calls,
                    visual_references=checkpoint_references,
                ),
            )
            visual_evidence: list[ToolVisualEvidence] = []
            for call_index, call in enumerate(result.tool_calls):
                self._raise_if_interrupted(run)
                operation_kind = "render" if call.name in _RENDER_TOOL_NAMES else "tool"
                operation_id = f"{operation_kind}:{turn}:{call.id}"
                operation = self._begin_work_unit(operation_id, operation_kind)
                if isinstance(recovery, dict) and operation.get("state") in {"in_flight", "uncertain"}:
                    self._uncertain_work_unit(operation_id, "operation_outcome_uncertain")
                    raise AgentRecoveryBlocked("operation outcome is uncertain")
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
                dispatch_arguments = self._layout_arguments(
                    call.name,
                    call.arguments,
                    layout_contexts,
                )
                routing_error = self._panel_routing_error(
                    call.name,
                    call.arguments,
                    layout_contexts,
                )
                if routing_error is not None:
                    observation = DispatchedObservation(
                        json.dumps({"error": routing_error}, ensure_ascii=False)
                    )
                else:
                    observation = dispatch_observation(
                        self.registry, call.name, dispatch_arguments
                    )
                self._raise_if_interrupted(run)
                if call.name in {_LAYOUT_TOOL_NAME, _DECOMPOSE_TOOL_NAME}:
                    self._remember_layout_context(
                        observation.content,
                        call.arguments,
                        layout_contexts,
                    )
                review_operation_id = None
                if any(
                    isinstance(getattr(image, "metadata", None), dict)
                    and image.metadata.get("kind") == "generated_chart"
                    for image in observation.images
                ):
                    review_operation_id = f"review:{turn}:{call.id}"
                    self._begin_work_unit(review_operation_id, "review")
                observation = self._apply_generation_review(
                    observation,
                    run_id=run.id,
                    call_id=call.id,
                    arguments=call.arguments,
                    source_attachment_ids=run_attachment_ids,
                    emitter=emitter,
                    turn=turn,
                )
                self._raise_if_interrupted(run)
                if review_operation_id:
                    self._complete_work_unit(review_operation_id, "review", {"status": "completed"})
                observation_refs: Sequence[dict[str, Any]] = ()
                sink_images = observation.images
                if self._visual_observation_sink is not None and sink_images:
                    self._raise_if_interrupted(run)
                    try:
                        observation_refs = self._visual_observation_sink(
                            call.name,
                            call.id,
                            sink_images,
                        )
                    except Exception:  # noqa: BLE001 - observation diagnostics cannot abort the Agent
                        observation_refs = ()
                observation = _attach_visual_observation_refs(observation, observation_refs)
                tool_message = tool_entry(call, observation.content)
                self._current_messages.append(tool_message)
                self._messages.append(tool_message)
                self.memory.append(run, "tool", {"message": tool_message, "tool_name": call.name, "status": observation_status(observation.content)})
                checkpoint_references.extend(
                    item for item in observation_refs if isinstance(item, dict)
                )
                self._complete_work_unit(
                    operation_id,
                    operation_kind,
                    {"status": observation_status(observation.content)},
                    {"observations": list(observation_refs)},
                )
                remaining_calls = result.tool_calls[call_index + 1:]
                self._checkpoint(
                    run,
                    phase="tool",
                    next_action="tool" if remaining_calls else "model",
                    state=self._checkpoint_state(
                        user_input,
                        self._current_messages,
                        layout_contexts,
                        run_attachment_ids,
                        turn,
                        pending_tool_calls=remaining_calls,
                        visual_references=checkpoint_references,
                    ),
                )
                if emitter is not None:
                    self._raise_if_interrupted(run)
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
                            "review_mode": item.get("reviewMode"),
                            "internal_review": item.get("reviewMode") == "vlm",
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
                visual_evidence.extend(
                    ToolVisualEvidence(call.name, call.id, generated)
                    for generated in observation.images
                )
            if visual_evidence:
                self._raise_if_interrupted(run)
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
        self._raise_if_interrupted(run)
        terminal_answer = _BUDGET_MSG
        terminal_gate = self._review_manager.gate(run.id)
        if terminal_gate["pending"] or terminal_gate["failed"]:
            terminal_answer = _REVIEW_REQUIRED_MSG if terminal_gate["pending"] else _REVIEW_FAILED_MSG
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

    def _begin_work_unit(self, operation_id: str, operation_kind: str) -> dict[str, Any]:
        if self._operation_begin is None:
            return {"operationId": operation_id, "state": "in_flight"}
        try:
            result = self._operation_begin(operation_id, operation_kind)
            return result if isinstance(result, dict) else {"operationId": operation_id, "state": "in_flight"}
        except Exception:  # noqa: BLE001 - journaling remains a bounded diagnostic
            return {"operationId": operation_id, "state": "in_flight"}

    def _complete_work_unit(
        self,
        operation_id: str,
        operation_kind: str,
        result: dict[str, Any] | None = None,
        references: dict[str, Any] | None = None,
    ) -> None:
        if self._operation_complete is None:
            return
        try:
            self._operation_complete(operation_id, result=result, references=references)
        except Exception:  # noqa: BLE001 - trace persistence cannot stop the Agent
            self._uncertain_work_unit(operation_id, f"{operation_kind}_persistence_failed")

    def _uncertain_work_unit(self, operation_id: str, reason: str) -> None:
        if self._operation_uncertain is None:
            return
        try:
            self._operation_uncertain(operation_id, reason=reason)
        except Exception:  # noqa: BLE001 - bounded recovery fallback
            pass

    def _checkpoint(
        self,
        run: Any,
        *,
        state: dict[str, Any],
        phase: str,
        next_action: str,
    ) -> None:
        if self._checkpoint_sink is None:
            return
        try:
            checkpoint_state = dict(state)
            checkpoint_state.setdefault("phase", phase)
            checkpoint_state["nextAction"] = next_action
            self._checkpoint_sink(checkpoint_state, phase=phase, next_action=next_action)
        except Exception:  # noqa: BLE001 - checkpoint failure is surfaced as unavailable metadata
            return

    @staticmethod
    def _checkpoint_state(
        user_input: str | list[dict],
        messages: Sequence[dict[str, Any]],
        layout_contexts: dict[str, dict[str, Any]],
        attachment_ids: Sequence[str],
        turn: int,
        *,
        pending_tool_calls: Sequence[ToolCall],
        pending_answer: str | None = None,
        visual_references: Sequence[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        result = {
            "prompt": user_input if isinstance(user_input, str) else "[image attachment turn]",
            "messages": list(messages),
            "layoutContexts": layout_contexts,
            "attachmentIds": list(attachment_ids),
            "currentTurn": turn,
            "pendingToolCalls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in pending_tool_calls
            ],
            "visualReferences": list(visual_references)[:32],
        }
        if pending_answer is not None:
            result["pendingAnswer"] = pending_answer
        return result

    @staticmethod
    def _model_result_payload(result: NormalizedResult) -> dict[str, Any]:
        return {
            "content": result.content,
            "finishReason": result.finish_reason,
            "toolCalls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in result.tool_calls
            ],
        }

    @staticmethod
    def _recovery_tool_calls(recovery: Optional[dict[str, Any]]) -> list[ToolCall]:
        if not isinstance(recovery, dict) or recovery.get("nextAction") not in {"tool", "dispatch_tool"}:
            return []
        raw = recovery.get("pendingToolCalls")
        if not isinstance(raw, list):
            return []
        calls: list[ToolCall] = []
        for item in raw[:16]:
            if not isinstance(item, dict):
                continue
            if not all(isinstance(item.get(key), str) and item.get(key) for key in ("id", "name", "arguments")):
                continue
            calls.append(ToolCall(item["id"], item["name"], item["arguments"]))
        return calls

    def _interruption_requested(self) -> bool:
        event = self._interruption_event
        if event is None:
            return False
        if callable(event):
            try:
                return bool(event())
            except Exception:  # noqa: BLE001 - cancellation must remain best effort
                return False
        is_set = getattr(event, "is_set", None)
        return bool(is_set()) if callable(is_set) else bool(event)

    def _raise_if_interrupted(self, run: Any) -> None:
        if not self._interruption_requested():
            return
        try:
            self.memory.finish(run, RunStatus.INTERRUPTED, "interrupted")
        finally:
            raise AgentInterrupted("Agent run was interrupted")

    @staticmethod
    def _layout_arguments(
        tool_name: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> str:
        """Inject one cached validated layout into a geometry call."""
        if tool_name not in _GEOMETRY_TOOL_NAMES or not layout_contexts:
            return arguments
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return arguments
        if not isinstance(parsed, dict) or parsed.get("layout_context") is not None:
            return arguments
        attachment_id = parsed.get("attachment_id")
        panel_id = parsed.get("panel_id")
        context = None
        if isinstance(attachment_id, str) and isinstance(panel_id, str) and panel_id:
            context = layout_contexts.get(f"{attachment_id}::{panel_id}")
        if context is None and isinstance(attachment_id, str):
            context = layout_contexts.get(attachment_id)
        if context is None and len(layout_contexts) == 1:
            context = next(iter(layout_contexts.values()))
        if context is None:
            return arguments
        parsed["layout_context"] = context
        # Keep the public call compatible with direct test/custom sensors; the
        # authorized adapter recovers the panel ID from the injected context.
        parsed.pop("panel_id", None)
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _panel_routing_error(
        tool_name: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> str | None:
        """Reject an unresolved explicit panel route before sensor dispatch."""
        if tool_name not in _SCOPED_TOOL_NAMES:
            return None
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict) or "panel_id" not in parsed:
            return None
        panel_id = parsed.get("panel_id")
        attachment_id = parsed.get("attachment_id")
        if not isinstance(panel_id, str) or not panel_id.strip():
            return "panel routing failed: panel_id must be a non-empty stable identifier"
        if not isinstance(attachment_id, str) or not attachment_id.strip():
            return "panel routing failed: attachment_id is required with panel_id"
        key = f"{attachment_id}::{panel_id}"
        context = layout_contexts.get(key)
        if not isinstance(context, dict):
            return f"panel routing failed: {panel_id!r} is not registered for this attachment"
        scope = context.get("analysis_scope", context.get("panel_scope"))
        if not isinstance(scope, dict) or not isinstance(scope.get("bbox_px"), (list, tuple)):
            return f"panel routing failed: {panel_id!r} has no usable analysis scope"
        return None

    def _hydrate_persisted_panel_contexts(
        self,
        layout_contexts: dict[str, dict[str, Any]],
        attachment_ids: Sequence[str],
    ) -> None:
        """Load durable panel scopes into this run's routing cache."""
        store = getattr(self.attachments, "panel_store", None)
        if store is None or not hasattr(store, "list_panel_handoffs"):
            return
        ids = tuple(attachment_ids)
        if not ids and hasattr(store, "get_active_source"):
            ids = tuple(getattr(store.get_active_source(), "attachment_ids", ()) or ())
        for attachment_id in ids[:16]:
            try:
                handoffs = store.list_panel_handoffs(attachment_id)
            except Exception:  # noqa: BLE001 - persisted routing is advisory
                continue
            for handoff in handoffs[:_MAX_LAYOUT_CONTEXTS]:
                context = {
                    "version": 1,
                    "context_id": f"{handoff.panel_id}_layout",
                    "source_attachment_id": handoff.attachment_id,
                    "coordinate_system": "polar_2d" if handoff.chart_type == "pie" else "cartesian_2d" if handoff.role == "chart" or handoff.chart_type in {"bar", "line", "scatter"} else "unknown",
                    "analysis_scope": {
                        "role": "panel_scope",
                        "bbox_px": list(handoff.analysis_scope),
                        "source_origin_px": list(handoff.source_origin),
                        "confidence": handoff.confidence,
                        "evidence": ["persisted_panel_handoff"],
                    },
                    "measurement_frame": None,
                    "panel": {
                        "id": handoff.panel_id,
                        "name": handoff.name,
                        "source_bbox_px": list(handoff.source_bbox),
                        "scope_bbox_px": list(handoff.analysis_scope),
                    },
                    "validation": {
                        "status": "accepted" if handoff.status == "active" else "partial",
                        "accepted_for_analysis": handoff.status == "active",
                        "accepted_for_measurement": False,
                        "confidence": handoff.confidence,
                        "warnings": list(handoff.warnings),
                    },
                    "evidence": ["persisted_panel_handoff", "source_coordinates"],
                }
                layout_contexts[f"{attachment_id}::{handoff.panel_id}"] = context
                if len(layout_contexts) >= _MAX_LAYOUT_CONTEXTS:
                    return

    @staticmethod
    def _remember_layout_context(
        content: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> None:
        try:
            payload = json.loads(content)
            parsed_arguments = json.loads(arguments) if arguments.strip() else {}
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(payload, dict) or not isinstance(parsed_arguments, dict):
            return
        attachment_id = parsed_arguments.get("attachment_id")
        if not isinstance(attachment_id, str) or not attachment_id:
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        if isinstance(data.get("panels"), list):
            for panel in data["panels"]:
                if not isinstance(panel, dict) or not isinstance(panel.get("id"), str):
                    continue
                context = panel.get("layout_context")
                if not isinstance(context, dict):
                    continue
                cached = dict(context)
                cached["source_attachment_id"] = attachment_id
                panel_summary = dict(cached.get("panel") or {})
                panel_summary.update(
                    {
                        "id": panel["id"],
                        "name": panel.get("name"),
                        "chart_type": panel.get("chart_type"),
                    }
                )
                cached["panel"] = panel_summary
                layout_contexts[f"{attachment_id}::{panel['id']}"] = cached
                while len(layout_contexts) > _MAX_LAYOUT_CONTEXTS:
                    layout_contexts.pop(next(iter(layout_contexts)))
            return
        context = data.get("layout_context")
        if not isinstance(context, dict):
            return
        cached = dict(context)
        cached["source_attachment_id"] = attachment_id
        layout_contexts[attachment_id] = cached
        while len(layout_contexts) > _MAX_LAYOUT_CONTEXTS:
            layout_contexts.pop(next(iter(layout_contexts)))

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

    def _apply_generation_review(
        self,
        observation: Any,
        *,
        run_id: str,
        call_id: str,
        arguments: str,
        source_attachment_ids: Sequence[str],
        emitter: TraceEmitter | None = None,
        turn: int | None = None,
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
            if candidate.review_status is ReviewStatus.PENDING:
                semantic_result: ReviewResult | None = None
                if candidate.policy.semantic_required:
                    source_payload = self._review_manager.source_payload(candidate)
                    if source_payload is None:
                        semantic_result = ReviewResult(
                            status=ReviewStatus.FAILED,
                            checks={"source_evidence": "failed"},
                            issues=(ReviewIssue(
                                "source_binding_failure",
                                "source_attachment_ids",
                                "authorized source attachment is unavailable; bind an active source before retrying",
                            ),),
                            decision="fail",
                            confidence=0.0,
                            review_mode="vlm",
                            suggested_action="rebind_source",
                            recovery_classification="source_binding_failure",
                        )
                    else:
                        if emitter is not None:
                            emitter.emit(
                                "chart_review_started",
                                turn=turn,
                                internal_review=True,
                                tool_count=0,
                                candidate_id=candidate.candidate_id,
                                review_id=candidate.review_id,
                                review_mode="vlm",
                            )
                        semantic_result = review_candidate_with_vlm(
                            self.client,
                            candidate,
                            spec,
                            source_image=source_payload[0],
                            source_media_type=source_payload[1],
                            chat_kwargs=self._chat_kwargs,
                            trace_kwargs=(
                                {
                                    "trace_sink": emitter,
                                    "trace_run_id": emitter.run_id,
                                    "trace_turn": turn,
                                }
                                if emitter is not None and isinstance(self.client, LLMClient)
                                else None
                            ),
                        )
                candidate = self._review_manager.process(candidate, semantic_result=semantic_result)
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
