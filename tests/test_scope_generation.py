"""Regression tests for scope-aware generation context and candidate identity."""

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from chartagent.review import ChartReviewManager
from chartagent.attachments import AttachmentRegistry
from chartagent.panels import PanelHandoff
from chartagent.spec import (
    ChartCoverage,
    ChartFigure,
    ChartFigureItem,
    ChartMetadata,
    ChartSpec,
    ChartSpecCollection,
    ChartType,
    CoverageBasis,
    CoverageStatus,
    DataPoint,
    GenerationContext,
    GenerationCoverage,
    GenerationMode,
    GenerationSourceScope,
    FigureLayout,
    FigureSource,
    SelectionBasis,
)
from chartagent.source_scope import resolve_generation_scope
from chartagent.tools.chart.rendering import render_chart
from chartagent.tools.chart.specification import assemble_spec
from chartagent.tools.chart.catalog import CHART_TOOLS, register_chart_tools
from chartagent.tools.core.result import GeneratedImage
from chartagent.tools.core import ToolRegistry, dispatch_observation


def _transform_context() -> GenerationContext:
    return GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope("att_scope", ("panel_left",)),
        coverage=GenerationCoverage(
            basis=CoverageBasis.REQUESTED_SUBSET,
            source_series=("Actual", "Target"),
            represented_series=("Actual",),
            intentionally_omitted_series=("Target",),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="将左侧面板的 Actual 系列转换为饼图",
    )


def _pie_spec() -> ChartSpec:
    return ChartSpec(
        metadata=ChartMetadata(ChartType.PIE, title="Actual"),
        dataset=[DataPoint(category="A", value=1), DataPoint(category="B", value=2)],
        generation_context=_transform_context(),
    )


def test_generation_context_round_trips_on_single_chart_spec() -> None:
    spec = _pie_spec()

    assert spec.validate() == []
    rebuilt = ChartSpec.from_dict(spec.to_dict())

    assert rebuilt == spec
    assert rebuilt.generation_context is not None
    assert rebuilt.generation_context.source_scope is not None
    assert rebuilt.generation_context.source_scope.panel_ids == ("panel_left",)


def test_generation_context_round_trips_on_figure_collection() -> None:
    figure = ChartFigure(
        figure_id="figure-left",
        source=FigureSource("att_scope", "panel_left"),
        layout=FigureLayout("grid", 1),
        charts=[ChartFigureItem("pie", _pie_spec())],
        coverage=ChartCoverage(["Actual", "Target"], ["Actual"], ["Target"], "incomplete"),
        generation_context=_transform_context(),
    )
    collection = ChartSpecCollection("collection-scope", [figure])

    rebuilt = ChartSpecCollection.from_dict(collection.to_dict())

    assert rebuilt == collection
    assert rebuilt.figures[0].generation_context == _transform_context()


def test_collection_members_keep_independent_context_and_scope() -> None:
    right_context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope("att_scope", ("panel_right",)),
        coverage=GenerationCoverage(
            basis=CoverageBasis.REQUESTED_SUBSET,
            source_series=("Forecast",),
            represented_series=("Forecast",),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="转换右侧 panel",
    )
    left = ChartFigure(
        figure_id="figure-left",
        source=FigureSource("att_scope", "panel_left"),
        layout=FigureLayout("grid", 1),
        charts=[ChartFigureItem("left", _pie_spec())],
        coverage=ChartCoverage(["Actual", "Target"], ["Actual"], ["Target"], "complete"),
        generation_context=_transform_context(),
    )
    right = ChartFigure(
        figure_id="figure-right",
        source=FigureSource("att_scope", "panel_right"),
        layout=FigureLayout("grid", 1),
        charts=[ChartFigureItem(
            "right",
            ChartSpec(
                metadata=ChartMetadata(ChartType.PIE, title="Forecast"),
                dataset=[DataPoint(category="A", value=2)],
                generation_context=right_context,
            ),
        )],
        coverage=ChartCoverage(["Forecast"], ["Forecast"], [], "complete"),
        generation_context=right_context,
    )

    rebuilt = ChartSpecCollection.from_dict(ChartSpecCollection("collection-two", [left, right]).to_dict())

    assert rebuilt.figures[0].generation_context.source_scope.panel_ids == ("panel_left",)
    assert rebuilt.figures[1].generation_context.source_scope.panel_ids == ("panel_right",)
    assert rebuilt.figures[1].charts[0].spec.generation_context.source_scope.panel_ids == ("panel_right",)


