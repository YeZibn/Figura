"""Rebuild image inventory from Session Run facts and committed Panel records."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from figura.charts.chartfigure.limits import MAX_CHART_FIGURE_ITEMS
from figura.charts.chartspec import ChartType
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
from figura.shared.image_limits import MAX_IMAGE_BYTES

from figura.sources.models import PanelRecord
from figura.sources.panels import FiguraPanelService


_MEASUREMENT_TOOL_NAMES = frozenset({"measure_bars", "measure_lines", "measure_scatter", "measure_pie"})


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
class ChartFigureReference:
    run_id: str
    call_id: str


@dataclass(frozen=True)
class ChartSummary:
    chart_id: str
    chart_type: ChartType
    title: str


@dataclass(frozen=True)
class ChartFigureSummary:
    figure_ref: ChartFigureReference
    figure_digest: str
    title: str
    charts: tuple[ChartSummary, ...]


@dataclass(frozen=True)
class ChartRenderObservation:
    run_id: str
    call_id: str
    attempt_id: str
    figure_ref: ChartFigureReference
    outcome: ToolOutcome
    result: Mapping[str, object] | None = None
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        if self.outcome is ToolOutcome.SUCCEEDED:
            if not isinstance(self.result, Mapping) or self.error is not None:
                raise ValueError("successful render must contain only a result")
            object.__setattr__(self, "result", freeze_json_value(self.result))
        elif self.result is not None or not isinstance(self.error, ToolExecutionError):
            raise ValueError("failed render must contain only a structured error")


@dataclass(frozen=True)
class RunExecutionState:
    run_id: str
    available_attachments: tuple[AvailableAttachment, ...]
    panels: tuple[PanelRecord, ...]
    measurements: tuple[MeasurementObservation, ...]
    chart_figures: tuple[ChartFigureSummary, ...]
    chart_renders: tuple[ChartRenderObservation, ...]


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
        chart_figures = _committed_chart_figures(
            snapshot,
            current.run.session_id,
            current.run.ordinal,
        )
        chart_renders = _committed_chart_renders(
            snapshot,
            current.run.session_id,
            current.run.ordinal,
            {item.figure_ref: item.figure_digest for item in chart_figures},
        )
        return RunExecutionState(
            current.run.run_id,
            tuple(available),
            committed_panels,
            measurements,
            chart_figures,
            chart_renders,
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


def _committed_chart_figures(
    snapshot: SessionSnapshot,
    session_id: str,
    target_ordinal: int,
) -> tuple[ChartFigureSummary, ...]:
    ordered: list[tuple[int, int, int, ChartFigureSummary]] = []
    for state in snapshot.run_states:
        if state.run.session_id != session_id or state.run.ordinal > target_ordinal:
            continue
        calls = {
            fact.tool_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact)
        }
        results = {
            fact.payload.tool_call_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact)
        }
        attempts: dict[int, list[ToolAttemptStartedFact]] = {}
        for fact in state.tool_facts:
            if (
                fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
                and isinstance(fact.payload, ToolAttemptStartedFact)
            ):
                attempts.setdefault(fact.payload.tool_call_sequence, []).append(fact.payload)

        for sequence, call in calls.items():
            if call.tool_name != "assemble_chart_figure":
                continue
            result = results.get(sequence)
            if result is None:
                continue
            if result.tool_name != call.tool_name or result.call_id != call.call_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if not any(
                attempt.attempt_id == result.attempt_id and attempt.call_id == call.call_id
                for attempt in attempts.get(sequence, ())
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if result.outcome is not ToolOutcome.SUCCEEDED:
                continue
            summary = _chart_figure_summary(result.result, state.run.run_id, call.call_id)
            ordered.append((state.run.ordinal, sequence, call.position, summary))

    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in ordered)


def _chart_figure_summary(
    result: Mapping[str, object] | None,
    run_id: str,
    call_id: str,
) -> ChartFigureSummary:
    if not isinstance(result, Mapping) or set(result) != {
        "figure_ref",
        "figure_digest",
        "title",
        "charts",
    }:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    reference = result["figure_ref"]
    digest = result["figure_digest"]
    title = result["title"]
    raw_charts = result["charts"]
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"run_id", "call_id"}
        or reference.get("run_id") != run_id
        or reference.get("call_id") != call_id
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(title, str)
        or len(title) > 160
        or not isinstance(raw_charts, (tuple, list))
        or not 1 <= len(raw_charts) <= MAX_CHART_FIGURE_ITEMS
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    charts: list[ChartSummary] = []
    seen_ids: set[str] = set()
    for item in raw_charts:
        if not isinstance(item, Mapping) or set(item) != {"chart_id", "chart_type", "title"}:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        chart_id, raw_chart_type, chart_title = (
            item.get("chart_id"),
            item.get("chart_type"),
            item.get("title"),
        )
        if (
            not isinstance(chart_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", chart_id) is None
            or chart_id in seen_ids
            or not isinstance(raw_chart_type, str)
            or not isinstance(chart_title, str)
            or len(chart_title) > 160
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            chart_type = ChartType(raw_chart_type)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        seen_ids.add(chart_id)
        charts.append(ChartSummary(chart_id, chart_type, chart_title))

    return ChartFigureSummary(
        ChartFigureReference(run_id, call_id),
        digest,
        title,
        tuple(charts),
    )


def _committed_chart_renders(
    snapshot: SessionSnapshot,
    session_id: str,
    target_ordinal: int,
    accepted_figure_digests: Mapping[ChartFigureReference, str],
) -> tuple[ChartRenderObservation, ...]:
    ordered: list[tuple[int, int, int, ChartRenderObservation]] = []
    for state in snapshot.run_states:
        if state.run.session_id != session_id or state.run.ordinal > target_ordinal:
            continue
        calls = {
            fact.tool_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact)
        }
        results = {
            fact.payload.tool_call_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact)
        }
        attempts: dict[int, list[ToolAttemptStartedFact]] = {}
        for fact in state.tool_facts:
            if (
                fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
                and isinstance(fact.payload, ToolAttemptStartedFact)
            ):
                attempts.setdefault(fact.payload.tool_call_sequence, []).append(fact.payload)

        for sequence, call in calls.items():
            if call.tool_name != "render_chart_figure":
                continue
            result = results.get(sequence)
            if result is None:
                continue
            if result.tool_name != call.tool_name or result.call_id != call.call_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if not any(
                attempt.attempt_id == result.attempt_id and attempt.call_id == call.call_id
                for attempt in attempts.get(sequence, ())
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

            figure_ref = _render_figure_reference(call.arguments_json)
            if figure_ref is None or figure_ref not in accepted_figure_digests:
                continue

            if result.outcome is ToolOutcome.SUCCEEDED:
                parsed_result = _chart_render_result(result.result)
                if (
                    parsed_result is None
                    or parsed_result[0] != figure_ref
                    or parsed_result[1]["figure_digest"] != accepted_figure_digests[figure_ref]
                    or result.error is not None
                ):
                    continue
                observation = ChartRenderObservation(
                    run_id=state.run.run_id,
                    call_id=call.call_id,
                    attempt_id=result.attempt_id,
                    figure_ref=figure_ref,
                    outcome=result.outcome,
                    result=parsed_result[1],
                )
            else:
                if result.result is not None or not isinstance(result.error, ToolExecutionError):
                    continue
                observation = ChartRenderObservation(
                    run_id=state.run.run_id,
                    call_id=call.call_id,
                    attempt_id=result.attempt_id,
                    figure_ref=figure_ref,
                    outcome=result.outcome,
                    error=result.error,
                )
            ordered.append((state.run.ordinal, sequence, call.position, observation))

    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in ordered)


def _render_figure_reference(arguments_json: str) -> ChartFigureReference | None:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate render argument")
            result[key] = value
        return result

    try:
        arguments = json.loads(arguments_json, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None
    if not isinstance(arguments, dict) or set(arguments) != {"figure_ref"}:
        return None
    reference = arguments["figure_ref"]
    if (
        not isinstance(reference, dict)
        or set(reference) != {"run_id", "call_id"}
        or not isinstance(reference.get("run_id"), str)
        or not reference["run_id"]
        or not isinstance(reference.get("call_id"), str)
        or not reference["call_id"]
    ):
        return None
    return ChartFigureReference(reference["run_id"], reference["call_id"])


def _chart_render_result(
    result: Mapping[str, object] | None,
) -> tuple[ChartFigureReference, Mapping[str, object]] | None:
    if not isinstance(result, Mapping) or set(result) != {
        "figure_ref",
        "figure_digest",
        "image_sha256",
        "media_type",
        "byte_count",
        "width",
        "height",
    }:
        return None
    raw_reference = result.get("figure_ref")
    figure_digest = result.get("figure_digest")
    image_sha256 = result.get("image_sha256")
    byte_count = result.get("byte_count")
    width = result.get("width")
    height = result.get("height")
    if (
        not isinstance(raw_reference, Mapping)
        or set(raw_reference) != {"run_id", "call_id"}
        or not isinstance(raw_reference.get("run_id"), str)
        or not isinstance(raw_reference.get("call_id"), str)
        or not isinstance(figure_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", figure_digest) is None
        or not isinstance(image_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", image_sha256) is None
        or result.get("media_type") != "image/png"
        or type(byte_count) is not int
        or not 1 <= byte_count <= MAX_IMAGE_BYTES
        or type(width) is not int
        or type(height) is not int
        or width <= 0
        or height <= 0
    ):
        return None
    reference = ChartFigureReference(raw_reference["run_id"], raw_reference["call_id"])
    projected = {key: value for key, value in result.items() if key != "figure_ref"}
    return reference, projected


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
