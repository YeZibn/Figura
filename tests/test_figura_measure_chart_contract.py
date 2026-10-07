from __future__ import annotations

import json

import numpy as np
import pytest

from figura.charts.chartspec.models import ChartType
from figura.tools import ToolContext, ToolInvocation, ToolOutcome, ToolRegistry, ToolRuntime
from figura.tools.implementations import measure_chart as measure_chart_module
from figura.tools.implementations.measure_chart import (
    MEASURE_CHART_PARAMETERS_SCHEMA,
    measure_chart_definition,
)
from figura.tools.implementations.measurement_source import MeasurementSource
from figura.tools.measurements.contracts import (
    MEASUREMENT_RESULT_SCHEMA,
    MeasurementResult,
    MeasurementSensorResult,
    validate_measurement_result,
)
from figura.shared.json_schema import validate_instance, validate_schema_definition


def _axis() -> dict[str, object]:
    return {
        "kind": "numeric",
        "label_text": None,
        "label_confidence": None,
        "points_px": [[0, 10], [20, 10]],
        "ticks": [],
        "calibration": None,
    }


def _observations(chart_type: ChartType) -> dict[str, object]:
    axes = {"x": _axis(), "y": _axis()}
    if chart_type is ChartType.BAR:
        return {"orientation": "vertical", "mode": "single", "axes": axes, "baseline_px": None, "baseline_value": None, "series": [], "bars": []}
    if chart_type is ChartType.LINE:
        return {"axes": axes, "series": []}
    if chart_type is ChartType.SCATTER:
        return {"axes": axes, "series": []}
    if chart_type is ChartType.PIE:
        return {"center_px": [10, 10], "outer_radius_px": 5, "inner_radius_px": None, "sectors": []}
    if chart_type is ChartType.AREA:
        return {"axes": axes, "stacking": "none", "series": []}
    if chart_type is ChartType.HISTOGRAM:
        return {"axes": axes, "y_measure": "unknown", "bins": []}
    if chart_type is ChartType.BOX_PLOT:
        return {"axes": axes, "orientation": "vertical", "groups": []}
    if chart_type is ChartType.RADAR:
        return {"center_px": [10, 10], "spokes": [], "radial_grid": [], "series": []}
    if chart_type is ChartType.HEATMAP:
        return {"row_labels": [], "column_labels": [], "cells": []}
    if chart_type is ChartType.TREEMAP:
        return {"nodes": []}
    raise AssertionError(chart_type)


def _result(chart_type: ChartType, **overrides: object) -> MeasurementResult:
    values: dict[str, object] = {
        "chart_type": chart_type,
        "source_kind": "attachment",
        "source_id": "attachment-1",
        "image_size": (20, 12),
        "coordinate_system": "attachment_px",
        "status": "no_evidence",
        "observations": _observations(chart_type),
        "confidence": {"overall": 0.0, "geometry": 0.0, "calibration": 0.0, "association": 0.0},
    }
    values.update(overrides)
    return MeasurementResult(**values)  # type: ignore[arg-type]


def test_chart_measurement_schemas_are_valid_and_require_explicit_family() -> None:
    validate_schema_definition(MEASURE_CHART_PARAMETERS_SCHEMA, require_object=True)
    validate_schema_definition(MEASUREMENT_RESULT_SCHEMA, require_object=True)

    base = {"source_kind": "attachment", "source_id": "att-1", "chart_type": "heatmap"}
    assert validate_instance(base, MEASURE_CHART_PARAMETERS_SCHEMA) is None
    assert validate_instance({"source_kind": "attachment", "source_id": "att-1"}, MEASURE_CHART_PARAMETERS_SCHEMA)
    assert validate_instance({**base, "chart_type": "candle"}, MEASURE_CHART_PARAMETERS_SCHEMA)
    assert validate_instance({**base, "path": "/tmp/chart.png"}, MEASURE_CHART_PARAMETERS_SCHEMA)
    assert validate_instance(
        {**base, "observation_scope": {}},
        MEASURE_CHART_PARAMETERS_SCHEMA,
    )


@pytest.mark.parametrize("chart_type", list(ChartType))
def test_measurement_result_has_one_closed_observation_shape_for_each_family(chart_type: ChartType) -> None:
    result = _result(chart_type)

    assert validate_measurement_result(result) is None
    assert validate_instance(result.to_dict(), MEASUREMENT_RESULT_SCHEMA) is None


def test_measurement_result_rejects_mismatched_family_unknown_fields_and_bad_status() -> None:
    mismatched = _result(ChartType.BAR, observations=_observations(ChartType.LINE))
    unknown = _result(ChartType.BAR, observations={**_observations(ChartType.BAR), "extra": True})
    truncated = _result(ChartType.BAR, truncated=True)

    assert validate_measurement_result(mismatched).code == "any_of"
    assert validate_measurement_result(unknown).code == "any_of"
    assert validate_measurement_result(truncated).code == "truncation_status_mismatch"


