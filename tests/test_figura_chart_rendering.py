from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest
from matplotlib.axes import Axes
from PIL import Image

from figura.charts.chartfigure import parse_chart_figure
from figura.charts.chartfigure.rendering import render_chart_figure_image
from figura.charts.chartspec.models import PieDataset, PieSlice


def _chart_spec(chart_type: str) -> dict[str, object]:
    cartesian = {"kind": "cartesian", "x_axis": {"kind": "categorical"}, "y_axis": {"kind": "numeric"}}
    numeric = {"kind": "cartesian", "x_axis": {"kind": "numeric"}, "y_axis": {"kind": "numeric"}}
    datasets: dict[str, tuple[dict[str, object], dict[str, object]]] = {
        "bar": (cartesian, {
            "orientation": "vertical", "mode": "grouped",
            "categories": [{"id": "jan", "label": "一月"}, {"id": "feb", "label": "二月"}, {"id": "mar", "label": "三月"}],
            "series": [
                {"id": "north", "label": "北区", "values": [10, 15, 12]},
                {"id": "south", "label": "南区", "values": [8, 11, 14]},
            ],
        }),
        "line": (numeric, {"series": [
            {"id": "actual", "label": "实际", "points": [{"x": 1, "y": 4}, {"x": 2, "y": 8}, {"x": 3, "y": 6}]},
            {"id": "plan", "label": "计划", "points": [{"x": 1, "y": 3}, {"x": 2, "y": 5}, {"x": 3, "y": 7}]},
        ]}),
        "scatter": (numeric, {"series": [
            {"id": "sample", "label": "样本", "points": [{"x": 1, "y": 3, "size": 2}, {"x": 2, "y": 6, "size": 5}, {"x": 3, "y": 4, "size": 8}]}
        ]}),
        "pie": ({"kind": "none"}, {"slices": [
            {"id": "north", "label": "北区", "value": 55},
            {"id": "south", "label": "南区", "value": 30},
            {"id": "west", "label": "西区", "value": 15},
        ], "inner_radius_ratio": 0.42}),
        "area": (numeric, {"stacking": "none", "series": [
            {"id": "traffic", "label": "访问量", "points": [{"x": 1, "y": 2}, {"x": 2, "y": 5}, {"x": 3, "y": None}, {"x": 4, "y": 7}]}
        ]}),
        "histogram": (numeric, {"measure": "count", "bins": [
            {"start": 0, "end": 2, "value": 4}, {"start": 2, "end": 5, "value": 9}, {"start": 5, "end": 8, "value": 5}
        ]}),
        "box_plot": (cartesian, {"orientation": "vertical", "groups": [
            {"id": "control", "label": "对照", "lower_whisker": 1, "q1": 2, "median": 3, "q3": 4, "upper_whisker": 5, "outliers": [6]},
            {"id": "variant", "label": "实验", "lower_whisker": 2, "q1": 3, "median": 5, "q3": 6, "upper_whisker": 8},
        ]}),
        "radar": ({"kind": "polar", "value_range": {"min": 0, "max": 10}}, {
            "dimensions": [
                {"id": "speed", "label": "速度"}, {"id": "quality", "label": "质量"},
                {"id": "cost", "label": "成本"}, {"id": "stability", "label": "稳定性"},
            ],
            "series": [
                {"id": "alpha", "label": "方案 A", "values": [8, 7, 6, 9]},
                {"id": "beta", "label": "方案 B", "values": [6, 9, 8, 7]},
            ],
        }),
        "heatmap": ({"kind": "matrix"}, {
            "x_categories": [{"id": "x1", "label": "周一"}, {"id": "x2", "label": "周二"}, {"id": "x3", "label": "周三"}, {"id": "x4", "label": "周四"}],
            "y_categories": [{"id": "y1", "label": "北区"}, {"id": "y2", "label": "南区"}, {"id": "y3", "label": "西区"}],
            "values": [[1.5, 2.8, None, 4.2], [3.1, 1.2, 4.4, 2.5], [2.2, 3.9, 1.7, 4.8]],
        }),
        "treemap": ({"kind": "hierarchical"}, {
            "root_id": "root",
            "nodes": [
                {"id": "root", "parent_id": None, "label": "全部业务", "value": 10},
                {"id": "north", "parent_id": "root", "label": "北区", "value": 7},
                {"id": "alpha", "parent_id": "north", "label": "产品 A", "value": 2},
                {"id": "beta", "parent_id": "north", "label": "产品 B", "value": 5},
                {"id": "south", "parent_id": "root", "label": "南区", "value": 3},
            ],
        }),
    }
    coordinate, dataset = datasets[chart_type]
    return {
        "schema_version": 2,
        "metadata": {"chart_type": chart_type, "title": f"{chart_type.title()} 示例", "source": "Figura 测试数据", "note": "单位：示例值"},
        "coordinate_system": coordinate,
        "dataset": dataset,
    }


