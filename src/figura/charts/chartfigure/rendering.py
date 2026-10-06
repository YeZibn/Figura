"""Render validated ChartFigure values as bounded composite PNG images."""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from inspect import signature
from math import ceil, fsum, pi
from datetime import datetime

import numpy as np

import matplotlib as mpl
import matplotlib.dates as mdates
from matplotlib.axes import Axes as PlotAxes
from matplotlib.backend_bases import RendererBase
from matplotlib.text import Text
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, Rectangle
from matplotlib.transforms import Bbox

from figura.charts.chartspec.models import (
    BarOrientation,
    BarMode,
    CartesianCoordinateSystem,
    ChartType,
    PolarCoordinateSystem,
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
        treemap_labels: list[tuple[PlotAxes, Text, tuple[float, float, float, float]]] = []
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
            preexisting_axes = set(figure.axes)
            projection = "polar" if metadata.chart_type is ChartType.RADAR else None
            axis = figure.add_axes([
                (left + 50) / width, (bottom + 45) / height,
                (region.width - 75) / width, (region.height - 60) / height,
            ], projection=projection)
            treemap_labels.extend((axis, text, bounds) for text, bounds in _render_chart(axis, chart))
            _fit_plot(axis, region, canvas)
            regions.extend((candidate, region) for candidate in figure.axes if candidate not in preexisting_axes)
        canvas.draw()
        if any(not _contains(figure.bbox, text.get_window_extent(renderer)) for text in figure.texts):
            raise ValueError("ChartFigure text does not fit the canvas")
        for axis, region in regions:
            bbox = axis.get_tightbbox(renderer)
            if bbox is None or not _contains(region, bbox):
                raise ValueError("ChartFigure plot labels do not fit the canvas")
            for ticks in (axis.get_xticklabels(), axis.get_yticklabels()):
                visible = [tick.get_window_extent(renderer) for tick in ticks if tick.get_visible() and tick.get_text()]
                if any(left.overlaps(right) for index, left in enumerate(visible) for right in visible[index + 1 :]):
                    raise ValueError("ChartFigure axis labels overlap")
            labels = [text.get_window_extent(renderer) for text in axis.texts if text.get_text()]
            if any(a.overlaps(b) for index, a in enumerate(labels) for b in labels[index + 1:]):
                raise ValueError("ChartFigure labels overlap")
        for axis, text, bounds in treemap_labels:
            x0, y0 = axis.transData.transform((bounds[0], bounds[1]))
            x1, y1 = axis.transData.transform((bounds[0] + bounds[2], bounds[1] + bounds[3]))
            tile = Bbox.from_extents(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            if not _contains(tile, text.get_window_extent(renderer)):
                raise ValueError("ChartFigure treemap label does not fit its rectangle")
        output = BytesIO()
        canvas.print_png(output)

    image_bytes = output.getvalue()
    width, height = canvas.get_width_height()
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES or width <= 0 or height <= 0:
        raise ValueError("rendered ChartFigure exceeds image limits")
    return image_bytes, width, height


def _render_chart(axis: PlotAxes, item: ChartFigureItem) -> list[tuple[Text, tuple[float, float, float, float]]]:
    spec = item.chart_spec
    metadata = spec.metadata
    labels: list[tuple[Text, tuple[float, float, float, float]]] = []
    if metadata.chart_type is ChartType.BAR:
        _render_bar(axis, item)
    elif metadata.chart_type is ChartType.LINE:
        _render_line(axis, item)
    elif metadata.chart_type is ChartType.SCATTER:
        _render_scatter(axis, item)
    elif metadata.chart_type is ChartType.PIE:
        _render_pie(axis, item)
    elif metadata.chart_type is ChartType.AREA:
        _render_area(axis, item)
    elif metadata.chart_type is ChartType.HISTOGRAM:
        _render_histogram(axis, item)
    elif metadata.chart_type is ChartType.BOX_PLOT:
        _render_box_plot(axis, item)
    elif metadata.chart_type is ChartType.RADAR:
        _render_radar(axis, item)
    elif metadata.chart_type is ChartType.HEATMAP:
        _render_heatmap(axis, item)
    elif metadata.chart_type is ChartType.TREEMAP:
        labels = _render_treemap(axis, item)
    else:
        raise ValueError("unsupported chart type")

    if isinstance(spec.coordinate_system, CartesianCoordinateSystem):
        if spec.coordinate_system.x_axis.label:
            axis.set_xlabel(spec.coordinate_system.x_axis.label)
        if spec.coordinate_system.y_axis.label:
            axis.set_ylabel(spec.coordinate_system.y_axis.label)
    if metadata.chart_type is ChartType.HEATMAP:
        axis.set_xlabel("")
        axis.set_ylabel("")
    return labels if metadata.chart_type is ChartType.TREEMAP else []


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
    dataset = item.chart_spec.dataset
    categories = [category.label for category in dataset.categories]
    positions = np.arange(len(categories), dtype=float)
    series_count = len(dataset.series)
    colors = [_COLORS[index % len(_COLORS)] for index in range(series_count)]
    if dataset.mode is BarMode.STACKED:
        positive = np.zeros(len(categories), dtype=float)
        negative = np.zeros(len(categories), dtype=float)
        for index, series in enumerate(dataset.series):
            values = np.asarray(series.values, dtype=float)
            if dataset.orientation is BarOrientation.VERTICAL:
                bottoms = np.where(values >= 0, positive, negative)
                axis.bar(positions, values, bottom=bottoms, width=0.78, color=colors[index], label=series.label)
            else:
                lefts = np.where(values >= 0, positive, negative)
                axis.barh(positions, values, left=lefts, height=0.78, color=colors[index], label=series.label)
            positive += np.maximum(values, 0)
            negative += np.minimum(values, 0)
    else:
        bar_size = 0.8 / max(1, series_count)
        for index, series in enumerate(dataset.series):
            offset = (index - (series_count - 1) / 2) * bar_size
            series_positions = positions + offset
            if dataset.orientation is BarOrientation.VERTICAL:
                axis.bar(series_positions, series.values, width=bar_size, color=colors[index], label=series.label)
            else:
                axis.barh(series_positions, series.values, height=bar_size, color=colors[index], label=series.label)
    if dataset.orientation is BarOrientation.VERTICAL:
        axis.set_xticks(positions, categories)
        axis.grid(axis="y", alpha=0.2)
    else:
        axis.set_yticks(positions, categories)
        axis.grid(axis="x", alpha=0.2)
    axis.set_axisbelow(True)
    _legend(axis)


def _render_line(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    x_kind = item.chart_spec.coordinate_system.x_axis.kind
    mapper, ticks = _x_mapper([point.x for series in dataset.series for point in series.points], x_kind)
    for index, series in enumerate(dataset.series):
        x_values = [mapper(point.x) for point in series.points]
        y_values = [point.y if point.y is not None else np.nan for point in series.points]
        axis.plot(x_values, y_values, marker="o", color=_COLORS[index % len(_COLORS)], label=series.label)
    _apply_category_ticks(axis, ticks)
    axis.grid(alpha=0.2)
    _legend(axis)


def _render_scatter(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    all_points = [point for series in dataset.series for point in series.points]
    sizes = [point.size for point in all_points if point.size is not None]
    if sizes:
        minimum, maximum = min(sizes), max(sizes)
        area_by_size = {
            size: 144.0 if minimum == maximum else 36.0 + 216.0 * (size - minimum) / (maximum - minimum)
            for size in sizes
        }
    else:
        area_by_size = {}
    for index, series in enumerate(dataset.series):
        point_sizes = [area_by_size[point.size] for point in series.points] if area_by_size else 36.0
        axis.scatter(
            [point.x for point in series.points],
            [point.y for point in series.points],
            s=point_sizes,
            color=_COLORS[index % len(_COLORS)],
            label=series.label,
        )
    axis.grid(alpha=0.2)
    _legend(axis)


def _render_pie(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    slices = dataset.slices
    total = fsum(slice_item.value for slice_item in slices)
    percentages = iter(slice_item.value / total * 100 for slice_item in slices)

    def percentage_label(_percent: float) -> str:
        percent = next(percentages)
        return f"{percent:.1f}%" if percent > 0 else ""

    axis.pie(
        [slice_item.value for slice_item in slices],
        labels=[slice_item.label for slice_item in slices],
        colors=[_COLORS[index % len(_COLORS)] for index in range(len(slices))],
        autopct=percentage_label,
        textprops={"fontsize": 9},
        startangle=90,
        counterclock=False,
    )
    if dataset.inner_radius_ratio is not None and dataset.inner_radius_ratio > 0:
        axis.add_patch(Circle((0, 0), dataset.inner_radius_ratio, facecolor="white", edgecolor="white", zorder=3))
    axis.set_aspect("equal")


def _render_area(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    x_kind = item.chart_spec.coordinate_system.x_axis.kind
    mapper, ticks = _x_mapper([point.x for series in dataset.series for point in series.points], x_kind)
    cumulative: np.ndarray | None = None
    for index, series in enumerate(dataset.series):
        x_values = np.asarray([mapper(point.x) for point in series.points], dtype=float)
        y_values = np.asarray([np.nan if point.y is None else point.y for point in series.points], dtype=float)
        color = _COLORS[index % len(_COLORS)]
        if dataset.stacking == "stacked":
            assert cumulative is not None or index == 0
            lower = cumulative.copy() if cumulative is not None else np.zeros(len(y_values), dtype=float)
            cumulative = lower + y_values
            axis.fill_between(x_values, lower, cumulative, color=color, alpha=0.55, label=series.label)
            axis.plot(x_values, cumulative, color=color, linewidth=1.5)
        else:
            axis.fill_between(x_values, 0, y_values, color=color, alpha=0.28, label=series.label, where=np.isfinite(y_values))
            axis.plot(x_values, y_values, color=color, marker="o", linewidth=1.5)
    _apply_category_ticks(axis, ticks)
    axis.grid(alpha=0.2)
    _legend(axis)


def _render_histogram(axis: PlotAxes, item: ChartFigureItem) -> None:
    bins = item.chart_spec.dataset.bins
    left = [item.start for item in bins]
    widths = [item.end - item.start for item in bins]
    values = [item.value for item in bins]
    axis.bar(left, values, width=widths, align="edge", color=_COLORS[0], edgecolor="white", linewidth=1.0)
    axis.grid(axis="y", alpha=0.2)
    axis.set_axisbelow(True)


def _render_box_plot(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    vertical = dataset.orientation is BarOrientation.VERTICAL
    stats = [
        {
            "label": group.label,
            "whislo": group.lower_whisker,
            "q1": group.q1,
            "med": group.median,
            "q3": group.q3,
            "whishi": group.upper_whisker,
            "fliers": list(group.outliers),
        }
        for group in dataset.groups
    ]
    positions = np.arange(1, len(stats) + 1, dtype=float)
    orientation = "vertical" if vertical else "horizontal"
    orientation_keyword = {"orientation": orientation} if "orientation" in signature(axis.bxp).parameters else {"vert": vertical}
    artists = axis.bxp(
        stats,
        positions=positions,
        showfliers=True,
        patch_artist=True,
        manage_ticks=False,
        **orientation_keyword,
    )
    for index, patch in enumerate(artists["boxes"]):
        patch.set_facecolor(_COLORS[index % len(_COLORS)])
        patch.set_alpha(0.55)
    labels = [group.label for group in dataset.groups]
    if vertical:
        axis.set_xticks(positions, labels)
    else:
        axis.set_yticks(positions, labels)
    axis.grid(axis="y" if vertical else "x", alpha=0.2)
    axis.set_axisbelow(True)


def _render_radar(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    dimensions = dataset.dimensions
    angles = np.linspace(0, 2 * pi, len(dimensions), endpoint=False)
    axis.set_theta_offset(pi / 2)
    axis.set_theta_direction(-1)
    axis.set_thetagrids(np.degrees(angles), [dimension.label for dimension in dimensions])
    coordinate = item.chart_spec.coordinate_system
    if isinstance(coordinate, PolarCoordinateSystem):
        axis.set_ylim(coordinate.minimum, coordinate.maximum)
    for index, series in enumerate(dataset.series):
        values = np.asarray(series.values, dtype=float)
        closed_angles = np.r_[angles, angles[0]]
        closed_values = np.r_[values, values[0]]
        color = _COLORS[index % len(_COLORS)]
        axis.plot(closed_angles, closed_values, color=color, marker="o", label=series.label)
        axis.fill(closed_angles, closed_values, color=color, alpha=0.16)
    axis.grid(alpha=0.3)
    _legend(axis)


def _render_heatmap(axis: PlotAxes, item: ChartFigureItem) -> None:
    dataset = item.chart_spec.dataset
    values = np.asarray(dataset.values, dtype=float)
    masked = np.ma.masked_invalid(values)
    cmap = mpl.colormaps["viridis"].with_extremes(bad="#D9D9D9")
    numeric = values[np.isfinite(values)]
    image_options: dict[str, object] = {"cmap": cmap, "aspect": "auto", "interpolation": "nearest", "origin": "upper"}
    if len(numeric):
        low, high = float(np.min(numeric)), float(np.max(numeric))
        if low == high:
            padding = max(abs(low) * 0.01, 1e-6)
            low, high = low - padding, high + padding
        image_options.update(vmin=low, vmax=high)
    image = axis.imshow(masked, **image_options)
    x_labels = [category.label for category in dataset.x_categories]
    y_labels = [category.label for category in dataset.y_categories]
    axis.set_xticks(np.arange(len(x_labels)), x_labels)
    axis.set_yticks(np.arange(len(y_labels)), y_labels)
    if len(x_labels) > 4:
        axis.tick_params(axis="x", labelrotation=35)
    axis.set_xticks(np.arange(-0.5, len(x_labels), 1), minor=True)
    axis.set_yticks(np.arange(-0.5, len(y_labels), 1), minor=True)
    axis.grid(which="minor", color="white", linewidth=0.8)
    axis.tick_params(which="minor", bottom=False, left=False)
    if len(numeric):
        colorbar = axis.figure.colorbar(image, ax=axis, fraction=0.045, pad=0.04)
        colorbar.ax.tick_params(labelsize=8)


def _render_treemap(
    axis: PlotAxes, item: ChartFigureItem
) -> list[tuple[Text, tuple[float, float, float, float]]]:
    dataset = item.chart_spec.dataset
    nodes = list(dataset.nodes)
    by_id = {node.id: node for node in nodes}
    original_order = {node.id: index for index, node in enumerate(nodes)}
    children: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        if node.parent_id is not None:
            children[node.parent_id].append(node.id)

    weights: dict[str, float] = {}

    def node_weight(node_id: str) -> float:
        if node_id in weights:
            return weights[node_id]
        child_ids = children.get(node_id, [])
        value = fsum(node_weight(child_id) for child_id in child_ids) if child_ids else float(by_id[node_id].value or 0)
        weights[node_id] = value
        return value

    for node_id in by_id:
        node_weight(node_id)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.set_aspect("auto")
    axis.set_axis_off()
    label_bounds: list[tuple[Text, tuple[float, float, float, float]]] = []
    root = by_id[dataset.root_id]
    root_children = children.get(root.id, [])

    def draw_node(node_id: str, rect: tuple[float, float, float, float], depth: int) -> None:
        node = by_id[node_id]
        x, y, width, height = rect
        color_index = (original_order[node_id] + depth * 2) % len(_COLORS)
        color = _COLORS[color_index]
        axis.add_patch(Rectangle((x, y), width, height, facecolor=color, edgecolor="white", linewidth=1.2, zorder=depth + 1))
        child_ids = children.get(node_id, [])
        if child_ids:
            header_height = min(height * 0.22, 0.09)
            text = _draw_treemap_label(axis, node.label, x + width / 2, y + height - header_height / 2, color, fontsize=7)
            if text is not None:
                label_bounds.append((text, rect))
            pad = min(width, height) * 0.012
            inner = (x + pad, y + pad, max(0.0, width - 2 * pad), max(0.0, height - header_height - 2 * pad))
            child_rects = _squarify(
                [(child_id, weights[child_id], original_order[child_id]) for child_id in child_ids],
                inner,
            )
            for child_id in sorted(child_ids, key=original_order.__getitem__):
                draw_node(child_id, child_rects[child_id], depth + 1)
        else:
            text = _draw_treemap_label(axis, node.label, x + width / 2, y + height / 2, color, fontsize=7)
            if text is not None:
                label_bounds.append((text, rect))

    if root_children:
        if root.label:
            root_text = _draw_treemap_label(axis, root.label, 0.5, 0.965, "#FFFFFF", fontsize=8)
            if root_text is not None:
                label_bounds.append((root_text, (0.0, 0.91, 1.0, 1.0)))
        root_header = 0.08 if root.label else 0.0
        root_rect = (0.0, 0.0, 1.0, 1.0 - root_header)
        root_patch = Rectangle(root_rect[:2], root_rect[2], root_rect[3], facecolor="white", edgecolor="white", linewidth=0)
        axis.add_patch(root_patch)
        child_rects = _squarify(
            [(child_id, weights[child_id], original_order[child_id]) for child_id in root_children],
            root_rect,
        )
        for child_id in sorted(root_children, key=original_order.__getitem__):
            draw_node(child_id, child_rects[child_id], 0)
    else:
        draw_node(root.id, (0.0, 0.0, 1.0, 1.0), 0)
    return label_bounds


def _draw_treemap_label(
    axis: PlotAxes, label: str, x: float, y: float, background: str, *, fontsize: int
) -> Text | None:
    if not label:
        return None
    rgb = mpl.colors.to_rgb(background)
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return axis.text(
        x,
        y,
        label,
        ha="center",
        va="center",
        fontsize=fontsize,
        color="#202020" if luminance > 0.52 else "white",
        clip_on=True,
        zorder=20,
    )


def _squarify(items: list[tuple[str, float, int]], rect: tuple[float, float, float, float]) -> dict[str, tuple[float, float, float, float]]:
    x, y, width, height = rect
    if width <= 0 or height <= 0 or not items:
        raise ValueError("ChartFigure treemap layout is empty")
    ordered = sorted(items, key=lambda item: (-item[1], item[2]))
    total = fsum(item[1] for item in ordered)
    if total <= 0:
        raise ValueError("ChartFigure treemap weights are invalid")
    areas = [(node_id, weight * width * height / total, order) for node_id, weight, order in ordered]
    result: dict[str, tuple[float, float, float, float]] = {}
    while areas:
        side = min(width, height)
        row: list[tuple[str, float, int]] = []
        while areas:
            candidate = areas[0]
            if not row or _worst_row(row + [candidate], side) <= _worst_row(row, side):
                row.append(areas.pop(0))
            else:
                break
        row_area = fsum(item[1] for item in row)
        if width >= height:
            strip_width = row_area / height
            cursor_y = y
            for node_id, area, _ in row:
                tile_height = area / strip_width
                result[node_id] = (x, cursor_y, strip_width, tile_height)
                cursor_y += tile_height
            x += strip_width
            width = max(0.0, width - strip_width)
        else:
            strip_height = row_area / width
            cursor_x = x
            for node_id, area, _ in row:
                tile_width = area / strip_height
                result[node_id] = (cursor_x, y, tile_width, strip_height)
                cursor_x += tile_width
            y += strip_height
            height = max(0.0, height - strip_height)
        if areas and min(width, height) <= 1e-9:
            raise ValueError("ChartFigure treemap layout is degenerate")
    return result


def _worst_row(row: list[tuple[str, float, int]], side: float) -> float:
    if not row or side <= 0:
        return float("inf")
    areas = [item[1] for item in row]
    total = fsum(areas)
    return max(side * side * max(areas) / (total * total), (total * total) / (side * side * min(areas)))


def _x_mapper(values: list[object], kind: object):
    from figura.charts.chartspec.models import AxisKind

    if kind is AxisKind.CATEGORICAL:
        categories = list(dict.fromkeys(values))
        lookup = {value: index for index, value in enumerate(categories)}
        return (lambda value: lookup[value]), (list(range(len(categories))), [str(value) for value in categories])
    if kind is AxisKind.TIME:
        def to_date(value: object) -> float:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return float(mdates.date2num(parsed))

        return to_date, None
    return (lambda value: float(value)), None


def _apply_category_ticks(axis: PlotAxes, ticks) -> None:
    if ticks is None:
        return
    positions, labels = ticks
    axis.set_xticks(positions, labels)
    if len(labels) > 5:
        axis.tick_params(axis="x", labelrotation=35)


def _legend(axis: PlotAxes) -> None:
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(loc="best", fontsize=8, frameon=False)
