from __future__ import annotations

import json

from chartagent import Agent, Tool, ToolRegistry
from chartagent.agent.artifacts import (
    artifact_records_from_observation,
    attach_visual_observation_refs,
)
from chartagent.agent.measurement_flow import (
    measurement_data_from_content,
    measurement_evidence_from_sessions,
    measurement_trace_fields,
    register_measurement_observation,
)
from chartagent.measurement import MeasurementSession
from chartagent.agent.panel_routing import layout_arguments, panel_routing_error
from chartagent.agent.recovery import recovery_tool_calls
from chartagent.agent.turn import execute_model_turn, prepare_and_dispatch_tool_call
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.core.result import DispatchedObservation, GeneratedImage


def test_agent_data_collaborators_own_their_projection_helpers() -> None:
    assert attach_visual_observation_refs.__module__ == "chartagent.agent.artifacts"
    assert layout_arguments.__module__ == "chartagent.agent.panel_routing"
    assert measurement_data_from_content.__module__ == "chartagent.agent.measurement_flow"
    assert recovery_tool_calls.__module__ == "chartagent.agent.recovery"
    assert execute_model_turn.__module__ == "chartagent.agent.turn"
    assert prepare_and_dispatch_tool_call.__module__ == "chartagent.agent.turn"
    assert "Agent" not in vars(__import__("chartagent.agent.artifacts", fromlist=["Agent"]))
    assert "Agent" not in vars(__import__("chartagent.agent.panel_routing", fromlist=["Agent"]))
    assert "Agent" not in vars(__import__("chartagent.agent.recovery", fromlist=["Agent"]))
    assert "Agent" not in vars(__import__("chartagent.agent.turn", fromlist=["Agent"]))


def test_artifact_projection_preserves_panel_resource_lineage() -> None:
    image = GeneratedImage(
        content=b"crop",
        media_type="image/png",
        caption="panel crop",
        metadata={"panel_id": "panel_1", "resource_key": "crop_1"},
    )
    observation = DispatchedObservation(
        content=json.dumps({"data": {"panels": [{"id": "panel_1", "crop": {}}]}}),
        images=(image,),
    )
    attached = attach_visual_observation_refs(
        observation,
        [{"resourceKey": "crop_1", "observationId": "obs_1"}],
    )
    records = artifact_records_from_observation(
        "decompose_chart_image",
        "call_1",
        attached.content,
        ("att_1",),
        [{"resourceKey": "crop_1", "observationId": "obs_1"}],
    )

    payload = json.loads(attached.content)
    assert payload["data"]["panels"][0]["crop"]["resource_ref"]["observationId"] == "obs_1"
    assert records[-1]["kind"] == "panel"
    assert records[-1]["resource_refs"][0]["observationId"] == "obs_1"


def test_panel_routing_collaborator_keeps_scope_guardrails() -> None:
    contexts = {
        "att_1::panel_1": {"analysis_scope": {"bbox_px": [1, 2, 30, 40]}},
    }
    arguments = layout_arguments(
        "measure_bars",
        json.dumps({"attachment_id": "att_1", "panel_id": "panel_1"}),
        contexts,
    )
    assert json.loads(arguments)["layout_context"]["analysis_scope"]["bbox_px"] == [1, 2, 30, 40]
    assert panel_routing_error(
        "measure_bars",
        json.dumps({"attachment_id": "att_1", "panel_id": "missing"}),
        contexts,
    )


def test_measurement_flow_projects_current_candidate_evidence() -> None:
    content = json.dumps(
        {
            "data": {
                "measurement": {
                    "status": "partial",
                    "reference": {"session_id": "s1", "attempt_id": "a1"},
                    "attempt": {
                        "session_id": "s1",
                        "attempt_id": "a1",
                        "attachment_id": "att_1",
                        "panel_id": "panel_1",
                        "tool": "measure_bars",
                        "scope": {"bbox_px": [0, 0, 100, 100]},
                    },
                    "quality": {"issues": [{"code": "missing"}]},
                    "evidence": {"refs": [{"ref": "B1", "kind": "bar", "has_numeric_value": True}]},
                },
            }
        }
    )
    sessions: dict[str, MeasurementSession] = {}
    session = register_measurement_observation(sessions, content)
    assert session is not None
    projected = measurement_evidence_from_sessions(sessions)
    trace = measurement_trace_fields(content)
    assert projected[0]["measurement_ref"]["attempt_id"] == "a1"
    assert projected[0]["evidence_refs"][0]["ref"] == "B1"
    assert projected[0]["status"] == "partial"
    assert trace["measurement_evidence_refs"][0]["ref"] == "B1"
    assert "measurement_target" not in trace


def test_extracted_turn_boundaries_preserve_execution_order() -> None:
    events: list[str] = []

    class Client:
        def __init__(self) -> None:
            self.turn = 0

        def chat(self, messages, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return NormalizedResult(
                    tool_calls=[ToolCall("call_1", "ordered_tool", "{}")],
                )
            return NormalizedResult(content="done")

    registry = ToolRegistry()
    registry.register(
        Tool(
            "ordered_tool",
            "record operation ordering",
            {"type": "object"},
            lambda: events.append("tool") or {"ok": True},
        )
    )
    agent = Agent(
        Client(),
        registry,
    )

    assert agent.run("run") == "done"
    assert events == ["tool"]
