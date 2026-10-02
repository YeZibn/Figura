"""Render validated ChartFigure values as bounded composite PNG images."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from io import BytesIO
from math import ceil, fsum

import matplotlib as mpl
from matplotlib.axes import Axes as PlotAxes
from matplotlib.backend_bases import RendererBase
from matplotlib.text import Text
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.transforms import Bbox

from figura.charts.chartspec.models import (
    Axes,
    CategoryValuePoint,
    ChartType,
    CoordinatePoint,
)
from figura.shared.image_limits import MAX_IMAGE_BYTES

from .models import ChartFigure, ChartFigureItem
from .validation import validate_chart_figure


_CELL_WIDTH_INCHES = 6.4
_CELL_HEIGHT_INCHES = 4.8
_DPI = 100
_TITLE_HEIGHT_INCHES = 0.42
_COLORS = (
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
)


def render_chart_figure_image(value: ChartFigure) -> tuple[bytes, int, int]:
    """Return a PNG and its pixel dimensions for a semantically valid Figure."""
    issues = validate_chart_figure(value)
    if issues:
        raise ValueError("ChartFigure is invalid")

    chart_count = len(value.charts)
    rows = ceil(chart_count / value.layout.columns)
    title_height = _TITLE_HEIGHT_INCHES if value.title else 0
    figure = Figure(
        figsize=(
            value.layout.columns * _CELL_WIDTH_INCHES,
            rows * _CELL_HEIGHT_INCHES + title_height,
        ),
        dpi=_DPI,
        facecolor="white",
    )
    canvas = FigureCanvasAgg(figure)
    with mpl.rc_context(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["PingFang SC", "Arial Unicode MS", "Noto Sans CJK SC", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.facecolor": "white",
        }
    ):
        width, height = canvas.get_width_height()
        canvas.draw()
        renderer = canvas.get_renderer()
        top = height - 12
        if value.title:
            title = _canvas_text(figure, renderer, value.title, 20, top, width - 40, 16, bold=True)
            canvas.draw()
            top = title.get_window_extent(renderer).y0 - 16
        cell_height = (top - 12) / rows
        cell_width = width / value.layout.columns
        regions: list[tuple[PlotAxes, Bbox]] = []
        for index, chart in enumerate(value.charts):
            row, column = divmod(index, value.layout.columns)
            left = column * cell_width + 16
            right = (column + 1) * cell_width - 16
            bottom = top - (row + 1) * cell_height + 12
            child_top = top - row * cell_height - 8
            metadata = chart.chart_spec.metadata
            if metadata.title:
                title = _canvas_text(figure, renderer, metadata.title, left, child_top, right - left, 12)
                canvas.draw()
                child_top = title.get_window_extent(renderer).y0 - 12
            caption = "\n".join(text for text in (metadata.source, metadata.note) if text)
            if caption:
                text = _canvas_text(figure, renderer, caption, left, bottom, right - left, 8, bottom=True)
                canvas.draw()
                bottom = text.get_window_extent(renderer).y1 + 12
            region = Bbox.from_extents(left, bottom, right, child_top)
            if region.height < 140:
                raise ValueError("ChartFigure text does not fit the canvas")
            axis = figure.add_axes([
                (left + 50) / width, (bottom + 45) / height,
                (region.width - 75) / width, (region.height - 60) / height,
            ])
            _render_chart(axis, chart)
            _fit_plot(axis, region, canvas)
            regions.append((axis, region))
        canvas.draw()
        if any(not _contains(figure.bbox, text.get_window_extent(renderer)) for text in figure.texts):
            raise ValueError("ChartFigure text does not fit the canvas")
        for axis, region in regions:
            bbox = axis.get_tightbbox(renderer)
            if bbox is None or not _contains(region, bbox):
                raise ValueError("ChartFigure plot labels do not fit the canvas")
            labels = [text.get_window_extent(renderer) for text in axis.texts if text.get_text()]
            if any(a.overlaps(b) for index, a in enumerate(labels) for b in labels[index + 1:]):
                raise ValueError("ChartFigure pie labels overlap")
        output = BytesIO()
        canvas.print_png(output)

    image_bytes = output.getvalue()
    width, height = canvas.get_width_height()
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES or width <= 0 or height <= 0:
        raise ValueError("rendered ChartFigure exceeds image limits")
    return image_bytes, width, height


def _render_chart(axis: PlotAxes, item: ChartFigureItem) -> None:
    spec = item.chart_spec
    metadata = spec.metadata
    if metadata.chart_type is ChartType.BAR:
        _render_bar(axis, item)
    elif metadata.chart_type is ChartType.LINE:
        _render_line(axis, item)
    elif metadata.chart_type is ChartType.SCATTER:
        _render_scatter(axis, item)
    elif metadata.chart_type is ChartType.PIE:
        _render_pie(axis, item)
    else:
        raise ValueError("unsupported chart type")

    if isinstance(spec.axes, Axes):
        axis.set_xlabel(spec.axes.x.label)
        axis.set_ylabel(spec.axes.y.label)
        _apply_axis_bounds(axis, spec.axes)


def _canvas_text(
    figure: Figure, renderer: RendererBase, content: str,
    x: float, y: float, width: float, size: int,
    *, bold: bool = False, bottom: bool = False,
) -> Text:
    font = FontProperties(size=size, weight="bold" if bold else "normal")
    lines = []
    for paragraph in content.split("\n"):
        line = ""
        for char in paragraph:
            candidate = line + char
            measured = renderer.get_text_width_height_descent(candidate, font, ismath=False)[0]
            if measured > width and line:
                lines.append(line.rstrip())
                line = char
            else:
                line = candidate
        lines.append(line.rstrip())
    return figure.text(
        x / figure.bbox.width, y / figure.bbox.height, "\n".join(lines),
        ha="left", va="bottom" if bottom else "top", fontproperties=font, parse_math=False,
        color="#666666" if size == 8 else "#222222",
    )


def _contains(outer: Bbox, inner: Bbox) -> bool:
    return (inner.x0 >= outer.x0 - 1 and inner.y0 >= outer.y0 - 1
            and inner.x1 <= outer.x1 + 1 and inner.y1 <= outer.y1 + 1)


def _fit_plot(axis: PlotAxes, region: Bbox, canvas: FigureCanvasAgg) -> None:
    for _ in range(3):
        canvas.draw()
        bbox = axis.get_tightbbox(canvas.get_renderer())
        if bbox is None or _contains(region, bbox):
            return
        position = axis.get_window_extent()
        left = position.x0 + max(0, region.x0 - bbox.x0)
        bottom = position.y0 + max(0, region.y0 - bbox.y0)
        right = position.x1 - max(0, bbox.x1 - region.x1)
        top = position.y1 - max(0, bbox.y1 - region.y1)
        if right - left < 100 or top - bottom < 100:
            raise ValueError("ChartFigure plot does not fit the canvas")
        axis.set_position(Bbox.from_extents(left, bottom, right, top).transformed(
            axis.figure.transFigure.inverted()
        ))


def _render_bar(axis: PlotAxes, item: ChartFigureItem) -> None:
    spec = item.chart_spec
    points = tuple(point for point in spec.dataset if isinstance(point, CategoryValuePoint))
    categories = _categories(points, spec.axes.x.categories if isinstance(spec.axes, Axes) else None)
    series = _category_series(points)
    count = max(1, len(series))
    bar_width = 0.8 / count
    centers = tuple(range(len(categories)))
    for series_index, (series_name, values) in enumerate(series.items()):
        offset = (series_index - (count - 1) / 2) * bar_width
        positions = [center + offset for center in centers]
        axis.bar(
            positions,
            [values[category] for category in categories],
            width=bar_width,
            color=_COLORS[series_index % len(_COLORS)],
            label=_series_label(series_name, series_index),
        )
    axis.set_xticks(centers, categories)
    axis.grid(axis="y", alpha=0.2)
    if _show_series_legend(series):
        axis.legend()


def _render_line(axis: PlotAxes, item: ChartFigureItem) -> None:
    spec = item.chart_spec
    points = tuple(point for point in spec.dataset if isinstance(point, CoordinatePoint))
    series = _coordinate_series(points)
    categories = spec.axes.x.categories if isinstance(spec.axes, Axes) else None
    for index, (series_name, values) in enumerate(series.items()):
        x_values = [point.x for point in values]
        axis.plot(
            x_values,
            [point.y for point in values],
            marker="o",
            color=_COLORS[index % len(_COLORS)],
            label=_series_label(series_name, index),
        )
    if categories is not None:
        axis.set_xticks(tuple(range(len(categories))), categories)
    axis.grid(alpha=0.2)
    if _show_series_legend(series):
        axis.legend()


def _render_scatter(axis: PlotAxes, item: ChartFigureItem) -> None:
    points = tuple(
        point for point in item.chart_spec.dataset if isinstance(point, CoordinatePoint)
    )
    series = _coordinate_series(points)
    for index, (series_name, values) in enumerate(series.items()):
        axis.scatter(
            [point.x for point in values],
            [point.y for point in values],
            color=_COLORS[index % len(_COLORS)],
            label=_series_label(series_name, index),
        )
    axis.grid(alpha=0.2)
    if _show_series_legend(series):
        axis.legend()


def _render_pie(axis: PlotAxes, item: ChartFigureItem) -> None:
    points = tuple(
        point for point in item.chart_spec.dataset if isinstance(point, CategoryValuePoint)
    )
    total = fsum(point.value for point in points)
    percentages = iter(point.value / total * 100 for point in points)

    def percentage_label(_percent: float) -> str:
        percent = next(percentages)
        return f"{percent:.1f}%" if percent > 0 else ""

    axis.pie(
        [point.value for point in points],
        labels=[point.category for point in points],
        colors=[_COLORS[index % len(_COLORS)] for index in range(len(points))],
        autopct=percentage_label,
        textprops={"fontsize": 9},
        startangle=90,
        counterclock=False,
    )
    axis.set_aspect("equal")


def _categories(
    points: tuple[CategoryValuePoint, ...], declared: tuple[str, ...] | None
) -> tuple[str, ...]:
    if declared is not None:
        return declared
    return tuple(dict.fromkeys(point.category for point in points))


def _category_series(
    points: tuple[CategoryValuePoint, ...],
) -> dict[str | None, dict[str, int | float]]:
    grouped: dict[str | None, dict[str, int | float]] = defaultdict(dict)
    for point in points:
        grouped[point.series][point.category] = point.value
    return dict(grouped)


def _coordinate_series(
    points: tuple[CoordinatePoint, ...],
) -> dict[str | None, list[CoordinatePoint]]:
    grouped: dict[str | None, list[CoordinatePoint]] = defaultdict(list)
    for point in points:
        grouped[point.series].append(point)
    return dict(grouped)


def _series_label(series_name: str | None, index: int) -> str | None:
    if series_name is not None:
        return series_name
    return f"Series {index + 1}"


def _show_series_legend(series: Mapping[str | None, object]) -> bool:
    return len(series) > 1 or any(name is not None for name in series)


def _apply_axis_bounds(axis: PlotAxes, axes: Axes) -> None:
    if axes.x.min_value is not None or axes.x.max_value is not None:
        axis.set_xlim(left=axes.x.min_value, right=axes.x.max_value)
    if axes.y.min_value is not None or axes.y.max_value is not None:
        axis.set_ylim(bottom=axes.y.min_value, top=axes.y.max_value)
