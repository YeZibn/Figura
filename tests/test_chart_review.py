"""Tests for the generated-chart candidate review gate."""

import json

from chartagent.review import (
    CandidateStatus,
    ChartReviewManager,
    PublicationStatus,
    ReviewStatus,
    chart_spec_digest,
    select_review_policy,
    review_candidate_bytes,
    parse_vlm_review,
    build_vlm_review_messages,
    VLM_REVIEW_SYSTEM_PROMPT,
)
from chartagent.review.vlm import review_candidate_with_vlm
from chartagent.attachments import AttachmentRegistry
from dataclasses import replace
import pytest
from chartagent.spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from chartagent.tools.chart.rendering import render_chart
from chartagent.agent import Agent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools import ToolRegistry
from chartagent.tools.chart.catalog import register_chart_tools
from chartagent.gateway.service import GatewayService
from chartagent.runtime import AgentRuntime
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.memory.sqlite import SQLiteAgentMemory
from tests.chart_fixtures import line_chart


def _bar_spec() -> ChartSpec:
    return ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售"),
        axes=Axes(
            x=Axis(label="季度", categories=["Q1", "Q2", "Q3"]),
            y=Axis(label="金额"),
        ),
        dataset=[
            DataPoint(category="Q1", value=10),
            DataPoint(category="Q2", value=20),
            DataPoint(category="Q3", value=30),
        ],
    )


def _other_spec(chart_type: ChartType) -> ChartSpec:
    if chart_type is ChartType.PIE:
        return ChartSpec(
            metadata=ChartMetadata(chart_type=chart_type, title="渠道"),
            dataset=[DataPoint(category="线上", value=3), DataPoint(category="线下", value=2)],
        )
    return ChartSpec(
        metadata=ChartMetadata(chart_type=chart_type, title="趋势"),
        axes=Axes(Axis(label="时间"), Axis(label="数值")),
        dataset=[
            DataPoint(x=1, y=2, series="北区"),
            DataPoint(x=2, y=4, series="北区"),
            DataPoint(x=1, y=1, series="南区"),
            DataPoint(x=2, y=3, series="南区"),
        ],
    )


def test_review_policy_is_source_aware_and_digest_is_stable():
    spec = _bar_spec()
    assert chart_spec_digest(spec) == chart_spec_digest(spec.to_dict())
    assert select_review_policy(spec).semantic_required is False
    assert select_review_policy(spec, source_attachment_ids=("att_source",)).semantic_required is True
    assert select_review_policy(spec, source_attachment_ids=("att_source",)).source_linked is True


def test_direct_candidate_is_independently_reviewed_and_promoted():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate("run-1", "call-1", rendered.images[0], spec)

    assert candidate.status is CandidateStatus.REVIEW_PENDING
    assert candidate.publication_status is PublicationStatus.UNPUBLISHED
    reviewed = manager.process(candidate)

    assert reviewed.review_status is ReviewStatus.COMPLETED
    assert reviewed.publication_status in {
        PublicationStatus.PUBLISHED,
        PublicationStatus.PUBLISHED_WITH_WARNING,
    }
    assert manager.gate("run-1")["ok"] is True


def test_review_revalidates_a_spec_when_the_agent_bypasses_assembly():
    expected = _bar_spec()
    invalid = _bar_spec()
    invalid.axes = None
    rendered = render_chart(expected.to_dict())

    result = review_candidate_bytes(
        invalid,
        rendered.images[0].content,
        media_type="image/png",
        declared_width=1200,
        declared_height=800,
    )

    assert result.status is ReviewStatus.FAILED
    assert result.checks["structure"] == "failed"
    assert any(issue.code == "invalid_chart_spec" for issue in result.issues)


@pytest.mark.parametrize("chart_type", list(ChartType))
def test_independent_reviewer_supports_all_rendered_chart_types(chart_type):
    spec = _bar_spec() if chart_type is ChartType.BAR else _other_spec(chart_type)
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate("run-types", f"call-{chart_type.value}", rendered.images[0], spec)
    reviewed = manager.process(candidate)
    assert reviewed.publication_status is not PublicationStatus.REJECTED, reviewed.review.to_dict() if reviewed.review else None


def test_artifact_safety_review_does_not_call_chart_sensors(monkeypatch):
    png_bytes, payload = line_chart()
    spec = ChartSpec.from_dict(payload)
    called = []
    monkeypatch.setattr("chartagent.tools.chart.observation.line.extract_line_series", lambda _path: called.append(True))

    result = review_candidate_bytes(
        spec,
        png_bytes,
        media_type="image/png",
        declared_width=720,
        declared_height=480,
    )

    assert result.status is ReviewStatus.COMPLETED
    assert result.checks["render_fidelity"] == "not_run"
    assert called == []


