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
from collections.abc import Mapping
from typing import Any, Callable, List, Optional, Sequence

from ..client.client import LLMClient
from ..client.models import NormalizedResult, ToolCall
from ..decision_context import build_decision_context
from ..multimodal import ToolVisualEvidence, build_tool_observation_content
from ..prompting import assemble_prompt_context, panel_inventory_from_layout_contexts
from ..trace import (
    TraceEmitter,
    TraceSink,
    bounded_reasoning,
    summarize_arguments,
    summarize_images,
)
from ..tools.core import ToolRegistry
from ..tools.core.presentation import get_tool_presentation
from ..memory import AgentMemory, InMemoryAgentMemory, RunStatus
from ..measurement import (
    MEASUREMENT_TOOLS,
    MeasurementSession,
    sessions_from_state,
    sessions_to_state,
)
from ..review import (
    ChartReviewManager,
    GeneratedChartReviewAdapter,
    ReviewCoordinator,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    review_candidate_with_vlm,
)
from ..tools.core.result import GeneratedImage
from .tool_schema import registry_tools, tool_to_openai_schema
from .messages import assistant_entry, tool_entry
from .review_gate import (
    _BUDGET_MSG,
    _REVIEW_FAILED_MSG,
    _REVIEW_REQUIRED_MSG,
    review_gate_context,
)
from .observations import observation_status
from .artifacts import (
    _artifact_records_from_observation,
    _attach_visual_observation_refs,
    _lifecycle_trace_fields,
    _trace_result_summary,
)
from .measurement_flow import (
    _measurement_repair_context_from_content,
    _measurement_repair_contexts_from_sessions,
    _measurement_trace_fields,
    _merge_measurement_repair_contexts,
    measurement_decisions_from_content,
    register_measurement_observation,
)
from .panel_routing import (
    MAX_LAYOUT_CONTEXTS as _MAX_LAYOUT_CONTEXTS_CANONICAL,
    hydrate_persisted_panel_contexts,
    layout_arguments,
    panel_routing_error,
    remember_layout_context,
)
from .recovery import (
    AgentInterrupted,
    AgentRecoveryBlocked,
    begin_work_unit,
    checkpoint,
    checkpoint_state,
    complete_work_unit,
    interruption_requested,
    model_result_payload,
    raise_if_interrupted,
    recovery_tool_calls,
    uncertain_work_unit,
)
from .turn import (
    assistant_message_for_result,
    execute_model_turn,
    prepare_and_dispatch_tool_call,
)

