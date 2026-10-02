"""Runtime identity and aggregate-state invariants."""

from __future__ import annotations

from figura.providers.models import FinishReason

from .errors import RunError, RunErrorCode
from .models import (
    ActionKind,
    EventKind,
    NextAction,
    ProviderAttemptStatus,
    RecordKind,
    RunStatus,
    RunStopRequest,
    TERMINAL_MESSAGES,
    PREPARATION_MESSAGES,
    TerminalCode,
)
from .records import (
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    RunInput,
    RunState,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolFactKind,
    ToolResultFact,
)
from .record_validation import (
    _utf8_length,
    _validate_continuation_state,
    _validate_provider_attempts,
)


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value or _utf8_length(value) > 128:
        raise RunError(RunErrorCode.INVALID_REQUEST)


def _validate_state(state: RunState) -> None:
    run, checkpoint = state.run, state.checkpoint
    stop = state.stop_request
    if stop is not None and not isinstance(stop, RunStopRequest):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if stop is not None and (
        stop.run_id != run.run_id
        or not isinstance(stop.request_id, str) or not stop.request_id
        or len(stop.request_id) > 128
        or not isinstance(stop.requested_at, str) or not stop.requested_at
        or stop.reason != "user_requested"
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    records, events, tool_facts = state.records, state.events, state.tool_facts
    if (
        checkpoint.run_id != run.run_id
        or checkpoint.schema_version != 1
        or type(checkpoint.last_committed_tool_sequence) is not int
        or checkpoint.last_committed_tool_sequence < 0
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if not records or len(records) != checkpoint.last_committed_record_sequence:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if [record.record_sequence for record in records] != list(range(1, len(records) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if len(tool_facts) != checkpoint.last_committed_tool_sequence:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if [fact.tool_sequence for fact in tool_facts] != list(range(1, len(tool_facts) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    first = records[0]
    if first.record_kind is not RecordKind.INPUT or first.record_id != run.input_record_id:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    input_fact = first.payload
    if not isinstance(input_fact, RunInput):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if (input_fact.requested_provider, input_fact.requested_model) != (run.provider, run.model):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    response_records: list[ExecutionRecord] = []
    final_records: list[ExecutionRecord] = []
    saw_final = False
    for index, record in enumerate(records[1:], start=1):
        if record.record_kind is RecordKind.MODEL_RESPONSE and not saw_final:
            response_records.append(record)
        elif record.record_kind is RecordKind.FINAL_ANSWER and not saw_final and index == len(records) - 1:
            final_records.append(record)
            saw_final = True
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    response_by_id: dict[str, ExecutionRecord] = {}
    response_position: dict[str, int] = {}
    last_non_tool_response = -1
    for response_index, record in enumerate(response_records):
        response = record.payload
        if (
            not isinstance(response, ModelResponseFact)
            or (response.provider_id, response.model_id) != (run.provider, run.model)
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            finish_reason = FinishReason(response.finish_reason)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        response_by_id[record.record_id] = record
        response_position[record.record_id] = response_index
        if finish_reason is not FinishReason.TOOL_CALLS:
            last_non_tool_response = response_index
    if last_non_tool_response >= 0 and last_non_tool_response != len(response_records) - 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    _validate_continuation_state(run, response_records, state.provider_continuations)

    calls_by_response: dict[str, list[tuple[ToolExecutionFact, ToolCallFact]]] = {}
    calls_by_sequence: dict[int, tuple[ToolExecutionFact, ToolCallFact]] = {}
    calls_by_id: dict[str, tuple[ToolExecutionFact, ToolCallFact]] = {}
    attempts_by_id: dict[str, tuple[ToolExecutionFact, ToolAttemptStartedFact]] = {}
    results_by_attempt: dict[str, tuple[ToolExecutionFact, ToolResultFact]] = {}

    for fact in tool_facts:
        if fact.run_id != run.run_id or fact.schema_version != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact):
            call = fact.payload
            response_record = response_by_id.get(call.response_record_id)
            if response_record is None or call.call_id in calls_by_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_payload = response_record.payload
            if not isinstance(response_payload, ModelResponseFact) or response_payload.finish_reason != FinishReason.TOOL_CALLS.value:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            calls_by_response.setdefault(call.response_record_id, []).append((fact, call))
            calls_by_sequence[fact.tool_sequence] = (fact, call)
            calls_by_id[call.call_id] = (fact, call)
        elif fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED and isinstance(fact.payload, ToolAttemptStartedFact):
            attempt = fact.payload
            call_pair = calls_by_sequence.get(attempt.tool_call_sequence)
            if call_pair is None or attempt.attempt_id in attempts_by_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_pair[1]
            prior_attempts = [item for item in attempts_by_id.values() if item[1].tool_call_sequence == attempt.tool_call_sequence]
            if (
                attempt.call_id != call.call_id
                or attempt.registry_version != call.registry_version
                or attempt.attempt_number != len(prior_attempts) + 1
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attempts_by_id[attempt.attempt_id] = (fact, attempt)
        elif fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact):
            result = fact.payload
            attempt_pair = attempts_by_id.get(result.attempt_id)
            if attempt_pair is None or result.attempt_id in results_by_attempt:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attempt = attempt_pair[1]
            call_pair = calls_by_sequence.get(result.tool_call_sequence)
            if call_pair is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            call = call_pair[1]
            if (
                attempt.tool_call_sequence != result.tool_call_sequence
                or result.call_id != call.call_id
                or result.tool_name != call.tool_name
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            results_by_attempt[result.attempt_id] = (fact, result)
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    batch_response_ids = [
        record.record_id
        for record in response_records
        if isinstance(record.payload, ModelResponseFact)
        and record.payload.finish_reason == FinishReason.TOOL_CALLS.value
    ]
    if set(calls_by_response) != set(batch_response_ids):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    batch_rank = {response_id: index for index, response_id in enumerate(batch_response_ids)}
    call_position: dict[int, int] = {}
    for response_id in batch_response_ids:
        call_pairs = calls_by_response[response_id]
        call_pairs.sort(key=lambda pair: pair[1].position)
        if not 1 <= len(call_pairs) <= 64:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if [call.position for _, call in call_pairs] != list(range(len(call_pairs))):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if len({call.registry_version for _, call in call_pairs}) != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        call_sequences = [fact.tool_sequence for fact, _ in call_pairs]
        if call_sequences != list(range(call_sequences[0], call_sequences[0] + len(call_sequences))):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        for position, (fact, _call) in enumerate(call_pairs):
            call_position[fact.tool_sequence] = position

    fact_batch_ranks: list[int] = []
    for fact in tool_facts:
        if isinstance(fact.payload, ToolCallFact):
            response_id = fact.payload.response_record_id
        else:
            call_pair = calls_by_sequence.get(fact.payload.tool_call_sequence)
            if call_pair is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_id = call_pair[1].response_record_id
        fact_batch_ranks.append(batch_rank[response_id])
    if fact_batch_ranks != sorted(fact_batch_ranks):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if fact_batch_ranks and fact_batch_ranks[0] != 0:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    for left, right in zip(fact_batch_ranks, fact_batch_ranks[1:]):
        if right > left + 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    _validate_provider_attempts(
        run=run,
        checkpoint=checkpoint,
        response_records=response_records,
        response_by_id=response_by_id,
        provider_attempts=state.provider_attempts,
        tool_facts=tool_facts,
        calls_by_sequence=calls_by_sequence,
    )

    unresolved_action: NextAction | None = None
    for rank, response_id in enumerate(batch_response_ids):
        call_pairs = calls_by_response[response_id]
        batch_facts = [fact for fact in tool_facts if fact_batch_ranks[fact.tool_sequence - 1] == rank]
        call_facts = [fact for fact in batch_facts if fact.fact_kind is ToolFactKind.TOOL_CALL]
        if [fact.tool_sequence for fact in call_facts] != [fact.tool_sequence for fact, _ in call_pairs]:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if any(fact.fact_kind is ToolFactKind.TOOL_CALL for fact in batch_facts[len(call_pairs):]):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        next_position = 0
        latest_attempt_by_call: dict[int, str] = {}
        attempt_counts: dict[int, int] = {}
        for fact in batch_facts[len(call_pairs):]:
            payload = fact.payload
            call_sequence = payload.tool_call_sequence
            position = call_position[call_sequence]
            if position != next_position:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if isinstance(payload, ToolAttemptStartedFact):
                attempt_counts[call_sequence] = attempt_counts.get(call_sequence, 0) + 1
                if payload.attempt_number != attempt_counts[call_sequence]:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                latest_attempt_by_call[call_sequence] = payload.attempt_id
            elif isinstance(payload, ToolResultFact):
                if latest_attempt_by_call.get(call_sequence) != payload.attempt_id:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                next_position += 1
            else:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

        if rank < len(batch_response_ids) - 1 and next_position != len(call_pairs):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if next_position < len(call_pairs):
            current_sequence = call_pairs[next_position][0].tool_sequence
            current_attempt_id = latest_attempt_by_call.get(current_sequence)
            unresolved_action = (
                NextAction(ActionKind.TOOL_ATTEMPT, tool_call_sequence=current_sequence, attempt_id=current_attempt_id)
                if current_attempt_id is not None
                else NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=current_sequence)
            )

    if set(results_by_attempt) - set(attempts_by_id):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    final_records = [record for record in records if record.record_kind is RecordKind.FINAL_ANSWER]
    if len(final_records) > 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if final_records:
        final = final_records[0]
        if not response_records or not isinstance(final.payload, FinalAnswerFact):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if final.payload.response_record_id != response_records[-1].record_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        last_response = response_records[-1].payload
        if (
            not isinstance(last_response, ModelResponseFact)
            or last_response.finish_reason != FinishReason.STOP.value
            or not last_response.assistant_content.strip()
            or unresolved_action is not None
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if unresolved_action is not None:
        expected_action = unresolved_action
    elif response_records and isinstance(response_records[-1].payload, ModelResponseFact):
        latest_response = response_records[-1]
        latest_fact = latest_response.payload
        expected_action = (
            NextAction(ActionKind.MODEL)
            if latest_fact.finish_reason == FinishReason.TOOL_CALLS.value
            else NextAction(ActionKind.FINAL, latest_response.record_id)
        )
    else:
        expected_action = NextAction(ActionKind.MODEL)

    if state.provider_attempts and state.provider_attempts[-1].status is ProviderAttemptStatus.STARTED:
        expected_action = NextAction(
            ActionKind.PROVIDER_ATTEMPT,
            attempt_id=state.provider_attempts[-1].attempt_id,
        )
    elif (
        run.status in {RunStatus.FAILED, RunStatus.INTERRUPTED}
        and state.provider_attempts
        and state.provider_attempts[-1].status
        in {ProviderAttemptStatus.KNOWN_FAILURE, ProviderAttemptStatus.OUTCOME_UNKNOWN}
    ):
        expected_action = NextAction(
            ActionKind.PROVIDER_ATTEMPT,
            attempt_id=state.provider_attempts[-1].attempt_id,
        )

    if run.status is RunStatus.RUNNING:
        if (
            run.finished_at is not None
            or run.terminal_code is not None
            or run.final_record_id is not None
            or final_records
            or checkpoint.next_action != expected_action
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    elif run.status is RunStatus.COMPLETED:
        if (
            run.finished_at is None
            or run.terminal_code is not None
            or run.terminal_message is not None
            or checkpoint.next_action is not None
            or not final_records
            or run.final_record_id != final_records[0].record_id
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if expected_action.action_kind is not ActionKind.FINAL:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    else:
        if (
            run.finished_at is None
            or checkpoint.next_action != expected_action
            or run.final_record_id is not None
            or final_records
            or run.terminal_code not in {code.value for code in TerminalCode}
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            code = TerminalCode(run.terminal_code)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        if run.terminal_message != TERMINAL_MESSAGES[code] and not (
            code is TerminalCode.EXECUTION_FAILED
            and run.terminal_message in PREPARATION_MESSAGES.values()
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if (run.status is RunStatus.INTERRUPTED) != (code is TerminalCode.INTERRUPTED):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if not events or [event.event_sequence for event in events] != list(range(1, len(events) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if events[0].event_kind is not EventKind.RUN_CREATED:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    created_payload = events[0].payload
    if created_payload != {"session_id": run.session_id, "ordinal": run.ordinal}:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    terminal_event = events[-1] if run.status is not RunStatus.RUNNING else None
    progress_events = events[1:-1] if terminal_event is not None else events[1:]
    previous_revision = 0
    stop_notifications = 0
    for event in progress_events:
        revision = event.payload.get("checkpoint_revision")
        if (
            event.event_kind is not EventKind.RUN_PROGRESS
            or set(event.payload) != {"checkpoint_revision"}
            or type(revision) is not int
            or revision < previous_revision
            or revision > checkpoint.revision
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        is_stop_notification = stop is not None and event.created_at == stop.requested_at
        if is_stop_notification:
            if stop_notifications:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            stop_notifications += 1
        elif revision == previous_revision:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        previous_revision = revision
    if stop is not None and stop_notifications != 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if terminal_event is not None:
        if run.status is RunStatus.COMPLETED:
            if terminal_event.event_kind is not EventKind.RUN_COMPLETED or terminal_event.payload != {"final_artifact_refs": ()}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            expected_kind = EventKind.RUN_INTERRUPTED if run.status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
            if terminal_event.event_kind is not expected_kind or terminal_event.payload != {"terminal_code": run.terminal_code}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