def test_source_linked_candidate_cannot_finish_before_vlm_review():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate(
        "run-2",
        "call-2",
        rendered.images[0],
        spec,
        source_attachment_ids=("att_source",),
    )

    assert candidate.status is CandidateStatus.REVIEW_PENDING
    assert manager.gate("run-2")["ok"] is False
    assert manager.gate("run-2")["pending"][0]["candidateId"] == candidate.candidate_id


def test_failed_review_exposes_recovery_action_and_candidate_lineage():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    first = manager.create_candidate("run-repair", "call-1", rendered.images[0], spec, source_attachment_ids=("att_source",))
    failed_result = parse_vlm_review(json.dumps({
        "decision": "fail",
        "confidence": 0.9,
        "checks": {"chart_type": "pass", "orientation": "pass", "layout": "pass", "data_mapping": "fail", "labels": "pass", "readability": "pass"},
        "issues": [{"code": "value_mismatch", "location": "dataset[0].value", "severity": "error", "message": "数据不一致"}],
    }))
    failed = manager.process(first, semantic_result=replace(failed_result, candidate_id=first.candidate_id, review_id=first.review_id, chart_spec_digest=first.chart_spec_digest))
    gate = manager.gate("run-repair")
    assert gate["retryable"] is True
    assert gate["recoveryActions"][0]["action"] == "correct_chart_spec"

    second = manager.create_candidate("run-repair", "call-2", rendered.images[0], spec, source_attachment_ids=("att_source",))
    assert second.parent_candidate_id == first.candidate_id
    assert second.lineage_attempt == 2
    assert gate["failed"][0].get("superseded") is not True


def test_review_correction_budget_ends_in_explicit_unpublished_state():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    result = parse_vlm_review(json.dumps({
        "decision": "fail",
        "confidence": 0.9,
        "checks": {"chart_type": "pass", "orientation": "pass", "layout": "fail", "data_mapping": "pass", "labels": "pass", "readability": "pass"},
        "issues": [{"code": "layout_mismatch", "location": "axes", "severity": "error", "message": "布局不一致"}],
    }))
    current = None
    for index in range(4):
        current = manager.create_candidate("run-exhaust", f"call-{index}", rendered.images[0], spec, source_attachment_ids=("att_source",))
        if current.status is CandidateStatus.RETRY_EXHAUSTED:
            break
        current = manager.process(current, semantic_result=replace(result, candidate_id=current.candidate_id, review_id=current.review_id, chart_spec_digest=current.chart_spec_digest))
    assert current is not None
    assert current.status is CandidateStatus.RETRY_EXHAUSTED
    assert current.publication_status is PublicationStatus.REJECTED
    assert manager.gate("run-exhaust")["retryable"] is False