def test_measurement_result_enforces_collection_and_warning_bounds() -> None:
    oversized = _result(
        ChartType.HEATMAP,
        observations={
            "row_labels": [],
            "column_labels": [],
            "cells": [
                {"row_id": None, "column_id": None, "bounds_px": {"x": 0, "y": 0, "width": 1, "height": 1}, "color": None, "value": None}
                for _ in range(513)
            ],
        },
    )
    oversized_warning = _result(ChartType.TREEMAP, warnings=("x" * 257,))

    assert validate_measurement_result(oversized) is not None
    assert validate_measurement_result(oversized_warning) is not None


def test_measurement_result_checks_source_coordinate_frame_and_pixel_bounds() -> None:
    wrong_frame = _result(ChartType.PIE, coordinate_system="panel_px")
    out_of_bounds = _result(ChartType.PIE, observations={**_observations(ChartType.PIE), "center_px": [21, 10]})
    bad_rect = _result(
        ChartType.TREEMAP,
        observations={"nodes": [{"id": "n", "parent_id": None, "role": "leaf", "area_ratio_basis": "root_plot", "area_ratio_parent_id": None, "label": None, "bounds_px": {"x": 15, "y": 2, "width": 6, "height": 4}, "value": None, "area_ratio": 1.0}]},
    )

    assert validate_measurement_result(wrong_frame).code == "coordinate_frame_mismatch"
    assert validate_measurement_result(out_of_bounds).code == "pixel_out_of_bounds"
    assert validate_measurement_result(bad_rect).code == "pixel_out_of_bounds"


def test_measure_chart_routes_family_and_applies_shared_scope_and_source_context(monkeypatch) -> None:
    source = MeasurementSource(
        "attachment", "att-1", "chart.png", "attachment_px", b"png", 20, 12
    )
    monkeypatch.setattr(measure_chart_module, "resolve_measurement_source", lambda *_args: source)
    passed_scopes: list[object] = []

    def decode(image_bytes: bytes, scope: object):
        assert image_bytes == b"png"
        passed_scopes.append(scope)
        return np.zeros((12, 20, 3), dtype=np.uint8), np.ones((12, 20), dtype=bool)

    monkeypatch.setattr(measure_chart_module, "decode_scoped_image", decode)
    selected: list[ChartType] = []
    adapters = {
        chart_type: _adapter(chart_type, selected)
        for chart_type in ChartType
    }
    definition = measure_chart_definition(lambda *_args: None, object(), adapters)  # type: ignore[arg-type]
    runtime = ToolRuntime(ToolRegistry("measure-chart-tests", (definition,)))
    scope = {"include": [[[0, 0], [1000, 0], [1000, 1000], [0, 1000]]]}
    arguments = {"source_kind": "attachment", "source_id": "att-1", "chart_type": "heatmap", "observation_scope": scope}
    call_id = "measure-chart-call"
    result = runtime.invoke(
        ToolInvocation(call_id, "measure_chart", json.dumps(arguments)),
        ToolContext("run-1", "session-1", call_id),
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["chart_type"] == "heatmap"
    assert result.result["image_size"] == {"width": 20, "height": 12}
    assert selected == [ChartType.HEATMAP]
    assert len(passed_scopes) == 1
    assert passed_scopes[0]["include"][0] == ((0, 0), (1000, 0), (1000, 1000), (0, 1000))


def test_measure_chart_commits_partial_sensor_once_without_automatic_retry(monkeypatch) -> None:
    source = MeasurementSource("attachment", "att-1", "chart.png", "attachment_px", b"png", 20, 12)
    monkeypatch.setattr(measure_chart_module, "resolve_measurement_source", lambda *_args: source)
    monkeypatch.setattr(
        measure_chart_module,
        "decode_scoped_image",
        lambda *_args: (np.zeros((12, 20, 3), dtype=np.uint8), None),
    )
    calls: list[str] = []
    adapters = {chart_type: _adapter(chart_type, []) for chart_type in ChartType}

    def partial_sensor(_image):
        calls.append("called")
        return MeasurementSensorResult(
            status="partial",
            observations=_observations(ChartType.HEATMAP),
            confidence={"overall": 0.4, "geometry": 0.5, "calibration": 0.0, "association": 0.3},
            warnings=("color scale is unclear",),
        )

    adapters[ChartType.HEATMAP] = partial_sensor
    definition = measure_chart_definition(lambda *_args: None, object(), adapters)  # type: ignore[arg-type]
    runtime = ToolRuntime(ToolRegistry("measure-chart-no-retry", (definition,)))
    call_id = "partial-measurement-call"
    outcome = runtime.invoke(
        ToolInvocation(call_id, "measure_chart", json.dumps({"source_kind": "attachment", "source_id": "att-1", "chart_type": "heatmap"})),
        ToolContext("run-1", "session-1", call_id),
    )

    assert outcome.outcome is ToolOutcome.SUCCEEDED
    assert outcome.result["status"] == "partial"
    assert calls == ["called"]


def _adapter(chart_type: ChartType, selected: list[ChartType]):
    def run(_image):
        selected.append(chart_type)
        return MeasurementSensorResult(
            status="no_evidence",
            observations=_observations(chart_type),
            confidence={"overall": 0.0, "geometry": 0.0, "calibration": 0.0, "association": 0.0},
        )

    return run