def test_legacy_direct_chart_spec_stays_source_free() -> None:
    legacy = ChartSpec(
        metadata=ChartMetadata(ChartType.PIE, title="Legacy"),
        dataset=[DataPoint(category="A", value=1)],
    )

    rebuilt = ChartSpec.from_dict(legacy.to_dict())

    assert rebuilt.generation_context is None
    assert rebuilt.validate() == []


def test_source_linked_candidate_without_context_is_marked_unbound() -> None:
    manager = ChartReviewManager()
    image = GeneratedImage(content=b"png", media_type="image/png", caption="candidate")
    candidate = manager.create_candidate(
        "run-scope",
        "call-scope",
        image,
        ChartSpec(
            metadata=ChartMetadata(ChartType.PIE, title="Legacy source"),
            dataset=[DataPoint(category="A", value=1)],
        ),
        source_attachment_ids=("att_scope",),
    )

    assert candidate.context_status == "unbound"
    assert candidate.generation_context is None
    assert candidate.safe_metadata()["contextStatus"] == "unbound"


class _PanelStore:
    def __init__(self, handoffs: list[PanelHandoff]) -> None:
        self.handoffs = handoffs

    def list_panel_handoffs(self, attachment_id: str):
        return [item for item in self.handoffs if item.attachment_id == attachment_id]

    def get_panel_handoff(self, panel_id: str, *, attachment_id: str | None = None, revision: int | None = None):
        for handoff in self.handoffs:
            if handoff.panel_id != panel_id or handoff.attachment_id != attachment_id:
                continue
            if revision is not None and handoff.revision != revision:
                continue
            return handoff if handoff.status == "active" else None
        return None


def _scoped_attachments(tmp_path: Path) -> tuple[AttachmentRegistry, str]:
    image_path = tmp_path / "dashboard.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    attachments = AttachmentRegistry(session_id="session-scope")
    attachment = attachments.register(str(image_path))
    handoff = PanelHandoff(
        session_id="session-scope",
        attachment_id=attachment.id,
        attachment_sha256=attachment.sha256,
        panel_id="panel_left",
        revision=1,
        name="Left",
        slug="left",
        role="chart",
        chart_type="bar",
        source_bbox=(10, 10, 50, 40),
        analysis_scope=(12, 12, 40, 30),
        status="active",
    )
    attachments.panel_store = _PanelStore([handoff])
    return attachments, attachment.id


def _multi_scoped_attachments(tmp_path: Path) -> tuple[AttachmentRegistry, str]:
    image_path = tmp_path / "multi-panel.png"
    Image.new("RGB", (180, 90), "white").save(image_path)
    attachments = AttachmentRegistry(session_id="session-scope")
    attachment = attachments.register(str(image_path))
    attachments.panel_store = _PanelStore([
        PanelHandoff(
            session_id="session-scope", attachment_id=attachment.id, attachment_sha256=attachment.sha256,
            panel_id="panel_left", revision=1, name="Left", slug="left", role="chart", chart_type="bar",
            source_bbox=(8, 8, 54, 44), analysis_scope=(10, 10, 40, 30), status="active",
        ),
        PanelHandoff(
            session_id="session-scope", attachment_id=attachment.id, attachment_sha256=attachment.sha256,
            panel_id="panel_right", revision=1, name="Right", slug="right", role="chart", chart_type="line",
            source_bbox=(92, 16, 66, 54), analysis_scope=(100, 20, 50, 40), status="active",
        ),
    ])
    return attachments, attachment.id


def test_source_scope_resolver_returns_only_authorized_panel_crop(tmp_path: Path) -> None:
    attachments, attachment_id = _scoped_attachments(tmp_path)
    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left",)),
        coverage=GenerationCoverage(
            basis=CoverageBasis.REQUESTED_SUBSET,
            represented_series=("Actual",),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="转换左侧 panel",
    )

    resolved = resolve_generation_scope(attachments, context)

    assert resolved.resolved
    assert resolved.panel_ids == ("panel_left",)
    assert resolved.effective_scope["bbox_source_px"] == [12, 12, 40, 30]
    assert len(resolved.content) > 0
    assert "canonical_path" not in resolved.to_dict()


