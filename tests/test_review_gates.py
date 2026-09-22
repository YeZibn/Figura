import json
from types import SimpleNamespace

from chartagent.review.gates import (
    GateState,
    ReviewCoordinator,
    ReviewDecision,
    ReviewGateBlocked,
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
from chartagent.panels import PanelHandoff
from chartagent.spec import (
    Axes,
    Axis,
    ChartMetadata,
    ChartSpec,
    ChartType,
    CoverageBasis,
    CoverageStatus,
    DataPoint,
    GenerationContext,
    GenerationCoverage,
    GenerationMode,
    GenerationSourceScope,
    SelectionBasis,
)
from chartagent.tools.chart.rendering import render_chart
from chartagent.tools.chart.catalog import register_chart_tools
from chartagent.agent import Agent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.core import GeneratedImage, Tool, ToolRegistry, ToolResult
from chartagent.tools.adapters.chart import authorized_chart_tool
from chartagent.tools.chart.rendering import RENDER_CHART
from chartagent.tools.chart.specification import ASSEMBLE_SPEC
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.protocol import RunStatus as GatewayRunStatus
from chartagent.memory.sqlite import SQLiteAgentMemory


class _PanelStore:
    def __init__(self, handoffs):
        self.handoffs = handoffs

    def list_panel_handoffs(self, attachment_id):
        return [item for item in self.handoffs if item.attachment_id == attachment_id]

    def get_panel_handoff(self, panel_id, *, attachment_id=None, revision=None):
        for handoff in self.handoffs:
            if handoff.panel_id != panel_id or handoff.attachment_id != attachment_id:
                continue
            if revision is not None and handoff.revision != revision:
                continue
            return handoff if handoff.status == "active" else None
        return None


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
    assert gate.repair_kind == "spec_only"
    assert gate.repair_phase == "assemble"


def test_collection_review_allows_siblings_but_rejects_unrelated_parent():
    coordinator = ReviewCoordinator()
    first = coordinator.begin(
        "run-collection",
        ReviewType.GENERATED_CHART,
        "candidate-left",
        parent_id="collection:dashboard",
    )

    sibling = coordinator.begin(
        "run-collection",
        ReviewType.GENERATED_CHART,
        "candidate-right",
        parent_id="collection:dashboard",
    )
    assert sibling.parent_id == "collection:dashboard"
    assert sibling.review_id != first.review_id

    try:
        coordinator.begin(
            "run-collection",
            ReviewType.GENERATED_CHART,
            "candidate-other",
            parent_id="collection:other",
        )
    except ReviewGateBlocked:
        pass
    else:
        raise AssertionError("an unrelated collection must not cross the active review gate")

    coordinator.apply(first.review_id, {"decision": "pass"})
    assert coordinator.gate("run-collection").blocking is True
    coordinator.apply(sibling.review_id, {"decision": "pass"})
    assert coordinator.gate("run-collection").blocking is False

    partial = ReviewCoordinator()
    failed_child = partial.begin(
        "run-collection-partial",
        ReviewType.GENERATED_CHART,
        "candidate-failed",
        parent_id="collection:dashboard",
    )
    passing_child = partial.begin(
        "run-collection-partial",
        ReviewType.GENERATED_CHART,
        "candidate-passing",
        parent_id="collection:dashboard",
    )
    partial.apply(failed_child.review_id, {"decision": "repair_required", "next_action": "修复后重试"})
    partial.apply(passing_child.review_id, {"decision": "pass"})
    assert partial.gate("run-collection-partial").blocking is True


def test_evidence_and_source_rebind_repair_phases_are_ordered():
    coordinator = ReviewCoordinator()
    evidence = coordinator.begin("run-evidence", "generated_chart", "candidate-evidence", max_attempts=3)
    evidence = coordinator.apply(
        evidence.review_id,
        {"decision": "repair_required", "repair_kind": "evidence_needed", "next_action": "补充同范围证据"},
    )
    assert coordinator.gate("run-evidence").repair_phase == "evidence"
    coordinator.mark_repair_phase(evidence.review_id, "assemble")
    assert coordinator.gate("run-evidence").repair_phase == "assemble"
    coordinator.mark_repair_phase(evidence.review_id, "render")
    assert coordinator.gate("run-evidence").repair_phase == "render"

    rebind = coordinator.begin("run-rebind", "generated_chart", "candidate-rebind", max_attempts=3)
    rebind = coordinator.apply(
        rebind.review_id,
        {"decision": "repair_required", "repair_kind": "source_rebind", "next_action": "重新绑定 panel"},
    )
    assert coordinator.gate("run-rebind").repair_phase == "rebind"
    coordinator.mark_repair_phase(rebind.review_id, "assemble")
    assert coordinator.gate("run-rebind").repair_phase == "assemble"


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


def test_measurement_observation_does_not_create_shared_blocking_gate():
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

    assert answer == "我现在直接结束"
    assert calls == ["measure_bars"]
    skipped = [event for event in events if event.kind == "tool_skipped"]
    assert skipped == []
    assert any(event.kind == "measurement_decision_required" for event in events)
    assert not any(event.kind == "review_repair_required" for event in events)
    assert not any(event.kind == "review_gate_required" for event in events)
    assert any(event.kind == "measurement_observed" for event in events)


def test_generated_review_blocks_then_releases_only_after_controlled_redraw(tmp_path):
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2"]), y=Axis(label="金额")),
        dataset=[DataPoint(category="Q1", value=10), DataPoint(category="Q2", value=20)],
    )
    source_path = tmp_path / "source.png"
    source_rendered = render_chart(spec.to_dict())
    source_path.write_bytes(source_rendered.images[0].content)
    attachments = AttachmentRegistry(session_id="session-review")
    attachment = attachments.register(str(source_path))
    image_size = (source_rendered.data["width"], source_rendered.data["height"])
    attachments.panel_store = _PanelStore([
        PanelHandoff(
            session_id="session-review",
            attachment_id=attachment.id,
            attachment_sha256=attachment.sha256,
            panel_id="panel_sales",
            revision=1,
            name="销售图表",
            slug="sales",
            role="chart",
            chart_type="bar",
            source_bbox=(0, 0, image_size[0], image_size[1]),
            analysis_scope=(0, 0, image_size[0], image_size[1]),
        ),
    ])
    spec.generation_context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment.id, ("panel_sales",), revision=1),
        coverage=GenerationCoverage(
            basis=CoverageBasis.FULL_SOURCE,
            source_series=("Q1", "Q2"),
            represented_series=("Q1", "Q2"),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="重绘来源图表并校验柱状图布局",
    )

    class Client:
        def __init__(self):
            self.calls = []
            self.render_count = 0
            self.assemble_count = 0

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
            if self.render_count == 1 and self.assemble_count == 0:
                self.assemble_count += 1
                return NormalizedResult(
                    tool_calls=[
                        ToolCall(
                            "assemble-repair",
                            "assemble_spec",
                            json.dumps({
                                "chart_type": "bar",
                                "points": [
                                    {"category": "Q1", "value": 10},
                                    {"category": "Q2", "value": 20},
                                ],
                                "x_label": "季度",
                                "y_label": "金额",
                                "generation_context": spec.generation_context.to_dict(),
                            }, ensure_ascii=False),
                        )
                    ],
                    finish_reason="tool_calls",
                )
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
    canonical_starts = {
        event.payload["transition_id"]
        for event in events
        if event.kind == "review_started"
    }
    compatibility_starts = {
        event.payload["transition_id"]
        for event in events
        if event.kind == "chart_review_started"
    }
    assert canonical_starts == compatibility_starts
    assert {event.payload["check_type"] for event in events if event.kind == "review_subcheck"} >= {
        "deterministic_quality_audit",
        "semantic_vlm",
    }
    assert all(
        str(event.payload["unit_id"]).startswith("review:")
        for event in events
        if event.kind == "review_subcheck"
    )


