from __future__ import annotations

import json

import pytest

from chartagent.measurement import (
    MeasurementSession,
    attach_measurement_quality,
    measurement_gate,
    register_measurement,
    sessions_from_state,
    sessions_to_state,
)
from chartagent.tools.core import GeneratedImage, Tool, ToolRegistry, ToolResult, dispatch_observation
from chartagent.tools.chart.specification import assemble_spec
from chartagent.agent import Agent
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
    assert measurement["status"] == "accepted"
    assert set(measurement) >= {"status", "reference", "attempt", "source", "quality", "evidence"}


def test_measurement_quality_acceptance_and_lineage_round_trip():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
        captions=["柱状图测量叠加图"],
    )

    assert data["measurement"]["status"] == "accepted"
    assert data["measurement"]["quality"]["blocking"] is False
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement(sessions, data)
    assert session is not None
    assert session.accepted_attempt() is not None

    restored = sessions_from_state(sessions_to_state(sessions))
    restored_session = restored[session.session_id]
    reference = data["measurement"]["reference"]
    accepted, error = measurement_gate(reference, restored)

    assert error is None
    assert accepted is not None
    assert accepted["attempt_id"] == restored_session.current_attempt_id


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
    assert len(session.attempts) == 1

    reference = dict(data["measurement"]["reference"])
    reference["panel_id"] = "panel_other"
    accepted, error = measurement_gate(reference, sessions, expected_panel_id="panel_other")
    assert accepted is None
    assert error is not None
    assert error["code"] in {"measurement_panel_mismatch", "measurement_lineage_mismatch"}


def test_blocking_warning_requires_remeasurement():
    data = attach_measurement_quality(
        _bar_data(),
        source_tool="measure_bars",
        warnings=["baseline fit is uncertain; measurements may be partial"],
        image_count=1,
        source_attachment_id="att_chart",
        source_panel_id="panel_bars",
        source_run_id="run_1",
    )

    assert data["measurement"]["status"] == "remeasure_required"
    assert any(
        issue["code"] == "baseline_uncertain"
        for issue in data["measurement"]["quality"]["issues"]
    )


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

    assert measurement["status"] == "accepted"
    assert measurement["reference"]["attachment_id"] == "att_chart"
    assert measurement["reference"]["panel_id"] == "panel_bars"
    assert measurement["evidence"]["visual_count"] == 1


def test_assemble_spec_requires_code_owned_accepted_reference():
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
    assert result["provenance"]["status"] == "accepted"
    assert result["provenance"]["attempt_id"] == reference["attempt_id"]

    blocked = assemble_spec(
        chart_type="bar",
        points=[{"category": "A", "value": 1}],
        x_label="类别",
        y_label="数值",
        measurement_ref={**reference, "attempt_id": "matt_missing"},
        _measurement_context=sessions,
    )
    assert blocked["error"] == "measurement evidence gate failed"
    assert blocked["measurement_gate"]["next_action"]


def test_agent_passes_run_owned_measurement_session_to_assemble_gate():
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
    state = Agent._checkpoint_state(
        "读取图表",
        [],
        {},
        ["att_chart"],
        1,
        pending_tool_calls=(),
        measurement_sessions=sessions,
    )

    restored = sessions_from_state(state["measurementSessions"])
    assert restored[data["measurement"]["reference"]["session_id"]].accepted_attempt() is not None
