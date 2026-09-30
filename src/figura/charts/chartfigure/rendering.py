"""Render validated ChartFigure values as bounded composite PNG images."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from io import BytesIO
from math import ceil

import matplotlib as mpl
from matplotlib.axes import Axes as PlotAxes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

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
    axes = figure.subplots(rows, value.layout.columns, squeeze=False)

    with mpl.rc_context(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "PingFang SC",
                "Arial Unicode MS",
                "Noto Sans CJK SC",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    ):
        for index, chart in enumerate(value.charts):
            row, column = divmod(index, value.layout.columns)
            _render_chart(axes[row][column], chart)
        for index in range(chart_count, rows * value.layout.columns):
            row, column = divmod(index, value.layout.columns)
            axes[row][column].set_visible(False)

        if value.title:
            figure.suptitle(value.title, y=0.99, fontsize=16, fontweight="bold")
        figure.subplots_adjust(
            left=0.1,
            right=0.97,
            bottom=0.1,
            top=0.92 if value.title else 0.96,
            wspace=0.28,
            hspace=0.55,
        )
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

    if metadata.title:
        axis.set_title(metadata.title, fontsize=12)
    if isinstance(spec.axes, Axes):
        axis.set_xlabel(spec.axes.x.label)
        axis.set_ylabel(spec.axes.y.label)
        _apply_axis_bounds(axis, spec.axes)

    caption = "\n".join(text for text in (metadata.source, metadata.note) if text)
    if caption:
        axis.text(
            0,
            -0.2,
            caption,
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="#666666",
            wrap=True,
        )


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
    axis.pie(
        [point.value for point in points],
        labels=[point.category for point in points],
        colors=[_COLORS[index % len(_COLORS)] for index in range(len(points))],
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