def test_vlm_review_retries_one_transient_provider_failure():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate("run-vlm-retry", "call", rendered.images[0], spec)

    class Client:
        calls = 0

        def chat(self, _messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary")
            return type("Result", (), {"content": json.dumps({
                "decision": "pass",
                "confidence": 0.9,
                "checks": {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
                "issues": [],
            })})()

    client = Client()
    result = review_candidate_with_vlm(client, candidate, spec)
    assert client.calls == 2
    assert result.decision == "pass"


def test_vlm_review_blocks_a_chartspec_value_mismatch():
    result = parse_vlm_review(json.dumps({
        "decision": "fail",
        "confidence": 0.94,
        "checks": {
            "chart_type": "pass",
            "orientation": "pass",
            "layout": "pass",
            "data_mapping": "fail",
            "labels": "pass",
            "readability": "pass",
        },
        "issues": [{
            "code": "value_mismatch",
            "location": "dataset[1].value",
            "severity": "error",
            "message": "候选图中的数值与 ChartSpec 不一致",
        }],
    }))
    assert result.status is ReviewStatus.COMPLETED
    assert result.blocking is True
    assert result.decision == "fail"
    assert result.issues[0].code == "value_mismatch"


def test_vlm_review_prompt_describes_staged_checks_and_exact_contract():
    assert "整张画布是否发生旋转" in VLM_REVIEW_SYSTEM_PROMPT
    assert "零基线" in VLM_REVIEW_SYSTEM_PROMPT
    assert "bar：" in VLM_REVIEW_SYSTEM_PROMPT
    assert '"decision": "pass | pass_with_warning | fail"' in VLM_REVIEW_SYSTEM_PROMPT
    assert "顶层字段必须且只能是" in VLM_REVIEW_SYSTEM_PROMPT


def test_vlm_review_rejects_extra_top_level_fields():
    payload = {
        "decision": "pass",
        "confidence": 0.95,
        "checks": {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
        "issues": [],
        "extra": "not allowed",
    }
    result = parse_vlm_review(json.dumps(payload))
    assert result.status is ReviewStatus.FAILED
    assert result.issues[0].code == "invalid_vlm_output"


def test_vlm_review_rejects_extra_issue_fields():
    payload = {
        "decision": "fail",
        "confidence": 0.9,
        "checks": {"chart_type": "pass", "orientation": "pass", "layout": "fail", "data_mapping": "pass", "labels": "pass", "readability": "pass"},
        "issues": [{"code": "layout_mismatch", "location": "candidate.plot_area", "severity": "error", "message": "布局错误", "evidence": "extra"}],
    }
    result = parse_vlm_review(json.dumps(payload))
    assert result.status is ReviewStatus.FAILED
    assert result.issues[0].code == "invalid_vlm_output"


@pytest.mark.parametrize(
    "decision, checks, issues",
    [
        (
            "pass",
            {"chart_type": "pass", "orientation": "warning", "layout": "pass", "data_mapping": "pass", "labels": "pass", "readability": "pass"},
            [],
        ),
        (
            "pass_with_warning",
            {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
            [],
        ),
        (
            "fail",
            {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
            [],
        ),
    ],
)
def test_vlm_review_rejects_inconsistent_decision_contract(decision, checks, issues):
    result = parse_vlm_review(json.dumps({"decision": decision, "confidence": 0.8, "checks": checks, "issues": issues}))
    assert result.status is ReviewStatus.FAILED
    assert result.issues[0].code == "invalid_vlm_output"


def test_vlm_review_records_bar_baseline_failure():
    result = parse_vlm_review(json.dumps({
        "decision": "fail",
        "confidence": 0.97,
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
            "location": "candidate.plot_area.zero_baseline",
            "severity": "error",
            "message": "柱体底边未与坐标系零基线重合",
        }],
    }))
    assert result.status is ReviewStatus.COMPLETED
    assert result.blocking is True
    assert result.issues[0].code == "baseline_mismatch"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"decision": "unknown", "confidence": 0.5, "checks": {}, "issues": []}),
        json.dumps({"decision": "pass", "confidence": 2, "checks": {}, "issues": []}),
    ],
)
def test_vlm_review_rejects_malformed_or_unbounded_output(content):
    result = parse_vlm_review(content)
    assert result.status is ReviewStatus.FAILED
    assert result.decision == "fail"
    assert result.issues[0].code == "invalid_vlm_output"


def test_vlm_review_messages_do_not_include_local_paths(tmp_path):
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate(
        "run-message",
        "call-message",
        rendered.images[0],
        spec,
        source_attachment_ids=("att_source",),
    )
    source_path = tmp_path / "private-source.png"
    messages = build_vlm_review_messages(
        candidate,
        spec,
        source_image=rendered.images[0].content,
    )
    assert str(source_path) not in json.dumps(messages, ensure_ascii=False)
    assert any(part.get("type") == "image_url" for part in messages[1]["content"])


