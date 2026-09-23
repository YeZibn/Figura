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
    CandidateStatus,
    ChartReviewManager,
    PublicationStatus,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    review_candidate_bytes,
    review_candidate_with_vlm,
)
from ..tools.core.result import GeneratedImage
from .tool_schema import registry_tools, tool_to_openai_schema
from .messages import assistant_entry, tool_entry
from .review_gate import (
    _BUDGET_MSG,
    _REVIEW_FAILED_MSG,
    _REVIEW_REQUIRED_MSG,
)
from .observations import observation_status
from .artifacts import (
    _artifact_records_from_observation,
    _attach_visual_observation_refs,
    _lifecycle_trace_fields,
    _trace_result_summary,
)
from .measurement_flow import (
    measurement_evidence_from_sessions as _measurement_evidence_from_sessions,
    measurement_trace_fields as _measurement_trace_fields,
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
CandidateInputSink = Callable[[GeneratedImage, Mapping[str, Any]], Any]
_LAYOUT_TOOL_NAME = "inspect_chart_layout"
_DECOMPOSE_TOOL_NAME = "decompose_chart_image"
_MAX_LAYOUT_CONTEXTS = _MAX_LAYOUT_CONTEXTS_CANONICAL
_RENDER_TOOL_NAMES = frozenset({"render_chart", "generate_chart"})


def _tool_trace_identity(tool_name: str, call_id: str) -> tuple[str, str]:
    """Return the explicit timeline unit shared by one tool call and result."""
    if tool_name in MEASUREMENT_TOOLS:
        unit_type = "measurement"
    elif tool_name == "assemble_spec" or tool_name in _RENDER_TOOL_NAMES:
        unit_type = "generation"
    else:
        unit_type = "observation"
    return f"{unit_type}:{str(call_id)[:128]}", unit_type


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
        candidate_input_sink: CandidateInputSink | None = None,
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
        self._candidate_input_sink = candidate_input_sink
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
            raw_visual_refs = recovery.get("visualReferences")
            if isinstance(raw_visual_refs, list):
                checkpoint_references.extend(item for item in raw_visual_refs[:32] if isinstance(item, dict))
            measurement_sessions = sessions_from_state(recovery.get("measurementSessions"))
            review_state = recovery.get("reviewState")
            legacy_review_state = "executionGate" in recovery or (
                isinstance(review_state, Mapping)
                and ("records" in review_state or "executionGate" in review_state)
            )
            if review_state is None and legacy_review_state:
                raise AgentRecoveryBlocked("unsupported_review_state_version")
            if review_state is not None:
                try:
                    self._review_manager.restore(review_state, active_run_id=run.id)
                except (TypeError, ValueError) as exc:
                    raise AgentRecoveryBlocked(str(exc)) from exc
                if self._execution_gate_sink is not None:
                    try:
                        self._execution_gate_sink(self._review_manager.execution_gate(run.id).to_dict())
                    except Exception:  # noqa: BLE001 - projection failure cannot open the manager gate
                        pass
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
        if isinstance(recovery, dict) and recovery.get("nextAction") == "review":
            self._resume_pending_review(
                run,
                recovery,
                user_input=user_input,
                layout_contexts=layout_contexts,
                attachment_ids=run_attachment_ids,
                checkpoint_references=checkpoint_references,
                artifact_records=artifact_records,
                measurement_sessions=measurement_sessions,
                emitter=emitter,
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
                execution_gate = self._review_manager.execution_gate(run.id).to_dict()
                measurement_evidence = _measurement_evidence_from_sessions(measurement_sessions)
                decision_context = build_decision_context(
                    run_id=run.id,
                    execution_gate=execution_gate,
                    measurement_evidence=measurement_evidence,
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
                        "measurement_evidence": measurement_evidence,
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
                shared_gate = self._review_manager.execution_gate(run.id)
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
                    active_gate = self._review_manager.execution_gate(run.id)
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
                        ),
                    )
                    break
                if isinstance(call_arguments, dict) and isinstance(call_arguments.get("panel_id"), str):
                    selected_panel_id = call_arguments["panel_id"]
                operation_kind = "render" if call.name in _RENDER_TOOL_NAMES else "tool"
                operation_id = f"{operation_kind}:{turn}:{call.id}"
                operation_completed = False
                tool_unit_id, tool_unit_type = _tool_trace_identity(call.name, call.id)
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
                        unit_id=tool_unit_id,
                        unit_type=tool_unit_type,
                        phase="action",
                        actor="tool",
                        role="action",
                        state="running",
                        transition_id=f"{tool_unit_id}:started",
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
                def checkpoint_review(candidate_ids: Sequence[str]) -> None:
                    nonlocal operation_completed
                    if operation_kind == "render" and not operation_completed:
                        self._complete_work_unit(
                            operation_id,
                            operation_kind,
                            {"status": "rendered"},
                            {"candidateIds": list(candidate_ids[:16])},
                        )
                        operation_completed = True
                    state = self._checkpoint_state(
                        user_input,
                        self._current_messages,
                        layout_contexts,
                        run_attachment_ids,
                        turn,
                        pending_tool_calls=(),
                        visual_references=checkpoint_references,
                        artifact_records=artifact_records,
                        measurement_sessions=measurement_sessions,
                    )
                    state["pendingReview"] = {
                        "callId": call.id,
                        "toolName": call.name,
                        "turn": turn,
                        "candidateIds": list(candidate_ids[:16]),
                    }
                    saved = self._checkpoint(
                        run,
                        phase="review",
                        next_action="review",
                        state=state,
                    )
                    if self._checkpoint_sink is not None and not saved:
                        raise AgentRecoveryBlocked("review_checkpoint_unavailable")

                observation = self._apply_generation_review(
                    observation,
                    run=run,
                    run_id=run.id,
                    call_id=call.id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    source_attachment_ids=run_attachment_ids,
                    emitter=emitter,
                    turn=turn,
                    checkpoint_review=checkpoint_review,
                )
                self._raise_if_interrupted(run)
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
                            unit_id=tool_unit_id,
                            unit_type=tool_unit_type,
                            phase="assemble",
                            actor="tool",
                            role="action",
                            state="failed",
                            transition_id=f"{tool_unit_id}:assembly_validation_failed",
                            error=str(assembly_payload.get("error"))[:240],
                            issues=[str(item)[:160] for item in issues[:12]] if isinstance(issues, list) else [],
                            blocking=False,
                        )
                if call.name in MEASUREMENT_TOOLS:
                    measurement_session = register_measurement_observation(
                        measurement_sessions,
                        observation.content,
                    )
                    if measurement_session is not None:
                        self._advance_generated_repair_phase(run.id, "assemble")
                if call.name == "assemble_spec":
                    try:
                        assembled_payload = json.loads(observation.content)
                    except (TypeError, json.JSONDecodeError):
                        assembled_payload = None
                    if isinstance(assembled_payload, Mapping) and not assembled_payload.get("error"):
                        self._advance_generated_repair_phase(run.id, "render")
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
                if not operation_completed:
                    self._complete_work_unit(
                        operation_id,
                        operation_kind,
                        {"status": observation_status(observation.content)},
                        {"observations": list(observation_refs)},
                    )
                remaining_calls = result.tool_calls[call_index + 1:]
                shared_gate = self._review_manager.execution_gate(run.id)
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
                        unit_id=tool_unit_id,
                        unit_type=tool_unit_type,
                        phase="action",
                        actor="tool",
                        role="action",
                        state=observation_status(observation.content),
                        transition_id=f"{tool_unit_id}:completed",
                        status=observation_status(observation.content),
                        tool_status=observation_status(observation.content),
                        result=_trace_result_summary(observation.content),
                        image_count=len(observation.images),
                        **_lifecycle_trace_fields(observation.content),
                        **_measurement_trace_fields(observation.content),
                    )
                    if observation.images:
                        visual_kind = "generated_chart" if any(
                                image.metadata.get("kind") == "generated_chart"
                                for image in observation.images
                                if hasattr(image.metadata, "get")
                            ) else "visual_observation"
                        emitter.emit(
                            visual_kind,
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            unit_id=tool_unit_id,
                            unit_type=tool_unit_type,
                            phase="render" if visual_kind == "generated_chart" else "observe",
                            actor="tool",
                            role="action" if visual_kind == "generated_chart" else "observation",
                            state="available" if visual_kind == "generated_chart" else "observed",
                            transition_id=f"{tool_unit_id}:" + ("generated" if visual_kind == "generated_chart" else "observed"),
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
                ),
            )
        self._raise_if_interrupted(run)
        terminal_answer = _BUDGET_MSG
        shared_terminal_gate = self._review_manager.execution_gate(run.id)
        if shared_terminal_gate.blocking:
            terminal_answer = _REVIEW_FAILED_MSG if shared_terminal_gate.state.value in {"failed", "exhausted"} else _REVIEW_REQUIRED_MSG
        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=self.max_steps,
                max_steps=self.max_steps,
                answer=terminal_answer,
                execution_gate=shared_terminal_gate.to_dict(),
            )
        review_blocked = shared_terminal_gate.blocking
        self.memory.append(run, "terminal", {"answer": terminal_answer, "max_steps": self.max_steps, "execution_gate": shared_terminal_gate.to_dict()})
        self.memory.finish(run, RunStatus.FAILED if review_blocked else RunStatus.COMPLETED, "review_failed" if review_blocked else "budget")
        return terminal_answer

    def _review_gate_allows_call(self, run_id: str, call_name: str, arguments: Mapping[str, Any]) -> bool:
        """Allow model-selected, source-safe repair work under a review gate.

        The gate owns publication and terminal-state safety.  It deliberately
        does not turn a VLM repair hint into an ordered tool whitelist; each
        selected tool remains responsible for its own authorization, scope,
        lineage and schema checks.
        """
        gate = self._review_manager.execution_gate(run_id)
        if not gate.blocking:
            return True
        if gate.review_type is None:
            return False
        if gate.state.value in {"failed", "exhausted"}:
            return False
        if gate.review_type.value != "generated_chart":
            return False

        repair_tools = {
            _DECOMPOSE_TOOL_NAME,
            _LAYOUT_TOOL_NAME,
            "extract_text",
            "assemble_spec",
            *_RENDER_TOOL_NAMES,
            *MEASUREMENT_TOOLS,
        }
        if call_name not in repair_tools or self.registry.get(call_name) is None:
            return False

        candidate = self._review_manager.get(gate.subject_id or "")
        if candidate is None:
            return False
        requested_candidate = arguments.get("candidate_id")
        if requested_candidate is not None and requested_candidate != candidate.candidate_id:
            return False

        # If the model supplies an explicit generation context, it must be the
        # same immutable context as the failed candidate.  Missing context is
        # left to the selected tool's own source-scope validation so a model
        # may first recover a source binding or use a valid visual-only input.
        from ..spec import context_digest, normalize_generation_context

        raw_contexts: list[object] = []
        if arguments.get("generation_context") is not None:
            raw_contexts.append(arguments.get("generation_context"))
        spec = arguments.get("spec")
        if isinstance(spec, Mapping):
            if spec.get("generation_context") is not None:
                raw_contexts.append(spec.get("generation_context"))
            figure = spec.get("figure")
            if isinstance(figure, Mapping) and figure.get("generation_context") is not None:
                raw_contexts.append(figure.get("generation_context"))
        if candidate.context_digest and raw_contexts:
            for raw_context in raw_contexts:
                normalized = normalize_generation_context(raw_context)
                if normalized is None or context_digest(normalized) != candidate.context_digest:
                    return False
        return True

    def _advance_generated_repair_phase(self, run_id: str, phase: str) -> None:
        """Move the active generated-chart repair sub-loop to its next phase."""
        gate = self._review_manager.execution_gate(run_id)
        if (
            gate.blocking
            and gate.review_type is not None
            and gate.review_type.value == "generated_chart"
            and gate.review_id
        ):
            try:
                self._review_manager.mark_repair_phase(run_id, gate.review_id, phase)
            except (KeyError, ValueError):
                return
            if self._execution_gate_sink is not None:
                try:
                    self._execution_gate_sink(self._review_manager.execution_gate(run_id).to_dict())
                except Exception:  # noqa: BLE001 - projection cannot stop repair
                    pass

    def _record_candidate_review(
        self,
        run: Any,
        candidate: Any,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        tool_name: str,
        call_id: str,
        started: bool,
    ) -> None:
        """Persist and expose one transition derived from the candidate aggregate."""
        gate = self._review_manager.execution_gate(candidate.run_id)
        review = candidate.review or candidate.safety_result
        if started:
            state = "reviewing"
        elif candidate.publication_status is PublicationStatus.PUBLISHED:
            state = "passed"
        elif candidate.publication_status is PublicationStatus.PUBLISHED_WITH_WARNING:
            state = "passed_with_warning"
        elif candidate.status is CandidateStatus.RETRY_EXHAUSTED or gate.state.value == "exhausted":
            state = "exhausted"
        elif candidate.status is CandidateStatus.REVIEW_FAILED and gate.state.value == "repair_required":
            state = "repair_required"
        else:
            state = "failed"
        generation_context = candidate.generation_context.to_dict() if candidate.generation_context is not None else None
        source_scope = generation_context.get("source_scope") if isinstance(generation_context, Mapping) else None
        coverage = generation_context.get("coverage") if isinstance(generation_context, Mapping) else None
        subject_ref = {
            "candidate_id": candidate.candidate_id,
            "review_id": candidate.review_id,
            "chart_spec_digest": candidate.chart_spec_digest,
            "source_attachment_ids": list(candidate.source_attachment_ids[:16]),
            "panel_ids": list(candidate.panel_ids[:16]),
            "generation_context": generation_context,
            "context_status": candidate.context_status,
            "collection_id": candidate.collection_id,
            "figure_id": candidate.figure_id,
            "parent_candidate_id": candidate.parent_candidate_id,
        }
        evidence = [{
            "candidate_id": candidate.candidate_id,
            "review_id": candidate.review_id,
            "chart_spec_digest": candidate.chart_spec_digest,
            "repair_kind": review.repair_kind if review is not None else "none",
            "repair_target": dict(review.repair_target) if review is not None and isinstance(review.repair_target, Mapping) else None,
        }]
        issues = [issue.to_dict() for issue in (review.issues if review is not None else ())[:32]]
        payload: dict[str, Any] = {
            "reviewId": candidate.review_id,
            "runId": candidate.run_id,
            "reviewType": "generated_chart",
            "review_mode": review.review_mode if review is not None else "vlm" if candidate.policy.semantic_required else "safety",
            "subjectId": candidate.candidate_id,
            "state": state,
            "blocking": started or candidate.publication_status in {PublicationStatus.UNPUBLISHED, PublicationStatus.REJECTED},
            "attempt": candidate.lineage_attempt,
            "maxAttempts": candidate.policy.max_attempts,
            "remainingAttempts": max(0, candidate.policy.max_attempts - candidate.lineage_attempt),
            "issues": issues,
            "subjectRef": subject_ref,
            "evidence": evidence,
            "createdAt": candidate.updated_at,
            "updatedAt": candidate.updated_at,
            "repairKind": review.repair_kind if review is not None and review.repair_kind else "none",
            "repairPhase": candidate.repair_phase,
            "decision": review.decision if review is not None else "reviewing",
            "confidence": review.confidence if review is not None else None,
            "details": {
                "candidate_status": candidate.status.value,
                "review_status": candidate.review_status.value,
                "publication_status": candidate.publication_status.value,
                "review_mode": review.review_mode if review is not None else "vlm" if candidate.policy.semantic_required else "safety",
            },
            "execution_gate": gate.to_dict(),
            "tool_name": tool_name,
            "call_id": call_id,
            "candidate_id": candidate.candidate_id,
            "attempt": candidate.lineage_attempt,
            "parent_attempt": candidate.parent_attempt,
            "repair_kind": review.repair_kind if review is not None and review.repair_kind else "none",
            "collection_id": candidate.collection_id,
            "figure_id": candidate.figure_id,
            "parent_candidate_id": candidate.parent_candidate_id,
            "unit_id": f"review:{candidate.review_id}",
            "unit_type": "review",
            "phase": "repair" if state == "repair_required" else "review",
            "actor": "system",
            "role": "review",
            "review_id": candidate.review_id,
            "review_type": "generated_chart",
            "subject_id": candidate.candidate_id,
            "review_status": candidate.review_status.value,
            "transition_id": f"review:{candidate.review_id}:{candidate.lineage_attempt}:{state}",
            "candidate_status": candidate.status.value,
            "publication_status": candidate.publication_status.value,
        }
        if isinstance(source_scope, Mapping):
            payload["source_scope"] = dict(source_scope)
        if isinstance(coverage, Mapping):
            payload["coverage"] = dict(coverage)
        self.memory.append(run, "review", {"state": payload})
        if self._execution_gate_sink is not None:
            try:
                self._execution_gate_sink(payload["execution_gate"])
            except Exception:  # noqa: BLE001 - gate projection cannot stop the Agent
                pass
        if emitter is None:
            return
        if started:
            emitter.emit(
                "review_started",
                turn=turn,
                review_id=candidate.review_id,
                review_type="generated_chart",
                subject_id=candidate.candidate_id,
                unit_id=payload["unit_id"],
                transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:reviewing",
                state="reviewing",
                unit_type="review",
                phase="review",
                actor="system",
                role="review",
                parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                attempt=candidate.lineage_attempt,
                blocking=True,
                tool_name=tool_name,
                call_id=call_id,
                candidate_id=candidate.candidate_id,
                collection_id=candidate.collection_id,
            )
            return
        if state in {"passed", "passed_with_warning"}:
            emitter.emit("review_completed", turn=turn, **payload)
        elif state == "repair_required":
            emitter.emit("review_repair_required", turn=turn, **payload)
        else:
            emitter.emit("review_failed", turn=turn, **payload)
        publication_status = candidate.publication_status.value
        publication_kind = "generated_chart_published" if publication_status in {"published", "published_with_warning"} else "generated_chart_rejected"
        emitter.emit(
            publication_kind,
            turn=turn,
            unit_id=f"publication:{candidate.candidate_id}",
            unit_type="publication",
            phase="publish",
            actor="system",
            role="publication",
            parent_unit_id=payload["unit_id"],
            review_id=candidate.review_id,
            candidate_id=candidate.candidate_id,
            subject_id=candidate.candidate_id,
            attempt=candidate.lineage_attempt,
            publication_status=publication_status,
            state=publication_status,
            transition_id=f"publication:{candidate.candidate_id}:{candidate.lineage_attempt}:{publication_status}",
            tool_name=tool_name,
            call_id=call_id,
            reason=("review_failed" if publication_kind == "generated_chart_rejected" else None),
        )

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
            unit_id, unit_type = _tool_trace_identity(call.name, call.id)
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
                    unit_id=unit_id,
                    unit_type=unit_type,
                    phase="action",
                    actor="system",
                    role="action",
                    state="not_started",
                    transition_id=f"{unit_id}:skipped",
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
    ) -> bool | None:
        return checkpoint(
            self._checkpoint_sink,
            self._review_manager,
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

    def _resume_pending_review(
        self,
        run: Any,
        recovery: Mapping[str, Any],
        *,
        user_input: str | list[dict],
        layout_contexts: dict[str, dict[str, Any]],
        attachment_ids: Sequence[str],
        checkpoint_references: list[dict[str, Any]],
        artifact_records: list[dict[str, Any]],
        measurement_sessions: Mapping[str, MeasurementSession],
        emitter: TraceEmitter | None,
    ) -> None:
        """Finish a staged review before returning to the model after recovery."""
        pending = recovery.get("pendingReview")
        if not isinstance(pending, Mapping):
            raise AgentRecoveryBlocked("pending_review_reference_missing")
        call_id = pending.get("callId")
        tool_name = pending.get("toolName")
        candidate_ids = pending.get("candidateIds")
        if (
            not isinstance(call_id, str)
            or not call_id
            or not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(candidate_ids, list)
            or not candidate_ids
            or any(not isinstance(item, str) for item in candidate_ids)
        ):
            raise AgentRecoveryBlocked("pending_review_reference_invalid")
        turn = max(1, int(pending.get("turn", 1)))
        candidates = self._review_manager.candidates_for_review(run.id, candidate_ids)
        if {candidate.candidate_id for candidate, _ in candidates} != set(candidate_ids):
            raise AgentRecoveryBlocked("review_candidate_input_unavailable")
        remaining_calls = self._recovery_tool_calls(dict(recovery))

        def save_review_checkpoint(ids: Sequence[str]) -> None:
            state = self._checkpoint_state(
                user_input,
                self._current_messages,
                layout_contexts,
                attachment_ids,
                turn,
                pending_tool_calls=remaining_calls,
                visual_references=checkpoint_references,
                artifact_records=artifact_records,
                measurement_sessions=measurement_sessions,
            )
            state["pendingReview"] = {
                "callId": call_id,
                "toolName": tool_name,
                "turn": turn,
                "candidateIds": list(ids[:16]),
            }
            saved = self._checkpoint(run, phase="review", next_action="review", state=state)
            if self._checkpoint_sink is not None and not saved:
                raise AgentRecoveryBlocked("review_checkpoint_unavailable")

        images: list[GeneratedImage] = []
        review_payloads = []
        for candidate, spec in candidates:
            staged_image = self._review_manager.decorate_image(
                GeneratedImage(candidate.content, candidate.media_type, candidate.title),
                candidate,
            )
            if self._candidate_input_sink is None:
                raise AgentRecoveryBlocked("review_candidate_store_unavailable")
            try:
                staged_reference = self._candidate_input_sink(staged_image, spec.to_dict())
            except Exception as exc:  # noqa: BLE001 - recovery remains fail closed
                raise AgentRecoveryBlocked("review_candidate_store_unavailable") from exc
            if not staged_reference:
                raise AgentRecoveryBlocked("review_candidate_store_unavailable")
            candidate = self._finish_candidate_review(
                candidate,
                spec,
                emitter=emitter,
                turn=turn,
                checkpoint_review=save_review_checkpoint,
                candidate_ids=candidate_ids,
            )
            if candidate.run_id != run.id:
                raise AgentRecoveryBlocked("review_candidate_run_mismatch")
            if self._run_id is not None and candidate.run_id != self._run_id:
                raise AgentRecoveryBlocked("review_candidate_run_mismatch")
            staged_image = self._review_manager.decorate_image(
                GeneratedImage(candidate.content, candidate.media_type, candidate.title),
                candidate,
            )
            try:
                updated_reference = self._candidate_input_sink(staged_image, spec.to_dict())
            except Exception as exc:  # noqa: BLE001 - recovery remains fail closed
                raise AgentRecoveryBlocked("review_candidate_store_unavailable") from exc
            if not updated_reference:
                raise AgentRecoveryBlocked("review_candidate_store_unavailable")
            self._record_candidate_review(
                run,
                candidate,
                emitter=emitter,
                turn=turn,
                tool_name="generated_chart_review",
                call_id=call_id,
                started=False,
            )
            images.append(staged_image)
            review_payloads.append(candidate.safe_metadata())

        result_content = json.dumps(
            {
                "status": "success",
                "data": {"kind": "generated_chart", "review": review_payloads, "recovered": True},
                "review": review_payloads,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        tool_call = ToolCall(call_id, tool_name, "{}")
        tool_message = tool_entry(tool_call, result_content)
        self._current_messages.append(tool_message)
        self._messages.append(tool_message)
        self.memory.append(run, "tool", {"message": tool_message, "tool_name": tool_name, "status": "success"})
        references: Sequence[dict[str, Any]] = ()
        if self._visual_observation_sink is not None:
            references = self._visual_observation_sink(tool_name, call_id, images)
        checkpoint_references.extend(item for item in references if isinstance(item, dict))
        artifact_records.extend(
            _artifact_records_from_observation(tool_name, call_id, result_content, attachment_ids, references)
        )
        artifact_records[:] = artifact_records[-48:]
        if images:
            visual_message = {
                "role": "user",
                "content": build_tool_observation_content([ToolVisualEvidence(tool_name, call_id, images)]),
            }
            self._current_messages.append(visual_message)  # type: ignore[arg-type]
            self._messages.append(visual_message)  # type: ignore[arg-type]
            self.memory.append(run, "visual_metadata", {"tool_count": 1, "tools": [tool_name], "call_ids": [call_id], "image_count": len(images)})
        next_action = "tool" if remaining_calls else "model"
        self._checkpoint(
            run,
            phase="tool",
            next_action=next_action,
            state=self._checkpoint_state(
                user_input,
                self._current_messages,
                layout_contexts,
                attachment_ids,
                turn,
                pending_tool_calls=remaining_calls,
                visual_references=checkpoint_references,
                artifact_records=artifact_records,
                measurement_sessions=measurement_sessions,
            ),
        )

    def _apply_generation_review(
        self,
        observation: Any,
        *,
        run: Any | None = None,
        run_id: str,
        call_id: str,
        tool_name: str,
        arguments: str,
        source_attachment_ids: Sequence[str],
        emitter: TraceEmitter | None = None,
        turn: int | None = None,
        checkpoint_review: Callable[[Sequence[str]], None] | None = None,
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
        prepared: list[tuple[GeneratedImage, Any, Any, bool]] = []
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
                tool_name=tool_name,
                turn=turn or 0,
            )
            # The candidate itself opens the derived gate before persistence or review.
            persisted = self._candidate_input_sink is None and self._checkpoint_sink is None
            if self._candidate_input_sink is not None:
                try:
                    staged = self._candidate_input_sink(
                        self._review_manager.decorate_image(image, candidate),
                        review_spec.to_dict(),
                    )
                    persisted = bool(staged)
                except Exception:  # noqa: BLE001 - candidate storage must fail closed
                    persisted = False
            if run is not None:
                self._record_candidate_review(
                    run,
                    candidate,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                    started=True,
                )
            prepared.append((image, candidate, review_spec, persisted))
        if not prepared:
            return observation

        candidate_ids = [candidate.candidate_id for _, candidate, _, _ in prepared]
        for index, (image, candidate, review_spec, persisted) in enumerate(prepared):
            if candidate.safety_result is not None or candidate.status in {
                CandidateStatus.VERIFIED,
                CandidateStatus.WARNING,
                CandidateStatus.REVIEW_FAILED,
                CandidateStatus.TIMED_OUT,
                CandidateStatus.RETRY_EXHAUSTED,
            }:
                continue
            if not persisted:
                deterministic_result = ReviewResult(
                    status=ReviewStatus.FAILED,
                    checks={"candidate_storage": "failed"},
                    issues=(ReviewIssue(
                        "candidate_storage_failure",
                        "candidate.storage",
                        "candidate image and ChartSpec could not be stored for mandatory review",
                    ),),
                    decision="fail",
                    confidence=0.0,
                    review_mode="safety",
                    repair_kind="terminal",
                )
            else:
                deterministic_result = review_candidate_bytes(
                    review_spec,
                    candidate.content,
                    media_type=candidate.media_type,
                    declared_width=candidate.width,
                    declared_height=candidate.height,
                )
            candidate = self._review_manager.record_safety_result(candidate, deterministic_result)
            review_unit = f"review:{candidate.review_id}"
            if emitter is not None:
                emitter.emit(
                    "review_subcheck",
                    turn=turn,
                    unit_id=review_unit,
                    parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                    candidate_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    unit_type="review",
                    phase="review",
                    actor="system",
                    role="review",
                    transition_id=f"{review_unit}:{candidate.lineage_attempt}:deterministic",
                    attempt=candidate.lineage_attempt,
                    check_type="deterministic_quality_audit",
                    state="failed" if deterministic_result.blocking else "passed",
                    status="failed" if deterministic_result.blocking else "passed",
                    checks=dict(deterministic_result.checks),
                    issues=[issue.to_dict() for issue in deterministic_result.issues[:16]],
                )
            prepared[index] = (image, candidate, review_spec, persisted)

        resumable = all(persisted for _, _, _, persisted in prepared)
        if resumable and checkpoint_review is not None:
            checkpoint_review(candidate_ids)

        for image, candidate, review_spec, persisted in prepared:
            candidate = self._finish_candidate_review(
                candidate,
                review_spec,
                emitter=emitter,
                turn=turn or 0,
                checkpoint_review=checkpoint_review if resumable else None,
                candidate_ids=candidate_ids,
                checkpoint_before_semantic=False,
            )
            if run is not None:
                self._record_candidate_review(
                    run,
                    candidate,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                    started=False,
                )
            generated.append(self._review_manager.decorate_image(image, candidate))
            review_payloads.append(candidate.safe_metadata())
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

    def _finish_candidate_review(
        self,
        candidate: Any,
        spec: Any,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        checkpoint_review: Callable[[Sequence[str]], None] | None,
        candidate_ids: Sequence[str],
        checkpoint_before_semantic: bool = True,
    ) -> Any:
        """Apply the stored deterministic result and one semantic decision."""
        if candidate.status in {
            CandidateStatus.VERIFIED,
            CandidateStatus.WARNING,
            CandidateStatus.REVIEW_FAILED,
            CandidateStatus.TIMED_OUT,
            CandidateStatus.RETRY_EXHAUSTED,
        }:
            return candidate
        safety_result = candidate.safety_result
        if safety_result is None:
            safety_result = review_candidate_bytes(
                spec,
                candidate.content,
                media_type=candidate.media_type,
                declared_width=candidate.width,
                declared_height=candidate.height,
            )
            candidate = self._review_manager.record_safety_result(candidate, safety_result)
            if emitter is not None:
                emitter.emit(
                    "review_subcheck",
                    turn=turn,
                    unit_id=f"review:{candidate.review_id}",
                    candidate_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    unit_type="review",
                    phase="review",
                    actor="system",
                    role="review",
                    transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:deterministic",
                    attempt=candidate.lineage_attempt,
                    check_type="deterministic_quality_audit",
                    state="failed" if safety_result.blocking else "passed",
                    status="failed" if safety_result.blocking else "passed",
                    checks=dict(safety_result.checks),
                    issues=[issue.to_dict() for issue in safety_result.issues[:16]],
                )
        semantic_result = self._review_manager.semantic_result(candidate)
        if candidate.policy.semantic_required:
            if safety_result.blocking:
                if semantic_result is None and emitter is not None:
                    emitter.emit(
                        "review_subcheck",
                        turn=turn,
                        unit_id=f"review:{candidate.review_id}",
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        unit_type="review",
                        phase="review",
                        actor="system",
                        role="review",
                        transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:semantic_not_run",
                        attempt=candidate.lineage_attempt,
                        check_type="semantic_vlm",
                        state="not_run",
                        status="not_run",
                        reason="确定性审核未通过",
                    )
            elif semantic_result is None:
                if checkpoint_review is not None and checkpoint_before_semantic:
                    checkpoint_review(candidate_ids)
                if emitter is not None:
                    emitter.emit(
                        "review_subcheck",
                        turn=turn,
                        unit_id=f"review:{candidate.review_id}",
                        parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        unit_type="review",
                        phase="review",
                        actor="vlm",
                        role="review",
                        transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:semantic_started",
                        attempt=candidate.lineage_attempt,
                        check_type="semantic_vlm",
                        state="running",
                        status="running",
                    )
                source_resolution = self._review_manager.source_resolution(candidate)
                source_payload = (source_resolution.content, source_resolution.media_type) if source_resolution.resolved else None
                if source_payload is None:
                    hint = source_resolution.action_hint or "重新绑定有效的 source_scope"
                    semantic_result = ReviewResult(
                        status=ReviewStatus.FAILED,
                        checks={"source_evidence": source_resolution.status},
                        issues=(ReviewIssue(
                            "source_binding_failure",
                            "generation_context.source_scope",
                            f"source scope is {source_resolution.status}; {hint}",
                        ),),
                        decision="fail",
                        confidence=0.0,
                        review_mode="vlm",
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        chart_spec_digest=candidate.chart_spec_digest,
                        suggested_action="rebind_source",
                        recovery_classification="source_binding_failure",
                        repair_kind="source_rebind",
                    )
                else:
                    semantic_result = review_candidate_with_vlm(
                        self.client,
                        candidate,
                        spec,
                        source_image=source_payload[0],
                        source_media_type=source_payload[1],
                        chat_kwargs=self._chat_kwargs,
                        trace_kwargs=(
                            {"trace_sink": emitter, "trace_run_id": emitter.run_id, "trace_turn": turn}
                            if emitter is not None and isinstance(self.client, LLMClient) else None
                        ),
                    )
                self._review_manager.remember_semantic_result(candidate, semantic_result)
                if checkpoint_review is not None:
                    checkpoint_review(candidate_ids)
            if semantic_result is not None and emitter is not None:
                emitter.emit(
                    "review_subcheck",
                    turn=turn,
                    unit_id=f"review:{candidate.review_id}",
                    parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                    candidate_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    unit_type="review",
                    phase="review",
                    actor="vlm",
                    role="review",
                    transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:semantic_completed",
                    attempt=candidate.lineage_attempt,
                    check_type="semantic_vlm",
                    state=semantic_result.status.value,
                    status=semantic_result.status.value,
                    decision=semantic_result.decision,
                    checks=dict(semantic_result.checks),
                    issues=[issue.to_dict() for issue in semantic_result.issues[:16]],
                )
        return self._review_manager.process(
            candidate,
            safety_result=safety_result,
            semantic_result=semantic_result,
        )


_assistant_entry = assistant_entry
_tool_entry = tool_entry
_observation_status = observation_status