def test_source_scope_resolver_marks_changed_attachment_stale(tmp_path: Path) -> None:
    attachments, attachment_id = _scoped_attachments(tmp_path)
    attachment = attachments.get(attachment_id)
    assert attachment is not None
    Path(attachment.canonical_path).write_bytes(b"changed")

    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left",)),
        coverage=GenerationCoverage(
            basis=CoverageBasis.REQUESTED_SUBSET,
            represented_series=("Actual",),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="转换左侧 panel",
    )

    resolved = resolve_generation_scope(attachments, context)

    assert resolved.status == "stale"
    assert resolved.content == b""


def test_assemble_and_render_preserve_requested_subset_context() -> None:
    context = _transform_context()
    payload = assemble_spec(
        "pie",
        [{"category": "A", "value": 1}, {"category": "B", "value": 2}],
        title="Actual",
        generation_context=context.to_dict(),
    )

    assert "error" not in payload
    assert payload["generation_context"]["coverage"]["basis"] == "requested_subset"
    rendered = render_chart(payload)
    assert rendered.data["generation_context"]["mode"] == "transform"
    assert rendered.images[0].metadata["generation_context"]["source_scope"]["panel_ids"] == ["panel_left"]


def test_assemble_rejects_figure_context_source_mismatch() -> None:
    context = _transform_context()
    figure = {
        "figure_id": "figure-right",
        "source": {"attachment_id": "att_scope", "panel_id": "panel_right"},
        "generation_context": context.to_dict(),
        "layout": {"type": "grid", "columns": 1},
        "coverage": {
            "basis": "requested_subset",
            "source_series": ["Actual", "Target"],
            "represented_series": ["Actual"],
            "omitted_series": ["Target"],
            "status": "complete",
        },
        "charts": [{
            "chart_id": "actual",
            "chart_type": "pie",
            "points": [{"category": "A", "value": 1}],
        }],
    }

    result = assemble_spec(figure=figure)

    assert result["error"] == "generation_context panel does not match figure source"
    assert result["issues"][0]["location"].endswith("source_scope.panel_ids")


def test_source_scope_resolver_does_not_require_source_for_synthesis() -> None:
    context = GenerationContext(
        mode=GenerationMode.SYNTHESIZE,
        source_scope=None,
        coverage=GenerationCoverage(),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="直接生成一张饼图",
    )

    resolved = resolve_generation_scope(None, context)

    assert resolved.status == "not_applicable"


def test_review_manager_uses_resolver_crop_and_fails_closed_after_attachment_change(tmp_path: Path) -> None:
    attachments, attachment_id = _scoped_attachments(tmp_path)
    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left",), revision=1),
        coverage=GenerationCoverage(
            basis=CoverageBasis.REQUESTED_SUBSET,
            represented_series=("Actual",),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="只审核左侧 panel",
    )
    spec = ChartSpec(
        metadata=ChartMetadata(ChartType.PIE, title="Actual"),
        dataset=[DataPoint(category="A", value=1), DataPoint(category="B", value=2)],
        generation_context=context,
    )
    rendered = render_chart(spec.to_dict())
    manager = ChartReviewManager(attachments=attachments)
    candidate = manager.create_candidate(
        "run-scope-review",
        "call-scope-review",
        rendered.images[0],
        spec,
        source_attachment_ids=(attachment_id,),
    )

    source_payload = manager.source_payload(candidate)
    assert source_payload is not None
    with Image.open(BytesIO(source_payload[0])) as crop:
        assert crop.size == (40, 30)
    assert manager.source_resolution(candidate).effective_scope["bbox_source_px"] == [12, 12, 40, 30]

    attachment = attachments.get(attachment_id)
    assert attachment is not None
    Path(attachment.canonical_path).write_bytes(b"changed")
    assert manager.source_payload(candidate) is None
    assert manager.source_resolution(candidate).status == "stale"


