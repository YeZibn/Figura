"""Tests for deterministic ChartSpec-to-image generation."""

from io import BytesIO
import warnings
import pytest
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from PIL import Image

from chartagent.spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from chartagent.tools import ToolRegistry, dispatch_observation
from chartagent.tools.chart import rendering
from chartagent.tools.chart.rendering import MAX_CHART_HEIGHT, render_chart
from chartagent.tools.chart.catalog import register_chart_tools
from chartagent.tools.chart.specification import validate_spec
from chartagent.tools.core.result import ToolResult


def _spec(chart_type: ChartType) -> ChartSpec:
    if chart_type is ChartType.BAR:
        return ChartSpec(
            metadata=ChartMetadata(chart_type=chart_type, title="销售额"),
            axes=Axes(x=Axis(label="季度", categories=["Q1", "Q2", "Q3"]), y=Axis(label="金额")),
            dataset=[
                DataPoint(category="Q1", value=10),
                DataPoint(category="Q2", value=20),
                DataPoint(category="Q3", value=30),
            ],
        )
    if chart_type is ChartType.PIE:
        return ChartSpec(
            metadata=ChartMetadata(chart_type=chart_type, title="渠道占比"),
            dataset=[DataPoint(category="线上", value=3), DataPoint(category="线下", value=2)],
        )
    return ChartSpec(
        metadata=ChartMetadata(chart_type=chart_type, title="趋势"),
        axes=Axes(x=Axis(label="时间"), y=Axis(label="数值")),
        dataset=[
            DataPoint(x=1, y=2, series="北区"),
            DataPoint(x=2, y=4, series="北区"),
            DataPoint(x=1, y=1, series="南区"),
            DataPoint(x=2, y=3, series="南区"),
        ],
    )


def test_render_chart_supports_all_chart_types_and_fixed_dimensions():
    for chart_type in ChartType:
        result = render_chart(_spec(chart_type).to_dict())

        assert isinstance(result, ToolResult)
        assert result.data["kind"] == "generated_chart"
        assert result.data["chart_type"] == chart_type.value
        assert result.data["width"] == 1200
        assert result.data["height"] == 800
        assert result.data["byte_count"] == len(result.images[0].content)
        with Image.open(BytesIO(result.images[0].content)) as image:
            assert image.format == "PNG"
            assert image.size == (1200, 800)
        assert result.data["validation"]["status"] in {"passed", "warning"}
        assert result.data["validation"]["checks"]["artifact"] == "passed"
        assert result.data["font"]["status"] in {"resolved", "fallback"}
        assert result.data["font"]["source"] in {"configured", "system", "fallback"}


def test_render_chart_preserves_multi_series_metadata():
    result = render_chart(_spec(ChartType.LINE).to_dict())

    assert isinstance(result, ToolResult)
    assert result.data["series"] == ["北区", "南区"]
    assert result.data["point_count"] == 4