def test_vlm_review_requires_matching_candidate_and_review_ids():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate("run-3", "call-3", rendered.images[0], spec, source_attachment_ids=("att_source",))
    semantic = parse_vlm_review(json.dumps({
        "decision": "pass",
        "confidence": 0.9,
        "checks": {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
        "issues": [],
    }))
    mismatched = replace(semantic, candidate_id="cand_wrong", review_id="review_wrong", chart_spec_digest="0" * 64)
    reviewed = manager.process(candidate, semantic_result=mismatched)
    assert reviewed.publication_status is PublicationStatus.REJECTED
    assert reviewed.review is not None
    assert reviewed.review.issues[0].code == "review_identity_mismatch"


def test_gateway_candidate_promotion_requires_matching_completed_review(tmp_path):
    database = tmp_path / "review.db"
    memory = SQLiteAgentMemory("review-session", database=database)
    try:
        store = GatewayHistoryStore(database, artifact_root=tmp_path / "artifacts")
        run_id = "run-review"
        store.create_run(run_id, memory.session.id)
        spec = _bar_spec()
        rendered = render_chart(spec.to_dict())
        manager = ChartReviewManager()
        candidate = manager.create_candidate(run_id, "call", rendered.images[0], spec)
        reviewed = manager.process(candidate)
        image = manager.decorate_image(rendered.images[0], reviewed)

        pending = store.add_candidate(run_id, memory.session.id, image)
        assert pending is not None
        assert "artifactId" not in pending
        assert pending["candidateId"] == candidate.candidate_id
        assert store.promote_candidate(
            run_id,
            memory.session.id,
            candidate.candidate_id,
            "review_wrong",
            candidate.chart_spec_digest,
            candidate_status=reviewed.status.value,
            review_status=reviewed.review_status.value,
            publication_status=reviewed.publication_status.value,
        ) is None
        final = store.promote_candidate(
            run_id,
            memory.session.id,
            candidate.candidate_id,
            candidate.review_id,
            candidate.chart_spec_digest,
            candidate_status=reviewed.status.value,
            review_status=reviewed.review_status.value,
            publication_status=reviewed.publication_status.value,
            review=reviewed.review.to_dict() if reviewed.review else None,
        )
        assert final is not None
        assert final["artifactId"].startswith("artifact_")
        assert store.get_artifact(memory.session.id, run_id, final["artifactId"], artifact_kind="generated_chart") is not None
        assert store.get_candidate(memory.session.id, run_id, candidate.candidate_id) is None
    finally:
        memory.close()


def test_agent_final_answer_is_rejected_while_source_linked_candidate_is_pending():
    spec = _bar_spec().to_dict()

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append(kwargs["tools"])
            if len(self.calls) == 1:
                return NormalizedResult(tool_calls=[ToolCall("render", "render_chart", __import__("json").dumps({"spec": spec}))])
            return NormalizedResult(content="不应直接宣称已验证")

    registry = ToolRegistry()
    register_chart_tools(registry)
    client = Client()
    result = Agent(client, registry, max_steps=2).run("请重绘 att_source")

    assert result == "*stopped: generated chart review failed; no artifact published*"
    assert "review_generated_chart" not in {item["function"]["name"] for item in client.calls[1]}


def test_failed_vlm_review_trace_has_independent_lifecycle_fields(tmp_path):
    import json

    spec = _bar_spec().to_dict()

    source_path = tmp_path / "source.png"
    source_path.write_bytes(render_chart(spec).images[0].content)
    attachments = AttachmentRegistry()
    attachment = attachments.register(str(source_path))

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, _messages, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("tools") is None:
                return NormalizedResult(content=json.dumps({
                    "decision": "fail",
                    "confidence": 0.9,
                    "checks": {
                        "chart_type": "pass", "orientation": "pass", "layout": "pass",
                        "data_mapping": "fail", "labels": "pass", "readability": "pass",
                    },
                    "issues": [{"code": "value_mismatch", "location": "dataset[0]", "severity": "error", "message": "数据不一致"}],
                }))
            if len([item for item in self.calls if item.get("tools") is not None]) == 1:
                return NormalizedResult(
                    tool_calls=[ToolCall("render", "render_chart", json.dumps({"spec": spec}))]
                )
            return NormalizedResult(content="模型不能绕过失败审核")

    events = []
    registry = ToolRegistry()
    register_chart_tools(registry)
    client = Client()
    result = Agent(client, registry, attachments=attachments, max_steps=3, trace=events.append).run(f"请重绘 {attachment.id}")

    assert result == "*stopped: generated chart review failed; no artifact published*"
    assert any(call.get("tools") is None for call in client.calls)
    started = next(event for event in events if event.kind == "chart_review_started")
    assert started.payload["internal_review"] is True
    assert started.payload["tool_count"] == 0
    completed = next(event for event in events if event.kind == "chart_review_completed")
    assert completed.payload["review_mode"] == "vlm"


def test_gateway_publishes_only_after_direct_candidate_review(tmp_path):
    database = tmp_path / "gateway-review.db"

    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                import json

                return NormalizedResult(
                    tool_calls=[
                        ToolCall("render", "render_chart", json.dumps({"spec": _bar_spec().to_dict()}))
                    ]
                )
            return NormalizedResult(content="图表已完成审核")

    def runtime_factory(name, *, run_id, trace_sink, visual_observation_sink):
        memory = SQLiteAgentMemory(name, database=database, create=False)
        registry = ToolRegistry()
        register_chart_tools(registry)
        agent = Agent(
            Client(),
            registry,
            memory=memory,
            run_id=run_id,
            trace=trace_sink,
            visual_observation_sink=visual_observation_sink,
        )
        return AgentRuntime(agent, memory, None)  # type: ignore[arg-type]

    service = GatewayService(database=database, runtime_factory=runtime_factory)
    session_id = service.create_session("gateway-review")['session']['id']
    accepted = service.start_run(session_id, "直接生成")
    run = service.get_run(session_id, accepted["run"]["runId"])
    assert run.wait_terminal(timeout=5)
    generated = [event for event in run.iter_events() if event.kind == "generated_chart"]
    assert generated
    artifact = generated[-1].payload["artifacts"][0]
    assert artifact["publicationStatus"] in {"published", "published_with_warning"}
    assert artifact["artifactId"].startswith("artifact_")
    assert service.get_generated_artifact(session_id, run.run_id, artifact["artifactId"])[1] == "image/png"
    service.close()
