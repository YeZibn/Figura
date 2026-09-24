"""Coordinate one Agent run while leaving public lifecycle APIs on Agent."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Optional

from ..client.client import LLMClient
from ..decision_context import build_decision_context
from ..memory import RunStatus
from ..measurement import sessions_from_state
from ..multimodal import build_tool_observation_content
from ..prompting import assemble_prompt_context, panel_inventory_from_layout_contexts
from ..trace import TraceEmitter
from .panel_routing import hydrate_persisted_panel_contexts
from .execution import RunExecutionContext
from .final_answer import guard_final_answer
from .measurement_flow import measurement_evidence_from_sessions
from .messages import assistant_entry, tool_entry
from .recovery import (
    AgentRecoveryBlocked,
    AgentInterrupted,
    interruption_requested,
    raise_if_interrupted,
    recovery_tool_calls,
)
from .tool_schema import registry_tools
from .tool_execution import ToolExecutionFlow
from .turn import assistant_message_for_result, execute_model_turn
from ..tools.core.definition import ToolReplayEffect


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
        agent._messages = execution.messages
        agent._current_messages = execution.current_messages
        if isinstance(recovery, dict):
            loader = getattr(agent.memory, "execution_context", None)
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
                execution.visual_references.extend(item for item in raw_visual_refs[:32] if isinstance(item, dict))
            execution.measurement_sessions.update(sessions_from_state(recovery.get("measurementSessions")))
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
        existing_execution_cursor = None
        history_store = getattr(run, "history_store", None)
        if history_store is not None:
            try:
                existing_execution_cursor = history_store.get_execution_cursor(run.id)
            except Exception:  # noqa: BLE001 - execution callback will surface storage failures
                existing_execution_cursor = None
        if agent._execution_commit is not None and not recovery and existing_execution_cursor is None:
            agent._execution_commit(
                "input",
                {
                    "text": user_input if isinstance(user_input, str) else "[image attachment turn]",
                    "attachmentIds": list(execution.attachment_ids),
                },
                turn=0,
                next_action_kind="model",
                work_key="input:0",
            )
        layout_contexts = execution.layout_contexts
        artifact_records = execution.artifact_records
        visual_references = execution.visual_references
        measurement_sessions = execution.measurement_sessions
        run_attachment_ids = execution.attachment_ids
        hydrate_persisted_panel_contexts(agent.attachments, layout_contexts, run_attachment_ids)
        if not agent._current_messages or agent._current_messages[-1].get("role") != "user":
            agent._current_messages.append(user_message)  # type: ignore[arg-type]
        execution.tools = registry_tools(agent.registry)
        tools = execution.tools
        if isinstance(recovery, dict) and isinstance(recovery.get("executionModelEntryId"), str):
            execution.model_entry_id = recovery["executionModelEntryId"]
        execution.emitter = (
            TraceEmitter(agent._trace_sink, run_id=agent._trace_run_id or run.id)
            if agent._trace_sink is not None
            else None
        )
        emitter = execution.emitter

        if isinstance(recovery, dict) and recovery.get("resumeCheckpointAction") in {"verify", "promote"}:
            staged_ref = recovery.get("resumeStagedRef")
            call_id = recovery.get("resumeToolCallId")
            model_entry_id = recovery.get("executionModelEntryId")
            if not all(isinstance(value, str) and value for value in (staged_ref, call_id, model_entry_id)):
                raise AgentRecoveryBlocked("execution_checkpoint_identity_unavailable")
            try:
                agent._verification_flow.resume_checkpoint(
                    action=str(recovery["resumeCheckpointAction"]),
                    staged_ref=staged_ref,
                    run_id=run.id,
                    model_entry_id=model_entry_id,
                    call_id=call_id,
                    turn=max(0, int(recovery.get("currentTurn", 0) or 0)),
                    emitter=emitter,
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                raise AgentRecoveryBlocked("verification_checkpoint_unavailable") from exc

        execution.pending_recovery_calls = recovery_tool_calls(recovery)
        if isinstance(recovery, dict) and recovery.get("nextAction") == "final" and isinstance(recovery.get("pendingAnswer"), str):
            answer = guard_final_answer(str(recovery["pendingAnswer"]), run.records)
            if agent._execution_commit is not None:
                agent._execution_commit(
                    "final_answer",
                    {"answer": answer, "recovered": True},
                    turn=max(0, int(recovery.get("currentTurn", 0) or 0)),
                    next_action_kind="model",
                    work_key=f"final:resume:{execution.model_entry_id or 'answer'}",
                    event_kind="final_answer_committed",
                    event_payload={"recovered": True, "answer_length": len(answer)},
                )
            agent.memory.append(run, "final", {"answer": answer, "recovered": True})
            agent.memory.finish(run, RunStatus.COMPLETED, "recovered_final")
            return answer
        try:
            completed_model_steps = max(0, int(recovery.get("modelStepCount", 0))) if isinstance(recovery, dict) else 0
            recovered_turn = max(0, int(recovery.get("currentTurn", 0))) if isinstance(recovery, dict) else 0
        except (TypeError, ValueError):
            completed_model_steps = 0
            recovered_turn = 0
        remaining_model_steps = max(0, agent.max_steps - completed_model_steps)
        first_turn = (
            max(1, recovered_turn)
            if execution.pending_recovery_calls
            else max(1, recovered_turn + (1 if isinstance(recovery, dict) else 0))
        )
        loop_count = remaining_model_steps + (1 if execution.pending_recovery_calls else 0)
        for step in range(loop_count):
            turn = first_turn + step
            system_message = None
            prompt_metadata: dict[str, Any] | None = None
            if agent._system:
                panel_inventory = panel_inventory_from_layout_contexts(layout_contexts)
                selected_panel = next(
                    (item for item in panel_inventory if item.get("panel_id") == execution.selected_panel_id),
                    None,
                )
                active_generation_context = next(
                    (
                        item.get("generation_context")
                        for item in reversed(artifact_records)
                        if isinstance(item, Mapping) and isinstance(item.get("generation_context"), Mapping)
                    ),
                    None,
                )
                measurement_evidence = measurement_evidence_from_sessions(measurement_sessions)
                decision_context = build_decision_context(
                    run_id=run.id,
                    measurement_evidence=measurement_evidence,
                    selected_panel=selected_panel,
                    generation_context=active_generation_context,
                    phase="model",
                    retry_budget=max(0, agent.max_steps - completed_model_steps),
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
                        "retry_budget": max(0, agent.max_steps - completed_model_steps),
                        "generation_context": active_generation_context,
                        "decision_context": decision_context,
                    },
                    panel_inventory=panel_inventory,
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
            def commit_model_response(kind, payload, **kwargs):
                if kind == "model_response" and isinstance(payload, dict):
                    calls = payload.get("toolCalls")
                    if isinstance(calls, list):
                        for call in calls[:16]:
                            if not isinstance(call, dict):
                                continue
                            tool = agent.registry.get(str(call.get("name") or ""))
                            call["replayEffect"] = (
                                tool.replay_effect.value
                                if tool is not None
                                else ToolReplayEffect.RECONCILE_REQUIRED.value
                            )
                entry = agent._execution_commit(kind, payload, **kwargs)
                execution.model_entry_id = entry.entry_id
                return entry

            result, execution.pending_recovery_calls = execute_model_turn(
                agent.client,
                agent._messages,
                tools,
                chat_kwargs=chat_kwargs,
                pending_recovery_calls=execution.pending_recovery_calls,
                memory=agent.memory,
                run=run,
                interruption_event=agent._interruption_event,
                emitter=emitter,
                turn=turn,
                trace_reasoning=agent._trace_reasoning,
                execution_commit=commit_model_response if agent._execution_commit is not None else None,
            )
            if not result.tool_calls:
                raise_if_interrupted(agent._interruption_event, agent.memory, run)
                result.content = guard_final_answer(result.content, run.records)
                assistant_message = assistant_entry(result)
                agent._current_messages.append(assistant_message)
                agent._messages.append(assistant_message)
                agent.memory.append(run, "assistant", {"message": assistant_message})
                if agent._execution_commit is not None:
                    agent._execution_commit(
                        "final_answer",
                        {"answer": result.content, "finishReason": result.finish_reason},
                        turn=turn,
                        next_action_kind="model",
                        work_key=f"final:{execution.model_entry_id or turn}",
                        event_kind="final_answer_committed",
                        event_payload={"turn": turn, "answer_length": len(result.content)},
                    )
                agent.memory.append(run, "final", {"answer": result.content, "finish_reason": result.finish_reason})
                unresolved_verification = any(
                    record.kind == "verification_result"
                    and record.payload.get("status") == "unavailable"
                    for record in run.records
                )
                agent.memory.finish(
                    run,
                    RunStatus.FAILED if unresolved_verification else RunStatus.COMPLETED,
                    "verification_unavailable" if unresolved_verification else "final",
                )
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
        raise_if_interrupted(agent._interruption_event, agent.memory, run)
        terminal_answer = "*stopped: max_steps reached*"
        if emitter is not None:
            emitter.emit(
                "budget_exhausted",
                turn=agent.max_steps,
                max_steps=agent.max_steps,
                answer=terminal_answer,
            )
        if agent._execution_commit is not None:
            agent._execution_commit(
                "final_answer",
                {"answer": terminal_answer, "reason": "budget_exhausted"},
                turn=agent.max_steps,
                next_action_kind="model",
                work_key=f"final:budget:{agent.max_steps}",
                event_kind="final_answer_committed",
                event_payload={"turn": agent.max_steps, "answer_length": len(terminal_answer)},
            )
        agent.memory.append(run, "terminal", {"answer": terminal_answer, "max_steps": agent.max_steps})
        unresolved_verification = any(
            isinstance(record.payload, dict)
            and record.kind == "verification_result"
            and record.payload.get("status") == "unavailable"
            for record in run.records
        )
        agent.memory.finish(run, RunStatus.FAILED if unresolved_verification else RunStatus.COMPLETED, "verification_unavailable" if unresolved_verification else "budget")
        return terminal_answer