def test_configured_font_is_used_without_exposing_path(monkeypatch):
    font_path = font_manager.findfont(FontProperties(family="DejaVu Sans"))
    monkeypatch.setenv(rendering.FONT_PATH_ENV, font_path)
    monkeypatch.setattr(rendering, "_font_supports_cjk", lambda _path: True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result = render_chart(_spec(ChartType.BAR).to_dict())

    assert isinstance(result, ToolResult)
    assert result.data["font"] == {
        "status": "resolved",
        "source": "configured",
        "family": "DejaVu Sans",
    }
    assert font_path not in str(result.data)
    assert font_path not in str(result.images[0].metadata)
    assert result.warnings == ()


def test_invalid_configured_font_returns_bounded_fallback(monkeypatch):
    monkeypatch.setenv(rendering.FONT_PATH_ENV, "/missing/figura-cjk-font.ttf")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result = render_chart(_spec(ChartType.PIE).to_dict())

    assert isinstance(result, ToolResult)
    assert result.data["font"] == {
        "status": "fallback",
        "source": "fallback",
        "family": None,
    }
    assert len(result.warnings) == 1
    assert rendering.FONT_PATH_ENV in result.warnings[0]
    assert "/missing/" not in str(result.data)


def test_system_font_resolution_is_ordered_and_reported(monkeypatch):
    font_path = font_manager.findfont(FontProperties(family="DejaVu Sans"))
    seen_families: list[str] = []

    def fake_findfont(properties, *, fallback_to_default=True):
        if fallback_to_default is not False:
            return font_path
        family = properties.get_family()[0]
        seen_families.append(family)
        if family == rendering._CJK_FAMILIES[1]:
            return font_path
        raise ValueError("font not found")

    monkeypatch.delenv(rendering.FONT_PATH_ENV, raising=False)
    monkeypatch.setattr(rendering.font_manager, "findfont", fake_findfont)
    monkeypatch.setattr(rendering, "_font_supports_cjk", lambda _path: True)
    monkeypatch.setattr(rendering, "_font_name", lambda _properties, _path: "DejaVu Sans")

    resolved = rendering._resolve_font()

    assert resolved.status == "resolved"
    assert resolved.source == "system"
    assert resolved.family == "DejaVu Sans"
    assert seen_families == list(rendering._CJK_FAMILIES[:2])


def test_chinese_specs_keep_font_diagnostics_for_all_chart_types(monkeypatch):
    monkeypatch.setenv(rendering.FONT_PATH_ENV, "")
    for chart_type in ChartType:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = render_chart(_spec(chart_type).to_dict())
        assert isinstance(result, ToolResult)
        assert result.data["font"]["status"] in {"resolved", "fallback"}
        if result.data["font"]["status"] == "resolved":
            assert result.warnings == ()
            assert not any("Glyph" in str(item.message) for item in caught)
        else:
            assert result.warnings


def test_render_chart_rejects_negative_or_zero_pie_totals():
    negative = _spec(ChartType.PIE).to_dict()
    negative["dataset"][0]["value"] = -1
    zero = _spec(ChartType.PIE).to_dict()
    zero["dataset"] = [{"category": "空", "value": 0}]

    negative_result = render_chart(negative)
    zero_result = render_chart(zero)

    assert isinstance(negative_result, dict)
    assert any(issue["location"] == "dataset[0].value" for issue in negative_result["issues"])
    assert isinstance(zero_result, dict)
    assert any(issue["location"] == "dataset" for issue in zero_result["issues"])


def test_render_chart_rejects_invalid_specs_and_dimensions():
    invalid = {"metadata": {"chart_type": "bar"}, "dataset": [{"category": "Q1", "value": "bad"}]}

    invalid_result = render_chart(invalid)
    oversized_result = render_chart(_spec(ChartType.BAR).to_dict(), height=MAX_CHART_HEIGHT + 1)

    assert isinstance(invalid_result, dict)
    assert invalid_result["error"] == "ChartSpec cannot be rendered"
    assert isinstance(oversized_result, dict)
    assert any(issue["location"] == "dimensions" for issue in oversized_result["issues"])


def test_render_chart_is_registered_and_dispatches_visual_payload():
    registry = ToolRegistry()
    register_chart_tools(registry)
    result = dispatch_observation(
        registry,
        "render_chart",
        '{"spec": ' + __import__("json").dumps(_spec(ChartType.BAR).to_dict(), ensure_ascii=False) + "}",
    )

    assert result.images
    assert '"kind": "generated_chart"' in result.content


def _grouped_spec_with_missing_value() -> dict:
    return {
        "metadata": {"chart_type": "bar", "title": "分组"},
        "axes": {
            "x": {"label": "类别", "categories": ["A", "B"]},
            "y": {"label": "数值"},
        },
        "dataset": [
            {"category": "A", "value": 1, "series": "甲"},
            {"category": "A", "value": 2, "series": "乙"},
            {"category": "B", "value": 3, "series": "乙"},
        ],
    }


@pytest.mark.parametrize(
    "spec",
    [
        {"metadata": {"chart_type": "pie"}, "dataset": [{"category": "A", "value": -1}, {"category": "B", "value": 2}]},
        {"metadata": {"chart_type": "pie"}, "dataset": [{"category": "A", "value": 0}]},
        {"metadata": {"chart_type": "bar"}, "axes": {"x": {"label": "x"}, "y": {"label": "y"}}, "dataset": [{"category": "A", "value": 1}, {"category": "A", "value": 2}]},
        _grouped_spec_with_missing_value(),
        {"metadata": {"chart_type": "line"}, "axes": {"x": {"label": "x", "min_value": 2, "max_value": 1}, "y": {"label": "y"}}, "dataset": [{"x": 1, "y": 2}]},
    ],
)
def test_validate_spec_and_render_chart_agree_on_generation_eligibility(spec):
    validation = validate_spec(spec)
    rendered = render_chart(spec)

    assert validation["ok"] is False
    assert isinstance(rendered, dict)
    assert rendered["validation"]["status"] == "failed"


def test_grouped_bar_requires_explicit_zero_for_each_series_category():
    missing = render_chart(_grouped_spec_with_missing_value())
    complete = _grouped_spec_with_missing_value()
    complete["dataset"].append({"category": "B", "value": 0, "series": "甲"})

    assert isinstance(missing, dict)
    assert any(issue["code"] == "missing_category_value" for issue in missing["validation"]["issues"])
    assert isinstance(render_chart(complete), ToolResult)


def test_render_chart_applies_numeric_axis_ranges(monkeypatch):
    observed: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}

    def capture(fig, ax, spec):
        observed["limits"] = (tuple(float(value) for value in ax.get_xlim()), tuple(float(value) for value in ax.get_ylim()))
        return []

    monkeypatch.setattr(rendering, "_audit_figure", capture)
    spec = _spec(ChartType.LINE).to_dict()
    spec["axes"]["x"].update({"min_value": 1, "max_value": 2})
    spec["axes"]["y"].update({"min_value": 0, "max_value": 5})

    result = render_chart(spec)

    assert isinstance(result, ToolResult)
    assert observed["limits"] == ((1.0, 2.0), (0.0, 5.0))
    assert result.data["validation"]["checks"]["artifact"] == "passed"


