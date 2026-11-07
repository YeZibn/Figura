"""Rebuild exact repeated OCR/measurement observations from committed Run facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.records import RunState
from figura.shared.json_schema import JsonValueError, canonical_json_dumps
from figura.shared.source_refs import ToolResultSourceRef
from figura.tools.contracts import ToolOutcome

from .execution_state import _parse_object, _tool_facts, _validate_failure, _validate_result_identity


_ELIGIBLE_TOOLS = frozenset({"extract_text", "measure_chart"})


@dataclass(frozen=True)
class RepeatedObservationNotice:
    """A prompt-safe summary of one repeated latest observation group."""

    tool_name: str
    matching_call_count: int
    recent_result_refs: tuple[ToolResultSourceRef, ToolResultSourceRef]
    latest_result_sequence: int

    def to_prompt_value(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "matching_call_count": self.matching_call_count,
            "recent_result_refs": [ref.to_dict() for ref in self.recent_result_refs],
        }


@dataclass(frozen=True)
class _ObservationCall:
    result_ref: ToolResultSourceRef
    tool_sequence: int


def project_repeated_observations(state: RunState) -> tuple[RepeatedObservationNotice, ...]:
    """Project matching successful logical calls; never alter or replace their facts."""
    if not isinstance(state, RunState):
        raise TypeError("state must be a RunState")

    calls, attempts, results = _tool_facts(state)
    by_action: dict[tuple[str, str, str], dict[str, list[_ObservationCall]]] = {}
    latest_by_action: dict[tuple[str, str, str], str] = {}

    for sequence, call in sorted(calls.items()):
        if call.tool_name not in _ELIGIBLE_TOOLS:
            continue
        result = results.get(sequence)
        if result is None:
            continue
        _validate_result_identity(call, result, attempts.get(sequence, ()))
        if result.outcome is ToolOutcome.FAILED:
            _validate_failure(result)
            continue
        if result.outcome is not ToolOutcome.SUCCEEDED:
            continue
        if result.error is not None or not isinstance(result.result, Mapping):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        arguments = _parse_object(call.arguments_json)
        if arguments is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            action_key = (
                call.tool_name,
                call.registry_version,
                canonical_json_dumps(arguments),
            )
            observation_key = canonical_json_dumps(result.result)
        except (JsonValueError, TypeError, ValueError, RecursionError, OverflowError):
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None

        observation_calls = by_action.setdefault(action_key, {}).setdefault(observation_key, [])
        observation_calls.append(
            _ObservationCall(
                ToolResultSourceRef(state.run.run_id, call.call_id),
                sequence,
            )
        )
        latest_by_action[action_key] = observation_key

    notices: list[RepeatedObservationNotice] = []
    for action_key, observations in by_action.items():
        latest_observation = latest_by_action[action_key]
        matching = observations[latest_observation]
        if len(matching) < 2:
            continue
        notices.append(
            RepeatedObservationNotice(
                tool_name=action_key[0],
                matching_call_count=len(matching),
                recent_result_refs=(matching[-2].result_ref, matching[-1].result_ref),
                latest_result_sequence=matching[-1].tool_sequence,
            )
        )

    notices.sort(key=lambda notice: notice.latest_result_sequence)
    return tuple(notices)


def encode_repeated_observations(
    notices: tuple[RepeatedObservationNotice, ...],
) -> str:
    """Serialize prompt-safe notice metadata deterministically."""
    return canonical_json_dumps([notice.to_prompt_value() for notice in notices])

