"""Rebuild image inventory from Session Run facts and committed Panel records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ActionKind, RecordKind, RunStatus, ToolFactKind
from figura.runtime.records import (
    RunInput,
    RunState,
    SessionSnapshot,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolResultFact,
)
from figura.tools import ToolOutcome
from figura.tools.contracts import ToolExecutionError, freeze_json_value

from figura.sources.models import PanelRecord
from figura.sources.panels import FiguraPanelService


_MEASUREMENT_TOOL_NAMES = frozenset({"measure_bars", "measure_lines", "measure_scatter"})


@dataclass(frozen=True)
class AvailableAttachment:
    attachment_id: str
    filename: str


@dataclass(frozen=True)
class MeasurementObservation:
    run_id: str
    call_id: str
    attempt_id: str
    tool_name: str
    source_kind: Literal["attachment", "panel"]
    source_id: str
    outcome: ToolOutcome
    result: Mapping[str, object] | None = None
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        if self.outcome is ToolOutcome.SUCCEEDED:
            if not isinstance(self.result, Mapping) or self.error is not None:
                raise ValueError("successful measurement must contain only a result")
            object.__setattr__(self, "result", freeze_json_value(self.result))
        elif self.result is not None or not isinstance(self.error, ToolExecutionError):
            raise ValueError("failed measurement must contain only a structured error")


@dataclass(frozen=True)
class RunExecutionState:
    run_id: str
    available_attachments: tuple[AvailableAttachment, ...]
    panels: tuple[PanelRecord, ...]
    measurements: tuple[MeasurementObservation, ...]


class RunExecutionStateService:
    __slots__ = ("_coordinator", "_panels")

    def __init__(self, coordinator: RunCoordinator, panels: FiguraPanelService) -> None:
        if not isinstance(coordinator, RunCoordinator) or not isinstance(panels, FiguraPanelService):
            raise TypeError("invalid RunExecutionState dependencies")
        object.__setattr__(self, "_coordinator", coordinator)
        object.__setattr__(self, "_panels", panels)

    def for_run(self, session_id: str, run_id: str) -> RunExecutionState:
        current = self._coordinator.read_run_state(session_id, run_id)
        prior = self._coordinator.read_prior_run_states(session_id, run_id)
        return self.build(current, prior)

    def build(
        self,
        current: RunState,
        prior: tuple[RunState, ...],
    ) -> RunExecutionState:
        if not isinstance(current, RunState) or not isinstance(prior, tuple):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if tuple(state.run.ordinal for state in prior) != tuple(range(1, current.run.ordinal)):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if any(
            state.run.session_id != current.run.session_id or state.run.status is RunStatus.RUNNING
            for state in prior
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        input_states = (*prior, current)
        snapshot = self._coordinator.read_session_snapshot(current.run.session_id)
        session_state = next(
            (state for state in snapshot.run_states if state.run.run_id == current.run.run_id),
            None,
        )
        if session_state is None or session_state.run.session_id != current.run.session_id:
            raise RunError(RunErrorCode.RUN_NOT_FOUND)

        attachment_by_id = {item.attachment_id: item for item in snapshot.attachments}
        seen: set[str] = set()
        available: list[AvailableAttachment] = []
        for state in input_states:
            run_input = _run_input(state)
            for attachment_id in run_input.attachment_ids:
                if attachment_id in seen:
                    continue
                metadata = attachment_by_id.get(attachment_id)
                if metadata is None:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                seen.add(attachment_id)
                available.append(AvailableAttachment(attachment_id, metadata.filename))

        committed_panels = _committed_panels(snapshot, self._panels.list(current.run.session_id))
        measurements = _committed_measurements(
            snapshot,
            current.run.session_id,
            current.run.ordinal,
            frozenset(seen),
            frozenset(record.panel_id for record in committed_panels),
        )
        return RunExecutionState(
            current.run.run_id,
            tuple(available),
            committed_panels,
            measurements,
        )

    def list_session_panels(self, session_id: str) -> tuple[PanelRecord, ...]:
        snapshot = self._coordinator.read_session_snapshot(session_id)
        return _committed_panels(snapshot, self._panels.list(session_id))

    def resolve_panel(self, session_id: str, panel_id: str):
        return self._panels.resolve(session_id, panel_id)


def _run_input(state: RunState) -> RunInput:
    record = next(
        (item for item in state.records if item.record_id == state.run.input_record_id),
        None,
    )
    if record is None or not isinstance(record.payload, RunInput):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return record.payload


def _committed_panels(
    snapshot: SessionSnapshot,
    records: tuple[PanelRecord, ...],
) -> tuple[PanelRecord, ...]:
    records_by_id = {record.panel_id: record for record in records}
    ordered: list[PanelRecord] = []
    seen: set[str] = set()
    for state in snapshot.run_states:
        calls = {
            fact.tool_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact)
        }
        for fact in state.tool_facts:
            if fact.fact_kind is not ToolFactKind.TOOL_RESULT or not isinstance(fact.payload, ToolResultFact):
                continue
            result = fact.payload
            call = calls.get(result.tool_call_sequence)
            if (
                call is None
                or call.tool_name != "decompose_chart_image"
                or result.outcome is not ToolOutcome.SUCCEEDED
            ):
                continue
            if not isinstance(result.result, Mapping) or not isinstance(result.result.get("panels"), tuple | list):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            for item in result.result["panels"]:
                if not isinstance(item, Mapping):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                panel_id, name, source_id = item.get("panel_id"), item.get("name"), item.get("source_attachment_id")
                record = records_by_id.get(panel_id) if isinstance(panel_id, str) else None
                if (
                    record is None
                    or record.panel_id in seen
                    or record.session_id != state.run.session_id
                    or record.run_id != state.run.run_id
                    or record.name != name
                    or record.source_attachment_id != source_id
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                seen.add(record.panel_id)
                ordered.append(record)
    return tuple(ordered)


def _committed_measurements(
    snapshot: SessionSnapshot,
    session_id: str,
    target_ordinal: int,
    attachment_ids: frozenset[str],
    panel_ids: frozenset[str],
) -> tuple[MeasurementObservation, ...]:
    ordered: list[tuple[int, int, int, MeasurementObservation]] = []
    for state in snapshot.run_states:
        if state.run.session_id != session_id or state.run.ordinal > target_ordinal:
            continue
        calls = {
            fact.tool_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact)
        }
        attempts: dict[int, list[ToolAttemptStartedFact]] = {}
        for fact in state.tool_facts:
            if (
                fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
                and isinstance(fact.payload, ToolAttemptStartedFact)
            ):
                attempts.setdefault(fact.payload.tool_call_sequence, []).append(fact.payload)

        for fact in state.tool_facts:
            if fact.fact_kind is not ToolFactKind.TOOL_RESULT or not isinstance(fact.payload, ToolResultFact):
                continue
            result_fact = fact.payload
            if result_fact.tool_name not in _MEASUREMENT_TOOL_NAMES:
                continue
            call = calls.get(result_fact.tool_call_sequence)
            if (
                call is None
                or call.tool_name not in _MEASUREMENT_TOOL_NAMES
                or call.call_id != result_fact.call_id
                or not any(
                    attempt.call_id == call.call_id and attempt.attempt_id == result_fact.attempt_id
                    for attempt in attempts.get(result_fact.tool_call_sequence, ())
                )
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

            source = _measurement_source(call.arguments_json)
            if source is None:
                continue
            source_kind, source_id = source
            if source_kind == "attachment" and source_id not in attachment_ids:
                continue
            if source_kind == "panel" and source_id not in panel_ids:
                continue

            if result_fact.outcome is ToolOutcome.SUCCEEDED:
                if not isinstance(result_fact.result, Mapping) or result_fact.error is not None:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if (
                    result_fact.result.get("source_kind") != source_kind
                    or result_fact.result.get("source_id") != source_id
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                observation = MeasurementObservation(
                    run_id=state.run.run_id,
                    call_id=call.call_id,
                    attempt_id=result_fact.attempt_id,
                    tool_name=call.tool_name,
                    source_kind=source_kind,
                    source_id=source_id,
                    outcome=result_fact.outcome,
                    result=result_fact.result,
                )
            else:
                if result_fact.result is not None or not isinstance(result_fact.error, ToolExecutionError):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                observation = MeasurementObservation(
                    run_id=state.run.run_id,
                    call_id=call.call_id,
                    attempt_id=result_fact.attempt_id,
                    tool_name=call.tool_name,
                    source_kind=source_kind,
                    source_id=source_id,
                    outcome=result_fact.outcome,
                    error=result_fact.error,
                )
            ordered.append((state.run.ordinal, result_fact.tool_call_sequence, call.position, observation))

    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in ordered)


def _measurement_source(arguments_json: str) -> tuple[Literal["attachment", "panel"], str] | None:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate measurement argument")
            result[key] = value
        return result

    try:
        arguments = json.loads(arguments_json, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None
    if not isinstance(arguments, dict):
        return None
    kind, source_id = arguments.get("source_kind"), arguments.get("source_id")
    if (
        not isinstance(kind, str)
        or kind not in {"attachment", "panel"}
        or not isinstance(source_id, str)
        or not source_id
        or len(source_id) > 128
    ):
        return None
    return kind, source_id
