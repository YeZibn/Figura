"""Pure selection and response validation for Session context compaction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
from figura.memory import AssistantMessage, MemoryMessage, ToolMessage, UserMessage
from figura.memory.projector import _project_run_messages
from figura.providers import FinishReason, ProviderId, ProviderResponse
from figura.providers.token_estimation import estimate_text_tokens
from figura.runtime.models import RunStatus
from figura.runtime.records import (
    ContextCompactionOperation,
    RunState,
    SessionContextCheckpoint,
    ToolCallFact,
    ToolExecutionFact,
)
from figura.shared.source_refs import (
    HistorySourceRef,
    MessageSourceRef,
    source_ref_from_dict,
)


_SUMMARY_FIELDS = (
    "current_goal",
    "constraints",
    "decisions",
    "facts",
    "progress",
    "open_questions",
    "resources",
    "proposals",
)
_PROGRESS_FIELDS = ("completed", "in_progress", "pending", "blocked")
_SUMMARY_ITEM_FIELDS = {"text", "source_refs"}


@dataclass(frozen=True)
class ContextHistoryBudgets:
    context_capacity_tokens: int
    raw_history_tokens: int
    summary_tokens: int


@dataclass(frozen=True)
class CompactionSelection:
    selected_run_states: tuple[RunState, ...]
    covered_run_id: str
    covered_run_ordinal: int
    covered_record_sequence: int
    covered_tool_sequence: int


@dataclass(frozen=True)
class _InteractionUnit:
    state: RunState
    messages: tuple[MemoryMessage, ...]
    record_sequence: int
    tool_sequence: int
    estimated_tokens: int
    input_locator_tokens: int


def calculate_context_history_budgets(
    context_capacity_tokens: object,
) -> ContextHistoryBudgets | None:
    """Allocate approximate ten-percent history budgets from a valid capacity."""
    if type(context_capacity_tokens) is not int or context_capacity_tokens <= 0:
        return None
    allocation = context_capacity_tokens // 10
    return ContextHistoryBudgets(
        context_capacity_tokens,
        allocation,
        allocation,
    )


def eligible_compaction_runs(
    prior_run_states: tuple[RunState, ...],
    checkpoint_ordinal: int,
) -> tuple[RunState, ...]:
    """Return the closed Run prefix after a checkpoint, including the newest Run."""
    if type(checkpoint_ordinal) is not int or checkpoint_ordinal < 0:
        return ()
    selected: list[RunState] = []
    for state in prior_run_states:
        if state.run.ordinal < checkpoint_ordinal:
            continue
        if state.run.status is not RunStatus.COMPLETED:
            break
        selected.append(state)
    return tuple(selected)


def select_compaction_coverage(
    prior_run_states: tuple[RunState, ...],
    previous_checkpoint: SessionContextCheckpoint | None,
    raw_history_budget_tokens: int,
    *,
    estimate_tokens: Callable[[str], int | None] = estimate_text_tokens,
) -> CompactionSelection | None:
    """Choose a chronological summary prefix and a recent complete-interaction suffix."""
    if (
        not isinstance(prior_run_states, tuple)
        or type(raw_history_budget_tokens) is not int
        or raw_history_budget_tokens < 0
        or not callable(estimate_tokens)
    ):
        return None
    checkpoint_ordinal = previous_checkpoint.covered_run_ordinal if previous_checkpoint else 0
    eligible = eligible_compaction_runs(prior_run_states, checkpoint_ordinal)
    candidate_units: list[_InteractionUnit] = []
    for state in eligible:
        units = _interaction_units(state, estimate_tokens)
        if state.records and not units:
            return None
        for unit in units:
            if not _unit_is_after_checkpoint(unit, previous_checkpoint):
                continue
            candidate_units.append(unit)
    if not candidate_units:
        return None

    eligible_ids = {state.run.run_id for state in eligible}
    protected_states = tuple(
        state for state in prior_run_states
        if state.run.ordinal > checkpoint_ordinal and state.run.run_id not in eligible_ids
    )
    protected_tokens = 0
    for state in protected_states:
        estimate = _estimate_protected_run(state, estimate_tokens)
        if estimate is None:
            return None
        protected_tokens += estimate

    remaining = max(0, raw_history_budget_tokens - protected_tokens)
    suffix_start = len(candidate_units)
    suffix_tokens = 0
    suffix_run_ids: set[str] = set()
    for index in range(len(candidate_units) - 1, -1, -1):
        unit = candidate_units[index]
        locator_tokens = (
            unit.input_locator_tokens
            if unit.state.run.run_id not in suffix_run_ids else 0
        )
        unit_tokens = unit.estimated_tokens + locator_tokens
        if suffix_tokens + unit_tokens <= remaining:
            suffix_tokens += unit_tokens
            suffix_run_ids.add(unit.state.run.run_id)
            suffix_start = index
            continue
        # Keep the newest complete interaction even when it alone exceeds the target.
        if suffix_start == len(candidate_units) and protected_tokens == 0:
            suffix_start = index
            suffix_tokens += unit_tokens
        break

    if suffix_start == 0:
        return None
    covered_unit = candidate_units[suffix_start - 1]
    selected_states = _unique_states(candidate_units[:suffix_start])
    return CompactionSelection(
        selected_run_states=selected_states,
        covered_run_id=covered_unit.state.run.run_id,
        covered_run_ordinal=covered_unit.state.run.ordinal,
        covered_record_sequence=covered_unit.record_sequence,
        covered_tool_sequence=covered_unit.tool_sequence,
    )


def selection_for_coverage(
    prior_run_states: tuple[RunState, ...],
    previous_checkpoint: SessionContextCheckpoint | None,
    operation: ContextCompactionOperation,
) -> CompactionSelection | None:
    """Rebuild an already-persisted selection without consulting current budgets."""
    if not isinstance(operation, ContextCompactionOperation):
        return None
    checkpoint_ordinal = previous_checkpoint.covered_run_ordinal if previous_checkpoint else 0
    eligible = eligible_compaction_runs(prior_run_states, checkpoint_ordinal)
    candidate_units: list[_InteractionUnit] = []
    for state in eligible:
        for unit in _interaction_units(state, lambda _text: 0):
            if _unit_is_after_checkpoint(unit, previous_checkpoint):
                candidate_units.append(unit)
    cutoff_index = next((
        index for index, unit in enumerate(candidate_units)
        if unit.state.run.run_id == operation.covered_run_id
        and unit.state.run.ordinal == operation.covered_run_ordinal
        and unit.record_sequence == operation.covered_record_sequence
        and unit.tool_sequence == operation.covered_tool_sequence
    ), None)
    if cutoff_index is None:
        return None
    covered_prefix = candidate_units[:cutoff_index + 1]
    return CompactionSelection(
        selected_run_states=_unique_states(covered_prefix),
        covered_run_id=operation.covered_run_id,
        covered_run_ordinal=operation.covered_run_ordinal,
        covered_record_sequence=operation.covered_record_sequence,
        covered_tool_sequence=operation.covered_tool_sequence,
    )


def _interaction_units(
    state: RunState,
    estimate_tokens: Callable[[str], int | None],
) -> tuple[_InteractionUnit, ...]:
    incomplete_batches = []
    messages = _project_run_messages(
        state,
        incomplete_batches if state.run.status is not RunStatus.COMPLETED else None,
    )
    if not messages:
        return ()
    groups = _group_interactions(messages)
    record_sequences = {record.record_id: record.record_sequence for record in state.records}
    facts_by_call: dict[str, list[ToolExecutionFact]] = {}
    for fact in state.tool_facts:
        call_id = getattr(fact.payload, "call_id", None)
        if isinstance(call_id, str):
            facts_by_call.setdefault(call_id, []).append(fact)

    units: list[_InteractionUnit] = []
    prior_tool_sequence = 0
    for index, group in enumerate(groups):
        record_sequence = max(
            record_sequences[message.source_record_id]
            for message in group
            if isinstance(message, (UserMessage, AssistantMessage))
        )
        calls = [
            call.call_id
            for message in group if isinstance(message, AssistantMessage)
            for call in message.tool_calls
        ]
        tool_sequence = max(
            [prior_tool_sequence]
            + [fact.tool_sequence for call_id in calls for fact in facts_by_call.get(call_id, ())]
        )
        prior_tool_sequence = tool_sequence
        if state.run.status is RunStatus.COMPLETED and index == len(groups) - 1:
            record_sequence = state.checkpoint.last_committed_record_sequence
            tool_sequence = state.checkpoint.last_committed_tool_sequence
        process_messages = [
            _message_projection(message)
            for message in group if not isinstance(message, UserMessage)
        ]
        projection = {
            "run_id": state.run.run_id,
            "run_ordinal": state.run.ordinal,
            "messages": process_messages,
        }
        token_count = estimate_tokens(json.dumps(
            projection, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ))
        if type(token_count) is not int or token_count < 0:
            return ()
        input_locator_tokens = 0
        if any(isinstance(item, (AssistantMessage, ToolMessage)) for item in messages):
            locator_estimate = estimate_tokens(json.dumps(
                _historical_run_context_projection(state),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ))
            if type(locator_estimate) is not int or locator_estimate < 0:
                return ()
            input_locator_tokens = locator_estimate
        units.append(_InteractionUnit(
            state, group, record_sequence, tool_sequence, token_count,
            input_locator_tokens,
        ))
    return tuple(units)


def _group_interactions(messages: tuple[MemoryMessage, ...]) -> tuple[tuple[MemoryMessage, ...], ...]:
    if not messages or not isinstance(messages[0], UserMessage):
        return ()
    groups: list[list[MemoryMessage]] = [[messages[0]]]
    has_assistant = False
    for message in messages[1:]:
        if isinstance(message, AssistantMessage) and has_assistant:
            groups.append([message])
            has_assistant = True
            continue
        groups[-1].append(message)
        if isinstance(message, AssistantMessage):
            has_assistant = True
    return tuple(tuple(group) for group in groups)


def _message_projection(message: MemoryMessage) -> dict[str, object]:
    if isinstance(message, UserMessage):
        return _historical_run_context_projection(
            message.run_id, message.run_ordinal, message.source_record_id
        )
    if isinstance(message, AssistantMessage):
        return {
            "reference": {"kind": "message", "run_id": message.run_id,
                          "record_id": message.source_record_id},
            "role": "assistant", "text": message.content,
            "tool_calls": [{"call_id": call.call_id, "tool_name": call.tool_name,
                            "arguments": call.arguments_json} for call in message.tool_calls],
        }
    if isinstance(message, ToolMessage):
        return {
            "reference": {"kind": "tool_result", "run_id": message.run_id,
                          "call_id": message.tool_call_id},
            "role": "tool", "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    raise ValueError("unsupported projected history message")


def _historical_run_context_projection(
    state_or_run_id: RunState | str,
    run_ordinal: int | None = None,
    input_record_id: str | None = None,
) -> dict[str, object]:
    if isinstance(state_or_run_id, RunState):
        run_id = state_or_run_id.run.run_id
        run_ordinal = state_or_run_id.run.ordinal
        input_record_id = state_or_run_id.run.input_record_id
    else:
        run_id = state_or_run_id
    if not isinstance(run_id, str) or type(run_ordinal) is not int or not isinstance(input_record_id, str):
        raise ValueError("invalid historical Run input locator")
    return {
        "figura_context_type": "historical_run_context",
        "run_id": run_id,
        "run_ordinal": run_ordinal,
        "input_ref": {
            "kind": "message",
            "run_id": run_id,
            "record_id": input_record_id,
        },
    }


def _estimate_protected_run(
    state: RunState,
    estimate_tokens: Callable[[str], int | None],
) -> int | None:
    units = _interaction_units(state, estimate_tokens)
    if state.records and not units:
        return None
    total = sum(unit.estimated_tokens for unit in units)
    total += units[0].input_locator_tokens
    incomplete_batches = []
    _project_run_messages(state, incomplete_batches)
    if incomplete_batches:
        outcome = {
            "run_id": state.run.run_id,
            "status": state.run.status.value,
            "terminal_code": state.run.terminal_code,
            "incomplete_batches": [asdict(batch) for batch in incomplete_batches],
        }
        estimate = estimate_tokens(json.dumps(
            outcome, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ))
        if type(estimate) is not int or estimate < 0:
            return None
        total += estimate
    return total


def _unit_is_after_checkpoint(
    unit: _InteractionUnit,
    checkpoint: SessionContextCheckpoint | None,
) -> bool:
    if checkpoint is None or unit.state.run.ordinal > checkpoint.covered_run_ordinal:
        return True
    if unit.state.run.ordinal < checkpoint.covered_run_ordinal:
        return False
    if unit.state.run.run_id != checkpoint.covered_run_id:
        return False
    return (
        unit.record_sequence > checkpoint.covered_record_sequence
        or unit.tool_sequence > checkpoint.covered_tool_sequence
    )


def _unique_states(units: list[_InteractionUnit]) -> tuple[RunState, ...]:
    selected: list[RunState] = []
    seen: set[str] = set()
    for unit in units:
        if unit.state.run.run_id not in seen:
            seen.add(unit.state.run.run_id)
            selected.append(unit.state)
    return tuple(selected)


def validate_summary_response(
    response: ProviderResponse,
    *,
    provider_id: str,
    model_id: str,
    allowed_refs: tuple[HistorySourceRef, ...],
    selected_runs: tuple[RunState, ...],
) -> tuple[dict[str, object], tuple[HistorySourceRef, ...]]:
    """Validate JSON shape and require every summary item to cite authorized facts."""
    if (
        not isinstance(response, ProviderResponse)
        or not isinstance(response.provider_id, ProviderId)
        or response.provider_id.value != provider_id
        or response.model_id != model_id
        or response.finish_reason is not FinishReason.STOP
        or response.tool_calls
        or response.continuation is not None
        or not isinstance(response.assistant_content, str)
    ):
        raise ValueError("summary response did not satisfy the text completion contract")
    try:
        value = json.loads(response.assistant_content, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("summary response is not valid JSON") from None
    if not isinstance(value, dict) or set(value) != set(_SUMMARY_FIELDS):
        raise ValueError("summary response has an invalid top-level contract")
    progress = value["progress"]
    if not isinstance(progress, dict) or set(progress) != set(_PROGRESS_FIELDS):
        raise ValueError("summary response has an invalid progress contract")

    authorized = set(allowed_refs)
    used_refs: list[HistorySourceRef] = []
    normalized: dict[str, object] = {}
    for field in _SUMMARY_FIELDS:
        if field == "progress":
            normalized[field] = {
                status: _validate_summary_items(
                    progress[status], authorized, used_refs
                )
                for status in _PROGRESS_FIELDS
            }
            continue
        normalized[field] = _validate_summary_items(
            value[field], authorized, used_refs
        )

    run_outcomes: list[dict[str, object]] = []
    for state in selected_runs:
        input_ref = MessageSourceRef(state.run.run_id, state.run.input_record_id)
        if input_ref in authorized:
            run_outcomes.append({
                "run_id": state.run.run_id,
                "run_ordinal": state.run.ordinal,
                "status": state.run.status.value,
                "terminal_code": state.run.terminal_code,
                "source_refs": [input_ref.to_dict()],
            })
        if input_ref in authorized and input_ref not in used_refs:
            used_refs.append(input_ref)
    summary = {
        "trust": "untrusted_history",
        **normalized,
        "run_outcomes": run_outcomes,
    }
    return summary, tuple(used_refs)


def _validate_summary_items(
    value: object,
    authorized: set[HistorySourceRef],
    used_refs: list[HistorySourceRef],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("summary section must be a list")
    items: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _SUMMARY_ITEM_FIELDS:
            raise ValueError("summary item has an invalid shape")
        text = item["text"]
        refs_value = item["source_refs"]
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(refs_value, list)
            or not refs_value
        ):
            raise ValueError("summary item must contain text and source references")
        refs: list[HistorySourceRef] = []
        for raw_ref in refs_value:
            ref = source_ref_from_dict(raw_ref)
            if ref not in authorized or ref in refs:
                raise ValueError("summary item references an unauthorized or duplicate source")
            refs.append(ref)
            if ref not in used_refs:
                used_refs.append(ref)
        items.append({"text": text.strip(), "source_refs": [ref.to_dict() for ref in refs]})
    return items


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value
