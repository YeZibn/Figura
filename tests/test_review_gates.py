"""Generated-chart gate projections and recovery use one review aggregate."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from chartagent.agent import Agent
from chartagent.attachments import AttachmentRegistry
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.decision_timeline import TimelineProtocolError, enrich_event_payload
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.protocol import RunStatus as GatewayRunStatus
from chartagent.memory.sqlite import SQLiteAgentMemory
from chartagent.panels import PanelHandoff
from chartagent.review import (
    CandidateStatus,
    ChartReviewManager,
    PublicationStatus,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    review_candidate_bytes,
)
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
from chartagent.tools.chart.catalog import register_chart_tools
from chartagent.tools.chart.rendering import render_chart
from chartagent.tools.core import GeneratedImage, Tool, ToolRegistry, ToolResult


class _PanelStore:
    def __init__(self, handoffs):
        self.handoffs = handoffs

    def get_panel_handoff(self, panel_id, *, attachment_id=None, revision=None):
        for handoff in self.handoffs:
            if handoff.panel_id != panel_id or handoff.attachment_id != attachment_id:
                continue
            if revision is not None and handoff.revision != revision:
                continue
            return handoff if handoff.status == "active" else None
        return None


def _source_context(attachment_id: str, panel_id: str) -> GenerationContext:
    return GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, (panel_id,), revision=1),
        coverage=GenerationCoverage(
            basis=CoverageBasis.FULL_SOURCE,
            source_series=("Q1", "Q2"),
            represented_series=("Q1", "Q2"),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="重绘来源图表并校验柱状图布局",
    )


def _spec() -> ChartSpec:
    return ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2"]), y=Axis(label="金额")),
        dataset=[DataPoint(category="Q1", value=10), DataPoint(category="Q2", value=20)],
    )


def _safety(manager: ChartReviewManager, candidate):
    spec = manager.get_spec(candidate.candidate_id, candidate.review_id)
    assert spec is not None
    result = review_candidate_bytes(
        spec,
        candidate.content,
        media_type=candidate.media_type,
        declared_width=candidate.width,
        declared_height=candidate.height,
    )
    return manager.record_safety_result(candidate, result)


def _semantic(candidate, decision: str = "pass") -> ReviewResult:
    failed = decision == "fail"
    checks = {
        name: "fail" if failed and name == "data_mapping" else "pass"
        for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")
    }
    return ReviewResult(
        status=ReviewStatus.COMPLETED,
        checks=checks,
        issues=(ReviewIssue("value_mismatch", "dataset[0].value", "数值不一致"),) if failed else (),
        decision=decision,
        confidence=0.95,
        review_mode="vlm",
        candidate_id=candidate.candidate_id,
        review_id=candidate.review_id,
        chart_spec_digest=candidate.chart_spec_digest,
        repair_kind="spec_only" if failed else "none",
    )


def test_manager_owns_candidate_review_and_derived_gate():
    spec = _spec()
    image = render_chart(spec.to_dict()).images[0]
    manager = ChartReviewManager()
    candidate = manager.create_candidate(
        "run-review",
        "render-1",
        image,
        spec,
        source_attachment_ids=("att_source",),
    )

    candidate = _safety(manager, candidate)
    assert candidate.status is CandidateStatus.REVIEW_PENDING
    gate = manager.execution_gate("run-review")
    assert gate.blocking is True
    assert gate.state.value == "reviewing"
    assert gate.subject_id == candidate.candidate_id

    semantic = _semantic(candidate)
    reviewed = manager.process(candidate, semantic_result=semantic)
    assert reviewed.semantic_result is semantic
    assert reviewed.publication_status is PublicationStatus.PUBLISHED
    assert manager.execution_gate("run-review").blocking is False
    assert manager.summary("run-review")["ok"] is True

    state = manager.to_state("run-review")
    assert state["version"] == 1
    assert "executionGate" not in state
    assert "records" not in state
    assert "content" not in state["candidates"][0]
    assert "chartSpec" not in state["candidates"][0]


def test_retry_supersedes_failed_attempt_and_gate_tracks_new_candidate():
    spec = _spec()
    image = render_chart(spec.to_dict()).images[0]
    manager = ChartReviewManager()
    first = manager.create_candidate("run-retry", "render-1", image, spec, source_attachment_ids=("att_source",))
    first = _safety(manager, first)
    failed = manager.process(first, semantic_result=_semantic(first, "fail"))

    gate = manager.execution_gate("run-retry")
    assert failed.status is CandidateStatus.REVIEW_FAILED
    assert gate.blocking is True
    assert gate.state.value == "repair_required"

    second = manager.create_candidate("run-retry", "render-2", image, spec, source_attachment_ids=("att_source",))
    gate = manager.execution_gate("run-retry")
    assert first.candidate_id != second.candidate_id
    assert second.parent_candidate_id == first.candidate_id
    assert second.lineage_attempt == 2
    assert manager.get(first.candidate_id).superseded is True
    assert gate.blocking is True
    assert gate.state.value == "reviewing"
    assert gate.subject_id == second.candidate_id


def test_model_selected_repair_tools_remain_bound_to_failed_candidate_context():
    spec = _spec()
    context = _source_context("att_source", "panel_sales")
    spec.generation_context = context
    image = render_chart(spec.to_dict()).images[0]
    manager = ChartReviewManager()
    candidate = manager.create_candidate(
        "run-repair-tools",
        "render-1",
        image,
        spec,
        source_attachment_ids=("att_source",),
    )
    candidate = _safety(manager, candidate)
    failed_semantic = _semantic(candidate, "fail")
    failed_semantic = replace(
        failed_semantic,
        repair_kind="evidence_needed",
        repair_target={"panel_id": "panel_sales", "refs": ["B1"], "fields": ["value"]},
    )
    manager.process(candidate, semantic_result=failed_semantic)

    registry = ToolRegistry()
    for name in ("inspect_chart_layout", "measure_bars", "assemble_spec", "render_chart", "publish_chart"):
        registry.register(Tool(name, name, {"type": "object", "properties": {}}, lambda **_: {}))
    agent = Agent(type("Client", (), {})(), registry, review_manager=manager)

    assert agent._review_gate_allows_call("run-repair-tools", "inspect_chart_layout", {}) is True
    assert agent._review_gate_allows_call("run-repair-tools", "measure_bars", {"generation_context": context.to_dict()}) is True
    wrong_context = context.to_dict()
    wrong_context["source_scope"] = {"attachment_id": "att_other", "panel_ids": ["panel_other"], "revision": 1}
    assert agent._review_gate_allows_call("run-repair-tools", "measure_bars", {"generation_context": wrong_context}) is False
    assert agent._review_gate_allows_call("run-repair-tools", "publish_chart", {}) is False


def test_collection_children_keep_independent_pass_and_failure_results():
    spec = _spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidates = []
    for index in range(2):
        image = rendered.images[0]
        image = GeneratedImage(
            image.content,
            image.media_type,
            image.caption,
            {**image.metadata, "collection_id": "collection-1"},
        )
        candidates.append(manager.create_candidate(
            "run-collection",
            f"render-{index}",
            image,
            spec,
            source_attachment_ids=("att_source",),
        ))

    first, second = (_safety(manager, item) for item in candidates)
    first = manager.process(first, semantic_result=_semantic(first, "fail"))
    second = manager.process(second, semantic_result=_semantic(second))

    assert first.publication_status is PublicationStatus.REJECTED
    assert second.publication_status is PublicationStatus.PUBLISHED
    gate = manager.execution_gate("run-collection")
    assert gate.blocking is True
    assert gate.subject_id == first.candidate_id
    summary = manager.summary("run-collection")
    assert len(summary["failed"]) == 1
    assert len(summary["published"]) == 1


def test_agent_repairs_failed_candidate_then_publishes_the_redraw(tmp_path):
    spec = _spec()
    rendered = render_chart(spec.to_dict())
    source_path = tmp_path / "source.png"
    source_path.write_bytes(rendered.images[0].content)
    attachments = AttachmentRegistry(session_id="session-review")
    attachment = attachments.register(str(source_path))
    image_size = (rendered.data["width"], rendered.data["height"])
    attachments.panel_store = _PanelStore([PanelHandoff(
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
    )])
    spec.generation_context = _source_context(attachment.id, "panel_sales")

    class Client:
        def __init__(self):
            self.render_count = 0
            self.assemble_count = 0

        def chat(self, _messages, **kwargs):
            if kwargs.get("tools") is None:
                if self.render_count == 1:
                    return NormalizedResult(content=json.dumps({
                        "decision": "fail",
                        "confidence": 0.9,
                        "checks": {
                            "chart_type": "pass", "orientation": "pass", "layout": "fail",
                            "data_mapping": "pass", "labels": "pass", "readability": "pass",
                        },
                        "issues": [{
                            "code": "baseline_mismatch",
                            "location": "plot.zero_baseline",
                            "severity": "error",
                            "message": "柱体底边未与零基线重合",
                        }],
                    }, ensure_ascii=False))
                return NormalizedResult(content=json.dumps({
                    "decision": "pass",
                    "confidence": 0.95,
                    "checks": {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
                    "issues": [],
                }))
            if self.render_count == 1 and self.assemble_count == 0:
                self.assemble_count += 1
                return NormalizedResult(tool_calls=[ToolCall(
                    "assemble-repair",
                    "assemble_spec",
                    json.dumps({
                        "chart_type": "bar",
                        "points": [{"category": "Q1", "value": 10}, {"category": "Q2", "value": 20}],
                        "x_label": "季度",
                        "y_label": "金额",
                        "generation_context": spec.generation_context.to_dict(),
                    }, ensure_ascii=False),
                )])
            if self.render_count >= 2:
                return NormalizedResult(content="图表已通过审核", finish_reason="stop")
            self.render_count += 1
            return NormalizedResult(tool_calls=[ToolCall(
                f"render-{self.render_count}",
                "render_chart",
                json.dumps({"spec": spec.to_dict()}, ensure_ascii=False),
            )])

    events = []
    registry = ToolRegistry()
    register_chart_tools(registry)
    client = Client()
    answer = Agent(client, registry, attachments=attachments, max_steps=6, trace=events.append).run(
        f"请重绘 {attachment.id}"
    )

    assert answer == "图表已通过审核"
    assert client.render_count == 2
    assert any(event.kind == "review_repair_required" for event in events)
    assert any(event.kind == "review_completed" for event in events)
    assert any(
        event.kind == "review_completed" and event.payload["execution_gate"]["blocking"] is False
        for event in events
    )
    assert not any(event.kind.startswith("chart_review_") for event in events)


def test_versioned_snapshot_restores_all_review_children_from_private_inputs():
    spec = _spec()
    image = render_chart(spec.to_dict()).images[0]
    inputs = {}
    manager = ChartReviewManager()

    published = manager.create_candidate("run-parent", "render-published", image, spec)
    published = _safety(manager, published)
    assert published.publication_status is PublicationStatus.PUBLISHED

    pending = manager.create_candidate(
        "run-parent",
        "render-pending",
        image,
        spec,
        source_attachment_ids=("att_source",),
    )
    pending = _safety(manager, pending)
    semantic = _semantic(pending)
    manager.remember_semantic_result(pending, semantic)
    for candidate in (published, pending):
        inputs[("run-parent", candidate.candidate_id, candidate.review_id, candidate.chart_spec_digest)] = {
            "content": candidate.content,
            "media_type": candidate.media_type,
            "chart_spec": spec.to_dict(),
        }

    state = manager.to_state("run-parent")
    resolver = lambda *key: inputs.get(tuple(key))
    restored = ChartReviewManager(candidate_input_resolver=resolver)
    restored.restore(state, active_run_id="run-child")
    restored_candidates = restored.candidates_for_review(
        "run-child",
        [published.candidate_id, pending.candidate_id],
    )

    assert [candidate.candidate_id for candidate, _ in restored_candidates] == [
        published.candidate_id,
        pending.candidate_id,
    ]
    assert restored_candidates[0][0].publication_status is PublicationStatus.PUBLISHED
    assert restored.semantic_result(restored_candidates[1][0]) == semantic
    assert restored.execution_gate("run-child").subject_id == pending.candidate_id
    resumed_candidate = restored.process(restored_candidates[1][0])
    assert resumed_candidate.publication_status is PublicationStatus.PUBLISHED
    assert resumed_candidate.review is not None
    assert resumed_candidate.review.review_id == pending.review_id
    assert not restored.execution_gate("run-child").blocking

    unavailable = ChartReviewManager(candidate_input_resolver=lambda *_: None)
    with pytest.raises(ValueError, match="review_candidate_input_unavailable"):
        unavailable.restore(state, active_run_id="run-child")
    changed_digest_state = {
        **state,
        "candidates": [
            {**item, "chartSpecDigest": "0" * 64}
            if item["candidateId"] == pending.candidate_id else item
            for item in state["candidates"]
        ],
    }
    with pytest.raises(ValueError, match="review_candidate_identity_mismatch"):
        ChartReviewManager(candidate_input_resolver=lambda *key: inputs[(key[0], key[1], key[2], pending.chart_spec_digest)]).restore(
            changed_digest_state,
            active_run_id="run-child",
        )
    with pytest.raises(ValueError, match="unsupported_review_state_version"):
        ChartReviewManager(candidate_input_resolver=lambda *_: None).restore({"records": [], "executionGate": {}})


def test_review_events_keep_one_canonical_lifecycle():
    payload = enrich_event_payload(
        "review_completed",
        {
            "unit_id": "review:review_1",
            "unit_type": "review",
            "phase": "review",
            "actor": "system",
            "role": "review",
            "transition_id": "review:review_1:1:passed",
            "review_id": "review_1",
            "review_type": "generated_chart",
            "state": "passed",
        },
        run_id="run-1",
        sequence=1,
    )
    assert payload["unit_id"] == "review:review_1"
    assert payload["review_id"] == "review_1"
    assert payload["state"] == "passed"

    with pytest.raises(TimelineProtocolError, match="已废弃"):
        enrich_event_payload("chart_review_completed", {}, run_id="run-1", sequence=2)


def test_review_snapshot_parser_rejects_malformed_result_instead_of_dropping_issues():
    result = ReviewResult(
        status=ReviewStatus.FAILED,
        issues=(ReviewIssue("layout_mismatch", "plot.baseline", "基准线偏移"),),
        decision="fail",
        confidence=0.9,
        review_mode="vlm",
        candidate_id="candidate-1",
        review_id="review-1",
        chart_spec_digest="a" * 64,
    )
    payload = result.to_dict()
    payload["issues"][0]["message"] = None

    assert ReviewResult.from_dict(payload) is None


def test_measurement_observation_does_not_create_generated_review_gate():
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

        def chat(self, _messages, **_kwargs):
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
    registry.register(Tool(
        "measure_bars",
        "measure bars",
        {"type": "object", "properties": {"attachment_id": {"type": "string"}, "panel_id": {"type": "string"}}},
        sensor,
    ))
    answer = Agent(Client(), registry, system="测试审核门禁", max_steps=2, trace=events.append).run("读取 att_1")

    assert answer == "我现在直接结束"
    assert calls == ["measure_bars"]
    assert not any(event.kind == "tool_skipped" for event in events)
    assert any(event.kind == "tool_call" and event.payload.get("tool_name") == "measure_bars" for event in events)
    assert not any(event.kind in {"review_repair_required", "review_gate_required"} for event in events)
    assert any(event.kind == "tool_result" and event.payload.get("tool_name") == "measure_bars" for event in events)
    assert all(not event.kind.startswith("measurement_") for event in events)


def test_gateway_run_summary_keeps_the_derived_gate_projection(tmp_path):
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
