"""Pure selection and response validation for Session context compaction."""

from __future__ import annotations

import json
from figura.providers import FinishReason, ProviderId, ProviderResponse
from figura.runtime.models import RunStatus
from figura.runtime.records import RunState
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


def eligible_compaction_runs(
    prior_run_states: tuple[RunState, ...],
    checkpoint_ordinal: int,
) -> tuple[RunState, ...]:
    """Select a contiguous completed prefix while retaining the newest Run raw."""
    if type(checkpoint_ordinal) is not int or checkpoint_ordinal < 0:
        return ()
    if len(prior_run_states) < 2:
        return ()
    protected_ordinal = prior_run_states[-1].run.ordinal
    selected: list[RunState] = []
    for state in prior_run_states:
        if state.run.ordinal <= checkpoint_ordinal or state.run.ordinal >= protected_ordinal:
            continue
        if state.run.status is not RunStatus.COMPLETED:
            break
        selected.append(state)
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
        if input_ref not in authorized:
            raise ValueError("selected Run input reference is missing")
        run_outcomes.append({
            "run_id": state.run.run_id,
            "run_ordinal": state.run.ordinal,
            "status": state.run.status.value,
            "terminal_code": state.run.terminal_code,
            "source_refs": [input_ref.to_dict()],
        })
        if input_ref not in used_refs:
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
