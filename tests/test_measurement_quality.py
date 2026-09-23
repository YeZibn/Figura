from __future__ import annotations

import json

import pytest

from chartagent.measurement import (
    MeasurementSession,
    attach_measurement_quality,
    register_measurement,
    sessions_from_state,
    sessions_to_state,
    validate_measurement_evidence,
)
from chartagent.tools.core import GeneratedImage, Tool, ToolRegistry, ToolResult, dispatch_observation
from chartagent.tools.chart.specification import assemble_spec
from chartagent.agent import Agent
from chartagent.agent.recovery import checkpoint_state
from chartagent.client.models import NormalizedResult, ToolCall


def _bar_data() -> dict:
    return {
        "image_size": [320, 240],
        "plot_area": {"bbox": [40, 20, 240, 180]},
        "baseline": {"slope": 0.0, "intercept": 200.0},
        "bars": [
            {"id": 1, "measure": {"ratio": 1.0}},
            {"id": 2, "measure": {"ratio": 2.0}},
        ],
        "confidence": {"overall": 0.92, "geometry": 0.95},
        "warnings": [],
    }


@pytest.mark.parametrize(
    ("tool", "data"),
    [
        (
            "extract_line_series",
            {
                "series": [{"trace": {"polyline_px": [[10, 40], [30, 20]]}}],
                "plot_frame": {"x_axis": {"points_px": [[10, 40], [30, 40]]}, "y_axis": {"points_px": [[10, 40], [10, 20]]}},
                "confidence": {"overall": 0.9},
                "warnings": [],
            },
        ),
        (
            "extract_scatter_points",
            {
                "series": [{"points": [{"id": "point_1"}]}],
                "points": [{"id": "point_1"}],
                "plot_frame": {"x_axis": {"points_px": [[10, 40], [30, 40]]}, "y_axis": {"points_px": [[10, 40], [10, 20]]}},
                "confidence": {"overall": 0.9},
                "warnings": [],
            },
        ),
        (
            "extract_pie_slices",
            {
                "sectors": [{"id": "sector_1", "measure": {"ratio": 1.0}}],
                "totals": {"consistent": True},
                "confidence": {"overall": 0.9},
                "warnings": [],
            },
        ),
    ],
)
def test_all_chart_sensors_share_the_same_quality_envelope(tool, data):
    result = attach_measurement_quality(
        data,
        source_tool=tool,
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_chart",
        source_run_id="run_1",
    )

    measurement = result["measurement"]
    assert measurement["status"] == "complete"
    assert set(measurement) >= {"status", "reference", "attempt", "source", "quality", "evidence"}


def test_measurement_quality_provenance_and_lineage_round_trip():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
        captions=["柱状图测量叠加图"],
    )

    assert data["measurement"]["status"] == "complete"
    assert data["measurement"]["quality"]["blocking"] is False
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, data)
    assert session is not None
    assert session.current_attempt() is not None

    restored = sessions_from_state(sessions_to_state(sessions))
    restored_session = restored[session.session_id]
    reference = data["measurement"]["reference"]
    provenance, error = validate_measurement_evidence(reference, restored)

    assert error is None
    assert provenance is not None
    assert provenance["attempt_id"] == restored_session.current_attempt().attempt_id


def test_measurement_result_exposes_the_effective_scope_used_by_the_sensor():
    effective_scope = {
        "mode": "panel",
        "attachment_id": "att_chart",
        "panel_id": "panel_bars",
        "source_bbox_px": [12, 18, 240, 180],
        "local_image_size": [240, 180],
    }
    result = attach_measurement_quality(
        _bar_data() | {"effective_scope": effective_scope},
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )

    measurement = result["measurement"]
    assert measurement["effective_scope"] == effective_scope
    assert measurement["attempt"]["effective_scope"] == effective_scope
    assert measurement["evidence"]["effective_scope"] == effective_scope


def test_measurement_session_deduplicates_attempt_and_rejects_cross_panel():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, data)
    assert session is not None
    register_measurement(sessions, data)
    assert session.current_attempt().attempt_id == data["measurement"]["reference"]["attempt_id"]

    reference = dict(data["measurement"]["reference"])
    reference["panel_id"] = "panel_other"
    provenance, error = validate_measurement_evidence(reference, sessions, expected_panel_id="panel_other")
    assert provenance is None
    assert error is not None
    assert error["code"] in {"measurement_panel_mismatch", "measurement_lineage_mismatch"}


