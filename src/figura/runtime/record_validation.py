"""Consistency checks for persisted Runtime attempts and continuation facts."""

from __future__ import annotations

from figura.providers.errors import ProviderFailureCode

from .errors import RunError, RunErrorCode
from .models import (
    ProviderAttemptStatus,
    Run,
    RunStatus,
    TerminalCode,
)
from .records import (
    ExecutionCheckpoint,
    ExecutionRecord,
    ModelResponseFact,
    ProviderAttempt,
    ProviderContinuationFact,
    ToolCallFact,
    ToolExecutionFact,
)


def _utf8_length(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return 2**63 - 1


def _validate_provider_attempts(
    *,
    run: Run,
    checkpoint: ExecutionCheckpoint,
    response_records: list[ExecutionRecord],
    response_by_id: dict[str, ExecutionRecord],
    provider_attempts: tuple[ProviderAttempt, ...],
    tool_facts: tuple[ToolExecutionFact, ...],
    calls_by_sequence: dict[int, tuple[ToolExecutionFact, ToolCallFact]],
) -> None:
    if len(provider_attempts) > 8:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if [attempt.attempt_sequence for attempt in provider_attempts] != list(
        range(1, len(provider_attempts) + 1)
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    attempt_ids: set[str] = set()
    linked_response_ids: set[str] = set()
    for index, attempt in enumerate(provider_attempts):
        if (
            attempt.run_id != run.run_id
            or not isinstance(attempt.attempt_id, str)
            or not attempt.attempt_id
            or _utf8_length(attempt.attempt_id) > 128
            or attempt.attempt_id in attempt_ids
            or type(attempt.base_record_sequence) is not int
            or attempt.base_record_sequence < 1
            or attempt.base_record_sequence > checkpoint.last_committed_record_sequence
            or type(attempt.base_tool_sequence) is not int
            or attempt.base_tool_sequence < 0
            or attempt.base_tool_sequence > checkpoint.last_committed_tool_sequence
            or not isinstance(attempt.started_at, str)
            or not attempt.started_at
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        attempt_ids.add(attempt.attempt_id)
        if attempt.status is ProviderAttemptStatus.STARTED:
            if (
                index != len(provider_attempts) - 1
                or attempt.response_record_id is not None
                or attempt.failure_code is not None
                or attempt.finished_at is not None
                or run.status is not RunStatus.RUNNING
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        elif attempt.status is ProviderAttemptStatus.RESPONSE_COMMITTED:
            if (
                not isinstance(attempt.response_record_id, str)
                or not attempt.response_record_id
                or attempt.failure_code is not None
                or not isinstance(attempt.finished_at, str)
                or not attempt.finished_at
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_record = response_by_id.get(attempt.response_record_id)
            if response_record is None or attempt.response_record_id in linked_response_ids:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            linked_response_ids.add(attempt.response_record_id)
        elif attempt.status is ProviderAttemptStatus.KNOWN_FAILURE:
            if (
                index != len(provider_attempts) - 1
                or attempt.response_record_id is not None
                or not isinstance(attempt.failure_code, str)
                or not isinstance(attempt.finished_at, str)
                or not attempt.finished_at
                or (run.status, run.terminal_code) not in {
                    (RunStatus.FAILED, TerminalCode.EXECUTION_FAILED.value),
                    (RunStatus.INTERRUPTED, TerminalCode.INTERRUPTED.value),
                }
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        elif attempt.status is ProviderAttemptStatus.OUTCOME_UNKNOWN:
            if (
                index != len(provider_attempts) - 1
                or attempt.response_record_id is not None
                or not isinstance(attempt.finished_at, str)
                or not attempt.finished_at
                or (run.status, run.terminal_code) not in {
                    (RunStatus.FAILED, TerminalCode.PROVIDER_OUTCOME_UNKNOWN.value),
                    (RunStatus.INTERRUPTED, TerminalCode.INTERRUPTED.value),
                }
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if attempt.failure_code is not None:
            try:
                ProviderFailureCode(attempt.failure_code)
            except ValueError:
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None

    # Responses written before schema v4 form an unlinked prefix. All later
    # responses must have exactly one attempt row.
    legacy_prefix: list[ExecutionRecord] = []
    saw_linked_response = False
    for response in response_records:
        if response.record_id in linked_response_ids:
            saw_linked_response = True
        elif saw_linked_response:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            legacy_prefix.append(response)

    response_sequence_by_id = {record.record_id: record.record_sequence for record in response_records}
    fact_response_sequence: dict[int, int] = {}
    for fact in tool_facts:
        if isinstance(fact.payload, ToolCallFact):
            response_record_id = fact.payload.response_record_id
        else:
            call_pair = calls_by_sequence.get(fact.payload.tool_call_sequence)
            if call_pair is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_record_id = call_pair[1].response_record_id
        if response_record_id not in response_sequence_by_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        fact_response_sequence[fact.tool_sequence] = response_sequence_by_id[response_record_id]

    expected_base_record_sequence = (
        legacy_prefix[-1].record_sequence if legacy_prefix else 1
    )
    for index, attempt in enumerate(provider_attempts):
        if attempt.base_record_sequence != expected_base_record_sequence:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        expected_base_tool_sequence = max(
            (
                fact.tool_sequence
                for fact in tool_facts
                if fact_response_sequence[fact.tool_sequence] <= expected_base_record_sequence
            ),
            default=0,
        )
        if attempt.base_tool_sequence != expected_base_tool_sequence:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        if attempt.status is ProviderAttemptStatus.RESPONSE_COMMITTED:
            response_record = response_by_id[attempt.response_record_id]
            if response_record.record_sequence != attempt.base_record_sequence + 1:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            expected_base_record_sequence = response_record.record_sequence
        elif index != len(provider_attempts) - 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if provider_attempts:
        last_attempt = provider_attempts[-1]
        if last_attempt.status is ProviderAttemptStatus.STARTED and (
            last_attempt.base_record_sequence != checkpoint.last_committed_record_sequence
            or last_attempt.base_tool_sequence != checkpoint.last_committed_tool_sequence
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if last_attempt.status in {
            ProviderAttemptStatus.KNOWN_FAILURE,
            ProviderAttemptStatus.OUTCOME_UNKNOWN,
        } and (
            last_attempt.base_record_sequence != checkpoint.last_committed_record_sequence
            or last_attempt.base_tool_sequence != checkpoint.last_committed_tool_sequence
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _validate_continuation_state(
    run: Run,
    response_records: list[ExecutionRecord],
    continuation_facts: tuple[ProviderContinuationFact, ...],
) -> None:
    referenced_by_response: dict[str, str] = {}
    seen_references: set[str] = set()
    for record in response_records:
        response = record.payload
        if not isinstance(response, ModelResponseFact):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        reference = response.continuation_ref
        if reference is None:
            continue
        if (
            response.schema_version != 2
            or not isinstance(reference, str)
            or not reference
            or _utf8_length(reference) > 128
            or reference in seen_references
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        seen_references.add(reference)
        referenced_by_response[record.record_id] = reference

    if [fact.response_record_id for fact in continuation_facts] != list(referenced_by_response):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    records_by_id = {record.record_id: record for record in response_records}
    seen_continuation_ids: set[str] = set()
    for fact in continuation_facts:
        record = records_by_id.get(fact.response_record_id)
        if (
            fact.run_id != run.run_id
            or record is None
            or fact.continuation_id in seen_continuation_ids
            or fact.continuation_id != referenced_by_response[fact.response_record_id]
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        response = record.payload
        if (
            not isinstance(response, ModelResponseFact)
            or fact.provider_id != run.provider
            or fact.provider_id != response.provider_id
            or fact.created_at != record.created_at
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        seen_continuation_ids.add(fact.continuation_id)

