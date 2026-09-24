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
from ..tools.core.definition import ToolReplayEffect
from .artifacts import (
    artifact_records_from_observation,
    attach_visual_observation_refs,
    chart_context_trace_fields,
    trace_result_summary,
)
from .execution import (
    DECOMPOSE_TOOL_NAME as _DECOMPOSE_TOOL_NAME,
    LAYOUT_TOOL_NAME as _LAYOUT_TOOL_NAME,
    RunExecutionContext,
    tool_trace_identity,
)
from .messages import tool_entry
from .measurement_flow import measurement_trace_fields, register_measurement_observation
from .observations import observation_status
from .panel_routing import remember_layout_context
from .recovery import (
    AgentRecoveryBlocked,
    raise_if_interrupted,
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
        recovery = execution.recovery
        layout_contexts = execution.layout_contexts
        artifact_records = execution.artifact_records
        visual_references = execution.visual_references
        measurement_sessions = execution.measurement_sessions
        run_attachment_ids = execution.attachment_ids
        emitter = execution.emitter

        stop_batch = False
        visual_evidence: list[ToolVisualEvidence] = []
        current_output_artifacts: list[dict[str, Any]] = []
        for call_index, call in enumerate(calls):
            raise_if_interrupted(agent._interruption_event, agent.memory, run)
            execution.current_tool_name = call.name
            execution.pending_action = f"执行 {call.name} 并把结果作为当前 run 的证据"
            try:
                call_arguments = json.loads(call.arguments) if call.arguments.strip() else {}
            except (TypeError, json.JSONDecodeError):
                call_arguments = {}
            if isinstance(call_arguments, dict) and isinstance(call_arguments.get("panel_id"), str):
                execution.selected_panel_id = call_arguments["panel_id"]
            tool = agent.registry.get(call.name)
            if isinstance(recovery, dict) and (
                tool is None or tool.replay_effect is ToolReplayEffect.RECONCILE_REQUIRED
            ):
                raise AgentRecoveryBlocked("tool_effect_requires_reconciliation")
            tool_unit_id, tool_unit_type = tool_trace_identity(call.name, call.id)
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
            verified_images, verification_facts = agent._verification_flow.process(
                observation.images,
                spec_value=call_arguments.get("spec") if isinstance(call_arguments, Mapping) else None,
                run_id=run.id,
                model_entry_id=execution.model_entry_id,
                call_id=call.id,
                turn=turn,
                emitter=emitter,
                tool_name=call.name,
            )
            for fact in verification_facts:
                verification = fact.get("verification") if isinstance(fact, Mapping) else None
                if isinstance(verification, Mapping):
                    agent.memory.append(run, "verification_result", dict(verification))
                    if isinstance(fact.get("artifactId"), str):
                        agent.memory.append(run, "promotion_result", {
                            "artifactId": fact["artifactId"],
                            "stagedRef": fact.get("stagedRef"),
                            "verificationRef": verification.get("verificationRef"),
                        })
                    reference = {
                        "artifact_id": fact.get("artifactId") or fact.get("stagedRef"),
                        "kind": "generated_chart",
                        "status": verification.get("status", "unavailable"),
                        "staged_ref": fact.get("stagedRef"),
                        "artifact_id_published": fact.get("artifactId"),
                        "verification": dict(verification),
                        "generation_context": next(
                            (
                                dict(item.metadata.get("generation_context"))
                                for item in verified_images
                                if isinstance(item.metadata, Mapping)
                                and item.metadata.get("stagedRef") == fact.get("stagedRef")
                                and isinstance(item.metadata.get("generation_context"), Mapping)
                            ),
                            None,
                        ),
                    }
                    artifact_records.append(reference)
                    artifact_records[:] = artifact_records[-48:]
            if verification_facts:
                try:
                    response_payload = json.loads(observation.content)
                except (TypeError, json.JSONDecodeError):
                    response_payload = None
                if isinstance(response_payload, dict):
                    response_payload["chartVerification"] = verification_facts[:16]
                    data_payload = response_payload.get("data")
                    if isinstance(data_payload, dict):
                        data_payload = dict(data_payload)
                        data_payload["chartVerification"] = verification_facts[:16]
                        response_payload["data"] = data_payload
                    observation = type(observation)(
                        content=json.dumps(response_payload, ensure_ascii=False),
                        images=verified_images,
                    )
                else:
                    observation = type(observation)(content=observation.content, images=verified_images)
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
            if call.name == "assemble_spec":
                try:
                    assembled_payload = json.loads(observation.content)
                except (TypeError, json.JSONDecodeError):
                    assembled_payload = None
            observed_artifacts = artifact_records_from_observation(
                call.name,
                call.id,
                observation.content,
                run_attachment_ids,
                observation_refs,
            )
            artifact_records.extend(observed_artifacts)
            current_output_artifacts.extend(
                item for item in observed_artifacts
                if item.get("kind") == "generated_chart"
            )
            artifact_records[:] = artifact_records[-48:]
            remaining_calls = calls[call_index + 1:]
            if agent._durable_execution_port is not None:
                agent._durable_execution_port.commit_execution_entry(
                    "tool_result",
                    {
                        "toolName": call.name,
                        "callId": call.id,
                        "modelEntryId": execution.model_entry_id,
                        "observation": observation.content,
                        "visualReferences": list(observation_refs)[:32],
                    },
                    turn=turn,
                    next_action_kind="tool" if remaining_calls else "model",
                    call_id=remaining_calls[0].id if remaining_calls else None,
                    message_entry_id=execution.model_entry_id,
                    work_key=f"tool:{execution.model_entry_id or turn}:{call.id}",
                    event_kind="tool_result_committed",
                    event_payload={
                        "turn": turn,
                        "call_id": call.id,
                        "tool_name": call.name,
                        "status": observation_status(observation.content),
                    },
                )
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
            visual_references.extend(
                item for item in observation_refs if isinstance(item, dict)
            )
            execution.pending_action = "处理工具观察并决定下一步证据或 ChartSpec 操作"
            if emitter is not None:
                raise_if_interrupted(agent._interruption_event, agent.memory, run)
                image_payload = {"images": summarize_images(observation.images)}
                if observation_refs:
                    regular_refs = [
                        reference
                        for reference in observation_refs
                        if reference.get("artifactKind") != "generated_chart"
                    ]
                    if regular_refs:
                        image_payload["observations"] = regular_refs
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
                    **chart_context_trace_fields(observation.content),
                    **measurement_trace_fields(observation.content),
                )
                if observation.images:
                    has_generated_chart = any(
                        image.metadata.get("kind") == "generated_chart"
                        for image in observation.images
                        if hasattr(image.metadata, "get")
                    )
                    if not has_generated_chart:
                        emitter.emit(
                            "visual_observation",
                            turn=turn,
                            tool_name=call.name,
                            call_id=call.id,
                            unit_id=tool_unit_id,
                            unit_type=tool_unit_type,
                            phase="observe",
                            actor="tool",
                            role="observation",
                            state="observed",
                            transition_id=f"{tool_unit_id}:observed",
                            **image_payload,
                            **chart_context_trace_fields(observation.content),
                        )
            visual_evidence.extend(
                ToolVisualEvidence(call.name, call.id, generated)
                for generated in observation.images
            )
            if stop_batch:
                break
        if current_output_artifacts:
            execution.current_output_artifacts[:] = current_output_artifacts[-48:]
        return ToolExecutionOutcome(tuple(visual_evidence), stop_batch)