def test_warning_is_diagnostic_and_partial_evidence_remains_a_candidate():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        warnings=["baseline fit is uncertain; measurements may be partial"],
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )

    assert data["measurement"]["status"] == "partial"
    assert any(
        issue["code"] == "baseline_uncertain"
        for issue in data["measurement"]["quality"]["issues"]
    )
    sessions: dict[str, MeasurementSession] = {}
    register_measurement(sessions, data)
    candidate, error = validate_measurement_evidence(
        data["measurement"]["reference"],
        sessions,
        evidence_refs=["B1"],
    )
    assert error is None
    assert candidate is not None
    assert candidate["status"] == "candidate"
    assert candidate["measurement_status"] == "partial"


def test_measurement_target_is_bounded_and_round_trips_with_current_attempt():
    base = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        warnings=["baseline fit is uncertain; measurements may be partial"],
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, base)
    assert session is not None
    target = {
        "target_id": "baseline-focus",
        "panel_id": "panel_bars",
        "parent_attempt_id": base["measurement"]["reference"]["attempt_id"],
        "region_kind": "baseline",
        "fields": ["baseline", "bars.measure", "ignored"],
        "bbox_source_px": [20, 180, 260, 24],
        "source_image_size": [320, 240],
        "reason": "复查柱体底边与零基线",
    }
    normalized, error = session.validate_measurement_target(
        target,
        parent_attempt_id=base["measurement"]["reference"]["attempt_id"],
    )
    assert error is None
    assert normalized is not None
    child = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
        parent_attempt_id=base["measurement"]["reference"]["attempt_id"],
        measurement_target=normalized,
    )
    register_measurement(sessions, child)
    restored = sessions_from_state(sessions_to_state(sessions))
    restored_attempt = restored[session.session_id].current_attempt()
    assert restored_attempt is not None
    assert restored_attempt.parent_attempt_id == base["measurement"]["reference"]["attempt_id"]
    assert restored_attempt.target["bbox_source_px"] == [20.0, 180.0, 260.0, 24.0]
    assert restored_attempt.target_fingerprint


def test_measurement_target_refs_resolve_to_bounded_focus_regions_and_persist():
    data = attach_measurement_quality(
        {
            "image_size": [320, 240],
            "series": [{"id": "series_1", "label": "Q1", "color": "#2277cc"}],
            "bars": [
                {
                    "id": 1,
                    "series_id": "series_1",
                    "geometry": {"bbox_px": [20, 40, 24, 120]},
                    "measure": {"ratio": 1.0},
                }
            ],
            "legend": [{"label": "Q1", "geometry": {"bbox_px": [8, 8, 30, 14]}}],
            "baseline": {"slope": 0.0, "intercept": 200.0},
            "confidence": {"overall": 0.9},
            "warnings": [],
        },
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )
    refs = data["measurement"]["evidence"]["refs"]
    assert {item["ref"] for item in refs} >= {"S1", "B1", "L1"}

    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, data)
    assert session is not None
    normalized, error = session.validate_measurement_target(
        {
            "refs": ["B1", "L1"],
            "mode": "exclude",
            "fields": ["bars.measure", "baseline"],
            "reason": "排除疑似图例并复查柱体",
        },
        parent_attempt_id=session.current_attempt().attempt_id,
    )
    assert error is None
    assert normalized is not None
    assert normalized["mode"] == "exclude"
    assert normalized["resolved_refs"] == ["B1", "L1"]
    assert len(normalized["resolved_regions_px"]) == 2
    assert normalized["bbox_px"] == [8.0, 8.0, 36.0, 152.0]

    restored = sessions_from_state(sessions_to_state(sessions))
    restored_session = restored[session.session_id]
    assert restored_session.evidence_refs()[1]["ref"] == "B1"
    assert restored_session.current_attempt().attempt_id == session.current_attempt().attempt_id


