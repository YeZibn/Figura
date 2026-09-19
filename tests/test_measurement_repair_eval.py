"""Offline evaluation matrix for targeted measurement repair.

This suite does not claim provider/VLM numerical accuracy. It locks the
source, geometry, lineage, quality-gate, and assembly contracts that a real
authorized-image evaluation must satisfy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chartagent.agent.loop import Agent
from chartagent.measurement import (
    MeasurementSession,
    attach_measurement_quality,
    measurement_gate,
    register_measurement,
    sessions_from_state,
)
from chartagent.tools.chart.observation.scope import ResolvedPanelScope, resolve_measurement_target
from chartagent.tools.chart.observation.bars import measure_bars
from chartagent.tools.chart.observation.dashboard import decompose_chart_image
from chartagent.tools.chart.observation.pie import extract_pie_slices
from chartagent.tools.chart.observation.segmentation import DeterministicPanelSegmenter
from chartagent.tools.chart.specification import assemble_spec
from chartagent.panels import PanelHandoff


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).parent / "fixtures" / "measurement_repair_manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _measurement_data(tool: str) -> dict:
    if tool == "measure_bars":
        return {
            "image_size": [640, 480],
            "plot_area": {"bbox": [80, 60, 480, 340]},
            "baseline": {"slope": 0.0, "intercept": 400.0},
            "bars": [
                {"id": "bar_1", "measure": {"ratio": 1.0}},
                {"id": "bar_2", "measure": {"ratio": 2.0}},
            ],
            "confidence": {"overall": 0.92, "geometry": 0.95},
            "warnings": [],
        }
    if tool == "extract_line_series":
        return {
            "image_size": [640, 480],
            "plot_frame": {
                "x_axis": {"points_px": [[80, 400], [560, 400]]},
                "y_axis": {"points_px": [[80, 400], [80, 60]]},
            },
            "series": [
                {"id": "series_1", "trace": {"polyline_px": [[80, 360], [560, 100]]}},
                {"id": "series_2", "trace": {"polyline_px": [[80, 320], [560, 180]]}},
            ],
            "confidence": {"overall": 0.9},
            "warnings": [],
        }
    if tool == "extract_pie_slices":
        return {
            "image_size": [640, 480],
            "center_px": [320, 240],
            "sectors": [
                {"id": "sector_1", "measure": {"ratio": 0.6}},
                {"id": "sector_2", "measure": {"ratio": 0.4}},
            ],
            "totals": {"consistent": True, "ratio_sum": 1.0},
            "confidence": {"overall": 0.9},
            "warnings": [],
        }
    if tool == "extract_scatter_points":
        return {
            "image_size": [640, 480],
            "plot_frame": {
                "x_axis": {"points_px": [[80, 400], [560, 400]]},
                "y_axis": {"points_px": [[80, 400], [80, 60]]},
            },
            "series": [{"id": "series_1", "points": [{"id": "point_1", "x": 1, "y": 2}]}],
            "points": [{"id": "point_1", "x": 1, "y": 2}],
            "confidence": {"overall": 0.9},
            "warnings": [],
        }
    raise AssertionError(f"unsupported evaluation tool: {tool}")


def _points(chart_type: str) -> list[dict]:
    if chart_type == "bar":
        return [{"category": "A", "value": 1}, {"category": "B", "value": 2}]
    if chart_type == "pie":
        return [{"category": "A", "value": 0.6}, {"category": "B", "value": 0.4}]
    return [{"x": 1, "y": 2, "series": "S1"}, {"x": 2, "y": 3, "series": "S1"}]


def test_measurement_repair_manifest_is_relative_and_complete():
    manifest = _manifest()
    samples = manifest["samples"]
    geometries = {sample["geometry"] for sample in samples}
    assert {"multi_panel", "vertical", "horizontal", "rotated", "grouped", "stacked", "multi_series", "sectors"} <= geometries
    assert {"dashboard", "bar", "line", "pie", "scatter"} <= {sample["chart_type"] for sample in samples}
    assert manifest["metrics"]["fields"] == [
        "panel_identification",
        "measurement_field_coverage",
        "source_coordinate_mapping",
        "quality_status",
        "assembly_status",
    ]
    assert manifest["metrics"]["comparison"]["before"]["targeted_repair_acceptance"] == 0.0
    assert manifest["metrics"]["comparison"]["after_contract"]["targeted_repair_acceptance"] == 1.0
    serialized = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "api_key" not in serialized.lower()
    assert "secret" not in serialized.lower()
    for sample in samples:
        fixture = sample["fixture"]
        if fixture.startswith("synthetic:"):
            continue
        fixture_path = ROOT / fixture
        assert not Path(fixture).is_absolute()
        assert fixture_path.is_file(), fixture


def test_real_dashboard_fixture_reaches_named_panel_measurement(tmp_path):
    dashboard = ROOT / "photo" / "dashboard_text_two_bars_pie.png"
    regions = [
        {
            "proposal_id": "summary",
            "name": "Quarterly Business Summary",
            "role": "text_block",
            "bbox_norm": [0.012, 0.040, 0.976, 0.237],
        },
        {
            "proposal_id": "revenue",
            "name": "Revenue by Region",
            "role": "chart",
            "chart_type": "bar",
            "bbox_norm": [0.013, 0.302, 0.348, 0.657],
        },
        {
            "proposal_id": "orders",
            "name": "Monthly Orders",
            "role": "chart",
            "chart_type": "bar",
            "bbox_norm": [0.371, 0.302, 0.320, 0.656],
        },
        {
            "proposal_id": "segments",
            "name": "Customer Segments",
            "role": "chart",
            "chart_type": "pie",
            "bbox_norm": [0.703, 0.303, 0.285, 0.655],
        },
    ]
    decomposition = decompose_chart_image(
        str(dashboard),
        regions=regions,
        segmenter=DeterministicPanelSegmenter(),
    )
    assert decomposition.data["segmentation"]["panel_count"] == 4
    assert {panel["chart_type"] for panel in decomposition.data["panels"]} == {"unknown", "bar", "pie"}
    crops = {
        image.metadata["panel_id"]: image
        for image in decomposition.images
        if image.metadata.get("kind") == "dashboard_panel_crop"
    }
    assert len(crops) == 4
    chart_panels = [panel for panel in decomposition.data["panels"] if panel["chart_type"] in {"bar", "pie"}]
    assert len(chart_panels) == 3
    for panel in chart_panels:
        image = crops[panel["id"]]
        crop_path = tmp_path / f"{panel['id']}.png"
        crop_path.write_bytes(image.content)
        observed = (
            measure_bars(str(crop_path))
            if panel["chart_type"] == "bar"
            else extract_pie_slices(str(crop_path))
        )
        assert hasattr(observed, "data")
        assert observed.data["focus"]["requested"] is False
        assert observed.data["measurement_target"] is None


@pytest.mark.parametrize(
    "sample",
    [
        sample
        for sample in _manifest()["samples"]
        if sample["chart_type"] != "dashboard"
    ],
    ids=lambda sample: sample["id"],
)
def test_each_chart_family_completes_targeted_repair_and_assembly(sample: dict):
    tool = sample["measurement_tool"]
    chart_type = sample["chart_type"]
    panel_id = f"panel_{sample['id']}"
    common = {
        "source_tool": tool,
        "image_count": 1,
        "source_attachment_id": "att_eval",
        "source_panel_id": panel_id,
        "source_run_id": "run_eval",
    }
    failed = attach_measurement_quality(
        _measurement_data(tool),
        warnings=["coverage is partial; targeted evidence is required"],
        **common,
    )
    assert failed["measurement"]["status"] == "remeasure_required"
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, failed["data"] if "data" in failed else failed)
    assert session is not None
    parent = session.current_attempt_id
    target = {
        "target_id": f"{sample['id']}-target",
        "panel_id": panel_id,
        "parent_attempt_id": parent,
        "region_kind": sample["target_region"].split(".")[0],
        "fields": [sample["target_region"]],
        "bbox_source_px": [80, 60, 480, 340],
        "source_image_size": [640, 480],
        "reason": "离线评估中的局部证据复查",
    }
    normalized, error = session.validate_repair_target(
        target,
        tool=tool,
        parent_attempt_id=parent,
    )
    assert error is None and normalized is not None
    accepted_data = attach_measurement_quality(
        _measurement_data(tool),
        parent_attempt_id=parent,
        measurement_target=normalized,
        **common,
    )
    assert accepted_data["measurement"]["status"] == "accepted"
    register_measurement(sessions, accepted_data)
    accepted = session.accepted_attempt()
    assert accepted is not None
    assert accepted.parent_attempt_id == parent
    assert accepted.target["bbox_source_px"] == [80.0, 60.0, 480.0, 340.0]

    gated, gate_error = measurement_gate(accepted.reference(), sessions)
    assert gate_error is None
    assert gated is not None and gated["attempt_id"] == accepted.attempt_id
    assembly = assemble_spec(
        chart_type=chart_type,
        points=_points(chart_type),
        title=sample["id"],
        x_label="类别" if chart_type in {"bar", "line", "scatter"} else "",
        y_label="数值" if chart_type in {"bar", "line", "scatter"} else "",
        measurement_ref=accepted.reference(),
        _measurement_context=sessions,
    )
    assert "error" not in assembly
    assert assembly["provenance"]["status"] == "accepted"


def test_eval_metrics_compare_initial_and_targeted_repair_states():
    samples = [sample for sample in _manifest()["samples"] if sample["chart_type"] != "dashboard"]
    initial_statuses: list[str] = []
    repaired_statuses: list[str] = []
    for sample in samples:
        tool = sample["measurement_tool"]
        panel_id = f"panel_{sample['id']}"
        common = {
            "source_tool": tool,
            "image_count": 1,
            "source_attachment_id": "att_metrics",
            "source_panel_id": panel_id,
            "source_run_id": "run_metrics",
        }
        failed = attach_measurement_quality(
            _measurement_data(tool),
            warnings=["coverage is partial"],
            **common,
        )
        initial_statuses.append(failed["measurement"]["status"])
        sessions: dict[str, MeasurementSession] = {}
        session = register_measurement(sessions, failed)
        assert session is not None
        parent = session.current_attempt_id
        normalized, error = session.validate_repair_target(
            {
                "target_id": f"metrics-{sample['id']}",
                "panel_id": panel_id,
                "parent_attempt_id": parent,
                "region_kind": sample["target_region"].split(".")[0],
                "fields": [sample["target_region"]],
                "bbox_source_px": [80, 60, 480, 340],
                "source_image_size": [640, 480],
            },
            tool=tool,
            parent_attempt_id=parent,
        )
        assert error is None and normalized is not None
        repaired = attach_measurement_quality(
            _measurement_data(tool),
            measurement_target=normalized,
            parent_attempt_id=parent,
            **common,
        )
        repaired_statuses.append(repaired["measurement"]["status"])

    before_rate = sum(status == "accepted" for status in initial_statuses) / len(initial_statuses)
    after_rate = sum(status == "accepted" for status in repaired_statuses) / len(repaired_statuses)
    thresholds = _manifest()["metrics"]["thresholds"]
    assert before_rate == 0.0
    assert after_rate >= thresholds["accepted_after_targeted_repair_min"]


def test_failure_matrix_blocks_cross_panel_duplicate_and_budget_overrun():
    sample = next(item for item in _manifest()["samples"] if item["id"] == "bar_vertical")
    tool = sample["measurement_tool"]
    session_data = attach_measurement_quality(
        _measurement_data(tool),
        source_tool=tool,
        image_count=1,
        source_attachment_id="att_eval",
        source_panel_id="panel_eval",
        source_run_id="run_eval",
        warnings=["coverage is partial"],
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, session_data)
    assert session is not None
    parent = session.current_attempt_id
    target = {
        "target_id": "eval-target-1",
        "panel_id": "panel_eval",
        "parent_attempt_id": parent,
        "region_kind": "bars",
        "fields": ["bars"],
        "bbox_source_px": [80, 60, 480, 340],
        "source_image_size": [640, 480],
    }

    _, cross_panel = session.validate_repair_target(
        {**target, "panel_id": "panel_other"},
        tool=tool,
        parent_attempt_id=parent,
    )
    assert cross_panel is not None
    assert cross_panel["code"] == "measurement_panel_mismatch"

    normalized, error = session.validate_repair_target(target, tool=tool, parent_attempt_id=parent)
    assert error is None and normalized is not None
    register_measurement(
        sessions,
        attach_measurement_quality(
            _measurement_data(tool),
            source_tool=tool,
            image_count=1,
            source_attachment_id="att_eval",
            source_panel_id="panel_eval",
            source_run_id="run_eval",
            parent_attempt_id=parent,
            measurement_target=normalized,
        ),
    )
    current = session.current_attempt_id
    _, duplicate = session.validate_repair_target(
        {**target, "target_id": "different-label", "parent_attempt_id": current},
        tool=tool,
        parent_attempt_id=current,
    )
    assert duplicate is not None
    assert duplicate["code"] == "measurement_target_duplicate"

    for index in range(2, session.max_repair_attempts + 1):
        parent = session.current_attempt_id
        candidate = {**target, "target_id": f"eval-target-{index}", "parent_attempt_id": parent, "bbox_source_px": [80 + index, 60, 480, 340]}
        normalized, error = session.validate_repair_target(candidate, tool=tool, parent_attempt_id=parent)
        assert error is None and normalized is not None
        register_measurement(
            sessions,
            attach_measurement_quality(
                _measurement_data(tool),
                source_tool=tool,
                image_count=1,
                source_attachment_id="att_eval",
                source_panel_id="panel_eval",
                source_run_id="run_eval",
                parent_attempt_id=parent,
                measurement_target=normalized,
            ),
        )
    exhausted_parent = session.current_attempt_id
    _, exhausted = session.validate_repair_target(
        {**target, "target_id": "eval-target-over-budget", "parent_attempt_id": exhausted_parent, "bbox_source_px": [40, 40, 200, 120]},
        tool=tool,
        parent_attempt_id=exhausted_parent,
    )
    assert exhausted is not None
    assert exhausted["code"] == "measurement_repair_budget_exhausted"


def test_target_outside_panel_is_rejected_without_expanding_scope():
    panel = PanelHandoff(
        session_id="session_eval",
        attachment_id="att_eval",
        attachment_sha256="a" * 64,
        panel_id="panel_eval",
        revision=1,
        name="评估图表",
        slug="eval-chart",
        role="chart",
        chart_type="bar",
        source_bbox=(100, 100, 200, 160),
        analysis_scope=(100, 100, 200, 160),
        confidence=0.95,
    )
    scope = ResolvedPanelScope(panel, (640, 480), (200, 160))
    target, error = resolve_measurement_target(
        {
            "target_id": "outside",
            "panel_id": "panel_eval",
            "region_kind": "bars",
            "bbox_source_px": [400, 400, 80, 60],
            "source_image_size": [640, 480],
        },
        scope,
    )
    assert target is None
    assert error == "measurement target does not intersect the selected panel"


def test_checkpoint_restores_pending_lineage_and_accepted_attempt():
    initial = attach_measurement_quality(
        _measurement_data("measure_bars"),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_eval",
        source_panel_id="panel_eval",
        source_run_id="run_eval",
        warnings=["coverage is partial"],
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, initial)
    assert session is not None
    parent = session.current_attempt_id
    target, error = session.validate_repair_target(
        {
            "target_id": "checkpoint-target",
            "panel_id": "panel_eval",
            "parent_attempt_id": parent,
            "region_kind": "bars",
            "fields": ["bars"],
            "bbox_source_px": [100, 100, 200, 120],
            "source_image_size": [640, 480],
        },
        tool="measure_bars",
        parent_attempt_id=parent,
    )
    assert error is None and target is not None
    child = attach_measurement_quality(
        _measurement_data("measure_bars"),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_eval",
        source_panel_id="panel_eval",
        source_run_id="run_eval",
        parent_attempt_id=parent,
        measurement_target=target,
    )
    register_measurement(sessions, child)
    state = Agent._checkpoint_state(
        "继续",
        [],
        {},
        ["att_eval"],
        2,
        pending_tool_calls=(),
        measurement_sessions=sessions,
    )
    restored = sessions_from_state(state["measurementSessions"])
    restored_session = restored[session.session_id]
    assert restored_session.accepted_attempt() is not None
    assert restored_session.accepted_attempt().parent_attempt_id == parent
    assert state["pendingMeasurementRepair"] is None


def test_direct_assembly_without_measurement_session_keeps_legacy_path():
    result = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
    )
    assert "error" not in result
    assert "provenance" not in result
