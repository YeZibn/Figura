"""Tests for deterministic ChartSpec-to-image generation."""

from io import BytesIO

from PIL import Image

from chartagent.spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from chartagent.tools import ToolRegistry, dispatch_observation
from chartagent.tools.chart.generation import MAX_CHART_HEIGHT, render_chart
from chartagent.tools.chart.register import register_chart_tools
from chartagent.tools.result import ToolResult


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


def test_render_chart_preserves_multi_series_metadata():
    result = render_chart(_spec(ChartType.LINE).to_dict())

    assert isinstance(result, ToolResult)
    assert result.data["series"] == ["北区", "南区"]
    assert result.data["point_count"] == 4


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
