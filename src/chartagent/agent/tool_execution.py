"""Execute one ordered tool-call batch and commit its observations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..client.models import ToolCall
from ..measurement import MEASUREMENT_TOOLS
from ..multimodal import ToolVisualEvidence
from ..trace import TraceEmitter, summarize_arguments, summarize_images
from ..tools.core.presentation import get_tool_presentation
from .artifacts import (
    artifact_records_from_observation,
    attach_visual_observation_refs,
    lifecycle_trace_fields,
    trace_result_summary,
)
from .execution import (
    DECOMPOSE_TOOL_NAME as _DECOMPOSE_TOOL_NAME,
    LAYOUT_TOOL_NAME as _LAYOUT_TOOL_NAME,
    RENDER_TOOL_NAMES as _RENDER_TOOL_NAMES,
    RunExecutionContext,
    tool_trace_identity,
)
from .messages import tool_entry
from .measurement_flow import measurement_trace_fields, register_measurement_observation
from .observations import observation_status
from .panel_routing import remember_layout_context
from .recovery import (
    AgentRecoveryBlocked,
    begin_work_unit,
    checkpoint,
    checkpoint_state,
    complete_work_unit,
    raise_if_interrupted,
    uncertain_work_unit,
)
from .turn import prepare_and_dispatch_tool_call


@dataclass(frozen=True)
class ToolExecutionOutcome:
    visual_evidence: tuple[ToolVisualEvidence, ...]
    stop_batch: bool


class ToolExecutionFlow:
    """Run each model-selected tool serially through its complete lifecycle."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def execute(
        self,
        execution: RunExecutionContext,
        calls: Sequence[ToolCall],
        *,
        turn: int,
    ) -> ToolExecutionOutcome:
        agent = self.agent
        run = execution.run
        user_input = execution.user_input
        recovery = execution.recovery
        layout_contexts = execution.layout_contexts
        artifact_records = execution.artifact_records
        checkpoint_references = execution.checkpoint_references
        measurement_sessions = execution.measurement_sessions
        run_attachment_ids = execution.attachment_ids
        emitter = execution.emitter

        stop_batch = False
        visual_evidence: list[ToolVisualEvidence] = []
        for call_index, call in enumerate(calls):
            raise_if_interrupted(agent._interruption_event, agent.memory, run)
            execution.current_tool_name = call.name
            execution.pending_action = f"执行 {call.name} 并把结果作为当前 run 的证据"
            try:
                call_arguments = json.loads(call.arguments) if call.arguments.strip() else {}
            except (TypeError, json.JSONDecodeError):
                call_arguments = {}
            if not agent._review_flow.allows_tool_call(
                run.id,
                call.name,
                call_arguments if isinstance(call_arguments, Mapping) else {},
            ):
                active_gate = agent._review_manager.execution_gate(run.id)
                self._skip_calls(
                    execution,
                    calls[call_index:],
                    gate=active_gate,
                    emitter=emitter,
                    turn=turn,
                )
                checkpoint(
                    agent._checkpoint_sink,
                    agent._review_manager,
                    run,
                    phase="review",
                    next_action="model",
                    state=checkpoint_state(
                        user_input,
                        agent._current_messages,
                        layout_contexts,
                        run_attachment_ids,
                        turn,
                        pending_tool_calls=(),
                        visual_references=checkpoint_references,
                        artifact_records=artifact_records,
                        measurement_sessions=measurement_sessions,
                    ),
                )
                stop_batch = True
                break
            if isinstance(call_arguments, dict) and isinstance(call_arguments.get("panel_id"), str):
                execution.selected_panel_id = call_arguments["panel_id"]
            operation_kind = "render" if call.name in _RENDER_TOOL_NAMES else "tool"
            operation_id = f"{operation_kind}:{turn}:{call.id}"
            operation_completed = False
            tool_unit_id, tool_unit_type = tool_trace_identity(call.name, call.id)
            operation = begin_work_unit(agent._operation_begin, operation_id, operation_kind)
            if isinstance(recovery, dict) and operation.get("state") in {"in_flight", "uncertain"}:
                uncertain_work_unit(agent._operation_uncertain, operation_id, "operation_outcome_uncertain")
                raise AgentRecoveryBlocked("operation outcome is uncertain")
            if emitter is not None:
                presentation = get_tool_presentation(call.name, tool=agent.registry.get(call.name))
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
                agent.registry,
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
            raise_if_interrupted(agent._interruption_event, agent.memory, run)
            if call.name in {_LAYOUT_TOOL_NAME, _DECOMPOSE_TOOL_NAME}:
                remember_layout_context(
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
                    agent._review_flow.advance_repair_phase(run.id, "assemble")
            def checkpoint_review(candidate_ids: Sequence[str]) -> None:
                nonlocal operation_completed
                if operation_kind == "render" and not operation_completed:
                    complete_work_unit(
                        agent._operation_complete,
                        agent._operation_uncertain,
                        operation_id,
                        operation_kind,
                        {"status": "rendered"},
                        {"candidateIds": list(candidate_ids[:16])},
                    )
                    operation_completed = True
                state = checkpoint_state(
                    user_input,
                    agent._current_messages,
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
                saved = checkpoint(
                    agent._checkpoint_sink,
                    agent._review_manager,
                    run,
                    phase="review",
                    next_action="review",
                    state=state,
                )
                if agent._checkpoint_sink is not None and not saved:
                    raise AgentRecoveryBlocked("review_checkpoint_unavailable")

            observation = agent._review_flow.apply_generation_review(
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
            raise_if_interrupted(agent._interruption_event, agent.memory, run)
            observation_refs: Sequence[dict[str, Any]] = ()
            sink_images = observation.images
            if agent._visual_observation_sink is not None and sink_images:
                raise_if_interrupted(agent._interruption_event, agent.memory, run)
                try:
                    observation_refs = agent._visual_observation_sink(
                        call.name,
                        call.id,
                        sink_images,
                    )
                except Exception:  # noqa: BLE001 - observation diagnostics cannot abort the Agent
                    observation_refs = ()
            observation = attach_visual_observation_refs(observation, observation_refs)
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
                    agent._review_flow.advance_repair_phase(run.id, "assemble")
            if call.name == "assemble_spec":
                try:
                    assembled_payload = json.loads(observation.content)
                except (TypeError, json.JSONDecodeError):
                    assembled_payload = None
                if isinstance(assembled_payload, Mapping) and not assembled_payload.get("error"):
                    agent._review_flow.advance_repair_phase(run.id, "render")
            artifact_records.extend(
                artifact_records_from_observation(
                    call.name,
                    call.id,
                    observation.content,
                    run_attachment_ids,
                    observation_refs,
                )
            )
            artifact_records = artifact_records[-48:]
            tool_message = tool_entry(call, observation.content)
            agent._current_messages.append(tool_message)
            agent._messages.append(tool_message)
            agent.memory.append(
                run,
                "tool",
                {
                    "message": tool_message,
                    "tool_name": call.name,
                    "status": observation_status(observation.content),
                    **measurement_trace_fields(observation.content),
                },
            )
            checkpoint_references.extend(
                item for item in observation_refs if isinstance(item, dict)
            )
            if not operation_completed:
                complete_work_unit(
                    agent._operation_complete,
                    agent._operation_uncertain,
                    operation_id,
                    operation_kind,
                    {"status": observation_status(observation.content)},
                    {"observations": list(observation_refs)},
                )
            remaining_calls = calls[call_index + 1:]
            shared_gate = agent._review_manager.execution_gate(run.id)
            stop_batch = shared_gate.blocking
            if stop_batch and remaining_calls:
                self._skip_calls(
                    execution,
                    remaining_calls,
                    gate=shared_gate,
                    emitter=emitter,
                    turn=turn,
                )
                remaining_calls = ()
            checkpoint(
                agent._checkpoint_sink,
                agent._review_manager,
                run,
                phase="tool",
                next_action="tool" if remaining_calls else "model",
                state=checkpoint_state(
                    user_input,
                    agent._current_messages,
                    layout_contexts,
                    run_attachment_ids,
                    turn,
                    pending_tool_calls=remaining_calls,
                    visual_references=checkpoint_references,
                    artifact_records=artifact_records,
                    measurement_sessions=measurement_sessions,
                ),
            )
            execution.pending_action = "处理工具观察并决定下一步证据或 ChartSpec 操作"
            if emitter is not None:
                raise_if_interrupted(agent._interruption_event, agent.memory, run)
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
                    transition_id=f"{tool_unit_id}:completed",
                    status=observation_status(observation.content),
                    result=trace_result_summary(observation.content),
                    image_count=len(observation.images),
                    **lifecycle_trace_fields(observation.content),
                    **measurement_trace_fields(observation.content),
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
                        **lifecycle_trace_fields(observation.content),
                    )
            visual_evidence.extend(
                ToolVisualEvidence(call.name, call.id, generated)
                for generated in observation.images
            )
            if stop_batch:
                break
        return ToolExecutionOutcome(tuple(visual_evidence), stop_batch)

    def _skip_calls(
        self,
        execution: RunExecutionContext,
        calls: Sequence[ToolCall],
        *,
        gate: Any,
        emitter: TraceEmitter | None,
        turn: int,
    ) -> None:
        """Record tool calls that review safety prevented from starting."""
        if not calls:
            return
        agent = self.agent
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
            unit_id, unit_type = tool_trace_identity(call.name, call.id)
            message = tool_entry(call, content)
            execution.current_messages.append(message)
            execution.messages.append(message)
            agent.memory.append(
                execution.run,
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
                presentation = get_tool_presentation(call.name, tool=agent.registry.get(call.name))
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
                    reason="review_gate_blocked",
                )
