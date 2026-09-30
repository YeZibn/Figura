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