def test_render_chart_respects_declared_bar_category_order():
    spec = _spec(ChartType.BAR).to_dict()
    spec["axes"]["x"]["categories"] = ["Q3", "Q1", "Q2"]

    result = render_chart(spec)

    assert isinstance(result, ToolResult)
    assert result.data["validation"]["checks"]["fidelity"] == "passed"


def test_artist_fidelity_failure_does_not_publish_image(monkeypatch):
    monkeypatch.setattr(rendering, "_render_bar", lambda ax, spec, font: ax.bar([0], [1]))

    result = render_chart(_spec(ChartType.BAR).to_dict())

    assert isinstance(result, dict)
    assert result["validation"]["status"] == "failed"
    assert any(issue["code"] == "artist_count_mismatch" for issue in result["validation"]["issues"])


def test_dense_category_layout_returns_explicit_warning():
    categories = [f"类别{i}" for i in range(13)]
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="密集类别"),
        axes=Axes(x=Axis(label="类别", categories=categories), y=Axis(label="数值")),
        dataset=[DataPoint(category=category, value=index + 1) for index, category in enumerate(categories)],
    )

    result = render_chart(spec.to_dict())

    assert isinstance(result, ToolResult)
    assert result.data["validation"]["status"] == "warning"
    assert result.data["validation"]["checks"]["layout"] == "warning"
    assert any(issue["code"] == "label_density" for issue in result.data["validation"]["issues"])


def test_dense_legend_layout_returns_explicit_warning():
    dataset = [
        DataPoint(x=x, y=x + index, series=f"系列{index}")
        for index in range(9)
        for x in (0, 1)
    ]
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.LINE, title="多系列"),
        axes=Axes(x=Axis(label="时间"), y=Axis(label="数值")),
        dataset=dataset,
    )

    result = render_chart(spec.to_dict())

    assert isinstance(result, ToolResult)
    assert result.data["validation"]["status"] == "warning"
    assert result.data["validation"]["checks"]["layout"] == "warning"
    assert any(issue["code"] == "legend_density" for issue in result.data["validation"]["issues"])


def test_render_chart_rejects_blank_encoded_png(monkeypatch):
    def blank_savefig(_figure, target, **_kwargs):
        Image.new("RGB", (1200, 800), "white").save(target, format="PNG")

    monkeypatch.setattr(rendering.plt.Figure, "savefig", blank_savefig)

    result = render_chart(_spec(ChartType.BAR).to_dict())

    assert isinstance(result, dict)
    assert any(issue["code"] == "blank_artifact" for issue in result["validation"]["issues"])


def test_render_chart_rejects_malformed_encoded_png(monkeypatch):
    def malformed_savefig(_figure, target, **_kwargs):
        target.write(b"not a png")

    monkeypatch.setattr(rendering.plt.Figure, "savefig", malformed_savefig)

    result = render_chart(_spec(ChartType.BAR).to_dict())

    assert isinstance(result, dict)
    assert any(issue["code"] == "artifact_decode" for issue in result["validation"]["issues"])


def test_validation_diagnostics_are_bounded_and_do_not_include_image_bytes_or_paths():
    result = render_chart(_spec(ChartType.BAR).to_dict())

    assert isinstance(result, ToolResult)
    serialized = str(result.data)
    assert len(result.data["validation"]["issues"]) <= 32
    assert "content" not in serialized
    assert "/Users/" not in serialized