def test_measurement_target_refs_reject_unknown_or_unbounded_candidates():
    data = attach_measurement_quality(
        {"series": [{"id": "series_1"}], "warnings": []},
        source_tool="extract_line_series",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_line",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, data)
    assert session is not None
    _, unknown = session.validate_measurement_target(
        {"refs": ["B1"], "mode": "include"},
        parent_attempt_id=session.current_attempt().attempt_id,
    )
    assert unknown is not None
    assert unknown["code"] == "measurement_target_ref_unknown"

    _, unbounded = session.validate_measurement_target(
        {"refs": ["S1"], "mode": "include"},
        parent_attempt_id=session.current_attempt().attempt_id,
    )
    assert unbounded is not None
    assert unbounded["code"] == "measurement_target_ref_unbounded"


def test_assemble_uses_actual_evidence_refs_and_rejects_unknown_refs():
    from chartagent.tools.chart.specification import assemble_spec

    data = attach_measurement_quality(
        {
            "image_size": [320, 240],
            "series": [{"id": "series_1", "label": "Q1"}],
            "bars": [
                {
                    "id": 1,
                    "series_id": "series_1",
                    "geometry": {"bbox_px": [20, 40, 24, 120]},
                    "measure": {"ratio": 1.0},
                }
            ],
            "baseline": {"slope": 0.0, "intercept": 200.0},
            "confidence": {"overall": 0.9},
            "warnings": [],
        },
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
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
        _measurement_context=sessions,
        evidence_refs=["B1"],
    )
    assert "error" not in assembled
    assert assembled["provenance"]["evidence_refs"] == ["B1"]

    invalid_ref = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
        measurement_ref=reference,
        evidence_refs=["UNKNOWN"],
        _measurement_context=sessions,
    )
    assert invalid_ref["error"] == "measurement evidence validation failed"
    assert invalid_ref["measurement_validation"]["code"] == "measurement_evidence_ref_unknown"
    from chartagent.tools.chart.specification import ASSEMBLE_SPEC

    assert "measurement_decision" not in ASSEMBLE_SPEC.parameters["properties"]

    invalid_label = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1, "series": "series_1"}],
        x_label="类别",
        y_label="数值",
    )
    assert invalid_label["issues"][0]["location"] == "points[0].series"


def test_measurement_target_rejects_cross_panel_and_stale_parent():
    base = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, base)
    assert session is not None
    current = base["measurement"]["reference"]["attempt_id"]
    target = {
        "target_id": "focus-1",
        "panel_id": "panel_other",
        "parent_attempt_id": current,
        "region_kind": "bars",
        "fields": ["bars"],
        "bbox_source_px": [10, 10, 100, 100],
    }
    _, error = session.validate_measurement_target(target, parent_attempt_id=current)
    assert error is not None
    assert error["code"] == "measurement_panel_mismatch"

    target["panel_id"] = "panel_bars"
    normalized, error = session.validate_measurement_target(target, parent_attempt_id=current)
    assert error is None and normalized is not None
    child = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
        parent_attempt_id=current,
        measurement_target=normalized,
    )
    assert register_measurement(sessions, child) is session
    stale, stale_error = session.validate_measurement_target(
        {**target, "panel_id": "panel_bars"},
        parent_attempt_id=current,
    )
    assert stale is None
    assert stale_error is not None
    assert stale_error["code"] == "measurement_parent_mismatch"


def test_dispatch_adds_measurement_contract_with_server_context():
    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {
                "type": "object",
                "properties": {"attachment_id": {"type": "string"}},
                "required": ["attachment_id"],
            },
            lambda attachment_id: ToolResult(
                _bar_data(),
                [GeneratedImage(b"overlay", "image/png", "bar overlay")],
            ),
        )
    )

    observation = dispatch_observation(
        registry,
        "measure_bars",
        json.dumps({"attachment_id": "att_chart"}),
        source_run_id="run_1",
        source_panel_id="panel_bars",
    )
    payload = json.loads(observation.content)
    measurement = payload["data"]["measurement"]

    assert measurement["status"] == "complete"
    assert measurement["reference"]["attachment_id"] == "att_chart"
    assert measurement["reference"]["panel_id"] == "panel_bars"
    assert measurement["evidence"]["visual_count"] == 1


def test_assemble_spec_validates_lineage_and_preserves_quality_diagnostics():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    register_measurement(sessions, data)
    reference = data["measurement"]["reference"]

    result = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
        measurement_ref=reference,
        _measurement_context=sessions,
    )

    assert "error" not in result
    assert result["provenance"]["attempt_id"] == reference["attempt_id"]
    assert result["provenance"]["quality"]["blocking"] is False

    blocked = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
        measurement_ref={**reference, "attempt_id": "matt_missing"},
        _measurement_context=sessions,
    )
    assert blocked["error"] == "measurement evidence validation failed"
    assert blocked["measurement_validation"]["next_action"]

    failed = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        warnings=["baseline fit is uncertain; measurements may be partial"],
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_2",
    )
    failed_sessions: dict[str, MeasurementSession] = {}
    register_measurement(failed_sessions, failed)
    assembled_with_warning = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
        measurement_ref=failed["measurement"]["reference"],
        evidence_refs=["B1"],
        _measurement_context=failed_sessions,
    )
    assert "error" not in assembled_with_warning
    assert assembled_with_warning["provenance"]["quality"]["warnings"]
    assert assembled_with_warning["provenance"]["evidence_refs"] == ["B1"]


