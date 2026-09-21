import json
from types import SimpleNamespace

from chartagent.review.gates import (
    GateState,
    ReviewCoordinator,
    ReviewDecision,
    ReviewState,
    ReviewType,
    normalize_review_event,
)
from chartagent.review import (
    ChartReviewManager,
    GeneratedChartReviewAdapter,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    PublicationStatus,
)
from chartagent.attachments import AttachmentRegistry
from chartagent.spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from chartagent.tools.chart.rendering import render_chart
from chartagent.tools.chart.catalog import register_chart_tools
from chartagent.agent import Agent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.core import GeneratedImage, Tool, ToolRegistry, ToolResult
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.protocol import RunStatus as GatewayRunStatus
from chartagent.memory.sqlite import SQLiteAgentMemory


def test_review_coordinator_blocks_until_explicit_pass():
    coordinator = ReviewCoordinator()
    record = coordinator.begin(
        "run_1",
        ReviewType.MEASUREMENT,
        "matt_1",
        subject_ref={"attachment_id": "att_1", "panel_id": "panel_1"},
        next_action="重新测量 baseline",
    )

    assert record.state is ReviewState.REVIEWING
    assert coordinator.gate("run_1").state is GateState.REVIEWING
    assert coordinator.can_continue("run_1") is False

    duplicate = coordinator.begin("run_1", "measurement", "matt_1")
    assert duplicate.review_id == record.review_id

    passed = coordinator.apply(record.review_id, {"decision": "pass", "confidence": 0.9})
    assert passed.state is ReviewState.PASSED
    assert coordinator.gate("run_1").state is GateState.OPEN
    assert coordinator.can_continue("run_1") is True


def test_repair_decision_keeps_gate_closed_and_preserves_diagnostics():
    coordinator = ReviewCoordinator()
    record = coordinator.begin("run_1", "generated_chart", "candidate_1", max_attempts=2)
    repaired = coordinator.apply(
        record.review_id,
        {
            "decision": "repair_required",
            "issues": [
                {
                    "code": "wrong_baseline",
                    "location": "plot.zero_baseline",
                    "message": "基准线不一致",
                    "severity": "blocking",
                }
            ],
            "repair_action": {"action": "correct_chart_spec", "fields": ["axes.y"]},
            "next_action": "修正 ChartSpec 后重新渲染",
        },
    )

    assert repaired.state is ReviewState.REPAIR_REQUIRED
    gate = coordinator.gate("run_1")
    assert gate.state is GateState.REPAIR_REQUIRED
    assert gate.blocking is True
    assert gate.repair_action == {"action": "correct_chart_spec", "fields": ["axes.y"]}
    assert gate.issues[0].severity == "error"


def test_exhausted_review_cannot_be_released_by_a_later_decision():
    coordinator = ReviewCoordinator()
    record = coordinator.begin("run_1", "measurement", "matt_1", max_attempts=1)
    exhausted = coordinator.apply(record.review_id, {"decision": "exhausted"})
    assert exhausted.state is ReviewState.EXHAUSTED
    assert coordinator.gate("run_1").state is GateState.EXHAUSTED

    replay = coordinator.apply(record.review_id, {"decision": "pass"})
    assert replay.state is ReviewState.EXHAUSTED
    assert coordinator.can_continue("run_1") is False


def test_review_state_round_trips_through_checkpoint_projection():
    coordinator = ReviewCoordinator()
    record = coordinator.begin(
        "run_1",
        "measurement",
        "matt_1",
        attempt=2,
        parent_id="matt_0",
        subject_ref={"attachment_id": "att_1", "panel_id": "panel_1"},
    )
    coordinator.apply(record.review_id, {"decision": "repair_required", "next_action": "重新测量"})
    state = coordinator.to_state("run_1")

    restored = ReviewCoordinator()
    restored.restore(state["records"])
    restored_gate = restored.gate("run_1")
    assert restored_gate.state is GateState.REPAIR_REQUIRED
    assert restored_gate.review_id == record.review_id
    assert restored.to_state("run_1")["executionGate"]["blocking"] is True


def test_legacy_review_events_have_one_frontend_projection():
    required = normalize_review_event(
        "measurement_repair_required",
        {"review_id": "review_1", "attempt": 1, "repair": {"action": "remeasure"}},
    )
    assert required["reviewType"] == "measurement"
    assert required["state"] == "repair_required"
    assert required["blocking"] is True

    published = normalize_review_event(
        "generated_chart_published",
        {"review_id": "review_2", "publication_status": "published_with_warning"},
    )
    assert published["reviewType"] == "generated_chart"
    assert published["state"] == "passed_with_warning"
    assert published["blocking"] is False


