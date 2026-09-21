from __future__ import annotations

import numpy as np

from chartagent.measurement import MeasurementSession, attach_measurement_quality, register_measurement
from chartagent.panels import PanelHandoff
from chartagent.tools.chart.observation.scope import (
    ResolvedPanelScope,
    apply_measurement_focus,
    observation_scope_focus_context,
    resolve_observation_scope,
)
from chartagent.tools.chart.specification import assemble_spec


def _scope() -> ResolvedPanelScope:
    panel = PanelHandoff(
        session_id="session_1",
        attachment_id="att_1",
        attachment_sha256="a" * 64,
        panel_id="panel_1",
        revision=1,
        name="销售柱状图",
        slug="sales-bars",
        role="chart",
        chart_type="bar",
        source_bbox=(100, 50, 300, 200),
        analysis_scope=(120, 70, 240, 160),
        confidence=0.9,
    )
    return ResolvedPanelScope(panel, (500, 400), (240, 160))


def test_observation_scope_resolves_panel_norm_and_preserves_source_lineage():
    resolved, error = resolve_observation_scope(
        {
            "panel_id": "panel_1",
            "attachment_id": "att_1",
            "coordinate_space": "panel_norm",
            "include": [{"role": "geometry", "bbox": [0.25, 0.25, 0.5, 0.5]}],
            "exclude": [{"role": "legend", "bbox": [0.0, 0.0, 0.2, 0.2]}],
            "objectives": ["确认柱体和基准线"],
        },
        _scope(),
    )

    assert error is None
    assert resolved is not None
    assert resolved["status"] == "applied"
    assert resolved["include_regions_px"] == [[60.0, 40.0, 120.0, 80.0]]
    assert resolved["include"][0]["bbox_source_px"] == [180.0, 110.0, 120.0, 80.0]
    assert resolved["exclude"][0]["bbox_px"] == [0.0, 0.0, 48.0, 32.0]
    assert resolved["overlay"]["panel_id"] == "panel_1"


def test_observation_scope_rejects_out_of_panel_regions():
    resolved, error = resolve_observation_scope(
        {
            "coordinate_space": "panel_px",
            "include": [{"bbox": [220, 0, 40, 20]}],
        },
        _scope(),
    )

    assert resolved is None
    assert error and "outside" in error


def test_direct_scope_focus_maps_normalized_coordinates_without_widening():
    focus = observation_scope_focus_context(
        {
            "coordinate_space": "panel_norm",
            "include": [{"bbox": [0.25, 0.25, 0.5, 0.5]}],
        },
        width=100,
        height=80,
    )
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    focused = apply_measurement_focus(image, focus)

    assert focus["applied"] is True
    assert focus["search_area"] == [25, 20, 50, 40]
    assert np.all(focused[20:60, 25:75] == 0)
    assert np.all(focused[:20] == 255)
    assert np.all(focused[:, :25] == 255)


def test_exclude_only_scope_keeps_panel_searchable_and_masks_only_excluded_area():
    focus = observation_scope_focus_context(
        {
            "coordinate_space": "panel_px",
            "exclude": [{"bbox": [10, 10, 20, 20]}],
        },
        width=60,
        height=50,
    )
    image = np.zeros((50, 60, 3), dtype=np.uint8)
    focused = apply_measurement_focus(image, focus)

    assert focus["mode"] == "exclude"
    assert np.all(focused[10:30, 10:30] == 255)
    assert np.all(focused[0:10] == 0)
    assert np.all(focused[:, 40:] == 0)


def test_abandoned_decision_is_explicit_and_does_not_require_fake_selected_ref():
    data = attach_measurement_quality(
        {
            "bars": [{"id": "bar_1", "geometry": {"bbox_px": [10, 20, 20, 80]}, "measure": {"ratio": None}}],
            "baseline": {"slope": 0.0, "intercept": 100.0},
            "confidence": {"overall": 0.2},
            "warnings": ["bar values are partial"],
        },
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_1",
        source_panel_id="panel_1",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, data)
    assert session is not None
    reference = data["measurement"]["reference"]

    assembled = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
        measurement_ref=reference,
        measurement_decision={
            "status": "abandoned",
            "session_id": reference["session_id"],
            "attempt_id": reference["attempt_id"],
            "evidence_basis": "当前柱体数值无法确认，保留视觉判断",
        },
        _measurement_context=sessions,
    )

    assert "error" not in assembled
    assert assembled["provenance"]["status"] == "abandoned"
    assert assembled["_measurement_decision"]["decision_status"] == "abandoned"
