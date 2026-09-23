"""Coordinate one Agent run while leaving public lifecycle APIs on Agent."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import partial
from typing import Any, Optional, Sequence

from ..client.client import LLMClient
from ..client.models import ToolCall
from ..decision_context import build_decision_context
from ..memory import RunStatus
from ..measurement import MeasurementSession, sessions_from_state
from ..multimodal import ToolVisualEvidence, build_tool_observation_content
from ..prompting import assemble_prompt_context, panel_inventory_from_layout_contexts
from ..trace import TraceEmitter
from ..tools.core.result import GeneratedImage
from .panel_routing import hydrate_persisted_panel_contexts
from .artifacts import artifact_records_from_observation
from .execution import RunExecutionContext
from .measurement_flow import measurement_evidence_from_sessions
from .messages import assistant_entry, tool_entry
from .recovery import (
    AgentInterrupted,
    AgentRecoveryBlocked,
    checkpoint,
    checkpoint_state,
    interruption_requested,
    raise_if_interrupted,
    recovery_tool_calls,
)
from .review_gate import _BUDGET_MSG, _REVIEW_FAILED_MSG, _REVIEW_REQUIRED_MSG
from .tool_schema import registry_tools
from .tool_execution import ToolExecutionFlow
from .turn import assistant_message_for_result, execute_model_turn


class AgentRunOrchestrator:
    """Own the per-run recovery, turn scheduling, tool ordering, and termination."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def run(self, user_input: str | list[dict], *, recovery_context: Optional[dict[str, Any]] = None) -> str:
        """Drive one user turn to completion (final answer or budget cap).

        ``user_input`` is a plain string or an OpenAI multimodal content list
        (e.g. from ``build_user_content``); it is appended to history and
        forwarded to the client unchanged.
        """
        agent = self.agent
        if interruption_requested(agent._interruption_event):
            raise AgentInterrupted("Agent run was interrupted before it started")
        recovery = recovery_context if recovery_context is not None else agent._recovery_context
        run = agent.memory.begin_run(agent._run_id) if agent._run_id is not None else agent.memory.begin_run()
        execution = RunExecutionContext(run=run, user_input=user_input, recovery=recovery)
        persist_checkpoint = partial(checkpoint, agent._checkpoint_sink, agent._review_manager)
        agent._messages = execution.messages
        agent._current_messages = execution.current_messages
        if isinstance(recovery, dict):
            loader = getattr(agent.memory, "recovery_context", None)
            hydrated = loader(recovery, budget=agent.context_budget) if callable(loader) else []
            if hydrated:
                agent._current_messages.extend(hydrated)  # type: ignore[arg-type]
            raw_layouts = recovery.get("layoutContexts")
            if isinstance(raw_layouts, dict):
                execution.layout_contexts.update({
                    str(key): value for key, value in list(raw_layouts.items())[:execution.max_layout_contexts]
                    if isinstance(value, dict)
                })
            raw_artifacts = recovery.get("artifactIndex")
            if isinstance(raw_artifacts, list):
                execution.artifact_records.extend(item for item in raw_artifacts[:48] if isinstance(item, dict))
            raw_visual_refs = recovery.get("visualReferences")
            if isinstance(raw_visual_refs, list):
                execution.checkpoint_references.extend(item for item in raw_visual_refs[:32] if isinstance(item, dict))
            execution.measurement_sessions.update(sessions_from_state(recovery.get("measurementSessions")))
            review_state = recovery.get("reviewState")
            legacy_review_state = "executionGate" in recovery or (
                isinstance(review_state, Mapping)
                and ("records" in review_state or "executionGate" in review_state)
            )
            if review_state is None and legacy_review_state:
                raise AgentRecoveryBlocked("unsupported_review_state_version")
            if review_state is not None:
                try:
                    agent._review_manager.restore(review_state, active_run_id=run.id)
                except (TypeError, ValueError) as exc:
                    raise AgentRecoveryBlocked(str(exc)) from exc
                if agent._execution_gate_sink is not None:
                    try:
                        agent._execution_gate_sink(agent._review_manager.execution_gate(run.id).to_dict())
                    except Exception:  # noqa: BLE001 - projection failure cannot open the manager gate
                        pass
        user_message = {"role": "user", "content": user_input}
        agent.memory.append(run, "user", {"message": user_message, "text": user_input if isinstance(user_input, str) else "[image attachment turn]"})
        if isinstance(user_input, str):
            execution.attachment_ids = tuple(re.findall(r"\batt_[A-Za-z0-9]+\b", user_input))
            for ordinal, attachment_id in enumerate(execution.attachment_ids, start=1):
                agent.memory.append(run, "attachment", {"attachment_id": attachment_id, "ordinal": ordinal})
                if agent.attachments is not None:
                    agent.attachments.bind_run(attachment_id, run.id)
        else:
            execution.attachment_ids = ()
        layout_contexts = execution.layout_contexts
        artifact_records = execution.artifact_records
        checkpoint_references = execution.checkpoint_references
        measurement_sessions = execution.measurement_sessions
        run_attachment_ids = execution.attachment_ids
        hydrate_persisted_panel_contexts(agent.attachments, layout_contexts, run_attachment_ids)
        if not agent._current_messages or agent._current_messages[-1].get("role") != "user":
            agent._current_messages.append(user_message)  # type: ignore[arg-type]
        execution.tools = registry_tools(agent.registry)
        tools = execution.tools
        execution.emitter = (
            TraceEmitter(agent._trace_sink, run_id=agent._trace_run_id or run.id)
            if agent._trace_sink is not None
            else None
        )
        emitter = execution.emitter

        execution.pending_recovery_calls = recovery_tool_calls(recovery)
        if isinstance(recovery, dict) and recovery.get("nextAction") == "review":
            self._resume_pending_review(
                agent,
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
            execution.pending_recovery_calls = recovery_tool_calls(recovery)
        if isinstance(recovery, dict) and recovery.get("nextAction") == "final" and isinstance(recovery.get("pendingAnswer"), str):
            answer = str(recovery["pendingAnswer"])
            agent.memory.append(run, "final", {"answer": answer, "recovered": True})
            agent.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
            return answer
        for step in range(agent.max_steps):
            turn = step + 1
            system_message = None
            prompt_metadata: dict[str, Any] | None = None
            if agent._system:
                review_gate = agent._review_manager.gate(run.id)
                panel_inventory = panel_inventory_from_layout_contexts(layout_contexts)
                selected_panel = next(
                    (item for item in panel_inventory if item.get("panel_id") == execution.selected_panel_id),
                    None,
                )
                active_generation_context = None
                for candidate_item in (
                    list(review_gate.get("pending") or []) + list(review_gate.get("failed") or [])
                ):
                    if isinstance(candidate_item, Mapping) and isinstance(candidate_item.get("generationContext"), Mapping):
                        active_generation_context = candidate_item["generationContext"]
                        break
                execution_gate = agent._review_manager.execution_gate(run.id).to_dict()
                measurement_evidence = measurement_evidence_from_sessions(measurement_sessions)
                decision_context = build_decision_context(
                    run_id=run.id,
                    execution_gate=execution_gate,
                    measurement_evidence=measurement_evidence,
                    selected_panel=selected_panel,
                    generation_context=active_generation_context,
                    phase="model",
                    retry_budget=agent.max_steps,
                )
                prompt_context = assemble_prompt_context(
                    tools=agent.registry.list(),
                    artifacts=artifact_records,
                    runtime_state={
                        "run_id": run.id,
                        "phase": "model",
                        "active_source": run_attachment_ids,
                        "selected_panel": selected_panel,
                        "current_tool": execution.current_tool_name,
                        "pending_action": execution.pending_action,
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
                        "retry_budget": agent.max_steps,
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
                system_message = {"role": "system", "content": f"{agent._system}\n\n{dynamic}"}
            execution.messages = agent.memory.context(run, system_message, agent.context_budget, current_messages=agent._current_messages)
            agent._messages = execution.messages
            if emitter is not None and not isinstance(agent.client, LLMClient):
                emitter.emit(
                    "model_started",
                    turn=turn,
                    model=agent._chat_kwargs.get("model"),
                    message_count=len(agent._messages),
                    tool_count=len(tools),
                    prompt_bundle=prompt_metadata,
                )
            chat_kwargs = dict(agent._chat_kwargs)
            if emitter is not None and isinstance(agent.client, LLMClient):
                chat_kwargs.update(
                    trace_sink=emitter,
                    trace_run_id=emitter.run_id,
                    trace_turn=turn,
                )
            result, execution.pending_recovery_calls = execute_model_turn(
                agent.client,
                agent._messages,
                tools,
                chat_kwargs=chat_kwargs,
                pending_recovery_calls=execution.pending_recovery_calls,
                operation_begin=agent._operation_begin,
                operation_complete=agent._operation_complete,
                operation_uncertain=agent._operation_uncertain,
                memory=agent.memory,
                run=run,
                interruption_event=agent._interruption_event,
                emitter=emitter,
                turn=turn,
                trace_reasoning=agent._trace_reasoning,
            )
            if not result.tool_calls:
                raise_if_interrupted(agent._interruption_event, agent.memory, run)
                assistant_message = assistant_entry(result)
                shared_gate = agent._review_manager.execution_gate(run.id)
                if shared_gate.blocking:
                    agent._current_messages.append(assistant_message)
                    agent._messages.append(assistant_message)
                    agent.memory.append(run, "assistant", {"message": assistant_message})
                    gate_message = {
                        "role": "user",
                        "content": json.dumps(
                            {"type": "execution_review_gate", "execution_gate": shared_gate.to_dict()},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                    agent._current_messages.append(gate_message)  # type: ignore[arg-type]
                    agent._messages.append(gate_message)  # type: ignore[arg-type]
                    agent.memory.append(run, "review_gate", {"state": shared_gate.to_dict()})
                    if shared_gate.state.value in {"failed", "exhausted"} or turn >= agent.max_steps:
                        agent.memory.append(
                            run,
                            "terminal",
                            {"answer": _REVIEW_FAILED_MSG, "execution_gate": shared_gate.to_dict()},
                        )
                        agent.memory.finish(run, RunStatus.FAILED, "review_failed")
                        return _REVIEW_FAILED_MSG
                    persist_checkpoint(
                        run,
                        phase="review",
                        next_action=shared_gate.next_action or "repair_review_gate",
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
                    continue
                agent._current_messages.append(assistant_message)
                agent._messages.append(assistant_message)
                agent.memory.append(run, "assistant", {"message": assistant_message})
                persist_checkpoint(
                    run,
                    phase="model",
                    next_action="final",
                    state=checkpoint_state(
                        user_input,
                        agent._current_messages,
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
                    agent.memory.append(run, "final", {"answer": answer, "recovered": True})
                    agent.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
                    return answer
                agent.memory.append(run, "final", {"answer": result.content, "finish_reason": result.finish_reason})
                agent.memory.finish(run, RunStatus.COMPLETED, "final")
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
                client=agent.client,
            )
            # ``assistant_message`` is the model-facing message. The memory
            # record stays sanitized and content/tool-call-only so provider
            # reasoning cannot leak into transcripts or ordinary records.
            agent._current_messages.append(assistant_message)
            agent._messages.append(assistant_message)
            agent.memory.append(run, "assistant", {"message": assistant_record})
            persist_checkpoint(
                run,
                phase="model",
                next_action="tool",
                state=checkpoint_state(
                    user_input,
                    agent._current_messages,
                    layout_contexts,
                    run_attachment_ids,
                    turn,
                    pending_tool_calls=result.tool_calls,
                    visual_references=checkpoint_references,
                    artifact_records=artifact_records,
                    measurement_sessions=measurement_sessions,
                ),
            )
            outcome = ToolExecutionFlow(agent).execute(execution, result.tool_calls, turn=turn)
            visual_evidence = list(outcome.visual_evidence)
            if visual_evidence:
                raise_if_interrupted(agent._interruption_event, agent.memory, run)
                visual_message = {
                    "role": "user",
                    "content": build_tool_observation_content(visual_evidence),
                }
                agent._current_messages.append(visual_message)  # type: ignore[arg-type]
                agent._messages.append(visual_message)  # type: ignore[arg-type]
                agent.memory.append(
                    run,
                    "visual_metadata",
                    {
                        "tool_count": len(visual_evidence),
                        "tools": [item.tool_name for item in visual_evidence],
                        "call_ids": [item.tool_call_id for item in visual_evidence],
                        "image_count": len(visual_evidence),
                    },
                )
            persist_checkpoint(
                run,
                phase="tool",
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
        raise_if_interrupted(agent._interruption_event, agent.memory, run)
        terminal_answer = _BUDGET_MSG
        shared_terminal_gate = agent._review_manager.execution_gate(run.id)
        if shared_terminal_gate.blocking:
            terminal_answer = _REVIEW_FAILED_MSG if shared_terminal_gate.state.value in {"failed", "exhausted"} else _REVIEW_REQUIRED_MSG
        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=agent.max_steps,
                max_steps=agent.max_steps,
                answer=terminal_answer,
            )
        review_blocked = shared_terminal_gate.blocking
        agent.memory.append(run, "terminal", {"answer": terminal_answer, "max_steps": agent.max_steps, "execution_gate": shared_terminal_gate.to_dict()})
        agent.memory.finish(run, RunStatus.FAILED if review_blocked else RunStatus.COMPLETED, "review_failed" if review_blocked else "budget")
        return terminal_answer

    def _resume_pending_review(
        self,
        agent: Any,
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
        candidates = agent._review_manager.candidates_for_review(run.id, candidate_ids)
        if {candidate.candidate_id for candidate, _ in candidates} != set(candidate_ids):
            raise AgentRecoveryBlocked("review_candidate_input_unavailable")
        remaining_calls = recovery_tool_calls(dict(recovery))
        persist_checkpoint = partial(checkpoint, agent._checkpoint_sink, agent._review_manager)

        def save_review_checkpoint(ids: Sequence[str]) -> None:
            state = checkpoint_state(
                user_input,
                agent._current_messages,
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
            saved = persist_checkpoint(run, phase="review", next_action="review", state=state)
            if agent._checkpoint_sink is not None and not saved:
                raise AgentRecoveryBlocked("review_checkpoint_unavailable")

        images: list[GeneratedImage] = []
        review_payloads = []
        for candidate, spec in candidates:
            staged_image = agent._review_manager.decorate_image(
                GeneratedImage(candidate.content, candidate.media_type, candidate.title),
                candidate,
            )
            if agent._candidate_input_sink is None:
                raise AgentRecoveryBlocked("review_candidate_store_unavailable")
            try:
                staged_reference = agent._candidate_input_sink(staged_image, spec.to_dict())
            except Exception as exc:  # noqa: BLE001 - recovery remains fail closed
                raise AgentRecoveryBlocked("review_candidate_store_unavailable") from exc
            if not staged_reference:
                raise AgentRecoveryBlocked("review_candidate_store_unavailable")
            candidate = agent._review_flow.finish_candidate_review(
                candidate,
                spec,
                emitter=emitter,
                turn=turn,
                checkpoint_review=save_review_checkpoint,
                candidate_ids=candidate_ids,
            )
            if candidate.run_id != run.id:
                raise AgentRecoveryBlocked("review_candidate_run_mismatch")
            if agent._run_id is not None and candidate.run_id != agent._run_id:
                raise AgentRecoveryBlocked("review_candidate_run_mismatch")
            staged_image = agent._review_manager.decorate_image(
                GeneratedImage(candidate.content, candidate.media_type, candidate.title),
                candidate,
            )
            try:
                updated_reference = agent._candidate_input_sink(staged_image, spec.to_dict())
            except Exception as exc:  # noqa: BLE001 - recovery remains fail closed
                raise AgentRecoveryBlocked("review_candidate_store_unavailable") from exc
            if not updated_reference:
                raise AgentRecoveryBlocked("review_candidate_store_unavailable")
            agent._review_flow.record_candidate_review(
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
        agent._current_messages.append(tool_message)
        agent._messages.append(tool_message)
        agent.memory.append(run, "tool", {"message": tool_message, "tool_name": tool_name, "status": "success"})
        references: Sequence[dict[str, Any]] = ()
        if agent._visual_observation_sink is not None:
            references = agent._visual_observation_sink(tool_name, call_id, images)
        checkpoint_references.extend(item for item in references if isinstance(item, dict))
        artifact_records.extend(
            artifact_records_from_observation(tool_name, call_id, result_content, attachment_ids, references)
        )
        artifact_records[:] = artifact_records[-48:]
        if images:
            visual_message = {
                "role": "user",
                "content": build_tool_observation_content(
                    [ToolVisualEvidence(tool_name, call_id, image) for image in images]
                ),
            }
            agent._current_messages.append(visual_message)  # type: ignore[arg-type]
            agent._messages.append(visual_message)  # type: ignore[arg-type]
            agent.memory.append(run, "visual_metadata", {"tool_count": 1, "tools": [tool_name], "call_ids": [call_id], "image_count": len(images)})
        next_action = "tool" if remaining_calls else "model"
        persist_checkpoint(
            run,
            phase="tool",
            next_action=next_action,
            state=checkpoint_state(
                user_input,
                agent._current_messages,
                layout_contexts,
                attachment_ids,
                turn,
                pending_tool_calls=remaining_calls,
                visual_references=checkpoint_references,
                artifact_records=artifact_records,
                measurement_sessions=measurement_sessions,
            ),
        )