def test_measurement_review_skips_remaining_tool_batch_until_repair():
    calls: list[str] = []
    events = []

    def sensor(attachment_id: str, panel_id: str | None = None):
        calls.append("measure_bars")
        return ToolResult(
            {
                "image_size": [320, 240],
                "plot_area": {"bbox": [40, 20, 240, 180]},
                "baseline": {"slope": 0.0, "intercept": 200.0},
                "bars": [{"id": 1, "measure": {"ratio": 1.0}}],
                "warnings": ["baseline fit is uncertain; measurements may be partial"],
            },
            [GeneratedImage(b"overlay", "image/png", "bar overlay")],
        )

    class Client:
        def __init__(self):
            self.turn = 0

        def chat(self, messages, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return NormalizedResult(
                    tool_calls=[
                        ToolCall("measure-1", "measure_bars", '{"attachment_id":"att_1"}'),
                        ToolCall("assemble-1", "assemble_spec", "{}"),
                    ],
                    finish_reason="tool_calls",
                )
            return NormalizedResult(content="我现在直接结束", finish_reason="stop")

    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {
                "type": "object",
                "properties": {"attachment_id": {"type": "string"}, "panel_id": {"type": "string"}},
            },
            sensor,
        )
    )
    answer = Agent(Client(), registry, system="测试审核门禁", max_steps=2, trace=events.append).run("读取 att_1")

    assert "review" in answer
    assert calls == ["measure_bars"]
    skipped = [event for event in events if event.kind == "tool_skipped"]
    assert len(skipped) == 1
    assert skipped[0].payload["call_id"] == "assemble-1"
    assert skipped[0].payload["status"] == "not_started"
    assert any(event.kind == "measurement_decision_required" for event in events)
    assert not any(event.kind == "review_repair_required" for event in events)
    assert any(event.kind == "review_gate_required" for event in events)


