"""Tests for the generated-chart candidate review gate."""

from chartagent.review import (
    CandidateStatus,
    ChartReviewManager,
    PublicationStatus,
    ReviewStatus,
    chart_spec_digest,
    select_review_policy,
    review_candidate_bytes,
)
import pytest
from chartagent.spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from chartagent.tools.chart.rendering import render_chart
from chartagent.agent import Agent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools import ToolRegistry, ToolResult
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


def test_line_reviewer_consumes_trace_and_confirmed_point_evidence(monkeypatch):
    png_bytes, payload = line_chart()
    spec = ChartSpec.from_dict(payload)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult([]),
    )

    result = review_candidate_bytes(
        spec,
        png_bytes,
        media_type="image/png",
        declared_width=720,
        declared_height=480,
    )

    geometry = next(item for item in result.evidence if item["kind"] == "line_geometry")
    assert geometry["traceCount"] == 2
    assert geometry["traceVertexCount"] > 0
    assert geometry["pointCount"] >= 2


def test_source_linked_candidate_cannot_finish_before_review_tool():
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


def test_reviewer_blocks_a_chartspec_value_mismatch():
    expected = _bar_spec()
    actual = _bar_spec()
    actual.dataset[1].value = 200
    rendered = render_chart(actual.to_dict())
    result = review_candidate_bytes(
        expected,
        rendered.images[0].content,
        media_type="image/png",
        declared_width=1200,
        declared_height=800,
    )
    assert result.status is ReviewStatus.FAILED
    assert any(issue.code in {"bar_value_mismatch", "bar_count_mismatch"} for issue in result.issues)


def test_review_tool_requires_matching_candidate_and_review_ids():
    spec = _bar_spec()
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager()
    candidate = manager.create_candidate("run-3", "call-3", rendered.images[0], spec)
    tool = manager.review_tool()

    denied = tool.fn(candidate.candidate_id, "review_wrong")
    assert "error" in denied
    accepted = tool.fn(candidate.candidate_id, candidate.review_id)
    assert accepted["candidate"]["candidateId"] == candidate.candidate_id


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

    assert result == "*stopped: generated chart review incomplete*"
    assert "review_generated_chart" in {item["function"]["name"] for item in client.calls[1]}


def test_pending_review_trace_has_independent_lifecycle_fields():
    import json

    spec = _bar_spec().to_dict()

    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, _messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return NormalizedResult(
                    tool_calls=[ToolCall("render", "render_chart", json.dumps({"spec": spec}))]
                )
            return NormalizedResult(content="等待审核")

    events = []
    registry = ToolRegistry()
    register_chart_tools(registry)
    result = Agent(Client(), registry, max_steps=2, trace=events.append).run("请重绘 att_source")

    assert result == "*stopped: generated chart review incomplete*"
    started = next(event for event in events if event.kind == "chart_review_started")
    assert started.payload["candidate_status"] == "review_pending"
    assert started.payload["review_status"] == "pending"
    assert started.payload["publication_status"] == "unpublished"
    assert "status" not in started.payload


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
