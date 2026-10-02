from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from figura.charts.chartfigure import parse_chart_figure
from figura.charts.chartfigure.rendering import render_chart_figure_image


def _chart_spec(chart_type: str) -> dict[str, object]:
    if chart_type == "bar":
        return {
            "schema_version": 1,
            "metadata": {"chart_type": "bar", "title": "月度销售"},
            "axes": {
                "x": {"label": "月份", "categories": ["一月", "二月"]},
                "y": {"label": "销售额", "min_value": 0, "max_value": 20},
            },
            "dataset": [
                {"category": "一月", "value": 10, "series": "北区"},
                {"category": "二月", "value": 15, "series": "北区"},
                {"category": "一月", "value": 12, "series": "南区"},
                {"category": "二月", "value": 18, "series": "南区"},
            ],
        }
    if chart_type == "line":
        return {
            "schema_version": 1,
            "metadata": {"chart_type": "line", "title": "Monthly trend"},
            "axes": {
                "x": {"label": "Month", "categories": ["Jan", "Feb"]},
                "y": {"label": "Sales", "min_value": 0, "max_value": 20},
            },
            "dataset": [
                {"x": 0, "y": 10, "series": "North"},
                {"x": 1, "y": 15, "series": "North"},
                {"x": 0, "y": 12, "series": "South"},
                {"x": 1, "y": 18, "series": "South"},
            ],
        }
    if chart_type == "scatter":
        return {
            "schema_version": 1,
            "metadata": {"chart_type": "scatter", "title": "Height and weight"},
            "axes": {
                "x": {"label": "Height", "min_value": 0, "max_value": 10},
                "y": {"label": "Weight", "min_value": 0, "max_value": 20},
            },
            "dataset": [
                {"x": 2, "y": 4, "series": "Group A"},
                {"x": 5, "y": 12, "series": "Group A"},
                {"x": 7, "y": 18, "series": "Group B"},
            ],
        }
    if chart_type == "pie":
        return {
            "schema_version": 1,
            "metadata": {"chart_type": "pie", "title": "Market share"},
            "axes": None,
            "dataset": [
                {"category": "A", "value": 55},
                {"category": "B", "value": 30},
                {"category": "C", "value": 15},
            ],
        }
    raise AssertionError(f"unsupported test chart type: {chart_type}")


def _figure(chart_types: tuple[str, ...], *, columns: int, title: str = ""):
    return parse_chart_figure(
        {
            "schema_version": 1,
            "title": title,
            "layout": {"columns": columns},
            "charts": [
                {"chart_id": f"chart-{index}", "chart_spec": _chart_spec(chart_type)}
                for index, chart_type in enumerate(chart_types)
            ],
        }
    )


@pytest.mark.parametrize("chart_type", ("bar", "line", "scatter", "pie"))
def test_renderer_outputs_a_decodable_png_for_each_chart_type(chart_type: str) -> None:
    image_bytes, width, height = render_chart_figure_image(
        _figure((chart_type,), columns=1)
    )

    with Image.open(BytesIO(image_bytes)) as image:
        image.verify()
        assert image.format == "PNG"
        assert image.size == (width, height) == (640, 480)