def test_evidence_needed_repair_allows_model_selected_assemble_render_review(tmp_path):
    initial_spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2", "Q3"]), y=Axis(label="金额")),
        dataset=[
            DataPoint(category="Q1", value=10),
            DataPoint(category="Q2", value=20),
            DataPoint(category="Q3", value=30),
        ],
    )
    rendered = render_chart(initial_spec.to_dict())
    source_path = tmp_path / "evidence-source.png"
    source_path.write_bytes(rendered.images[0].content)
    attachments = AttachmentRegistry(session_id="session-evidence-repair")
    attachment = attachments.register(str(source_path))
    image_size = (rendered.data["width"], rendered.data["height"])
    attachments.panel_store = _PanelStore([
        PanelHandoff(
            session_id="session-evidence-repair",
            attachment_id=attachment.id,
            attachment_sha256=attachment.sha256,
            panel_id="panel_sales",
            revision=1,
            name="销售图表",
            slug="sales",
            role="chart",
            chart_type="bar",
            source_bbox=(0, 0, image_size[0], image_size[1]),
            analysis_scope=(0, 0, image_size[0], image_size[1]),
        ),
    ])
    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment.id, ("panel_sales",), revision=1),
        coverage=GenerationCoverage(
            basis=CoverageBasis.FULL_SOURCE,
            source_series=("Q1", "Q2", "Q3"),
            represented_series=("Q1", "Q2", "Q3"),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="在同一 panel 内确认柱体数值后重绘",
    )
    spec_payload = initial_spec.to_dict()
    spec_payload["generation_context"] = context.to_dict()
    calls: list[dict] = []

    def sensor(image_path: str, **_kwargs):
        assert image_path
        return ToolResult(
            {
                "image_size": [image_size[0], image_size[1]],
                "plot_area": {"bbox": [40, 20, image_size[0] - 80, image_size[1] - 80]},
                "baseline": {"slope": 0.0, "intercept": image_size[1] - 80},
                "bars": [{"id": "B1", "geometry": {"bbox_px": [40, 80, 40, 100]}, "measure": {"value": 10}}],
                "confidence": {"overall": 0.9},
                "warnings": [],
            },
            (GeneratedImage(b"overlay", "image/png", "bar overlay"),),
        )

    measurement_tool = authorized_chart_tool(
        Tool(
            "measure_bars",
            "在授权 panel 内测量柱体并返回 evidence。",
            {
                "type": "object",
                "properties": {"image_path": {"type": "string"}},
                "required": ["image_path"],
                "additionalProperties": False,
            },
            sensor,
        ),
        attachments,
    )

    class Client:
        def __init__(self):
            self.outer_turn = 0
            self.review_calls = 0

        def chat(self, _messages, **kwargs):
            calls.append(kwargs)
            if kwargs.get("tools") is None:
                self.review_calls += 1
                if self.review_calls == 1:
                    return NormalizedResult(content=json.dumps({
                        "decision": "fail",
                        "confidence": 0.9,
                        "checks": {
                            "chart_type": "pass",
                            "orientation": "pass",
                            "layout": "pass",
                            "data_mapping": "fail",
                            "labels": "pass",
                            "readability": "pass",
                        },
                        "issues": [{
                            "code": "value_uncertain",
                            "location": "dataset[0].value",
                            "severity": "error",
                            "message": "需要同 panel 的数值证据",
                        }],
                        "repair_kind": "evidence_needed",
                        "target": {"panel_id": "panel_sales", "refs": ["B1"], "fields": ["value"], "reason": "确认柱体数值"},
                    }, ensure_ascii=False))
                return NormalizedResult(content=json.dumps({
                    "decision": "pass",
                    "confidence": 0.95,
                    "checks": {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
                    "issues": [],
                }))

            self.outer_turn += 1
            if self.outer_turn == 1:
                return NormalizedResult(tool_calls=[
                    ToolCall("measure-initial", "measure_bars", json.dumps({
                        "attachment_id": attachment.id,
                        "panel_id": "panel_sales",
                        "generation_context": context.to_dict(),
                    }, ensure_ascii=False)),
                    ToolCall("render-1", "render_chart", json.dumps({"spec": spec_payload}, ensure_ascii=False)),
                ])
            if self.outer_turn == 2:
                return NormalizedResult(tool_calls=[ToolCall("assemble-1", "assemble_spec", json.dumps({
                    "chart_type": "bar",
                    "points": [{"category": "Q1", "value": 10}, {"category": "Q2", "value": 20}, {"category": "Q3", "value": 30}],
                    "title": "销售",
                    "x_label": "季度",
                    "y_label": "金额",
                    "generation_context": context.to_dict(),
                }, ensure_ascii=False))])
            if self.outer_turn == 3:
                return NormalizedResult(tool_calls=[ToolCall("render-2", "render_chart", json.dumps({"spec": spec_payload}, ensure_ascii=False))])
            return NormalizedResult(content="证据已补充，图表审核通过", finish_reason="stop")

    registry = ToolRegistry()
    registry.register(measurement_tool)
    registry.register(ASSEMBLE_SPEC)
    registry.register(RENDER_CHART)
    events = []
    answer = Agent(
        Client(),
        registry,
        attachments=attachments,
        max_steps=8,
        trace=events.append,
    ).run(f"请处理 {attachment.id}")

    assert answer == "证据已补充，图表审核通过"
    assert len([item for item in calls if item.get("tools") is None]) == 2
    assert [event.payload["call_id"] for event in events if event.kind == "measurement_observed"] == ["measure-initial"]
    assert not any(event.kind == "tool_skipped" for event in events)
    assert any(event.kind == "review_repair_required" and event.payload["repair_kind"] == "evidence_needed" for event in events)
    assert any(event.kind == "review_completed" and event.payload["execution_gate"]["blocking"] is False for event in events)


def test_generated_review_gate_allows_alternative_authorized_tools_but_rejects_wrong_context():
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2"]), y=Axis(label="金额")),
        dataset=[DataPoint(category="Q1", value=10), DataPoint(category="Q2", value=20)],
    )
    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope("att-source", ("panel-sales",), revision=1),
        coverage=GenerationCoverage(
            basis=CoverageBasis.FULL_SOURCE,
            source_series=("Q1", "Q2"),
            represented_series=("Q1", "Q2"),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="审核失败后允许模型选择修复方式",
    )
    spec.generation_context = context
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate(
        "run-directed-repair",
        "render-1",
        rendered.images[0],
        spec,
        source_attachment_ids=("att-source",),
    )
    failed = manager.process(
        candidate,
        semantic_result=ReviewResult(
            status=ReviewStatus.COMPLETED,
            decision="fail",
            confidence=0.2,
            review_mode="vlm",
            candidate_id=candidate.candidate_id,
            review_id=candidate.review_id,
            chart_spec_digest=candidate.chart_spec_digest,
            issues=(ReviewIssue("value_uncertain", "dataset[0]", "需要补充证据"),),
            repair_kind="evidence_needed",
        ),
    )
    coordinator = ReviewCoordinator()
    GeneratedChartReviewAdapter().submit(coordinator, candidate=failed)
    registry = ToolRegistry()
    for name in ("inspect_chart_layout", "measure_bars", "assemble_spec", "render_chart"):
        registry.register(Tool(name, name, {"type": "object", "properties": {}}, lambda **_: {}))
    agent = Agent(
        type("Client", (), {})(),
        registry,
        review_manager=manager,
        review_coordinator=coordinator,
    )

    assert agent._review_gate_allows_call(
        "run-directed-repair",
        "inspect_chart_layout",
        {},
    ) is True
    assert agent._review_gate_allows_call(
        "run-directed-repair",
        "assemble_spec",
        {"generation_context": context.to_dict()},
    ) is True
    assert agent._review_gate_allows_call(
        "run-directed-repair",
        "measure_bars",
        {"generation_context": context.to_dict()},
    ) is True
    wrong_context = context.to_dict()
    wrong_context["source_scope"] = {"attachment_id": "att-other", "panel_ids": ["panel-other"], "revision": 1}
    assert agent._review_gate_allows_call(
        "run-directed-repair",
        "measure_bars",
        {"generation_context": wrong_context},
    ) is False
    assert agent._review_gate_allows_call(
        "run-directed-repair",
        "publish_chart",
        {},
    ) is False


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
