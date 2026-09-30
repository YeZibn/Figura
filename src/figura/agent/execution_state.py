"""Reconstruct the target Run's typed resource catalog from committed facts."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

from figura.charts.chartfigure import chart_figure_digest, parse_chart_figure, validate_chart_figure
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunStatus, ToolFactKind
from figura.runtime.records import (
    RunInput,
    RunState,
    SessionSnapshot,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolResultFact,
)
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.shared.json_schema import validate_instance
from figura.sources.models import AttachmentMetadata, PanelPoint, PanelRecord
from figura.sources.panels import FiguraPanelService
from figura.tools import ToolOutcome
from figura.tools.contracts import ToolExecutionError
from figura.tools.implementations.extract_text import EXTRACT_TEXT_RESULT_SCHEMA
from figura.tools.implementations.image import DECOMPOSE_RESULT_SCHEMA
from figura.tools.implementations.measure_bars import MEASURE_BARS_RESULT_SCHEMA
from figura.tools.implementations.measure_lines import MEASURE_LINES_RESULT_SCHEMA
from figura.tools.implementations.measure_pie import MEASURE_PIE_RESULT_SCHEMA
from figura.tools.implementations.measure_scatter import MEASURE_SCATTER_RESULT_SCHEMA
from figura.tools.implementations.measurement_schema import OBSERVATION_SCOPE

from .execution_resources import (
    AttachmentContent,
    ChartFigureContent,
    ChartFigureResult,
    ChartRenderContent,
    ExecutionResource,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)


_MEASUREMENT_SCHEMAS = {
    "measure_bars": MEASURE_BARS_RESULT_SCHEMA,
    "measure_lines": MEASURE_LINES_RESULT_SCHEMA,
    "measure_scatter": MEASURE_SCATTER_RESULT_SCHEMA,
    "measure_pie": MEASURE_PIE_RESULT_SCHEMA,
}
_OBSERVATION_TOOL_NAMES = frozenset({"extract_text", *_MEASUREMENT_SCHEMAS})
_RESOURCE_TOOL_NAMES = frozenset(
    {"decompose_chart_image", "extract_text", *_MEASUREMENT_SCHEMAS, "assemble_chart_figure", "render_chart_figure"}
)
_PanelPosition = tuple[int, int, int, int]
_PanelEntry = tuple[_PanelPosition, ExecutionResource]


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

    def build(self, current: RunState, prior: tuple[RunState, ...]) -> RunExecutionState:
        if not isinstance(current, RunState) or not isinstance(prior, tuple):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if tuple(state.run.ordinal for state in prior) != tuple(range(1, current.run.ordinal)):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if any(
            state.run.session_id != current.run.session_id or state.run.status is RunStatus.RUNNING
            for state in prior
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        states = (*prior, current)
        if any(
            state.run.session_id != current.run.session_id
            or (state is not current and state.run.status is RunStatus.RUNNING)
            for state in states
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)

        snapshot = self._coordinator.read_session_snapshot(current.run.session_id)
        if not any(state.run.run_id == current.run.run_id for state in snapshot.run_states):
            raise RunError(RunErrorCode.RUN_NOT_FOUND)

        attachment_metadata = _attachment_metadata(snapshot, current.run.session_id)
        attachment_ids = _input_attachment_ids(states, attachment_metadata)
        panel_entries, panel_positions = _committed_panels(
            states,
            self._panels.list(current.run.session_id),
            attachment_ids,
        )
        panel_ids = frozenset(resource.ref.id for _, resource in panel_entries)

        resources: list[ExecutionResource] = [
            ExecutionResource(
                ImageResourceRef("attachment", attachment_id),
                AttachmentContent(
                    metadata.session_id,
                    metadata.filename,
                    metadata.media_type,
                    metadata.byte_count,
                    metadata.created_at,
                ),
            )
            for attachment_id, metadata in attachment_ids.items()
        ]
        tool_entries = _committed_tool_resources(
            states,
            attachment_ids.keys(),
            panel_ids,
            panel_positions,
        )
        resources.extend(resource for _, resource in sorted((*panel_entries, *tool_entries), key=lambda item: item[0]))
        return RunExecutionState(current.run.run_id, tuple(resources))

    def list_session_panels(self, session_id: str) -> tuple[PanelRecord, ...]:
        snapshot = self._coordinator.read_session_snapshot(session_id)
        states = tuple(state for state in snapshot.run_states if state.run.session_id == session_id)
        attachments = _attachment_metadata(snapshot, session_id)
        attachment_ids = _input_attachment_ids(states, attachments)
        entries, _positions = _committed_panels(
            states,
            self._panels.list(session_id),
            attachment_ids,
        )
        return tuple(
            PanelRecord(
                resource.ref.id,
                resource.content.session_id,
                resource.content.run_id,
                resource.content.source_attachment_id,
                resource.content.name,
                resource.content.points,
            )
            for _, resource in entries
            if isinstance(resource.ref, ImageResourceRef) and isinstance(resource.content, PanelContent)
        )


def _attachment_metadata(snapshot: SessionSnapshot, session_id: str) -> dict[str, AttachmentMetadata]:
    by_id: dict[str, AttachmentMetadata] = {}
    for item in snapshot.attachments:
        if item.session_id != session_id or item.attachment_id in by_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        by_id[item.attachment_id] = item
    return by_id


def _input_attachment_ids(
    states: tuple[RunState, ...],
    metadata_by_id: Mapping[str, AttachmentMetadata],
) -> dict[str, AttachmentMetadata]:
    ordered: dict[str, AttachmentMetadata] = {}
    for state in states:
        for attachment_id in _run_input(state).attachment_ids:
            metadata = metadata_by_id.get(attachment_id)
            if metadata is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            ordered.setdefault(attachment_id, metadata)
    return ordered


def _run_input(state: RunState) -> RunInput:
    record = next((item for item in state.records if item.record_id == state.run.input_record_id), None)
    if record is None or not isinstance(record.payload, RunInput):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return record.payload


def _committed_panels(
    states: tuple[RunState, ...],
    records: tuple[PanelRecord, ...],
    attachment_ids: Mapping[str, AttachmentMetadata],
) -> tuple[tuple[_PanelEntry, ...], dict[ImageResourceRef, _PanelPosition]]:
    records_by_id = {record.panel_id: record for record in records}
    if len(records_by_id) != len(records):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    entries: list[tuple[tuple[int, int, int, int], ExecutionResource]] = []
    positions: dict[ImageResourceRef, _PanelPosition] = {}

    for state in states:
        calls, attempts, results = _tool_facts(state)
        for sequence, call in sorted(calls.items(), key=lambda item: (item[1].position, item[0])):
            if call.tool_name != "decompose_chart_image":
                continue
            result = results.get(sequence)
            if result is None:
                continue
            _validate_result_identity(call, result, attempts.get(sequence, ()))
            if result.outcome is ToolOutcome.FAILED:
                _validate_failure(result)
                continue
            if result.error is not None or not isinstance(result.result, Mapping):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if validate_instance(result.result, DECOMPOSE_RESULT_SCHEMA) is not None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            arguments = _parse_object(call.arguments_json)
            if arguments is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attachment_id = arguments.get("attachment_id")
            proposals = arguments.get("panels")
            raw_panels = result.result.get("panels")
            if (
                not isinstance(attachment_id, str)
                or attachment_id not in attachment_ids
                or not isinstance(proposals, (tuple, list))
                or not isinstance(raw_panels, (tuple, list))
                or len(proposals) != len(raw_panels)
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            position_prefix = (state.run.ordinal, sequence, call.position)
            for item_index, (proposal, panel_fact) in enumerate(zip(proposals, raw_panels, strict=True)):
                if not isinstance(proposal, Mapping) or not isinstance(panel_fact, Mapping):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                panel_id = panel_fact.get("panel_id")
                record = records_by_id.get(panel_id) if isinstance(panel_id, str) else None
                points = _panel_points(proposal.get("points"))
                if (
                    record is None
                    or record.session_id != state.run.session_id
                    or record.run_id != state.run.run_id
                    or record.source_attachment_id != attachment_id
                    or record.name != proposal.get("name")
                    or record.points != points
                    or panel_fact.get("name") != record.name
                    or panel_fact.get("source_attachment_id") != record.source_attachment_id
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                ref = ImageResourceRef("panel", record.panel_id)
                position = (*position_prefix, item_index)
                if ref in positions:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                content = PanelContent(
                    record.session_id,
                    record.run_id,
                    record.source_attachment_id,
                    record.name,
                    record.points,
                )
                entries.append((position, ExecutionResource(ref, content)))
                positions[ref] = position

    entries.sort(key=lambda item: item[0])
    return tuple(entries), positions


def _panel_points(value: object) -> tuple[PanelPoint, ...] | None:
    if not isinstance(value, (tuple, list)) or any(not isinstance(point, Mapping) for point in value):
        return None
    try:
        return tuple(PanelPoint(point["x"], point["y"]) for point in value)
    except (KeyError, TypeError, ValueError):
        return None


def _committed_tool_resources(
    states: tuple[RunState, ...],
    attachment_ids: Iterable[str],
    panel_ids: frozenset[str],
    panel_positions: Mapping[ImageResourceRef, _PanelPosition],
) -> tuple[tuple[tuple[int, int, int, int], ExecutionResource], ...]:
    attachment_set = frozenset(attachment_ids)
    entries: list[tuple[tuple[int, int, int, int], ExecutionResource]] = []
    measurements: dict[ToolResourceRef, MeasurementContent] = {}
    figures: dict[ToolResourceRef, ChartFigureContent] = {}

    for state in states:
        calls, attempts, results = _tool_facts(state)
        for sequence, call in sorted(calls.items(), key=lambda item: (item[1].position, item[0])):
            if call.tool_name not in _RESOURCE_TOOL_NAMES:
                continue
            result_fact = results.get(sequence)
            if result_fact is None or call.tool_name == "decompose_chart_image":
                continue
            _validate_result_identity(call, result_fact, attempts.get(sequence, ()))
            prefix = (state.run.ordinal, sequence, call.position)

            if call.tool_name in _OBSERVATION_TOOL_NAMES:
                content = _observation_content(
                    call,
                    result_fact,
                    attachment_set,
                    panel_ids,
                    panel_positions,
                    prefix,
                )
                kind = "ocr" if call.tool_name == "extract_text" else "measurement"
                ref = ToolResourceRef(kind, state.run.run_id, call.call_id)
                resource = ExecutionResource(ref, content)
                entries.append(((*prefix, 0), resource))
                if isinstance(content, MeasurementContent):
                    measurements[ref] = content
                continue

            if call.tool_name == "assemble_chart_figure":
                ref = ToolResourceRef("chart_figure", state.run.run_id, call.call_id)
                content = _chart_figure_content(state.run.run_id, call, result_fact, measurements)
                resource = ExecutionResource(ref, content)
                entries.append(((*prefix, 0), resource))
                figures[ref] = content
                continue

            if call.tool_name == "render_chart_figure":
                ref = ToolResourceRef("chart_render", state.run.run_id, call.call_id)
                content = _chart_render_content(call, result_fact, figures)
                entries.append(((*prefix, 0), ExecutionResource(ref, content)))

    entries.sort(key=lambda item: item[0])
    return tuple(entries)


def _observation_content(
    call: ToolCallFact,
    result_fact: ToolResultFact,
    attachment_ids: frozenset[str],
    panel_ids: frozenset[str],
    panel_positions: Mapping[ImageResourceRef, _PanelPosition],
    call_position: tuple[int, int, int],
) -> OcrContent | MeasurementContent:
    arguments = _parse_object(call.arguments_json)
    source_ref = _source_ref(arguments)
    scope = _scope(arguments)
    authorized = _source_is_authorized(source_ref, attachment_ids, panel_ids)
    if result_fact.outcome is ToolOutcome.SUCCEEDED:
        schema = (
            EXTRACT_TEXT_RESULT_SCHEMA
            if call.tool_name == "extract_text"
            else _MEASUREMENT_SCHEMAS[call.tool_name]
        )
        if (
            result_fact.error is not None
            or not isinstance(result_fact.result, Mapping)
            or validate_instance(result_fact.result, schema) is not None
            or source_ref is None
            or not authorized
            or ("observation_scope" in (arguments or {}) and scope is None)
            or result_fact.result.get("source_kind") != source_ref.kind
            or result_fact.result.get("source_id") != source_ref.id
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if source_ref.kind == "panel":
            panel_position = panel_positions.get(source_ref)
            if panel_position is None or panel_position >= (*call_position, 0):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
    else:
        _validate_failure(result_fact)
        if "observation_scope" in (arguments or {}) and scope is None:
            scope = None

    if call.tool_name == "extract_text":
        return OcrContent(
            result_fact.attempt_id,
            source_ref,
            scope,
            result_fact.outcome,
            result=result_fact.result,
            error=result_fact.error,
        )
    return MeasurementContent(
        result_fact.attempt_id,
        call.tool_name,
        source_ref,
        scope,
        result_fact.outcome,
        result=result_fact.result,
        error=result_fact.error,
    )


def _chart_figure_content(
    run_id: str,
    call: ToolCallFact,
    result_fact: ToolResultFact,
    measurements: Mapping[ToolResourceRef, MeasurementContent],
) -> ChartFigureContent:
    if result_fact.outcome is ToolOutcome.FAILED:
        _validate_failure(result_fact)
        return ChartFigureContent(result_fact.attempt_id, result_fact.outcome, error=result_fact.error)
    if result_fact.error is not None or not isinstance(result_fact.result, Mapping):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    arguments = _parse_object(call.arguments_json)
    if arguments is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        figure = parse_chart_figure(arguments)
    except (TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    if validate_chart_figure(figure):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    digest = chart_figure_digest(figure)
    expected = {
        "figure_ref": {"run_id": run_id, "call_id": call.call_id},
        "figure_digest": digest,
        "title": figure.title,
        "charts": [
            {
                "chart_id": chart.chart_id,
                "chart_type": chart.chart_spec.metadata.chart_type.value,
                "title": chart.chart_spec.metadata.title,
            }
            for chart in figure.charts
        ],
    }
    raw_reference = result_fact.result.get("figure_ref")
    if not isinstance(raw_reference, Mapping) or set(raw_reference) != {"run_id", "call_id"}:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if (
        raw_reference.get("run_id") != run_id
        or raw_reference.get("call_id") != call.call_id
        or result_fact.result.get("figure_digest") != digest
        or set(result_fact.result) != set(expected)
        or result_fact.result.get("title") != expected["title"]
        or _plain_json(result_fact.result) != expected
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    for chart in figure.charts:
        for reference in chart.measurement_refs:
            ref = ToolResourceRef("measurement", reference.run_id, reference.call_id)
            observation = measurements.get(ref)
            if observation is None or observation.outcome is not ToolOutcome.SUCCEEDED:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return ChartFigureContent(
        result_fact.attempt_id,
        result_fact.outcome,
        result=ChartFigureResult(figure, digest),
    )


def _chart_render_content(
    call: ToolCallFact,
    result_fact: ToolResultFact,
    figures: Mapping[ToolResourceRef, ChartFigureContent],
) -> ChartRenderContent:
    arguments = _parse_object(call.arguments_json)
    raw_reference = arguments.get("figure_ref") if arguments is not None else None
    figure_ref = _figure_ref(raw_reference)
    if result_fact.outcome is ToolOutcome.FAILED:
        _validate_failure(result_fact)
        return ChartRenderContent(
            result_fact.attempt_id,
            figure_ref,
            result_fact.outcome,
            error=result_fact.error,
        )
    if result_fact.error is not None or not isinstance(result_fact.result, Mapping) or figure_ref is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    figure = figures.get(figure_ref)
    if figure is None or figure.result is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    result = result_fact.result
    raw_result_ref = result.get("figure_ref")
    if (
        not isinstance(raw_result_ref, Mapping)
        or dict(raw_result_ref) != {"run_id": figure_ref.run_id, "call_id": figure_ref.call_id}
        or result.get("figure_digest") != figure.result.figure_digest
        or result.get("media_type") != "image/png"
        or not _digest(result.get("image_sha256"))
        or type(result.get("byte_count")) is not int
        or not 1 <= result["byte_count"] <= MAX_IMAGE_BYTES
        or type(result.get("width")) is not int
        or type(result.get("height")) is not int
        or not 1 <= result["width"] <= 1280
        or not 1 <= result["height"] <= 1962
        or set(result)
        != {"figure_ref", "figure_digest", "image_sha256", "media_type", "byte_count", "width", "height"}
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    metadata = {key: value for key, value in result.items() if key != "figure_ref"}
    return ChartRenderContent(result_fact.attempt_id, figure_ref, result_fact.outcome, result=metadata)


def _tool_facts(
    state: RunState,
) -> tuple[dict[int, ToolCallFact], dict[int, tuple[ToolAttemptStartedFact, ...]], dict[int, ToolResultFact]]:
    calls: dict[int, ToolCallFact] = {}
    attempts: dict[int, list[ToolAttemptStartedFact]] = {}
    results: dict[int, ToolResultFact] = {}
    for fact in state.tool_facts:
        if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact):
            if fact.tool_sequence in calls:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            calls[fact.tool_sequence] = fact.payload
        elif fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED and isinstance(
            fact.payload, ToolAttemptStartedFact
        ):
            attempts.setdefault(fact.payload.tool_call_sequence, []).append(fact.payload)
        elif fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact):
            if fact.payload.tool_call_sequence in results:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            results[fact.payload.tool_call_sequence] = fact.payload
    return calls, {key: tuple(value) for key, value in attempts.items()}, results


def _validate_result_identity(
    call: ToolCallFact,
    result: ToolResultFact,
    attempts: tuple[ToolAttemptStartedFact, ...],
) -> None:
    if (
        call.tool_name != result.tool_name
        or call.call_id != result.call_id
        or not any(attempt.call_id == call.call_id and attempt.attempt_id == result.attempt_id for attempt in attempts)
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _validate_failure(result: ToolResultFact) -> None:
    if result.result is not None or not isinstance(result.error, ToolExecutionError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _parse_object(value: str) -> Mapping[str, object] | None:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _source_ref(arguments: Mapping[str, object] | None) -> ImageResourceRef | None:
    if arguments is None:
        return None
    kind, source_id = arguments.get("source_kind"), arguments.get("source_id")
    if (
        not isinstance(kind, str)
        or kind not in {"attachment", "panel"}
        or not isinstance(source_id, str)
        or not source_id
    ):
        return None
    return ImageResourceRef(kind, source_id)


def _scope(arguments: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if arguments is None or "observation_scope" not in arguments:
        return None
    value = arguments["observation_scope"]
    if not isinstance(value, Mapping) or validate_instance(value, OBSERVATION_SCOPE) is not None:
        return None
    return value


def _source_is_authorized(
    ref: ImageResourceRef | None,
    attachment_ids: frozenset[str],
    panel_ids: frozenset[str],
) -> bool:
    if ref is None:
        return False
    if ref.kind == "attachment":
        return ref.id in attachment_ids
    return ref.id in panel_ids


def _figure_ref(value: object) -> ToolResourceRef | None:
    if not isinstance(value, Mapping) or set(value) != {"run_id", "call_id"}:
        return None
    run_id, call_id = value.get("run_id"), value.get("call_id")
    if not isinstance(run_id, str) or not run_id or not isinstance(call_id, str) or not call_id:
        return None
    return ToolResourceRef("chart_figure", run_id, call_id)


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value
