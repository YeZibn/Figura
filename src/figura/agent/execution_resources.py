"""Immutable, typed resources exposed to one Figura Run execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from figura.charts.chartfigure import ChartFigure, chart_figure_digest
from figura.runtime.errors import RunError, RunErrorCode
from figura.sources.models import PanelPoint
from figura.tools import ToolOutcome
from figura.tools.contracts import ToolExecutionError, freeze_json_value
from figura.tools.measurements.contracts import validate_measurement_result


ImageResourceKind: TypeAlias = Literal["attachment", "panel"]
ToolResourceKind: TypeAlias = Literal["ocr", "measurement", "chart_figure", "chart_render"]
ResourceKind: TypeAlias = ImageResourceKind | ToolResourceKind
_MEASUREMENT_TOOL_NAMES = frozenset({"measure_chart"})


@dataclass(frozen=True)
class ImageResourceRef:
    kind: ImageResourceKind
    id: str

    def __post_init__(self) -> None:
        if self.kind not in {"attachment", "panel"} or not _nonempty(self.id):
            raise ValueError("invalid image resource reference")


@dataclass(frozen=True)
class ToolResourceRef:
    kind: ToolResourceKind
    run_id: str
    call_id: str

    def __post_init__(self) -> None:
        if (
            self.kind not in {"ocr", "measurement", "chart_figure", "chart_render"}
            or not _nonempty(self.run_id)
            or not _nonempty(self.call_id)
        ):
            raise ValueError("invalid tool resource reference")


ResourceRef: TypeAlias = ImageResourceRef | ToolResourceRef


@dataclass(frozen=True)
class AttachmentContent:
    session_id: str
    filename: str
    media_type: str
    byte_count: int
    created_at: str

    def __post_init__(self) -> None:
        if (
            not _nonempty(self.session_id)
            or not _nonempty(self.filename)
            or not _nonempty(self.media_type)
            or type(self.byte_count) is not int
            or self.byte_count < 1
            or not _nonempty(self.created_at)
        ):
            raise ValueError("invalid Attachment resource content")


@dataclass(frozen=True)
class PanelContent:
    session_id: str
    run_id: str
    source_attachment_id: str
    name: str
    points: tuple[PanelPoint, ...]

    def __post_init__(self) -> None:
        if (
            not _nonempty(self.session_id)
            or not _nonempty(self.run_id)
            or not _nonempty(self.source_attachment_id)
            or not _nonempty(self.name)
        ):
            raise ValueError("invalid Panel resource content")
        if isinstance(self.points, list):
            object.__setattr__(self, "points", tuple(self.points))
        if not isinstance(self.points, tuple) or any(not isinstance(point, PanelPoint) for point in self.points):
            raise ValueError("Panel resource points must be immutable PanelPoint values")


@dataclass(frozen=True)
class OcrContent:
    attempt_id: str
    source_ref: ImageResourceRef | None
    observation_scope: Mapping[str, object] | None
    outcome: ToolOutcome
    result: Mapping[str, object] | None = field(default=None, repr=False)
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_observation(self.attempt_id, self.source_ref, self.outcome, self.result, self.error)
        if self.outcome is ToolOutcome.SUCCEEDED and self.source_ref is None:
            raise ValueError("successful OCR resource must have a source reference")
        object.__setattr__(self, "observation_scope", _freeze_optional_mapping(self.observation_scope))
        if self.result is not None:
            object.__setattr__(self, "result", _freeze_mapping(self.result, "OCR result"))


@dataclass(frozen=True)
class MeasurementContent:
    attempt_id: str
    tool_name: str
    source_ref: ImageResourceRef | None
    observation_scope: Mapping[str, object] | None
    outcome: ToolOutcome
    result: Mapping[str, object] | None = field(default=None, repr=False)
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_observation(self.attempt_id, self.source_ref, self.outcome, self.result, self.error)
        if self.tool_name not in _MEASUREMENT_TOOL_NAMES:
            raise ValueError("measurement resource tool_name is invalid")
        if self.outcome is ToolOutcome.SUCCEEDED and self.source_ref is None:
            raise ValueError("successful measurement resource must have a source reference")
        object.__setattr__(self, "observation_scope", _freeze_optional_mapping(self.observation_scope))
        if self.result is not None:
            frozen_result = _freeze_mapping(self.result, "measurement result")
            if self.outcome is ToolOutcome.SUCCEEDED:
                issue = validate_measurement_result(frozen_result)
                if (
                    issue is not None
                    or self.source_ref is None
                    or frozen_result.get("source_kind") != self.source_ref.kind
                    or frozen_result.get("source_id") != self.source_ref.id
                ):
                    raise ValueError("successful measurement resource result is invalid")
            object.__setattr__(self, "result", frozen_result)


@dataclass(frozen=True)
class ChartFigureResult:
    figure: ChartFigure
    figure_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.figure, ChartFigure)
            or not _nonempty(self.figure_digest)
            or chart_figure_digest(self.figure) != self.figure_digest
        ):
            raise ValueError("invalid ChartFigure resource result")


@dataclass(frozen=True)
class ChartFigureContent:
    attempt_id: str
    outcome: ToolOutcome
    result: ChartFigureResult | None = None
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_observation(self.attempt_id, None, self.outcome, self.result, self.error)
        if self.result is not None and not isinstance(self.result, ChartFigureResult):
            raise ValueError("ChartFigure resource result has an invalid type")


@dataclass(frozen=True)
class ChartRenderContent:
    attempt_id: str
    figure_ref: ToolResourceRef | None
    outcome: ToolOutcome
    result: Mapping[str, object] | None = field(default=None, repr=False)
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_observation(self.attempt_id, None, self.outcome, self.result, self.error)
        if self.figure_ref is not None and self.figure_ref.kind != "chart_figure":
            raise ValueError("render resource figure_ref must reference a ChartFigure")
        if self.outcome is ToolOutcome.SUCCEEDED and self.figure_ref is None:
            raise ValueError("successful render resource must have a Figure reference")
        if self.result is not None:
            object.__setattr__(self, "result", _freeze_mapping(self.result, "render result"))


ResourceContent: TypeAlias = (
    AttachmentContent
    | PanelContent
    | OcrContent
    | MeasurementContent
    | ChartFigureContent
    | ChartRenderContent
)


@dataclass(frozen=True)
class ExecutionResource:
    ref: ResourceRef
    content: ResourceContent

    def __post_init__(self) -> None:
        if not _content_matches_ref(self.ref, self.content):
            raise ValueError("resource reference and content kinds do not match")


@dataclass(frozen=True)
class RunExecutionState:
    run_id: str
    resources: tuple[ExecutionResource, ...]

    def __post_init__(self) -> None:
        if not _nonempty(self.run_id):
            raise ValueError("RunExecutionState run_id must be non-empty")
        if isinstance(self.resources, list):
            object.__setattr__(self, "resources", tuple(self.resources))
        if not isinstance(self.resources, tuple) or any(
            not isinstance(resource, ExecutionResource) for resource in self.resources
        ):
            raise ValueError("RunExecutionState resources must be an immutable resource tuple")
        refs = tuple(resource.ref for resource in self.resources)
        if len(refs) != len(set(refs)):
            raise ValueError("RunExecutionState resource references must be unique")

    def list(self, kind: ResourceKind | None = None) -> tuple[ExecutionResource, ...]:
        if kind is None:
            return self.resources
        if kind not in {"attachment", "panel", "ocr", "measurement", "chart_figure", "chart_render"}:
            raise ValueError("unknown resource kind")
        return tuple(resource for resource in self.resources if resource.ref.kind == kind)

    def get(self, ref: ResourceRef) -> ExecutionResource:
        for resource in self.resources:
            if resource.ref == ref:
                return resource
        raise RunError(RunErrorCode.RUN_NOT_FOUND)


def _content_matches_ref(ref: ResourceRef, content: ResourceContent) -> bool:
    if isinstance(ref, ImageResourceRef):
        return (ref.kind == "attachment" and isinstance(content, AttachmentContent)) or (
            ref.kind == "panel" and isinstance(content, PanelContent)
        )
    if isinstance(ref, ToolResourceRef):
        return (
            (ref.kind == "ocr" and isinstance(content, OcrContent))
            or (ref.kind == "measurement" and isinstance(content, MeasurementContent))
            or (ref.kind == "chart_figure" and isinstance(content, ChartFigureContent))
            or (ref.kind == "chart_render" and isinstance(content, ChartRenderContent))
        )
    return False


def _validate_observation(
    attempt_id: str,
    source_ref: ImageResourceRef | None,
    outcome: ToolOutcome,
    result: object | None,
    error: ToolExecutionError | None,
) -> None:
    if not _nonempty(attempt_id):
        raise ValueError("resource attempt_id must be non-empty")
    if source_ref is not None and not isinstance(source_ref, ImageResourceRef):
        raise ValueError("observation source_ref must be an image reference")
    if outcome is ToolOutcome.SUCCEEDED:
        if result is None or error is not None:
            raise ValueError("successful resource must contain only a result")
    elif outcome is ToolOutcome.FAILED:
        if result is not None or not isinstance(error, ToolExecutionError):
            raise ValueError("failed resource must contain only a structured error")
    else:
        raise ValueError("resource outcome is invalid")


def _freeze_mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    frozen = freeze_json_value(value)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return frozen


def _freeze_optional_mapping(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _freeze_mapping(value, "observation_scope")


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)
