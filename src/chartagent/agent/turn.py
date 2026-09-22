"""One model turn and one tool dispatch boundary for the Agent loop.

This module receives all mutable collaborators explicitly.  It intentionally
does not import ``Agent`` so the public loop remains the only orchestration
entry point and the turn code can be exercised independently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Optional

from ..client.client import LLMClient
from ..client.models import NormalizedResult, ToolCall
from ..measurement import MEASUREMENT_TOOLS, MeasurementSession
from ..memory import RunStatus
from ..tools.core import ToolRegistry, dispatch_observation
from ..tools.core.result import DispatchedObservation
from .messages import assistant_entry
from .measurement_flow import repair_target_context
from .panel_routing import layout_arguments, panel_routing_error
from .recovery import (
    begin_work_unit,
    complete_work_unit,
    model_result_payload,
    raise_if_interrupted,
    uncertain_work_unit,
)


@dataclass(frozen=True)
class ToolDispatchResult:
    """Prepared tool arguments and the native observation for one call."""

    call_arguments: Any
    dispatch_arguments: str
    source_panel_id: str | None
    source_attachment_id: str | None
    parent_attempt_id: str | None
    raw_observation_scope: Mapping[str, Any] | None
    prepared_target: dict[str, Any] | None
    observation: DispatchedObservation


def execute_model_turn(
    client: Any,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    *,
    chat_kwargs: dict[str, Any],
    pending_recovery_calls: Sequence[ToolCall],
    operation_begin: Callable[..., dict[str, Any]] | None,
    operation_complete: Callable[..., dict[str, Any] | None] | None,
    operation_uncertain: Callable[..., dict[str, Any] | None] | None,
    memory: Any,
    run: Any,
    interruption_event: Any,
    emitter: Any = None,
    turn: int,
    trace_reasoning: bool,
) -> tuple[NormalizedResult, list[ToolCall]]:
    """Run or recover one model operation and emit its model-side trace."""
    raise_if_interrupted(interruption_event, memory, run)
    operation_id = f"model:{turn}"
    if pending_recovery_calls:
        result = NormalizedResult(tool_calls=list(pending_recovery_calls), finish_reason="tool_calls")
        remaining_recovery_calls: list[ToolCall] = []
    else:
        begin_work_unit(operation_begin, operation_id, "model")
        try:
            result = client.chat(messages, tools=tools, **chat_kwargs)
        except Exception as exc:
            uncertain_work_unit(operation_uncertain, operation_id, "model_response_outcome_uncertain")
            memory.append(run, "error", {"error_code": "agent_call_failed", "error_type": type(exc).__name__[:64]})
            memory.finish(run, RunStatus.FAILED, "error")
            if emitter is not None and not isinstance(client, LLMClient):
                emitter.emit(
                    "model_completed",
                    turn=turn,
                    status="error",
                    error_code="agent_call_failed",
                    error_type=type(exc).__name__[:64],
                )
            raise
        complete_work_unit(
            operation_complete,
            operation_uncertain,
            operation_id,
            "model",
            model_result_payload(result),
        )
        remaining_recovery_calls = []

    if emitter is not None and not isinstance(client, LLMClient):
        emitter.emit(
            "model_completed",
            turn=turn,
            status="ok",
            content_length=len(result.content),
            reasoning_available=bool(result.reasoning),
            tool_calls=len(result.tool_calls),
            finish_reason=result.finish_reason,
        )
    if emitter is not None and trace_reasoning:
        from ..trace import bounded_reasoning

        emitter.emit(
            "reasoning",
            turn=turn,
            status="available" if result.reasoning else "unavailable",
            reasoning=bounded_reasoning(result.reasoning),
        )
    return result, remaining_recovery_calls


def prepare_and_dispatch_tool_call(
    registry: ToolRegistry,
    call: ToolCall,
    *,
    run_id: str,
    layout_contexts: dict[str, dict[str, Any]],
    measurement_sessions: Mapping[str, MeasurementSession],
    source_panel_id: str | None = None,
    source_attachment_id: str | None = None,
) -> ToolDispatchResult:
    """Validate scope/target and dispatch one tool call.

    Review decoration and memory/trace projection intentionally remain in the
    loop because they need run-level collaborators.  This boundary owns the
    tool input contract and native observation production only.
    """
    try:
        call_arguments: Any = json.loads(call.arguments) if call.arguments.strip() else {}
    except (TypeError, json.JSONDecodeError):
        call_arguments = {}
    raw_observation_scope = call_arguments.get("observation_scope") if isinstance(call_arguments, dict) else None
    raw_measurement_target = call_arguments.get("measurement_target") if isinstance(call_arguments, dict) else None
    if isinstance(call_arguments, dict):
        source_panel_id = call_arguments.get("panel_id") if isinstance(call_arguments.get("panel_id"), str) else source_panel_id
        source_attachment_id = call_arguments.get("attachment_id") if isinstance(call_arguments.get("attachment_id"), str) else source_attachment_id
    if source_panel_id is None and isinstance(raw_measurement_target, Mapping):
        candidate_panel = raw_measurement_target.get("panel_id")
        if isinstance(candidate_panel, str) and candidate_panel.strip():
            source_panel_id = candidate_panel
    if source_panel_id is None and isinstance(raw_observation_scope, Mapping):
        candidate_panel = raw_observation_scope.get("panel_id")
        if isinstance(candidate_panel, str) and candidate_panel.strip():
            source_panel_id = candidate_panel

    parent_attempt_id = None
    if call.name in MEASUREMENT_TOOLS and isinstance(raw_measurement_target, Mapping):
        for session in reversed(list(measurement_sessions.values())):
            if session.attachment_id == source_attachment_id and session.panel_id in {source_panel_id, None, "__source__"}:
                parent_attempt_id = session.current_attempt_id
                break

    prepared_target: dict[str, Any] | None = None
    repair_error: dict[str, Any] | None = None
    if call.name in MEASUREMENT_TOOLS and raw_measurement_target is not None:
        prepared_target, repair_error = repair_target_context(
            raw_measurement_target,
            measurement_sessions,
            source_attachment_id=source_attachment_id,
            source_panel_id=source_panel_id,
            source_tool=call.name,
            parent_attempt_id=parent_attempt_id,
        )
        if repair_error is None and prepared_target is not None and isinstance(call_arguments, dict):
            call_arguments["measurement_target"] = prepared_target

    dispatch_arguments = layout_arguments(
        call.name,
        json.dumps(call_arguments, ensure_ascii=False, separators=(",", ":"))
        if isinstance(call_arguments, dict)
        else call.arguments,
        layout_contexts,
    )
    routing_error = panel_routing_error(call.name, dispatch_arguments, layout_contexts)
    if repair_error is not None:
        observation = DispatchedObservation(
            json.dumps(
                {
                    "error": "measurement repair rejected",
                    "measurement_repair": repair_error,
                },
                ensure_ascii=False,
            )
        )
    elif routing_error is not None:
        observation = DispatchedObservation(json.dumps({"error": routing_error}, ensure_ascii=False))
    else:
        observation = dispatch_observation(
            registry,
            call.name,
            dispatch_arguments,
            source_run_id=run_id,
            source_panel_id=source_panel_id,
            source_parent_attempt_id=parent_attempt_id,
            source_measurement_target=prepared_target,
            source_observation_scope=raw_observation_scope if isinstance(raw_observation_scope, Mapping) else None,
            measurement_context=measurement_sessions if call.name == "assemble_spec" else None,
        )
    return ToolDispatchResult(
        call_arguments=call_arguments,
        dispatch_arguments=dispatch_arguments,
        source_panel_id=source_panel_id,
        source_attachment_id=source_attachment_id,
        parent_attempt_id=parent_attempt_id,
        raw_observation_scope=raw_observation_scope if isinstance(raw_observation_scope, Mapping) else None,
        prepared_target=prepared_target,
        observation=observation,
    )


def assistant_message_for_result(
    result: NormalizedResult,
    *,
    client: Any,
) -> tuple[Any, Any]:
    """Return model-facing and sanitized assistant entries for one result."""
    message = assistant_entry(
        result,
        include_reasoning=(
            getattr(getattr(client, "config", None), "provider", None) == "deepseek"
            and getattr(getattr(client, "config", None), "enable_thinking", False)
            and bool(result.reasoning)
        ),
    )
    return message, assistant_entry(result)