# Sentinel returned when the step budget is exhausted.
VisualObservationSink = Callable[[str, str, Sequence[GeneratedImage]], Sequence[dict[str, Any]]]
_LAYOUT_TOOL_NAME = "inspect_chart_layout"
_DECOMPOSE_TOOL_NAME = "decompose_chart_image"
_MAX_LAYOUT_CONTEXTS = _MAX_LAYOUT_CONTEXTS_CANONICAL
_RENDER_TOOL_NAMES = frozenset({"render_chart", "generate_chart"})


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
        review_coordinator: Optional[ReviewCoordinator] = None,
        interruption_event: Any = None,
        recovery_context: Optional[dict[str, Any]] = None,
        checkpoint_sink: Optional[Callable[..., bool]] = None,
        operation_begin: Optional[Callable[..., dict[str, Any]]] = None,
        operation_complete: Optional[Callable[..., dict[str, Any] | None]] = None,
        operation_uncertain: Optional[Callable[..., dict[str, Any] | None]] = None,
        execution_gate_sink: Optional[Callable[[Mapping[str, Any]], Any]] = None,
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
        self._review_coordinator = review_coordinator or ReviewCoordinator()
        self._generated_chart_review_adapter = GeneratedChartReviewAdapter()
        self._interruption_event = interruption_event
        self._recovery_context = recovery_context
        self._checkpoint_sink = checkpoint_sink
        self._operation_begin = operation_begin
        self._operation_complete = operation_complete
        self._operation_uncertain = operation_uncertain
        self._execution_gate_sink = execution_gate_sink
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
        artifact_records: list[dict[str, Any]] = []
        checkpoint_references: list[dict[str, Any]] = []
        measurement_sessions: dict[str, MeasurementSession] = {}
        pending_measurement_repairs: list[dict[str, Any]] = []
        measurement_decision_seen: set[str] = set()
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
            raw_artifacts = recovery.get("artifactIndex")
            if isinstance(raw_artifacts, list):
                artifact_records = [
                    item for item in raw_artifacts[:48] if isinstance(item, dict)
                ]
            measurement_sessions = sessions_from_state(recovery.get("measurementSessions"))
            review_state = recovery.get("reviewState") if isinstance(recovery.get("reviewState"), Mapping) else {}
            self._review_coordinator.restore(review_state.get("records", []))
            if isinstance(review_state.get("executionGate"), Mapping):
                self._review_coordinator.restore_gate(run.id, review_state["executionGate"])
            elif isinstance(recovery.get("executionGate"), Mapping):
                self._review_coordinator.restore_gate(run.id, recovery["executionGate"])
            pending_measurement_repairs = _measurement_repair_contexts_from_sessions(measurement_sessions)
            raw_repairs = recovery.get("pendingMeasurementRepairs")
            if isinstance(raw_repairs, list):
                pending_measurement_repairs = _merge_measurement_repair_contexts(
                    pending_measurement_repairs,
                    raw_repairs,
                )
            elif isinstance(recovery.get("pendingMeasurementRepair"), dict):
                pending_measurement_repairs = _merge_measurement_repair_contexts(
                    pending_measurement_repairs,
                    [recovery["pendingMeasurementRepair"]],
                )
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
        selected_panel_id: str | None = None
        current_tool_name: str | None = None
        pending_action = "检查当前请求并选择所需证据"
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
            system_message = None
            prompt_metadata: dict[str, Any] | None = None
            if self._system:
                review_gate = self._review_manager.gate(run.id)
                panel_inventory = panel_inventory_from_layout_contexts(layout_contexts)
                selected_panel = next(
                    (item for item in panel_inventory if item.get("panel_id") == selected_panel_id),
                    None,
                )
                active_generation_context = None
                for candidate_item in (
                    list(review_gate.get("pending") or []) + list(review_gate.get("failed") or [])
                ):
                    if isinstance(candidate_item, Mapping) and isinstance(candidate_item.get("generationContext"), Mapping):
                        active_generation_context = candidate_item["generationContext"]
                        break
                execution_gate = self._review_coordinator.gate(run.id).to_dict()
                decision_context = build_decision_context(
                    run_id=run.id,
                    execution_gate=execution_gate,
                    measurement_evidence=pending_measurement_repairs,
                    selected_panel=selected_panel,
                    generation_context=active_generation_context,
                    phase="model",
                    retry_budget=self.max_steps,
                )
                prompt_context = assemble_prompt_context(
                    tools=self.registry.list(),
                    artifacts=artifact_records,
                    runtime_state={
                        "run_id": run.id,
                        "phase": "model",
                        "active_source": run_attachment_ids,
                        "selected_panel": selected_panel,
                        "current_tool": current_tool_name,
                        "pending_action": pending_action,
                        "measurement_evidence": pending_measurement_repairs,
                        "recovery_status": "recovery_context_loaded" if recovery else "none",
                        "retry_count": max(
                            [
                                int(item.get("attempts", 0) or 0)
                                for item in (review_gate.get("failed") or [])
                                if isinstance(item, dict)
                            ]
                            or [0]
                        ),
                        "retry_budget": self.max_steps,
                        "publication_status": "published" if review_gate.get("published") else "not_published",
                        "execution_gate": execution_gate,
                        "generation_context": active_generation_context,
                        "decision_context": decision_context,
                    },
                    panel_inventory=panel_inventory,
                    review_gate=review_gate,
                )
                prompt_metadata = prompt_context["metadata"]
                dynamic = "\n\n".join(
                    (prompt_context["tools"], prompt_context["runtime"], prompt_context["artifacts"])
                )
                system_message = {"role": "system", "content": f"{self._system}\n\n{dynamic}"}
            self._messages = self.memory.context(run, system_message, self.context_budget, current_messages=self._current_messages)
            if emitter is not None and not isinstance(self.client, LLMClient):
                emitter.emit(
                    "model_started",
                    turn=turn,
                    model=self._chat_kwargs.get("model"),
                    message_count=len(self._messages),
                    tool_count=len(tools),
                    prompt_bundle=prompt_metadata,
                )
            chat_kwargs = dict(self._chat_kwargs)
            if emitter is not None and isinstance(self.client, LLMClient):
                chat_kwargs.update(
                    trace_sink=emitter,
                    trace_run_id=emitter.run_id,
                    trace_turn=turn,
                )
            result, pending_recovery_calls = execute_model_turn(
                self.client,
                self._messages,
                tools,
                chat_kwargs=chat_kwargs,
                pending_recovery_calls=pending_recovery_calls,
                operation_begin=self._operation_begin,
                operation_complete=self._operation_complete,
                operation_uncertain=self._operation_uncertain,
                memory=self.memory,
                run=run,
                interruption_event=self._interruption_event,
                emitter=emitter,
                turn=turn,
                trace_reasoning=self._trace_reasoning,
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
                                artifact_records=artifact_records,
                                measurement_sessions=measurement_sessions,
                                pending_measurement_repairs=pending_measurement_repairs,
                            ),
                        )
                        if emitter is not None:
                            emitter.emit("chart_review_repair_required", turn=turn, state=gate)
                        continue
                    if emitter is not None:
                        emitter.emit("generated_chart_rejected", turn=turn, state=gate, reason="review_failed")
                    self.memory.append(run, "terminal", {"answer": _REVIEW_FAILED_MSG, "review_gate": gate})
                    self.memory.finish(run, RunStatus.FAILED, "review_failed")
                    return _REVIEW_FAILED_MSG
                shared_gate = self._review_coordinator.gate(run.id)
                if shared_gate.blocking:
                    self._current_messages.append(assistant_message)
                    self._messages.append(assistant_message)
                    self.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {
                        "role": "user",
                        "content": json.dumps(
                            {"type": "execution_review_gate", "execution_gate": shared_gate.to_dict()},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                    self._current_messages.append(gate_message)  # type: ignore[arg-type]
                    self._messages.append(gate_message)  # type: ignore[arg-type]
                    self.memory.append(run, "review_gate", {"state": shared_gate.to_dict()})
                    if emitter is not None:
                        emitter.emit("review_gate_required", turn=turn, execution_gate=shared_gate.to_dict())
                    if shared_gate.state.value in {"failed", "exhausted"} or turn >= self.max_steps:
                        self.memory.append(
                            run,
                            "terminal",
                            {"answer": _REVIEW_FAILED_MSG, "execution_gate": shared_gate.to_dict()},
                        )
                        self.memory.finish(run, RunStatus.FAILED, "review_failed")
                        return _REVIEW_FAILED_MSG
                    self._checkpoint(
                        run,
                        phase="review",
                        next_action=shared_gate.next_action or "repair_review_gate",
                        state=self._checkpoint_state(
                            user_input,
                            self._current_messages,
                            layout_contexts,
                            run_attachment_ids,
                            turn,
                            pending_tool_calls=(),
                            visual_references=checkpoint_references,
                            artifact_records=artifact_records,
                            measurement_sessions=measurement_sessions,
                            pending_measurement_repairs=pending_measurement_repairs,
                        ),
                    )
                    continue
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
                        artifact_records=artifact_records,
                        measurement_sessions=measurement_sessions,
                        pending_measurement_repairs=pending_measurement_repairs,
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

            assistant_message, assistant_record = assistant_message_for_result(
                result,
                client=self.client,
            )
            # ``assistant_message`` is the model-facing message. The memory
            # record stays sanitized and content/tool-call-only so provider
            # reasoning cannot leak into transcripts or ordinary records.
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
                    artifact_records=artifact_records,
                    measurement_sessions=measurement_sessions,
                    pending_measurement_repairs=pending_measurement_repairs,
                ),
            )
            visual_evidence: list[ToolVisualEvidence] = []
            for call_index, call in enumerate(result.tool_calls):
                self._raise_if_interrupted(run)
                current_tool_name = call.name
                pending_action = f"执行 {call.name} 并把结果作为当前 run 的证据"
                try:
                    call_arguments = json.loads(call.arguments) if call.arguments.strip() else {}
                except (TypeError, json.JSONDecodeError):
                    call_arguments = {}
                if not self._review_gate_allows_call(
                    run.id,
                    call.name,
                    call_arguments if isinstance(call_arguments, Mapping) else {},
                ):
                    active_gate = self._review_coordinator.gate(run.id)
                    self._skip_tool_calls(
                        run,
                        result.tool_calls[call_index:],
                        gate=active_gate,
                        emitter=emitter,
                        turn=turn,
                    )
                    self._checkpoint(
                        run,
                        phase="review",
                        next_action="model",
                        state=self._checkpoint_state(
                            user_input,
                            self._current_messages,
                            layout_contexts,
                            run_attachment_ids,
                            turn,
                            pending_tool_calls=(),
                            visual_references=checkpoint_references,
                            artifact_records=artifact_records,
                            measurement_sessions=measurement_sessions,
                            pending_measurement_repairs=pending_measurement_repairs,
                        ),
                    )
                    break
                if isinstance(call_arguments, dict) and isinstance(call_arguments.get("panel_id"), str):
                    selected_panel_id = call_arguments["panel_id"]
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
                dispatch = prepare_and_dispatch_tool_call(
                    self.registry,
                    call,
                    run_id=run.id,
                    layout_contexts=layout_contexts,
                    measurement_sessions=measurement_sessions,
                )
                call_arguments = dispatch.call_arguments
                source_panel_id = dispatch.source_panel_id
                source_attachment_id = dispatch.source_attachment_id
                parent_attempt_id = dispatch.parent_attempt_id
                raw_observation_scope = dispatch.raw_observation_scope
                prepared_target = dispatch.prepared_target
                observation = dispatch.observation
                focus_unit_id = None
                required_focus = False
                if isinstance(prepared_target, Mapping):
                    focus_identity = str(
                        prepared_target.get("target_fingerprint")
                        or prepared_target.get("target_id")
                        or call.id
                    )[:160]
                    focus_unit_id = f"measurement:focus:{focus_identity}"
                    active_gate = self._review_coordinator.gate(run.id)
                    required_focus = bool(
                        active_gate.blocking
                        and active_gate.repair_kind == "evidence_needed"
                    )
                self._raise_if_interrupted(run)
                if call.name in {_LAYOUT_TOOL_NAME, _DECOMPOSE_TOOL_NAME}:
                    self._remember_layout_context(
                        observation.content,
                        call.arguments,
                        layout_contexts,
                    )
                    # A source-rebind gate must complete its handoff step
                    # before the model can assemble a new candidate.  The
                    # resolver remains the authority for the actual scope;
                    # this transition only advances the execution phase.
                    try:
                        handoff_payload = json.loads(observation.content)
                    except (TypeError, json.JSONDecodeError):
                        handoff_payload = None
                    if isinstance(handoff_payload, Mapping) and not handoff_payload.get("error"):
                        self._advance_generated_repair_phase(run.id, "assemble")
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
                    run=run,
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
                if call.name == "assemble_spec" and emitter is not None:
                    try:
                        assembly_payload = json.loads(observation.content)
                    except (TypeError, json.JSONDecodeError):
                        assembly_payload = None
                    if isinstance(assembly_payload, Mapping) and assembly_payload.get("error"):
                        issues = assembly_payload.get("issues")
                        if not isinstance(issues, list):
                            data_payload = assembly_payload.get("data")
                            issues = data_payload.get("issues") if isinstance(data_payload, Mapping) else None
                        emitter.emit(
                            "assembly_validation_failure",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            error=str(assembly_payload.get("error"))[:240],
                            issues=[str(item)[:160] for item in issues[:12]] if isinstance(issues, list) else [],
                            blocking=False,
                        )
                if call.name in MEASUREMENT_TOOLS:
                    if prepared_target is not None and emitter is not None:
                        emitter.emit(
                            "measurement_focus_requested",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            unit_id=focus_unit_id,
                            parent_unit_id=(
                                f"review:{self._review_coordinator.gate(run.id).review_id}"
                                if required_focus and self._review_coordinator.gate(run.id).review_id
                                else None
                            ),
                            required=required_focus,
                            target={
                                key: prepared_target.get(key)
                                for key in (
                                    "target_id",
                                    "target_fingerprint",
                                    "panel_id",
                                    "parent_attempt_id",
                                    "resolved_refs",
                                    "mode",
                                    "fields",
                                    "region_kind",
                                )
                                if prepared_target.get(key) is not None
                            },
                        )
                    focus_observed = False
                    try:
                        measurement_payload = json.loads(observation.content)
                        measurement_data = measurement_payload.get("data") if isinstance(measurement_payload, dict) else None
                        if isinstance(measurement_data, dict):
                            measurement_session = register_measurement_observation(
                                measurement_sessions,
                                observation.content,
                            )
                            if measurement_session is not None and emitter is not None:
                                focus_observed = True
                                emitter.emit(
                                    "measurement_observed",
                                    turn=turn,
                                    tool_name=call.name,
                                    call_id=call.id,
                                    unit_id=focus_unit_id,
                                    parent_unit_id=(
                                        f"review:{self._review_coordinator.gate(run.id).review_id}"
                                        if required_focus and self._review_coordinator.gate(run.id).review_id
                                        else None
                                    ),
                                    session_id=measurement_session.session_id,
                                    attachment_id=measurement_session.attachment_id,
                                    panel_id=measurement_session.panel_id,
                                    measurement_status=measurement_session.current_attempt().status
                                    if measurement_session.current_attempt() is not None
                                    else None,
                                    decision_status=measurement_session.decision_status,
                                    observation_scope=(measurement_data.get("observation_scope") if isinstance(measurement_data.get("observation_scope"), Mapping) else None),
                                    blocking=False,
                                    **_lifecycle_trace_fields(observation.content),
                                )
                                if measurement_session.repair_budget_remaining <= 0 and measurement_session.decision_status == "pending":
                                    emitter.emit(
                                        "measurement_repair_exhausted",
                                        turn=turn,
                                        tool_name=call.name,
                                        call_id=call.id,
                                        session_id=measurement_session.session_id,
                                        attempt_id=measurement_session.current_attempt_id,
                                        budget_remaining=0,
                                        next_action="由主 Agent 舍弃不可靠证据或选择已有有效引用；不自动重复测量",
                                    )
                            if measurement_session is not None:
                                pending_measurement_repairs = _measurement_repair_contexts_from_sessions(
                                    measurement_sessions
                                )
                                self._advance_generated_repair_phase(run.id, "assemble")
                    except (TypeError, json.JSONDecodeError):
                        pass
                    if prepared_target is not None and emitter is not None and not focus_observed:
                        emitter.emit(
                            "measurement_focus_failed",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            unit_id=focus_unit_id,
                            parent_unit_id=(
                                f"review:{self._review_coordinator.gate(run.id).review_id}"
                                if required_focus and self._review_coordinator.gate(run.id).review_id
                                else None
                            ),
                            required=required_focus,
                            status="pending" if required_focus else "abandoned",
                            reason="工具没有返回当前 target 的 measurement observation",
                            next_action={
                                "required": required_focus,
                                "allowed": ["request_same_scope_measurement", "abandon"],
                                "blocked": ["assemble", "publish"] if required_focus else [],
                                "reason": "必须先闭合当前 focused measurement 的 observation obligation" if required_focus else "可选局部观察未形成证据，可由主 Agent 明确放弃",
                            },
                        )
                if call.name == "assemble_spec":
                    self._record_measurement_decision_events(
                        run,
                        observation.content,
                        emitter=emitter,
                        turn=turn,
                        call_id=call.id,
                        seen=measurement_decision_seen,
                    )
                    try:
                        assembled_payload = json.loads(observation.content)
                    except (TypeError, json.JSONDecodeError):
                        assembled_payload = None
                    if isinstance(assembled_payload, Mapping) and not assembled_payload.get("error"):
                        self._advance_generated_repair_phase(run.id, "render")
                repair_context = _measurement_repair_context_from_content(observation.content)
                if repair_context is not None:
                    pending_measurement_repairs = _merge_measurement_repair_contexts(
                        pending_measurement_repairs,
                        [repair_context],
                    )
                    pending_action = str(repair_context.get("next_action") or "等待主 Agent 证据决策")[:240]
                    self.memory.append(run, "measurement_decision", {"state": repair_context})
                    if emitter is not None:
                        emitter.emit(
                            "measurement_decision_required",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            required=bool(
                                self._review_coordinator.gate(run.id).blocking
                                and self._review_coordinator.gate(run.id).repair_kind == "evidence_needed"
                            ),
                            decision=repair_context,
                        )
                        focus = repair_context.get("focus")
                        if isinstance(focus, Mapping) and focus.get("requested"):
                            emitter.emit(
                                "measurement_focus_applied"
                                if focus.get("applied") and focus.get("status") == "applied"
                                else "measurement_focus_failed",
                                turn=turn,
                                tool_name=call.name,
                                call_id=call.id,
                                unit_id=focus_unit_id,
                                required=required_focus,
                                focus={
                                    key: focus.get(key)
                                    for key in ("requested", "applied", "status", "mode", "target_refs", "search_scope", "region_px")
                                    if focus.get(key) is not None
                                },
                            )
                elif call.name in MEASUREMENT_TOOLS:
                    pending_measurement_repairs = _measurement_repair_contexts_from_sessions(
                        measurement_sessions
                    )
                artifact_records.extend(
                    _artifact_records_from_observation(
                        call.name,
                        call.id,
                        observation.content,
                        run_attachment_ids,
                        observation_refs,
                    )
                )
                artifact_records = artifact_records[-48:]
                tool_message = tool_entry(call, observation.content)
                self._current_messages.append(tool_message)
                self._messages.append(tool_message)
                self.memory.append(
                    run,
                    "tool",
                    {
                        "message": tool_message,
                        "tool_name": call.name,
                        "status": observation_status(observation.content),
                        **_measurement_trace_fields(observation.content),
                    },
                )
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
                shared_gate = self._review_coordinator.gate(run.id)
                stop_batch = shared_gate.blocking
                if stop_batch and remaining_calls:
                    self._skip_tool_calls(
                        run,
                        remaining_calls,
                        gate=shared_gate,
                        emitter=emitter,
                        turn=turn,
                    )
                    remaining_calls = ()
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
                        artifact_records=artifact_records,
                        measurement_sessions=measurement_sessions,
                        pending_measurement_repairs=pending_measurement_repairs,
                    ),
                )
                pending_action = "处理工具观察并决定下一步证据或 ChartSpec 操作"
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
                        result=_trace_result_summary(observation.content),
                        image_count=len(observation.images),
                        **_lifecycle_trace_fields(observation.content),
                        **_measurement_trace_fields(observation.content),
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
                            "attempt": item.get("candidateAttempt") or item.get("lineageAttempt") or item.get("attempt"),
                            "parent_attempt": item.get("parentAttempt") or item.get("parentCandidateId"),
                            "repair_kind": (item.get("review") or {}).get("repairKind") if isinstance(item.get("review"), Mapping) else item.get("repairKind"),
                            "collection_id": item.get("collectionId") or item.get("collection_id"),
                        }
                        generation_context = item.get("generationContext") or item.get("generation_context")
                        if isinstance(generation_context, Mapping):
                            if isinstance(generation_context.get("source_scope"), Mapping):
                                common_review_fields["source_scope"] = dict(generation_context["source_scope"])
                            if isinstance(generation_context.get("coverage"), Mapping):
                                common_review_fields["coverage"] = dict(generation_context["coverage"])
                        if item.get("reviewStatus") == "completed":
                            review_state = "passed" if publication_status in {"published", "published_with_warning"} else "failed"
                            review_transition = f"review:{item.get('reviewId') or item.get('review_id')}:{item.get('candidateAttempt') or item.get('lineageAttempt') or item.get('attempt') or 1}:{review_state}"
                            emitter.emit(
                                "chart_review_completed",
                                turn=turn,
                                unit_id=f"review:{item.get('reviewId') or item.get('review_id')}",
                                transition_id=review_transition,
                                state=review_state,
                                subject_id=item.get("candidateId"),
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
                            **_lifecycle_trace_fields(observation.content),
                        )
                visual_evidence.extend(
                    ToolVisualEvidence(call.name, call.id, generated)
                    for generated in observation.images
                )
                if stop_batch:
                    break
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
            pending_measurement_repairs = _merge_measurement_repair_contexts(
                _measurement_repair_contexts_from_sessions(measurement_sessions),
            )
            self._checkpoint(
                run,
                phase="tool",
                next_action="model",
                state=self._checkpoint_state(
                    user_input,
                    self._current_messages,
                    layout_contexts,
                    run_attachment_ids,
                    turn,
                    pending_tool_calls=(),
                    visual_references=checkpoint_references,
                    artifact_records=artifact_records,
                    measurement_sessions=measurement_sessions,
                    pending_measurement_repairs=pending_measurement_repairs,
                ),
            )
        self._raise_if_interrupted(run)
        terminal_answer = _BUDGET_MSG
        terminal_gate = self._review_manager.gate(run.id)
        shared_terminal_gate = self._review_coordinator.gate(run.id)
        if shared_terminal_gate.blocking:
            terminal_answer = _REVIEW_FAILED_MSG if shared_terminal_gate.state.value in {"failed", "exhausted"} else _REVIEW_REQUIRED_MSG
        elif terminal_gate["pending"] or terminal_gate["failed"]:
            terminal_answer = _REVIEW_REQUIRED_MSG if terminal_gate["pending"] else _REVIEW_FAILED_MSG
        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=self.max_steps,
                max_steps=self.max_steps,
                answer=terminal_answer,
                review_gate=terminal_gate,
                execution_gate=shared_terminal_gate.to_dict(),
            )
        review_blocked = shared_terminal_gate.blocking or terminal_gate["pending"] or terminal_gate["failed"]
        self.memory.append(run, "terminal", {"answer": terminal_answer, "max_steps": self.max_steps, "review_gate": terminal_gate, "execution_gate": shared_terminal_gate.to_dict()})
        self.memory.finish(run, RunStatus.FAILED if review_blocked else RunStatus.COMPLETED, "review_failed" if review_blocked else "budget")
        return terminal_answer

    def _review_gate_allows_call(self, run_id: str, call_name: str, arguments: Mapping[str, Any]) -> bool:
        """Allow only the repair action that owns an active shared gate."""
        gate = self._review_coordinator.gate(run_id)
        if not gate.blocking:
            return True
        if gate.review_type is None:
            return False
        if gate.state.value in {"failed", "exhausted"}:
            return False
        if gate.review_type.value == "generated_chart":
            repair_kind = gate.repair_kind
            generation_tools = _RENDER_TOOL_NAMES | {"assemble_spec"}
            measurement_tools = set(MEASUREMENT_TOOLS)
            if repair_kind == "spec_only":
                if gate.repair_phase == "assemble":
                    return call_name == "assemble_spec"
                if gate.repair_phase == "render":
                    return call_name in _RENDER_TOOL_NAMES
                return False
            if repair_kind == "evidence_needed":
                if gate.repair_phase == "evidence":
                    if call_name not in measurement_tools:
                        return False
                elif gate.repair_phase == "assemble":
                    return call_name == "assemble_spec"
                elif gate.repair_phase == "render":
                    return call_name in _RENDER_TOOL_NAMES
                else:
                    return False
                if call_name not in measurement_tools:
                    return False
                candidate = self._review_manager.get(gate.subject_id or "")
                if candidate is None or candidate.generation_context is None:
                    return False
                from ..spec import context_digest, normalize_generation_context

                requested_context = normalize_generation_context(arguments.get("generation_context"))
                if requested_context is None or context_digest(requested_context) != candidate.context_digest:
                    return False
                requested_candidate = arguments.get("candidate_id")
                return requested_candidate in {None, candidate.candidate_id}
            if repair_kind == "source_rebind":
                if gate.repair_phase == "rebind":
                    return call_name in {_DECOMPOSE_TOOL_NAME, _LAYOUT_TOOL_NAME}
                if gate.repair_phase == "assemble":
                    return call_name == "assemble_spec"
                if gate.repair_phase == "render":
                    return call_name in _RENDER_TOOL_NAMES
                return False
            return False
        return False

    def _advance_generated_repair_phase(self, run_id: str, phase: str) -> None:
        """Move the active generated-chart repair sub-loop to its next phase."""
        gate = self._review_coordinator.gate(run_id)
        if (
            gate.blocking
            and gate.review_type is not None
            and gate.review_type.value == "generated_chart"
            and gate.review_id
        ):
            try:
                self._review_coordinator.mark_repair_phase(gate.review_id, phase)
            except (KeyError, ValueError):
                return

    def _record_shared_review(
        self,
        run: Any,
        record: Any,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        tool_name: str,
        call_id: str,
        emit_start: bool = True,
    ) -> None:
        """Persist and expose one normalized review transition."""
        payload = record.to_dict()
        payload["execution_gate"] = self._review_coordinator.gate(record.run_id).to_dict()
        payload.update({"tool_name": tool_name, "call_id": call_id})
        subject_ref = record.subject_ref if isinstance(record.subject_ref, Mapping) else {}
        generation_context = subject_ref.get("generation_context")
        if isinstance(generation_context, Mapping):
            source_scope = generation_context.get("source_scope") or generation_context.get("sourceScope")
            coverage = generation_context.get("coverage")
            if isinstance(source_scope, Mapping):
                payload["source_scope"] = dict(source_scope)
            if isinstance(coverage, Mapping):
                payload["coverage"] = dict(coverage)
        payload["candidate_id"] = record.subject_id if record.review_type.value == "generated_chart" else None
        payload["attempt"] = record.attempt
        payload["parent_attempt"] = record.parent_id
        payload["repair_kind"] = record.repair_kind
        payload["collection_id"] = subject_ref.get("collection_id")
        payload["figure_id"] = subject_ref.get("figure_id")
        payload["parent_candidate_id"] = subject_ref.get("parent_candidate_id")
        payload["unit_id"] = f"review:{record.review_id}"
        payload["transition_id"] = f"review:{record.review_id}:{record.attempt}:{record.state.value}"
        self.memory.append(run, "review", {"state": payload})
        if self._execution_gate_sink is not None:
            try:
                self._execution_gate_sink(payload["execution_gate"])
            except Exception:  # noqa: BLE001 - gate projection cannot stop the Agent
                pass
        if emitter is None:
            return
        if record.state.value == "reviewing":
            emitter.emit(
                "review_started",
                turn=turn,
                review_id=record.review_id,
                review_type=record.review_type.value,
                subject_id=record.subject_id,
                unit_id=payload["unit_id"],
                transition_id=payload["transition_id"],
                state=record.state.value,
                attempt=record.attempt,
                blocking=True,
                tool_name=tool_name,
                call_id=call_id,
                candidate_id=payload.get("candidate_id"),
                collection_id=payload.get("collection_id"),
            )
            return
        if emit_start:
            emitter.emit(
                "review_started",
                turn=turn,
                review_id=record.review_id,
                review_type=record.review_type.value,
                subject_id=record.subject_id,
                unit_id=payload["unit_id"],
                transition_id=f"review:{record.review_id}:{record.attempt}:reviewing",
                state="reviewing",
                attempt=record.attempt,
                blocking=True,
                tool_name=tool_name,
                call_id=call_id,
                candidate_id=payload.get("candidate_id"),
                collection_id=payload.get("collection_id"),
            )
        if record.state.value in {"passed", "passed_with_warning"}:
            emitter.emit("review_completed", turn=turn, **payload)
        elif record.state.value == "repair_required":
            emitter.emit("review_repair_required", turn=turn, **payload)
        else:
            emitter.emit("review_failed", turn=turn, **payload)

    def _record_measurement_decision_events(
        self,
        run: Any,
        content: str,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        call_id: str,
        seen: set[str] | None = None,
    ) -> None:
        """Expose model evidence decisions without creating a measurement gate."""
        for decision in measurement_decisions_from_content(content):
            attempt_id = str(decision.get("attempt_id") or "").strip()
            if not attempt_id:
                continue
            decision_key = json.dumps(
                {
                    "attempt_id": attempt_id,
                    "selected_refs": list(decision.get("selected_refs") or [])[:64],
                    "discarded_refs": list(decision.get("discarded_refs") or [])[:64],
                    "status": decision.get("decision_status") or decision.get("status") or "selected",
                    "series_map": dict(decision.get("series_map") or {}) if isinstance(decision.get("series_map"), Mapping) else {},
                    "evidence_basis": decision.get("evidence_basis"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if seen is not None and decision_key in seen:
                continue
            if seen is not None:
                seen.add(decision_key)
            payload = {
                "turn": turn,
                "tool_name": "assemble_spec",
                "call_id": call_id,
                "session_id": decision.get("session_id"),
                "attempt_id": attempt_id,
                "selected_refs": list(decision.get("selected_refs") or [])[:64],
                "discarded_refs": list(decision.get("discarded_refs") or [])[:64],
                "decision_status": str(decision.get("decision_status") or decision.get("status") or "selected")[:32],
                "series_map": dict(decision.get("series_map") or {}) if isinstance(decision.get("series_map"), Mapping) else {},
                "evidence_basis": str(decision.get("evidence_basis") or "")[:80] or None,
                "blocking": False,
            }
            payload.update(_lifecycle_trace_fields(content))
            self.memory.append(run, "measurement_decision", {"state": payload})
            if emitter is not None:
                if payload["selected_refs"]:
                    emitter.emit("measurement_evidence_selected", **payload)
                if payload["discarded_refs"] or payload["decision_status"] in {"discarded", "abandoned"}:
                    emitter.emit("measurement_evidence_discarded", **payload)

    def _skip_tool_calls(
        self,
        run: Any,
        calls: Sequence[ToolCall],
        *,
        gate: Any,
        emitter: TraceEmitter | None,
        turn: int,
    ) -> None:
        """Append protocol-safe not-started results for calls blocked by a gate."""
        if not calls:
            return
        content = json.dumps(
            {
                "error": "review gate blocked",
                "status": "not_started",
                "review_gate": gate.to_dict(),
                "next_action": gate.next_action or "等待审核门禁释放",
            },
            ensure_ascii=False,
        )
        for call in calls:
            message = tool_entry(call, content)
            self._current_messages.append(message)
            self._messages.append(message)
            self.memory.append(
                run,
                "tool",
                {
                    "message": message,
                    "tool_name": call.name,
                    "status": "not_started",
                    "reason": "review_gate_blocked",
                    "review_gate": gate.to_dict(),
                },
            )
            if emitter is not None:
                presentation = get_tool_presentation(call.name, tool=self.registry.get(call.name))
                emitter.emit(
                    "tool_skipped",
                    turn=turn,
                    tool_name=call.name,
                    tool_display_name=presentation.display_name,
                    tool_label=presentation.label,
                    call_id=call.id,
                    status="not_started",
                    reason="review_gate_blocked",
                    review_gate=gate.to_dict(),
                )

    def _begin_work_unit(self, operation_id: str, operation_kind: str) -> dict[str, Any]:
        return begin_work_unit(self._operation_begin, operation_id, operation_kind)

    def _complete_work_unit(
        self,
        operation_id: str,
        operation_kind: str,
        result: dict[str, Any] | None = None,
        references: dict[str, Any] | None = None,
    ) -> None:
        complete_work_unit(
            self._operation_complete,
            self._operation_uncertain,
            operation_id,
            operation_kind,
            result,
            references,
        )

    def _uncertain_work_unit(self, operation_id: str, reason: str) -> None:
        uncertain_work_unit(self._operation_uncertain, operation_id, reason)

    def _checkpoint(
        self,
        run: Any,
        *,
        state: dict[str, Any],
        phase: str,
        next_action: str,
    ) -> None:
        checkpoint(
            self._checkpoint_sink,
            self._review_coordinator,
            run,
            state=state,
            phase=phase,
            next_action=next_action,
        )

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
        artifact_records: Sequence[dict[str, Any]] = (),
        measurement_sessions: Mapping[str, MeasurementSession] | None = None,
        pending_measurement_repairs: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return checkpoint_state(
            user_input,
            messages,
            layout_contexts,
            attachment_ids,
            turn,
            pending_tool_calls=pending_tool_calls,
            pending_answer=pending_answer,
            visual_references=visual_references,
            artifact_records=artifact_records,
            measurement_sessions=measurement_sessions,
            pending_measurement_repairs=pending_measurement_repairs,
        )

    @staticmethod
    def _model_result_payload(result: NormalizedResult) -> dict[str, Any]:
        return model_result_payload(result)

    @staticmethod
    def _recovery_tool_calls(recovery: Optional[dict[str, Any]]) -> list[ToolCall]:
        return recovery_tool_calls(recovery)

    def _interruption_requested(self) -> bool:
        return interruption_requested(self._interruption_event)

    def _raise_if_interrupted(self, run: Any) -> None:
        raise_if_interrupted(self._interruption_event, self.memory, run)

    # These small methods preserve the historical Agent test hooks while the
    # actual panel routing implementation lives in its focused collaborator.
    @staticmethod
    def _layout_arguments(
        tool_name: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> str:
        return layout_arguments(tool_name, arguments, layout_contexts)

    @staticmethod
    def _panel_routing_error(
        tool_name: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> str | None:
        return panel_routing_error(tool_name, arguments, layout_contexts)

    def _hydrate_persisted_panel_contexts(
        self,
        layout_contexts: dict[str, dict[str, Any]],
        attachment_ids: Sequence[str],
    ) -> None:
        hydrate_persisted_panel_contexts(self.attachments, layout_contexts, attachment_ids)

    @staticmethod
    def _remember_layout_context(
        content: str,
        arguments: str,
        layout_contexts: dict[str, dict[str, Any]],
    ) -> None:
        remember_layout_context(content, arguments, layout_contexts)
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
        run: Any | None = None,
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
            from ..spec import ChartFigure, ChartSpec, ChartSpecCollection

            collection = None
            if spec_payload.get("kind") == "chart_figure":
                figure_specs = [ChartFigure.from_dict(spec_payload)]
            elif spec_payload.get("kind") == "chart_spec_collection":
                collection = ChartSpecCollection.from_dict(spec_payload)
                figure_specs = list(collection.figures)
            else:
                figure_specs = [ChartSpec.from_dict(spec_payload)]
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
            review_spec = figure_specs[0]
            if collection is not None and len(figure_specs) > 1:
                figure_id = metadata.get("figure_id") or metadata.get("figureId")
                review_spec = next(
                    (figure for figure in figure_specs if figure.figure_id == figure_id),
                    figure_specs[0],
                )
            candidate = self._review_manager.create_candidate(
                run_id,
                call_id,
                image,
                review_spec,
                source_attachment_ids=source_attachment_ids,
            )
            # Open the shared gate before any VLM/provider review work.  The
            # generated artifact is therefore never visible as publishable
            # while the semantic review is still in flight.
            initial_shared_review = self._generated_chart_review_adapter.submit(
                self._review_coordinator,
                candidate=candidate,
            )
            if run is not None:
                self._record_shared_review(
                    run,
                    initial_shared_review,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                )
            if emitter is not None and initial_shared_review.state.value == "reviewing":
                # Compatibility alias for older consumers.  It deliberately
                # carries the same unit and transition as review_started, so
                # the shared projector renders only one visible start.
                emitter.emit(
                    "chart_review_started",
                    turn=turn,
                    unit_id=f"review:{initial_shared_review.review_id}",
                    transition_id=f"review:{initial_shared_review.review_id}:{initial_shared_review.attempt}:reviewing",
                    state="reviewing",
                    internal_review=True,
                    tool_count=0,
                    candidate_id=candidate.candidate_id,
                    subject_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    attempt=candidate.lineage_attempt,
                    review_mode="vlm" if candidate.policy.semantic_required else "safety",
                    collection_id=candidate.collection_id,
                )
            if candidate.review_status is ReviewStatus.PENDING:
                semantic_result: ReviewResult | None = None
                from ..review.evaluator import review_candidate_bytes

                deterministic_result = review_candidate_bytes(
                    review_spec,
                    candidate.content,
                    media_type=candidate.media_type,
                    declared_width=candidate.width,
                    declared_height=candidate.height,
                )
                review_unit = f"review:{candidate.review_id}"
                collection_parent = (
                    f"review:collection:{candidate.collection_id}"
                    if candidate.collection_id
                    else None
                )
                if emitter is not None:
                    emitter.emit(
                        "review_subcheck",
                        turn=turn,
                        unit_id=review_unit,
                        parent_unit_id=collection_parent,
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        attempt=candidate.lineage_attempt,
                        check_type="deterministic_quality_audit",
                        state="failed" if deterministic_result.blocking else "passed",
                        status="failed" if deterministic_result.blocking else "passed",
                        checks=dict(deterministic_result.checks),
                        issues=[issue.to_dict() for issue in deterministic_result.issues[:16]],
                    )
                if candidate.policy.semantic_required:
                    semantic_result = self._review_manager.semantic_result(candidate)
                    reused = semantic_result is not None
                    if semantic_result is None and deterministic_result.blocking:
                        if emitter is not None:
                            emitter.emit(
                                "review_subcheck",
                                turn=turn,
                                unit_id=review_unit,
                                parent_unit_id=collection_parent,
                                candidate_id=candidate.candidate_id,
                                review_id=candidate.review_id,
                                attempt=candidate.lineage_attempt,
                                check_type="semantic_vlm",
                                state="not_run",
                                status="not_run",
                                reason="deterministic quality audit 已阻塞",
                            )
                    elif semantic_result is None:
                        if emitter is not None:
                            emitter.emit(
                                "review_subcheck",
                                turn=turn,
                                unit_id=review_unit,
                                parent_unit_id=collection_parent,
                                candidate_id=candidate.candidate_id,
                                review_id=candidate.review_id,
                                attempt=candidate.lineage_attempt,
                                check_type="semantic_vlm",
                                state="running",
                                status="running",
                            )
                        source_resolution = self._review_manager.source_resolution(candidate)
                        source_payload = (
                            (source_resolution.content, source_resolution.media_type)
                            if source_resolution.resolved
                            else None
                        )
                        if source_payload is None:
                            resolution_hint = source_resolution.action_hint or "重新绑定有效的 source_scope"
                            resolution_status = source_resolution.status
                            semantic_result = ReviewResult(
                                status=ReviewStatus.FAILED,
                                checks={"source_evidence": resolution_status},
                                issues=(ReviewIssue(
                                    "source_binding_failure",
                                    "generation_context.source_scope",
                                    f"source scope is {resolution_status}; {resolution_hint}",
                                ),),
                                decision="fail",
                                confidence=0.0,
                                review_mode="vlm",
                                suggested_action="rebind_source",
                                recovery_classification="source_binding_failure",
                                repair_kind="source_rebind",
                            )
                        else:
                            semantic_result = review_candidate_with_vlm(
                                self.client,
                                candidate,
                                review_spec,
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
                        semantic_result = self._review_manager.remember_semantic_result(candidate, semantic_result)
                    if emitter is not None and semantic_result is not None:
                        emitter.emit(
                            "review_subcheck",
                            turn=turn,
                            unit_id=review_unit,
                            parent_unit_id=collection_parent,
                            candidate_id=candidate.candidate_id,
                            review_id=candidate.review_id,
                            attempt=candidate.lineage_attempt,
                            check_type="semantic_vlm",
                            state=semantic_result.status.value,
                            status=semantic_result.status.value,
                            decision=semantic_result.decision,
                            reused=reused,
                            checks=dict(semantic_result.checks),
                            issues=[issue.to_dict() for issue in semantic_result.issues[:16]],
                        )
                candidate = self._review_manager.process(candidate, semantic_result=semantic_result)
            shared_review = self._generated_chart_review_adapter.submit(
                self._review_coordinator,
                candidate=candidate,
            )
            if run is not None:
                self._record_shared_review(
                    run,
                    shared_review,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                    emit_start=False,
                )
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