def test_generated_review_blocks_then_releases_only_after_controlled_redraw(tmp_path):
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2"]), y=Axis(label="金额")),
        dataset=[DataPoint(category="Q1", value=10), DataPoint(category="Q2", value=20)],
    )
    source_path = tmp_path / "source.png"
    source_path.write_bytes(render_chart(spec.to_dict()).images[0].content)
    attachments = AttachmentRegistry()
    attachment = attachments.register(str(source_path))

    class Client:
        def __init__(self):
            self.calls = []
            self.render_count = 0

        def chat(self, _messages, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("tools") is None:
                if self.render_count == 1:
                    return NormalizedResult(
                        content=json.dumps({
                            "decision": "fail",
                            "confidence": 0.9,
                            "checks": {
                                "chart_type": "pass",
                                "orientation": "pass",
                                "layout": "fail",
                                "data_mapping": "pass",
                                "labels": "pass",
                                "readability": "pass",
                            },
                            "issues": [{
                                "code": "baseline_mismatch",
                                "location": "plot.zero_baseline",
                                "severity": "error",
                                "message": "柱体底边未与零基线重合",
                            }],
                        }, ensure_ascii=False),
                    )
                return NormalizedResult(content='{"decision":"pass","confidence":0.95,"checks":{"chart_type":"pass","orientation":"pass","layout":"pass","data_mapping":"pass","labels":"pass","readability":"pass"},"issues":[]}')
            if self.render_count >= 2:
                return NormalizedResult(content="图表已通过审核", finish_reason="stop")
            self.render_count += 1
            return NormalizedResult(
                tool_calls=[
                    ToolCall(
                        f"render-{self.render_count}",
                        "render_chart",
                        json.dumps({"spec": spec.to_dict()}, ensure_ascii=False),
                    )
                ],
                finish_reason="tool_calls",
            )

    events = []
    client = Client()
    registry = ToolRegistry()
    register_chart_tools(registry)
    answer = Agent(
        client,
        registry,
        attachments=attachments,
        max_steps=6,
        trace=events.append,
    ).run(f"请重绘 {attachment.id}")

    assert answer == "图表已通过审核"
    # The first candidate must be rejected before the second candidate is
    # allowed to use the render tool.  A final answer cannot bypass the gate.
    assert client.render_count == 2
    assert any(event.kind == "review_repair_required" for event in events)
    assert any(event.kind == "review_completed" for event in events)
    assert any(
        event.kind == "review_repair_required" and event.payload["execution_gate"]["blocking"]
        for event in events
    )
    assert any(
        event.kind == "review_completed" and event.payload["execution_gate"]["blocking"] is False
        for event in events
    )


def test_generated_candidate_review_uses_shared_gate_and_lineage():
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2"]), y=Axis(label="金额")),
        dataset=[DataPoint(category="Q1", value=10), DataPoint(category="Q2", value=20)],
    )
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    first = manager.create_candidate(
        "run-generated",
        "call-1",
        rendered.images[0],
        spec,
        source_attachment_ids=("att-source",),
    )
    failed_result = ReviewResult(
        status=ReviewStatus.COMPLETED,
        issues=(ReviewIssue("value_mismatch", "dataset[0]", "数据不一致"),),
        decision="fail",
        review_mode="vlm",
        candidate_id=first.candidate_id,
        review_id=first.review_id,
        chart_spec_digest=first.chart_spec_digest,
        suggested_action="correct_chart_spec",
    )
    failed = manager.process(first, semantic_result=failed_result)

    coordinator = ReviewCoordinator()
    adapter = GeneratedChartReviewAdapter()
    shared_failed = adapter.submit(coordinator, candidate=failed)
    assert shared_failed.state is ReviewState.REPAIR_REQUIRED
    assert coordinator.gate("run-generated").blocking is True

    second = manager.create_candidate(
        "run-generated",
        "call-2",
        rendered.images[0],
        spec,
        source_attachment_ids=("att-source",),
    )
    assert second.parent_candidate_id == first.candidate_id
    assert second.lineage_attempt == 2
    shared_pending = adapter.submit(coordinator, candidate=second)
    assert shared_pending.state is ReviewState.REVIEWING

    passed_result = ReviewResult(
        status=ReviewStatus.COMPLETED,
        decision="pass",
        review_mode="vlm",
        candidate_id=second.candidate_id,
        review_id=second.review_id,
        chart_spec_digest=second.chart_spec_digest,
    )
    reviewed = manager.process(second, semantic_result=passed_result)
    shared_passed = adapter.submit(coordinator, candidate=reviewed)
    assert reviewed.publication_status in {
        PublicationStatus.PUBLISHED,
        PublicationStatus.PUBLISHED_WITH_WARNING,
    }
    assert shared_passed.state in {ReviewState.PASSED, ReviewState.PASSED_WITH_WARNING}
    assert coordinator.gate("run-generated").blocking is False


def test_checkpoint_persists_review_records_and_active_gate():
    captured = {}
    coordinator = ReviewCoordinator()
    record = coordinator.begin(
        "run-checkpoint",
        ReviewType.MEASUREMENT,
        "matt_1",
        next_action="重新测量同一 panel",
    )
    coordinator.apply(record.review_id, {"decision": "repair_required", "next_action": "重新测量同一 panel"})
    agent = Agent(
        type("Client", (), {})(),
        ToolRegistry(),
        review_coordinator=coordinator,
        checkpoint_sink=lambda state, **_: captured.update(state),
    )

    agent._checkpoint(
        SimpleNamespace(id="run-checkpoint"),
        state={"messages": []},
        phase="review",
        next_action="remeasure",
    )

    assert captured["reviewState"]["records"][0]["state"] == "repair_required"
    assert captured["executionGate"]["blocking"] is True
    assert captured["executionGate"]["subjectId"] == "matt_1"


def test_gateway_run_projection_persists_execution_gate(tmp_path):
    database = tmp_path / "gate-projection.db"
    memory = SQLiteAgentMemory("gate-projection", database=database)
    session_id = memory.session.id
    memory.close()
    store = GatewayHistoryStore(database, retention_seconds=3600)
    store.create_run("run-gate", session_id)
    store.update_run(
        "run-gate",
        GatewayRunStatus.RUNNING,
        execution_gate={
            "state": "repair_required",
            "blocking": True,
            "reviewType": "generated_chart",
            "subjectId": "cand_1",
            "nextAction": "修复 ChartSpec",
        },
    )

    summary = store.get_run(session_id, "run-gate")
    assert summary is not None
    assert summary["executionGate"]["state"] == "repair_required"
    assert summary["executionGate"]["subjectId"] == "cand_1"