def test_renderer_preserves_mixed_figure_grid_and_title_canvas_size() -> None:
    figure = _figure(("bar", "line", "scatter", "pie"), columns=2, title="销售概览")

    image_bytes, width, height = render_chart_figure_image(figure)

    with Image.open(BytesIO(image_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (width, height) == (1280, 1002)


def test_renderer_rejects_semantically_invalid_figure() -> None:
    figure = _figure(("pie",), columns=1)
    invalid_figure = type(figure)(
        layout=type(figure.layout)(columns=2),
        charts=figure.charts,
        title=figure.title,
    )

    with pytest.raises(ValueError, match="ChartFigure is invalid"):
        render_chart_figure_image(invalid_figure)


def test_renderer_enforces_output_byte_limit(monkeypatch) -> None:
    import figura.charts.chartfigure.rendering as rendering

    monkeypatch.setattr(rendering, "MAX_IMAGE_BYTES", 1)

    with pytest.raises(ValueError, match="exceeds image limits"):
        render_chart_figure_image(_figure(("pie",), columns=1))


@pytest.mark.parametrize('types,columns', [
    (('pie',), 1), (('pie', 'pie'), 2), (('bar','line','pie'), 2),
    (('bar','line','scatter','pie'), 2), (('pie','pie','pie','pie'), 1),
])
@pytest.mark.parametrize('title', ['', '销售季度数据总览：目标与实际数值占比'])
def test_renderer_keeps_titles_and_captions_in_separate_visible_regions(types, columns, title, monkeypatch):
    from dataclasses import replace
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    raw = _figure(types, columns=columns, title=title)
    figure = replace(raw, charts=tuple(replace(item, chart_spec=replace(item.chart_spec,
        metadata=replace(item.chart_spec.metadata, title='季度销售额与实际完成情况对比：图表分析汇总',
            source='来源：测试图表的原始数据，包含各季度目标及实际完成值。',
            note='备注：以上数值为读图后的估计值，保留原始数据，不调整占比。'))) for item in raw.charts))
    captured = []
    original = FigureCanvasAgg.print_png
    def capture(canvas, *args, **kwargs):
        captured.append(canvas.figure)
        return original(canvas, *args, **kwargs)
    monkeypatch.setattr(FigureCanvasAgg, 'print_png', capture)
    render_chart_figure_image(figure)
    output = captured[0]
    renderer = output.canvas.get_renderer()
    texts = [text.get_window_extent(renderer) for text in output.texts if text.get_text()]
    assert len(texts) == 2 * len(types) + bool(title)
    assert all(output.bbox.contains(b.x0, b.y0) and output.bbox.contains(b.x1, b.y1) for b in texts)
    assert not any(a.overlaps(b) for index,a in enumerate(texts) for b in texts[index+1:])
    for axis in output.axes:
        bounds = axis.get_tightbbox(renderer)
        assert not any(bounds.overlaps(text) for text in texts)


def test_pie_percentages_preserve_rounding_and_zero_values(monkeypatch):
    from matplotlib.axes import Axes
    from dataclasses import replace
    from figura.charts.chartspec.models import CategoryValuePoint
    figure = _figure(('pie',), columns=1)
    item = figure.charts[0]
    points = tuple(CategoryValuePoint(category=key, value=value) for key,value in zip('ABCD', [1,1,1,0]))
    figure = replace(figure, charts=(replace(item, chart_spec=replace(item.chart_spec, dataset=points)),))
    labels = []
    original = Axes.pie
    def capture(axis, *args, **kwargs):
        result = original(axis, *args, **kwargs)
        labels.extend(text.get_text() for text in result[2])
        return result
    monkeypatch.setattr(Axes, 'pie', capture)
    render_chart_figure_image(figure)
    assert labels == ['33.3%', '33.3%', '33.3%', '']
    assert [point.value for point in figure.charts[0].chart_spec.dataset] == [1,1,1,0]


def test_renderer_fails_when_caption_cannot_fit():
    from dataclasses import replace
    figure = _figure(('pie',), columns=1)
    item = figure.charts[0]
    figure = replace(figure, charts=(replace(item, chart_spec=replace(item.chart_spec,
        metadata=replace(item.chart_spec.metadata, note='\n'.join(['备注'] * 45)))),))
    with pytest.raises(ValueError, match='text does not fit'):
        render_chart_figure_image(figure)


def test_renderer_rejects_overlapping_dense_pie_labels():
    from dataclasses import replace
    from figura.charts.chartspec.models import CategoryValuePoint
    figure = _figure(('pie',), columns=1)
    item = figure.charts[0]
    points = tuple(CategoryValuePoint(category=str(index), value=1) for index in range(100))
    figure = replace(figure, charts=(replace(item, chart_spec=replace(item.chart_spec, dataset=points)),))
    with pytest.raises(ValueError, match='labels overlap'):
        render_chart_figure_image(figure)