def test_authorized_measurement_fails_closed_for_cross_panel_and_ambiguous_scope(tmp_path: Path) -> None:
    attachments, attachment_id = _multi_scoped_attachments(tmp_path)
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)

    left_context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left",), revision=1),
        coverage=GenerationCoverage(
            basis=CoverageBasis.REQUESTED_SUBSET,
            represented_series=("Actual",),
            status=CoverageStatus.COMPLETE,
        ),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="测量左侧 panel",
    )
    outside = json.loads(dispatch_observation(
        registry,
        "measure_bars",
        json.dumps({
            "attachment_id": attachment_id,
            "panel_id": "panel_right",
            "generation_context": left_context.to_dict(),
        }, ensure_ascii=False),
    ).content)
    assert outside["error"] == "panel_id is outside generation_context source scope"

    both_context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left", "panel_right"), revision=1),
        coverage=left_context.coverage,
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="组合 panel 证据",
    )
    ambiguous = json.loads(dispatch_observation(
        registry,
        "measure_bars",
        json.dumps({"attachment_id": attachment_id, "generation_context": both_context.to_dict()}, ensure_ascii=False),
    ).content)
    assert ambiguous["error"] == "measurement scope is ambiguous across multiple panels"

    outside_target = json.loads(dispatch_observation(
        registry,
        "measure_bars",
        json.dumps({
            "attachment_id": attachment_id,
            "panel_id": "panel_left",
            "generation_context": left_context.to_dict(),
            "measurement_target": {
                "target_id": "outside-left",
                "panel_id": "panel_left",
                "bbox_source_px": [100, 20, 10, 10],
                "source_image_size": [180, 90],
                "fields": ["value"],
                "reason": "越界目标",
            },
        }, ensure_ascii=False),
    ).content)
    assert "measurement target routing failed" in outside_target["error"]
    assert outside_target["measurement_repair"]["code"] == "measurement_target_invalid"

    unscoped = json.loads(dispatch_observation(
        registry,
        "measure_bars",
        json.dumps({"attachment_id": attachment_id}, ensure_ascii=False),
    ).content)
    assert unscoped["error"] == "panel_id is required when an attachment has multiple active panels"
    assert unscoped["scope"]["status"] == "rejected"


def test_source_scope_resolver_unions_multiple_panels_without_widening_to_full_attachment(tmp_path: Path) -> None:
    attachments, attachment_id = _multi_scoped_attachments(tmp_path)
    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left", "panel_right")),
        coverage=GenerationCoverage(basis=CoverageBasis.REQUESTED_SUBSET, represented_series=("Actual",), status=CoverageStatus.COMPLETE),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="组合两个已声明面板的结果",
    )

    resolved = resolve_generation_scope(attachments, context)

    assert resolved.resolved
    assert resolved.effective_scope["bbox_source_px"] == [10, 10, 140, 50]
    assert resolved.effective_scope["panel_revisions"] == {"panel_left": 1, "panel_right": 1}
    assert resolved.effective_scope["local_image_size"] == [140, 50]
    assert resolved.effective_scope["bbox_source_px"] != [0, 0, 180, 90]


def test_source_scope_resolver_rejects_missing_panel_and_stale_revision(tmp_path: Path) -> None:
    attachments, attachment_id = _scoped_attachments(tmp_path)
    missing_panel = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_missing",)),
        coverage=GenerationCoverage(basis=CoverageBasis.REQUESTED_SUBSET, represented_series=("Actual",), status=CoverageStatus.COMPLETE),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="检查缺失面板",
    )
    stale_revision = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope(attachment_id, ("panel_left",), revision=2),
        coverage=GenerationCoverage(basis=CoverageBasis.REQUESTED_SUBSET, represented_series=("Actual",), status=CoverageStatus.COMPLETE),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="检查过期面板",
    )

    missing = resolve_generation_scope(attachments, missing_panel)
    stale = resolve_generation_scope(attachments, stale_revision)

    assert missing.status == "ambiguous"
    assert stale.status == "stale"
    assert missing.content == b"" and stale.content == b""


def test_chart_measurement_schemas_share_scope_and_candidate_contracts() -> None:
    measurement_names = {"measure_bars", "extract_line_series", "extract_pie_slices", "extract_scatter_points"}
    for tool in CHART_TOOLS:
        if tool.name not in measurement_names:
            continue
        properties = tool.parameters["properties"]
        assert {"measurement_target", "observation_scope", "generation_context", "candidate_id", "candidate_attempt"}.issubset(properties)
        assert tool.parameters["additionalProperties"] is False
        assert properties["measurement_target"]["additionalProperties"] is False
        assert properties["observation_scope"]["additionalProperties"] is False
        assert "不会自动触发" in properties["measurement_target"]["description"]
        assert "不会自动触发" in tool.description


def test_authorized_measurement_schema_keeps_the_same_contract() -> None:
    attachments = AttachmentRegistry(session_id="session-schema")
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    for name in ("measure_bars", "extract_line_series", "extract_pie_slices", "extract_scatter_points"):
        public = registry.get(name)
        assert public is not None
        properties = public.parameters["properties"]
        assert {"attachment_id", "panel_id", "measurement_target", "observation_scope", "generation_context", "candidate_id", "candidate_attempt"}.issubset(properties)
        assert public.parameters["additionalProperties"] is False
