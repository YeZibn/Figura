"""Rebuild image inventory from Session Run facts and committed Panel records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ActionKind, RecordKind, RunStatus, ToolFactKind
from figura.runtime.records import (
    RunInput,
    RunState,
    SessionSnapshot,
    ToolCallFact,
    ToolResultFact,
)
from figura.tools import ToolOutcome

from figura.sources.models import PanelRecord
from figura.sources.panels import FiguraPanelService


@dataclass(frozen=True)
class AvailableAttachment:
    attachment_id: str
    filename: str


@dataclass(frozen=True)
class RunExecutionState:
    run_id: str
    available_attachments: tuple[AvailableAttachment, ...]
    panels: tuple[PanelRecord, ...]


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
        return RunExecutionState(current.run.run_id, tuple(available), committed_panels)

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
            if call is None or call.tool_name != "decompose_chart_image" or result.outcome is not ToolOutcome.SUCCEEDED:
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


def latest_loaded_images(state: RunState) -> tuple[tuple[str, str, str], ...]:
    """Return distinct successful image loads from the latest committed tool batch."""
    if state.checkpoint.next_action is None or state.checkpoint.next_action.action_kind is not ActionKind.MODEL:
        raise RunError(RunErrorCode.INVALID_TRANSITION)
    response_id = next(
        (record.record_id for record in reversed(state.records) if record.record_kind is RecordKind.MODEL_RESPONSE),
        None,
    )
    if response_id is None:
        return ()
    calls = sorted(
        (
            (fact.tool_sequence, fact.payload)
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_CALL
            and isinstance(fact.payload, ToolCallFact)
            and fact.payload.response_record_id == response_id
        ),
        key=lambda pair: pair[1].position,
    )
    results = {
        fact.payload.tool_call_sequence: fact.payload
        for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact)
    }
    loaded: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for call_sequence, call in calls:
        if call.tool_name != "load_image":
            continue
        result = results.get(call_sequence)
        if result is None or result.outcome is not ToolOutcome.SUCCEEDED or not isinstance(result.result, Mapping):
            continue
        kind, source_id, name = result.result.get("source_kind"), result.result.get("source_id"), result.result.get("name")
        if not isinstance(kind, str) or kind not in {"attachment", "panel"} or not isinstance(source_id, str) or not isinstance(name, str):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        identity = (kind, source_id)
        if identity not in seen:
            seen.add(identity)
            loaded.append((kind, source_id, name))
    return tuple(loaded)