def test_agent_passes_run_owned_measurement_session_to_assembly():
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NormalizedResult(
                    tool_calls=[
                        ToolCall(
                            "measure-1",
                            "measure_bars",
                            json.dumps({"attachment_id": "att_chart"}),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            if self.calls == 2:
                tool_message = next(item for item in reversed(messages) if item.get("role") == "tool")
                payload = json.loads(tool_message["content"])
                reference = payload["data"]["measurement"]["reference"]
                return NormalizedResult(
                    tool_calls=[
                        ToolCall(
                            "assemble-1",
                            "assemble_spec",
                            json.dumps(
                                {
                                    "chart_type": "bar",
                                    "points": [{"category": "A", "value": 1}],
                                    "x_label": "类别",
                                    "y_label": "数值",
                                    "measurement_ref": reference,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            return NormalizedResult(content="完成", finish_reason="stop")

    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {"type": "object", "properties": {"attachment_id": {"type": "string"}}},
            lambda attachment_id: ToolResult(
                _bar_data(),
                [GeneratedImage(b"overlay", "image/png", "bar overlay")],
            ),
        )
    )
    from chartagent.tools.chart.specification import ASSEMBLE_SPEC

    registry.register(ASSEMBLE_SPEC)
    answer = Agent(Client(), registry, system="测试质量门禁", max_steps=4).run("读取当前图表")

    assert answer == "完成"


def test_agent_uses_main_decision_for_a_bounded_targeted_attempt_without_hidden_retry():
    calls: list[dict] = []
    events = []

    def sensor(attachment_id: str, panel_id: str | None = None, measurement_target: dict | None = None):
        calls.append({
            "attachment_id": attachment_id,
            "panel_id": panel_id,
            "measurement_target": measurement_target,
        })
        data = {
            "image_size": [320, 240],
            "plot_area": {"bbox": [40, 20, 240, 180]},
            "baseline": {"slope": 0.0, "intercept": 200.0},
            "series": [
                {"id": "series_1", "label": "Q1 2024", "color": "#2277cc"},
                {"id": "series_2", "label": "Q2 2024", "color": "#22aa88"},
            ],
            "bars": [
                {"id": 1, "series_id": "series_1", "geometry": {"bbox_px": [50, 80, 24, 120]}, "measure": {"ratio": 1.0}},
                {"id": 2, "series_id": "series_2", "geometry": {"bbox_px": [78, 60, 24, 140]}, "measure": {"ratio": 1.2}},
                {"id": 3, "series_id": "series_1", "geometry": {"bbox_px": [150, 100, 24, 100]}, "measure": {"ratio": 0.8}},
                {"id": 4, "series_id": "series_2", "geometry": {"bbox_px": [178, 72, 24, 128]}, "measure": {"ratio": 1.1}},
            ],
            "legend": [
                {"label": "Q1 2024", "geometry": {"bbox_px": [8, 8, 30, 14]}},
                {"label": "Q2 2024", "geometry": {"bbox_px": [48, 8, 30, 14]}},
            ],
            "confidence": {"overall": 0.92, "geometry": 0.95},
            "warnings": [],
        }
        if len(calls) == 1:
            data = dict(data)
            data["warnings"] = ["baseline fit is uncertain; measurements may be partial"]
        return ToolResult(data, [GeneratedImage(b"overlay", "image/png", "bar overlay")])

    class Client:
        def __init__(self):
            self.calls = 0
            self.evidence_context_seen = False

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NormalizedResult(
                    tool_calls=[
                        ToolCall(
                            "measure-1",
                            "measure_bars",
                            json.dumps({"attachment_id": "att_chart"}),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            if self.calls == 2:
                tool_message = next(item for item in reversed(messages) if item.get("role") == "tool")
                payload = json.loads(tool_message["content"])
                measurement = payload["data"]["measurement"]
                evidence_refs = measurement["evidence"]["refs"]
                legend_refs = [item["ref"] for item in evidence_refs if item.get("kind") == "legend"]
                assert legend_refs
                target = {
                    "refs": [legend_refs[0]],
                    "mode": "exclude",
                    "fields": ["bars.measure"],
                    "reason": "排除图例色块，只复核柱体证据",
                }
                return NormalizedResult(
                    tool_calls=[
                        ToolCall(
                            "measure-2",
                            "measure_bars",
                            json.dumps(
                                {
                                    "attachment_id": "att_chart",
                                    "measurement_target": target,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            if self.calls == 3:
                tool_message = next(item for item in reversed(messages) if item.get("role") == "tool")
                measurement = json.loads(tool_message["content"])["data"]["measurement"]
                evidence_refs = [item["ref"] for item in measurement["evidence"]["refs"] if item.get("ref") != "L1"]
                return NormalizedResult(
                    tool_calls=[
                        ToolCall(
                            "assemble-1",
                            "assemble_spec",
                            json.dumps(
                                {
                                    "chart_type": "bar",
                                    "x_label": "类别",
                                    "y_label": "数值",
                                    "points": [{"category": "A", "value": 1}],
                                    "measurement_ref": measurement["reference"],
                                        "evidence_refs": evidence_refs,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            self.evidence_context_seen = any(
                item.get("role") == "system" and "measurement_evidence" in str(item.get("content"))
                for item in messages
            )
            return NormalizedResult(content="完成", finish_reason="stop")

    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {
                "type": "object",
                "properties": {
                    "attachment_id": {"type": "string"},
                    "panel_id": {"type": "string"},
                    "measurement_target": {"type": "object", "additionalProperties": True},
                },
            },
            sensor,
        )
    )
    from chartagent.tools.chart.specification import ASSEMBLE_SPEC

    registry.register(ASSEMBLE_SPEC)
    client = Client()
    answer = Agent(
        client,
        registry,
        system="测试定向修复",
        max_steps=4,
        trace=events.append,
    ).run("读取 att_chart 的 panel_bars")

    assert answer == "完成"
    assert len(calls) == 2
    assert calls[1]["measurement_target"]["parent_attempt_id"]
    assert calls[1]["measurement_target"]["mode"] == "exclude"
    assert calls[1]["measurement_target"]["resolved_refs"] == ["L1"]
    assert client.evidence_context_seen is True
    assert sum(event.kind == "tool_call" for event in events) == 3
    assert sum(event.kind == "tool_result" for event in events) == 3
    assert all(event.kind not in {"measurement_decision_required", "measurement_observed", "measurement_evidence_selected"} for event in events)
    assert all("/Users/" not in event.to_json() for event in events)


def test_measurement_sessions_are_included_in_checkpoint_recovery_state():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )
    sessions: dict[str, MeasurementSession] = {}
    register_measurement(sessions, data)
    state = checkpoint_state(
        "读取图表",
        [],
        {},
        ["att_chart"],
        1,
        pending_tool_calls=(),
        measurement_sessions=sessions,
    )

    restored = sessions_from_state(state["measurementSessions"])
    restored_attempt = restored[data["measurement"]["reference"]["session_id"]].current_attempt()
    assert restored_attempt is not None
    assert restored_attempt.attempt_id == data["measurement"]["reference"]["attempt_id"]
    assert "pendingMeasurementRepair" not in state
    assert "pendingMeasurementRepairs" not in state


def test_checkpoint_keeps_only_one_current_measurement_attempt_per_panel():
    sessions: dict[str, MeasurementSession] = {}
    for panel_id in ("panel_bars", "panel_line"):
        register_measurement(
            sessions,
            attach_measurement_quality(
                _bar_data(),
                source_tool="measure_bars",
                warnings=["baseline fit is uncertain; measurements may be partial"],
                image_count=1,
                source_attachment_id="att_chart",
                source_panel_id=panel_id,
                source_run_id="run_multi",
            ),
        )

    state = checkpoint_state(
        "检查多个 panel",
        [],
        {},
        ["att_chart"],
        1,
        pending_tool_calls=(),
        measurement_sessions=sessions,
    )

    assert set(state["measurementSessions"]) == {session.session_id for session in sessions.values()}
    assert all("current_attempt" in value for value in state["measurementSessions"].values())
    assert all("attempts" not in value for value in state["measurementSessions"].values())
    assert "pendingMeasurementRepair" not in state
    assert "pendingMeasurementRepairs" not in state
