"""Pure projections from validated Run facts to complete conversation history."""

from __future__ import annotations

from collections import defaultdict

from figura.shared.json_schema import JsonValueError, canonical_json_dumps
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RecordKind, Run, RunStatus, ToolFactKind
from figura.runtime.records import (
    FinalAnswerFact,
    ModelResponseFact,
    RunInput,
    RunState,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolResultFact,
)

from .models import (
    AssistantMessage,
    MemoryMessage,
    MemoryToolCall,
    SessionHistory,
    ToolMessage,
    UserMessage,
)


def project_session_history(
    target_run: Run,
    prior_states: tuple[RunState, ...],
) -> SessionHistory:
    """Project all earlier, terminal Runs without including the target Run."""
    if (
        not isinstance(target_run, Run)
        or type(target_run.ordinal) is not int
        or target_run.ordinal < 1
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if not isinstance(prior_states, tuple) or any(
        not isinstance(state, RunState) for state in prior_states
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    expected_ordinals = tuple(range(1, target_run.ordinal))
    if tuple(state.run.ordinal for state in prior_states) != expected_ordinals:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    messages: list[MemoryMessage] = []
    for state in prior_states:
        if (
            not isinstance(state, RunState)
            or state.run.session_id != target_run.session_id
            or state.run.status is RunStatus.RUNNING
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        messages.extend(project_run_messages(state))
    return SessionHistory(
        session_id=target_run.session_id,
        target_run_id=target_run.run_id,
        target_run_ordinal=target_run.ordinal,
        messages=tuple(messages),
    )


def project_run_messages(state: RunState) -> tuple[MemoryMessage, ...]:
    """Project one Run's committed user, assistant, and tool messages."""
    if not isinstance(state, RunState):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    run = state.run
    if not state.records:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    input_record = state.records[0]
    run_input = input_record.payload
    if (
        input_record.run_id != run.run_id
        or input_record.record_sequence != 1
        or input_record.record_kind is not RecordKind.INPUT
        or input_record.record_id != run.input_record_id
        or not isinstance(run_input, RunInput)
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    calls_by_response: dict[str, list[tuple[int, ToolCallFact]]] = defaultdict(list)
    calls_by_sequence: dict[int, ToolCallFact] = {}
    results_by_call: dict[int, list[tuple[int, ToolResultFact]]] = defaultdict(list)
    attempts_by_call: dict[int, list[ToolAttemptStartedFact]] = defaultdict(list)
    for fact in state.tool_facts:
        if (
            not isinstance(fact, ToolExecutionFact)
            or fact.run_id != run.run_id
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if fact.fact_kind is ToolFactKind.TOOL_CALL:
            if not isinstance(fact.payload, ToolCallFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = fact.payload
            if fact.tool_sequence in calls_by_sequence:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            calls_by_sequence[fact.tool_sequence] = call
            calls_by_response[call.response_record_id].append((fact.tool_sequence, call))
        elif fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED:
            if not isinstance(fact.payload, ToolAttemptStartedFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attempts_by_call[fact.payload.tool_call_sequence].append(fact.payload)
        elif fact.fact_kind is ToolFactKind.TOOL_RESULT:
            if not isinstance(fact.payload, ToolResultFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            results_by_call[fact.payload.tool_call_sequence].append(
                (fact.tool_sequence, fact.payload)
            )
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    response_ids: set[str] = set()
    messages: list[MemoryMessage] = [
        UserMessage(
            run_id=run.run_id,
            run_ordinal=run.ordinal,
            source_record_id=input_record.record_id,
            text=run_input.text,
            attachment_ids=tuple(run_input.attachment_ids),
        )
    ]
    for record in state.records[1:]:
        if record.run_id != run.run_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if record.record_kind is RecordKind.FINAL_ANSWER:
            if not isinstance(record.payload, FinalAnswerFact):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if record.payload.response_record_id not in response_ids:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            continue
        if record.record_kind is not RecordKind.MODEL_RESPONSE or not isinstance(
            record.payload, ModelResponseFact
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        response_ids.add(record.record_id)
        call_pairs = sorted(
            calls_by_response.get(record.record_id, ()), key=lambda item: item[1].position
        )
        if [call.position for _, call in call_pairs] != list(range(len(call_pairs))):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if bool(call_pairs) != (record.payload.finish_reason == "tool_calls"):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        tool_calls = tuple(
            MemoryToolCall(
                call_id=call.call_id,
                tool_name=call.tool_name,
                arguments_json=call.arguments_json,
                position=call.position,
                registry_version=call.registry_version,
            )
            for _, call in call_pairs
        )
        messages.append(
            AssistantMessage(
                run_id=run.run_id,
                run_ordinal=run.ordinal,
                source_record_id=record.record_id,
                content=record.payload.assistant_content,
                tool_calls=tool_calls,
            )
        )

        for call_sequence, call in call_pairs:
            results = results_by_call.get(call_sequence, ())
            if len(results) != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            result_sequence, result = results[0]
            attempts = attempts_by_call.get(call_sequence, ())
            if not attempts or result.attempt_id not in {item.attempt_id for item in attempts}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if result.call_id != call.call_id or result.tool_name != call.tool_name:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            messages.append(
                ToolMessage(
                    run_id=run.run_id,
                    run_ordinal=run.ordinal,
                    source_tool_sequence=result_sequence,
                    tool_call_id=call.call_id,
                    content=tool_observation(result),
                )
            )

    if set(calls_by_response) - response_ids:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if set(results_by_call) - set(calls_by_sequence):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if set(attempts_by_call) - set(calls_by_sequence):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if any(len(results) != 1 for results in results_by_call.values()):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if any(sequence not in results_by_call for sequence in calls_by_sequence):
        raise RunError(RunErrorCode.INVALID_TRANSITION)
    return tuple(messages)


def tool_observation(result: ToolResultFact) -> str:
    """Encode a committed tool result with the Agent's bounded observation shape."""
    if not isinstance(result, ToolResultFact):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if result.outcome.value == "succeeded":
        if result.error is not None or result.result is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        payload: dict[str, object] = {
            "outcome": result.outcome.value,
            "result": result.result,
        }
    else:
        if result.error is None or result.result is not None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        error: dict[str, object] = {
            "code": result.error.code,
            "message": result.error.message,
            "retryable": result.error.retryable,
        }
        if result.error.field_path is not None:
            error["field_path"] = result.error.field_path
        payload = {"outcome": result.outcome.value, "error": error}
    try:
        return canonical_json_dumps(payload)
    except (JsonValueError, TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
