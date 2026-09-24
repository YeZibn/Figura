"""Rebuild an authorized Agent continuation from committed execution facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..agent.measurement_flow import register_measurement_observation
from ..agent.panel_routing import remember_layout_context
from ..measurement import MeasurementSession, sessions_to_state
from .execution_record import ExecutionCursor, ExecutionEntry, ExecutionRecordError


def recovery_state_from_entries(
    entries: Sequence[ExecutionEntry],
    cursor: ExecutionCursor,
    *,
    provider: str | None = None,
    parent_run_id: str | None = None,
) -> dict[str, Any]:
    """Return the bounded legacy Agent input shape from the committed prefix.

    This is a transient in-memory adapter. The durable source remains the
    immutable entry sequence and its typed cursor.
    """
    if cursor.entry_cursor > len(entries):
        raise ExecutionRecordError("execution cursor points past the committed prefix")
    prefix = list(entries[:cursor.entry_cursor])
    input_entry = next((item for item in prefix if item.kind == "input"), None)
    if input_entry is None:
        raise ExecutionRecordError("execution prefix has no user input")
    prompt = input_entry.payload.get("text")
    if not isinstance(prompt, str):
        prompt = "继续执行已提交的图表分析"
    attachments = input_entry.payload.get("attachmentIds")
    attachment_ids = [item for item in attachments[:16] if isinstance(item, str)] if isinstance(attachments, list) else []

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    model_entries = {item.entry_id: item for item in prefix if item.kind == "model_response" and item.entry_id}
    call_definitions: dict[str, dict[str, Any]] = {}
    for item in model_entries.values():
        calls = item.payload.get("toolCalls")
        if isinstance(calls, list):
            call_definitions.update(
                (call["id"], call)
                for call in calls
                if isinstance(call, dict) and isinstance(call.get("id"), str)
            )
    tool_results: list[ExecutionEntry] = []
    visual_references: list[dict[str, Any]] = []
    artifact_records: list[dict[str, Any]] = []
    measurement_sessions: dict[str, MeasurementSession] = {}
    layout_contexts: dict[str, dict[str, Any]] = {}
    for item in prefix:
        if item.kind == "model_response":
            calls = item.payload.get("toolCalls")
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": item.payload.get("content") or "",
            }
            if isinstance(calls, list) and calls:
                assistant["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in calls[:16]
                    if isinstance(call, dict)
                    and all(isinstance(call.get(key), str) for key in ("id", "name", "arguments"))
                ]
                reasoning = item.payload.get("reasoning_content")
                if provider == "deepseek" and isinstance(reasoning, str):
                    assistant["reasoning_content"] = reasoning
            messages.append(assistant)
        elif item.kind == "tool_result":
            tool_results.append(item)
            if item.payload.get("stagingCheckpoint") is True:
                continue
            call_id = item.payload.get("callId")
            observation = item.payload.get("observation")
            if isinstance(call_id, str) and isinstance(observation, str):
                messages.append({"role": "tool", "tool_call_id": call_id, "content": observation})
                register_measurement_observation(measurement_sessions, observation)
                call = call_definitions.get(call_id)
                if (
                    isinstance(call, dict)
                    and call.get("name") in {"inspect_chart_layout", "decompose_chart_image"}
                    and isinstance(call.get("arguments"), str)
                ):
                    remember_layout_context(observation, call["arguments"], layout_contexts)
            references = item.payload.get("visualReferences")
            if isinstance(references, list):
                for reference in references[:32]:
                    if not isinstance(reference, dict):
                        continue
                    owned_reference = dict(reference)
                    owned_reference.setdefault("runId", item.run_id)
                    visual_references.append(owned_reference)
                artifact_records.extend(
                    {**reference, "runId": item.run_id}
                    for reference in references[:32]
                    if isinstance(reference, dict) and reference.get("artifactKind") == "generated_chart"
                )

    pending_calls: list[dict[str, str]] = []
    active_model_entry_id: str | None = None
    requested_call_id: str | None = None
    recovery_action = cursor.next_action.kind
    checkpoint_action: str | None = None
    checkpoint_staged_ref: str | None = None
    if cursor.next_action.kind == "tool":
        active_model_entry_id = cursor.next_action.message_entry_id
        requested_call_id = cursor.next_action.call_id
    elif cursor.next_action.kind == "verify":
        staged_entry = next(
            (
                item for item in reversed(prefix)
                if item.kind == "tool_result"
                and item.payload.get("stagingCheckpoint") is True
                and item.payload.get("stagedRef") == cursor.next_action.staged_ref
            ),
            None,
        )
        if staged_entry is None:
            raise ExecutionRecordError("next verification action has no matching staged result")
        active_model_entry_id = staged_entry.payload.get("modelEntryId")
        requested_call_id = staged_entry.payload.get("callId")
        checkpoint_action = "verify"
        checkpoint_staged_ref = cursor.next_action.staged_ref
        recovery_action = "tool"
    elif cursor.next_action.kind == "promote":
        committed_verification = next(
            (
                item for item in reversed(prefix)
                if item.kind == "verification_result"
                and isinstance(item.payload.get("verification"), dict)
                and item.payload.get("verification", {}).get("stagedRef") == cursor.next_action.staged_ref
                and item.payload.get("verification", {}).get("verificationRef") == cursor.next_action.verification_ref
            ),
            None,
        )
        if committed_verification is None:
            raise ExecutionRecordError("next promotion action has no matching committed verification")
        active_model_entry_id = committed_verification.payload.get("modelEntryId")
        requested_call_id = committed_verification.payload.get("toolCallId")
        if not isinstance(active_model_entry_id, str) or not isinstance(requested_call_id, str):
            raise ExecutionRecordError("next promotion action has no tool identity")
        checkpoint_action = "promote"
        checkpoint_staged_ref = cursor.next_action.staged_ref
        recovery_action = "tool"
    if recovery_action == "tool":
        model_entry = model_entries.get(active_model_entry_id)
        if model_entry is None:
            raise ExecutionRecordError("next tool action references an unavailable model response")
        completed = {
            item.payload.get("callId")
            for item in tool_results
            if item.payload.get("modelEntryId") == active_model_entry_id
            and item.payload.get("stagingCheckpoint") is not True
        }
        calls = model_entry.payload.get("toolCalls")
        if not isinstance(calls, list):
            raise ExecutionRecordError("next tool action has no committed tool batch")
        found_requested = False
        for call in calls[:16]:
            if (
                isinstance(call, dict)
                and all(isinstance(call.get(key), str) and call[key] for key in ("id", "name", "arguments"))
                and call["id"] not in completed
            ):
                if call["id"] == requested_call_id:
                    found_requested = True
                if found_requested:
                    pending_calls.append({"id": call["id"], "name": call["name"], "arguments": call["arguments"]})
        if not pending_calls or pending_calls[0]["id"] != requested_call_id:
            raise ExecutionRecordError("next tool action does not match the pending tool batch")
        first_call = next(
            (call for call in calls if isinstance(call, dict) and call.get("id") == requested_call_id),
            None,
        )
        if first_call is not None and first_call.get("replayEffect") not in {
            "replay_safe", "idempotent_local_write"
        }:
            state_unavailable_tool_call = cursor.next_action.call_id
        else:
            state_unavailable_tool_call = None
    else:
        state_unavailable_tool_call = None

    state: dict[str, Any] = {
        "prompt": prompt,
        "messages": messages[-48:],
        "attachmentIds": attachment_ids,
        "currentTurn": cursor.turn,
        "nextAction": recovery_action,
        "pendingToolCalls": pending_calls,
        "visualReferences": visual_references[-32:],
        "artifactIndex": artifact_records[-48:],
        "layoutContexts": layout_contexts,
        "measurementSessions": sessions_to_state(measurement_sessions),
        "executionModelEntryId": active_model_entry_id,
        "parentRunId": parent_run_id,
        "executionCursor": cursor.entry_cursor,
        "modelStepCount": sum(item.kind == "model_response" for item in prefix),
    }
    if checkpoint_action is not None:
        state["resumeCheckpointAction"] = checkpoint_action
        state["resumeStagedRef"] = checkpoint_staged_ref
        state["resumeToolCallId"] = requested_call_id
    if state_unavailable_tool_call is not None:
        state["unreconciledToolCall"] = state_unavailable_tool_call
    if cursor.next_action.kind == "final":
        model_entry = model_entries.get(cursor.next_action.answer_entry_id)
        if model_entry is None or not isinstance(model_entry.payload.get("content"), str):
            raise ExecutionRecordError("final action references an unavailable answer")
        state["pendingAnswer"] = model_entry.payload["content"]
    return state


__all__ = ["recovery_state_from_entries"]
