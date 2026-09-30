from __future__ import annotations

from dataclasses import fields

import pytest

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import (
    AttachmentContent,
    ChartFigureContent,
    ChartFigureResult,
    ChartRenderContent,
    ExecutionResource,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.charts.chartfigure import chart_figure_digest, parse_chart_figure
from figura.runtime.errors import RunError, RunErrorCode
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.runtime.store import FiguraRunStore
from figura.tools import ToolOutcome
from figura.tools.contracts import ToolExecutionError


def _figure():
    return parse_chart_figure(
        {
            "schema_version": 1,
            "title": "Figure",
            "layout": {"columns": 1},
            "charts": [
                {
                    "chart_id": "share",
                    "chart_spec": {
                        "schema_version": 1,
                        "metadata": {"chart_type": "pie", "title": "Share"},
                        "axes": None,
                        "dataset": [{"category": "A", "value": 1}],
                    },
                }
            ],
        }
    )


def test_run_execution_state_owns_only_ordered_typed_resources() -> None:
    attachment_ref = ImageResourceRef("attachment", "attachment-1")
    measurement_ref = ToolResourceRef("measurement", "run-1", "measure-1")
    attachment = ExecutionResource(
        attachment_ref,
        AttachmentContent("session-1", "chart.png", "image/png", 12, "2026-01-01T00:00:00Z"),
    )
    measurement = ExecutionResource(
        measurement_ref,
        MeasurementContent(
            "attempt-1",
            "measure_bars",
            attachment_ref,
            None,
            ToolOutcome.SUCCEEDED,
            result={"bars": [{"id": "bar-1"}]},
        ),
    )
    state = RunExecutionState("run-1", (attachment, measurement))

    assert tuple(field.name for field in fields(RunExecutionState)) == ("run_id", "resources")
    assert tuple(field.name for field in fields(ExecutionResource)) == ("ref", "content")
    assert state.list() == (attachment, measurement)
    assert state.list("measurement") == (measurement,)
    assert state.get(measurement_ref) is measurement
    with pytest.raises(RunError) as missing:
        state.get(ToolResourceRef("ocr", "run-1", "missing"))
    assert missing.value.code is RunErrorCode.RUN_NOT_FOUND


def test_resource_catalog_rejects_duplicate_references_and_content_kind_mismatch() -> None:
    ref = ImageResourceRef("attachment", "attachment-1")
    resource = ExecutionResource(
        ref,
        AttachmentContent("session-1", "chart.png", "image/png", 12, "2026-01-01T00:00:00Z"),
    )

    with pytest.raises(ValueError, match="references must be unique"):
        RunExecutionState("run-1", (resource, resource))
    with pytest.raises(ValueError, match="kinds do not match"):
        ExecutionResource(ref, OcrContent("attempt-1", None, None, ToolOutcome.FAILED, error=ToolExecutionError(
            "source_unavailable", "图像不可用。", False
        )))


def test_observation_results_and_scope_are_deeply_immutable() -> None:
    source_ref = ImageResourceRef("attachment", "attachment-1")
    source = {"include": [{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}]}
    result = {"snippets": [{"text": "Label"}]}
    content = OcrContent(
        "attempt-1",
        source_ref,
        source,
        ToolOutcome.SUCCEEDED,
        result=result,
    )
    source["include"][0]["x"] = 999
    result["snippets"][0]["text"] = "changed"

    assert content.observation_scope["include"][0]["x"] == 1
    assert content.result["snippets"][0]["text"] == "Label"
    with pytest.raises(TypeError):
        content.result["snippets"][0]["text"] = "changed again"


def test_resources_require_exclusive_outcomes_and_valid_figure_links() -> None:
    source_ref = ImageResourceRef("attachment", "attachment-1")
    error = ToolExecutionError("observation_failed", "无法观察图像。", False)
    with pytest.raises(ValueError, match="only a result"):
        OcrContent("attempt-1", source_ref, None, ToolOutcome.SUCCEEDED, error=error)
    with pytest.raises(ValueError, match="only a structured error"):
        MeasurementContent("attempt-1", "measure_bars", source_ref, None, ToolOutcome.FAILED, result={})
    with pytest.raises(ValueError, match="source reference"):
        OcrContent("attempt-1", None, None, ToolOutcome.SUCCEEDED, result={})
    with pytest.raises(ValueError, match="figure_ref"):
        ChartRenderContent(
            "attempt-1",
            ToolResourceRef("measurement", "run-1", "measure-1"),
            ToolOutcome.FAILED,
            error=error,
        )


def test_chart_figure_resource_validates_its_committed_digest() -> None:
    figure = _figure()
    digest = chart_figure_digest(figure)
    content = ChartFigureContent(
        "attempt-1",
        ToolOutcome.SUCCEEDED,
        result=ChartFigureResult(figure, digest),
    )
    assert content.result.figure_digest == digest
    with pytest.raises(ValueError, match="invalid ChartFigure resource result"):
        ChartFigureResult(figure, "0" * 64)


def test_chart_figure_image_read_requires_explicit_render(tmp_path) -> None:
    store = FiguraRunStore(tmp_path)
    repository = SourcesRepository(store.database)
    attachments = FiguraAttachmentService(repository, store.data_root)
    panels = FiguraPanelService(repository, store.data_root, attachments)
    reader = RunExecutionImageReader(attachments, panels)
    figure = _figure()
    ref = ToolResourceRef("chart_figure", "run-1", "figure-1")
    content = ChartFigureContent(
        "attempt-1",
        ToolOutcome.SUCCEEDED,
        result=ChartFigureResult(figure, chart_figure_digest(figure)),
    )
    state = RunExecutionState("run-1", (ExecutionResource(ref, content),))

    with pytest.raises(RunError) as error:
        reader.read("session-1", state, ref)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