def _figure(chart_types: tuple[str, ...], *, columns: int, title: str = ""):
    return parse_chart_figure({
        "schema_version": 2,
        "title": title,
        "layout": {"columns": columns},
        "charts": [
            {"chart_id": f"chart-{index}", "chart_spec": _chart_spec(chart_type)}
            for index, chart_type in enumerate(chart_types)
        ],
    })


@pytest.mark.parametrize(
    "chart_type",
    ("bar", "line", "scatter", "pie", "area", "histogram", "box_plot", "radar", "heatmap", "treemap"),
)
def test_renderer_outputs_a_decodable_png_for_each_chart_type(chart_type: str) -> None:
    image_bytes, width, height = render_chart_figure_image(_figure((chart_type,), columns=1))

    with Image.open(BytesIO(image_bytes)) as image:
        image.verify()
        assert image.format == "PNG"
        assert image.size == (width, height) == (640, 480)


def test_renderer_preserves_mixed_figure_grid_and_title_canvas_size() -> None:
    figure = _figure(("bar", "radar", "heatmap", "treemap"), columns=2, title="销售与产品概览")

    image_bytes, width, height = render_chart_figure_image(figure)

    with Image.open(BytesIO(image_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (width, height) == (1280, 1002)


def test_renderer_rejects_semantically_invalid_figure() -> None:
    figure = _figure(("pie",), columns=1)
    invalid_figure = type(figure)(
        layout=type(figure.layout)(columns=2), charts=figure.charts, title=figure.title,
    )

    with pytest.raises(ValueError, match="ChartFigure is invalid"):
        render_chart_figure_image(invalid_figure)


def test_renderer_enforces_output_byte_limit(monkeypatch) -> None:
    import figura.charts.chartfigure.rendering as rendering

    monkeypatch.setattr(rendering, "MAX_IMAGE_BYTES", 1)
    with pytest.raises(ValueError, match="exceeds image limits"):
        render_chart_figure_image(_figure(("pie",), columns=1))


def test_donut_renderer_preserves_values_and_displays_one_decimal_percentages(monkeypatch) -> None:
    figure = _figure(("pie",), columns=1)
    item = figure.charts[0]
    slices = tuple(PieSlice(id=key, label=key, value=value) for key, value in zip("ABCD", [1, 1, 1, 0], strict=True))
    dataset = PieDataset(slices=slices, inner_radius_ratio=0.35)
    figure = replace(figure, charts=(replace(item, chart_spec=replace(item.chart_spec, dataset=dataset)),))
    labels: list[str] = []
    original = Axes.pie

    def capture(axis, *args, **kwargs):
        result = original(axis, *args, **kwargs)
        labels.extend(text.get_text() for text in result[2])
        return result

    monkeypatch.setattr(Axes, "pie", capture)
    render_chart_figure_image(figure)

    assert labels == ["33.3%", "33.3%", "33.3%", ""]
    assert [slice_item.value for slice_item in figure.charts[0].chart_spec.dataset.slices] == [1, 1, 1, 0]


def test_renderer_fails_when_caption_cannot_fit() -> None:
    figure = _figure(("pie",), columns=1)
    item = figure.charts[0]
    note = "\n".join(["备注内容"] * 30)
    figure = replace(item.chart_spec, metadata=replace(item.chart_spec.metadata, note=note))
    chart = replace(item, chart_spec=figure)
    canvas = replace(_figure(("pie",), columns=1), charts=(chart,))

    with pytest.raises(ValueError, match="text does not fit"):
        render_chart_figure_image(canvas)


def test_renderer_rejects_overlapping_dense_pie_labels() -> None:
    figure = _figure(("pie",), columns=1)
    item = figure.charts[0]
    slices = tuple(PieSlice(id=f"slice-{index}", label=str(index), value=1) for index in range(100))
    figure = replace(figure, charts=(replace(item, chart_spec=replace(item.chart_spec, dataset=PieDataset(slices))),))

    with pytest.raises(ValueError, match="labels overlap"):
        render_chart_figure_image(figure)
