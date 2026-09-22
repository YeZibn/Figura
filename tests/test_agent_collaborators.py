from __future__ import annotations

import json

from chartagent import Agent, Tool, ToolRegistry
from chartagent.agent.artifacts import (
    artifact_records_from_observation,
    attach_visual_observation_refs,
)
from chartagent.agent.measurement_flow import (
    measurement_decisions_from_content,
    measurement_evidence_uses_from_content,
    measurement_repair_context_from_content,
    merge_measurement_repair_contexts,
)
from chartagent.agent.panel_routing import layout_arguments, panel_routing_error
from chartagent.agent.recovery import checkpoint_state, recovery_tool_calls
from chartagent.agent.turn import execute_model_turn, prepare_and_dispatch_tool_call
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.core.result import DispatchedObservation, GeneratedImage


def test_agent_data_collaborators_own_their_projection_helpers() -> None:
    assert attach_visual_observation_refs.__module__ == "chartagent.agent.artifacts"
    assert layout_arguments.__module__ == "chartagent.agent.panel_routing"
    assert measurement_repair_context_from_content.__module__ == "chartagent.agent.measurement_flow"
    assert checkpoint_state.__module__ == "chartagent.agent.recovery"
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


def test_measurement_flow_projects_bounded_decisions() -> None:
    content = json.dumps(
        {
            "data": {
                "measurement": {
                    "status": "partial",
                    "reference": {"session_id": "s1", "attempt_id": "a1"},
                    "quality": {"issues": [{"code": "missing"}]},
                    "evidence": {"refs": ["ref_1"]},
                    "decision": {"status": "pending"},
                },
                "_measurement_decisions": [
                    {"attempt_id": "a1", "selected_refs": ["ref_1"]},
                ],
            }
        }
    )
    context = measurement_repair_context_from_content(content)
    decisions = measurement_decisions_from_content(content)
    merged = merge_measurement_repair_contexts([context], [{"attempt_id": "a1", "action": "focus"}])

    assert context is not None
    assert context["refs"] == ["ref_1"]
    assert len(decisions) == 1
    assert len(merged) == 2


def test_measurement_flow_derives_actual_evidence_use_from_assembly() -> None:
    content = json.dumps(
        {
            "data": {
                "metadata": {"chart_type": "bar"},
                "provenance": {
                    "session_id": "s1",
                    "attempt_id": "a1",
                    "attachment_id": "att_1",
                    "panel_id": "panel_1",
                    "evidence_refs": ["B1", "B2"],
                },
                "_evidence_refs": ["B1", "B2"],
            }
        }
    )

    uses = measurement_evidence_uses_from_content(content)

    assert uses == [{
        "session_id": "s1",
        "attempt_id": "a1",
        "attachment_id": "att_1",
        "panel_id": "panel_1",
        "evidence_refs": ["B1", "B2"],
        "status": "used",
    }]


def test_extracted_turn_boundaries_preserve_operation_order() -> None:
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
        operation_begin=lambda operation_id, kind: events.append(f"begin:{kind}") or {"state": "in_flight"},
        operation_complete=lambda operation_id, result=None, references=None: events.append("complete"),
    )

    assert agent.run("run") == "done"
    assert events == [
        "begin:model",
        "complete",
        "begin:tool",
        "tool",
        "complete",
        "begin:model",
        "complete",
    ]
