"""Pure, bounded semantic validation for ChartSpecData v2."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from figura.shared.json_schema import JsonValueError, canonical_json_dumps

from ..limits import MAX_ISSUES, MAX_TEXT_LENGTH
from .codec import _rfc3339
from .errors import ChartSpecIssue
from .limits import CHART_SPEC_SCHEMA_VERSION, MAX_CHART_SPEC_DATA_BYTES, MAX_DATA_POINTS, MAX_FINITE_NUMBER
from .models import (
    AreaDataset,
    AxisKind,
    BarDataset,
    BarMode,
    BarOrientation,
    BoxPlotDataset,
    BoxPlotGroup,
    CartesianAxis,
    CartesianCoordinateSystem,
    ChartCategory,
    ChartMetadata,
    ChartSpecData,
    ChartType,
    CoordinateSystemKind,
    HistogramDataset,
    HistogramBin,
    HistogramMeasure,
    HeatmapDataset,
    LineDataset,
    PieDataset,
    PieSlice,
    PolarCoordinateSystem,
    RadarDataset,
    RadarDimension,
    ScatterDataset,
    ScatterPoint,
    ScatterSeries,
    SimpleCoordinateSystem,
    TreemapDataset,
    TreemapNode,
    ValueSeries,
    XYPoint,
    XYSeries,
)


class _Issues:
    def __init__(self) -> None:
        self.values: list[ChartSpecIssue] = []

    def add(self, code: str, path: str, message: str) -> None:
        if len(self.values) < MAX_ISSUES:
            self.values.append(ChartSpecIssue(code, path, message[:240]))

    def result(self) -> tuple[ChartSpecIssue, ...]:
        return tuple(self.values)


def validate_chart_spec_data(value: object) -> tuple[ChartSpecIssue, ...]:
    """Return stable semantic issues without mutating or repairing the value."""
    issues = _Issues()
    if not isinstance(value, ChartSpecData):
        issues.add("invalid_chart_spec", "", "需要 ChartSpecData 值。")
        return issues.result()

    if type(value.schema_version) is not int or value.schema_version != CHART_SPEC_SCHEMA_VERSION:
        issues.add("unsupported_schema_version", "/schema_version", "ChartSpec schema_version 不受支持。")
    metadata = value.metadata
    if not isinstance(metadata, ChartMetadata):
        issues.add("invalid_metadata", "/metadata", "metadata 结构无效。")
        return issues.result()
    chart_type = metadata.chart_type if isinstance(metadata.chart_type, ChartType) else None
    if chart_type is None:
        issues.add("unsupported_chart_type", "/metadata/chart_type", "ChartSpec chart_type 不受支持。")
    _text(metadata.title, "/metadata/title", issues)
    if metadata.source is not None:
        _text(metadata.source, "/metadata/source", issues)
    _text(metadata.note, "/metadata/note", issues)

    coordinate = value.coordinate_system
    _validate_coordinate(coordinate, "/coordinate_system", issues)
    if chart_type is not None:
        _validate_chart_coordinate(chart_type, coordinate, issues)

    dataset = value.dataset
    if chart_type is not None:
        expected = {
            ChartType.BAR: BarDataset,
            ChartType.LINE: LineDataset,
            ChartType.SCATTER: ScatterDataset,
            ChartType.PIE: PieDataset,
            ChartType.AREA: AreaDataset,
            ChartType.HISTOGRAM: HistogramDataset,
            ChartType.BOX_PLOT: BoxPlotDataset,
            ChartType.RADAR: RadarDataset,
            ChartType.HEATMAP: HeatmapDataset,
            ChartType.TREEMAP: TreemapDataset,
        }[chart_type]
        if not isinstance(dataset, expected):
            issues.add("dataset_type_mismatch", "/dataset", "dataset 结构与 chart_type 不匹配。")
        else:
            _validate_dataset(chart_type, dataset, coordinate, issues)

    try:
        serialized = canonical_json_dumps(value.to_dict()).encode("utf-8")
        if len(serialized) > MAX_CHART_SPEC_DATA_BYTES:
            issues.add("content_too_large", "", "ChartSpec 内容超过 256 KiB 限制。")
    except (JsonValueError, UnicodeEncodeError, AttributeError, TypeError, ValueError, OverflowError):
        issues.add("invalid_chart_spec", "", "ChartSpec 无法规范化为 JSON。")
    return issues.result()


def _text(value: object, path: str, issues: _Issues, *, nonempty: bool = False) -> None:
    if not isinstance(value, str):
        issues.add("invalid_text", path, "文本字段必须是字符串。")
    elif nonempty and not value:
        issues.add("empty_text", path, "文本字段不能为空。")
    elif len(value) > MAX_TEXT_LENGTH:
        issues.add("text_too_long", path, "文本字段超过长度限制。")


def _id(value: object, path: str, issues: _Issues) -> None:
    if not isinstance(value, str) or not value or len(value) > 64:
        issues.add("invalid_id", path, "ID 必须是 1 到 64 个字符的非空字符串。")


def _number(value: object, path: str, issues: _Issues, *, minimum: float | None = None, exclusive_minimum: float | None = None) -> bool:
    valid = type(value) in (int, float)
    if valid:
        try:
            valid = math.isfinite(value) and abs(value) <= MAX_FINITE_NUMBER
        except (OverflowError, TypeError):
            valid = False
    if not valid:
        issues.add("invalid_number", path, "数值必须是有限 binary64 数字。")
        return False
    if minimum is not None and value < minimum:
        issues.add("number_below_minimum", path, "数值小于允许下界。")
        return False
    if exclusive_minimum is not None and value <= exclusive_minimum:
        issues.add("number_not_positive", path, "数值必须大于零。")
        return False
    return True


def _bounded(items: object, path: str, issues: _Issues, *, minimum: int = 1) -> bool:
    if not isinstance(items, (tuple, list)):
        issues.add("invalid_collection", path, "字段必须是有序数组。")
        return False
    if len(items) < minimum:
        issues.add("too_few_items", path, "数组项数小于允许范围。")
        return False
    if len(items) > MAX_DATA_POINTS:
        issues.add("too_many_items", path, "数组项数超过 512 项限制。")
        return False
    return True


def _unique_ids(items: Iterable[object], path: str, issues: _Issues) -> None:
    seen: set[str] = set()
    for index, item in enumerate(items):
        item_id = getattr(item, "id", None)
        _id(item_id, f"{path}/{index}/id", issues)
        if isinstance(item_id, str):
            if item_id in seen:
                issues.add("duplicate_id", f"{path}/{index}/id", "同一集合内的 ID 必须唯一。")
            seen.add(item_id)


def _validate_coordinate(value: object, path: str, issues: _Issues) -> None:
    if isinstance(value, CartesianCoordinateSystem):
        _axis(value.x_axis, f"{path}/x_axis", issues)
        _axis(value.y_axis, f"{path}/y_axis", issues)
    elif isinstance(value, PolarCoordinateSystem):
        _number(value.minimum, f"{path}/value_range/min", issues)
        _number(value.maximum, f"{path}/value_range/max", issues)
        if type(value.minimum) in (int, float) and type(value.maximum) in (int, float) and value.minimum >= value.maximum:
            issues.add("invalid_polar_range", f"{path}/value_range", "极坐标最大值必须大于最小值。")
    elif isinstance(value, SimpleCoordinateSystem):
        if value.kind not in {CoordinateSystemKind.MATRIX, CoordinateSystemKind.HIERARCHICAL, CoordinateSystemKind.NONE}:
            issues.add("invalid_coordinate_system", f"{path}/kind", "此 coordinate_system.kind 不应使用简单结构。")
    else:
        issues.add("invalid_coordinate_system", path, "coordinate_system 结构无效。")


def _axis(value: object, path: str, issues: _Issues) -> None:
    if not isinstance(value, CartesianAxis):
        issues.add("invalid_axis", path, "坐标轴结构无效。")
        return
    if not isinstance(value.kind, AxisKind):
        issues.add("invalid_axis_kind", f"{path}/kind", "坐标轴类型不受支持。")
    if value.label is not None:
        _text(value.label, f"{path}/label", issues)


def _validate_chart_coordinate(chart_type: ChartType, coordinate: object, issues: _Issues) -> None:
    expected = {
        ChartType.PIE: CoordinateSystemKind.NONE,
        ChartType.RADAR: CoordinateSystemKind.POLAR,
        ChartType.HEATMAP: CoordinateSystemKind.MATRIX,
        ChartType.TREEMAP: CoordinateSystemKind.HIERARCHICAL,
    }
    if chart_type in expected:
        actual = getattr(coordinate, "kind", None)
        if actual is not expected[chart_type]:
            issues.add("coordinate_type_mismatch", "/coordinate_system/kind", "coordinate_system.kind 与图表类型不匹配。")
    elif not isinstance(coordinate, CartesianCoordinateSystem):
        issues.add("coordinate_type_mismatch", "/coordinate_system/kind", "此图表类型需要笛卡尔坐标系。")


def _cartesian_axes(coordinate: object) -> tuple[CartesianAxis, CartesianAxis] | None:
    if not isinstance(coordinate, CartesianCoordinateSystem):
        return None
    if not isinstance(coordinate.x_axis, CartesianAxis) or not isinstance(coordinate.y_axis, CartesianAxis):
        return None
    return coordinate.x_axis, coordinate.y_axis


def _expect_axis_kind(axis: CartesianAxis, kind: AxisKind, path: str, issues: _Issues) -> None:
    if axis.kind is not kind:
        issues.add("axis_kind_mismatch", path, "坐标轴类型与数据结构不匹配。")


def _category(item: object, path: str, issues: _Issues) -> None:
    if not isinstance(item, (ChartCategory, RadarDimension)):
        issues.add("invalid_category", path, "类别必须包含 ID 和标签。")
        return
    _id(item.id, f"{path}/id", issues)
    _text(item.label, f"{path}/label", issues)


def _validate_dataset(chart_type: ChartType, dataset: object, coordinate: object, issues: _Issues) -> None:
    if isinstance(dataset, BarDataset):
        _validate_bar(dataset, coordinate, issues)
    elif isinstance(dataset, LineDataset):
        _validate_line(dataset.series, coordinate, "/dataset/series", issues)
    elif isinstance(dataset, AreaDataset):
        if dataset.stacking not in {"none", "stacked"}:
            issues.add("invalid_stacking", "/dataset/stacking", "stacking 必须是 none 或 stacked。")
        _validate_line(dataset.series, coordinate, "/dataset/series", issues, allow_null=dataset.stacking != "stacked")
        if dataset.stacking == "stacked":
            _same_ordered_x(dataset.series, issues)
    elif isinstance(dataset, ScatterDataset):
        _validate_scatter(dataset, coordinate, issues)
    elif isinstance(dataset, PieDataset):
        _validate_pie(dataset, issues)
    elif isinstance(dataset, HistogramDataset):
        _validate_histogram(dataset, coordinate, issues)
    elif isinstance(dataset, BoxPlotDataset):
        _validate_box_plot(dataset, coordinate, issues)
    elif isinstance(dataset, RadarDataset):
        _validate_radar(dataset, coordinate, issues)
    elif isinstance(dataset, HeatmapDataset):
        _validate_heatmap(dataset, issues)
    elif isinstance(dataset, TreemapDataset):
        _validate_treemap(dataset, issues)
    else:
        issues.add("invalid_dataset", "/dataset", f"{chart_type.value} dataset 类型无效。")


def _validate_bar(dataset: BarDataset, coordinate: object, issues: _Issues) -> None:
    if not isinstance(dataset.orientation, BarOrientation):
        issues.add("invalid_orientation", "/dataset/orientation", "柱状图方向无效。")
    if not isinstance(dataset.mode, BarMode):
        issues.add("invalid_mode", "/dataset/mode", "柱状图模式无效。")
    if not _bounded(dataset.categories, "/dataset/categories", issues) or not _bounded(dataset.series, "/dataset/series", issues):
        return
    for index, item in enumerate(dataset.categories):
        _category(item, f"/dataset/categories/{index}", issues)
    _unique_ids(dataset.categories, "/dataset/categories", issues)
    for index, series in enumerate(dataset.series):
        if not isinstance(series, ValueSeries):
            issues.add("invalid_series", f"/dataset/series/{index}", "柱状图系列结构无效。")
            continue
        _id(series.id, f"/dataset/series/{index}/id", issues)
        _text(series.label, f"/dataset/series/{index}/label", issues)
        if not isinstance(series.values, (tuple, list)):
            issues.add("invalid_collection", f"/dataset/series/{index}/values", "values 必须是数组。")
            continue
        if len(series.values) != len(dataset.categories):
            issues.add("category_value_count_mismatch", f"/dataset/series/{index}/values", "每个系列必须为每个类别提供一个值。")
        for value_index, number in enumerate(series.values):
            _number(number, f"/dataset/series/{index}/values/{value_index}", issues)
    _unique_ids(dataset.series, "/dataset/series", issues)
    axes = _cartesian_axes(coordinate)
    if axes is not None:
        x_axis, y_axis = axes
        if dataset.orientation is BarOrientation.VERTICAL:
            _expect_axis_kind(x_axis, AxisKind.CATEGORICAL, "/coordinate_system/x_axis/kind", issues)
            _expect_axis_kind(y_axis, AxisKind.NUMERIC, "/coordinate_system/y_axis/kind", issues)
        elif dataset.orientation is BarOrientation.HORIZONTAL:
            _expect_axis_kind(x_axis, AxisKind.NUMERIC, "/coordinate_system/x_axis/kind", issues)
            _expect_axis_kind(y_axis, AxisKind.CATEGORICAL, "/coordinate_system/y_axis/kind", issues)


def _validate_line(
    series_items: object,
    coordinate: object,
    path: str,
    issues: _Issues,
    *,
    allow_null: bool = True,
) -> None:
    if not _bounded(series_items, path, issues):
        return
    axes = _cartesian_axes(coordinate)
    x_kind = axes[0].kind if axes is not None else None
    if axes is not None:
        if x_kind not in {AxisKind.CATEGORICAL, AxisKind.NUMERIC, AxisKind.TIME}:
            issues.add("invalid_x_axis_kind", "/coordinate_system/x_axis/kind", "折线 x 轴类型无效。")
        _expect_axis_kind(axes[1], AxisKind.NUMERIC, "/coordinate_system/y_axis/kind", issues)
    for series_index, series in enumerate(series_items):
        item_path = f"{path}/{series_index}"
        if not isinstance(series, XYSeries):
            issues.add("invalid_series", item_path, "折线系列结构无效。")
            continue
        _id(series.id, f"{item_path}/id", issues)
        _text(series.label, f"{item_path}/label", issues)
        if not _bounded(series.points, f"{item_path}/points", issues):
            continue
        for point_index, point in enumerate(series.points):
            point_path = f"{item_path}/points/{point_index}"
            if not isinstance(point, XYPoint):
                issues.add("invalid_point", point_path, "折线点结构无效。")
                continue
            _coordinate_value(point.x, x_kind, f"{point_path}/x", issues)
            if point.y is None:
                if not allow_null:
                    issues.add("null_stacked_value", f"{point_path}/y", "堆叠面积图不允许空值。")
            else:
                _number(point.y, f"{point_path}/y", issues)
    _unique_ids(series_items, path, issues)


def _coordinate_value(value: object, kind: AxisKind | None, path: str, issues: _Issues) -> None:
    if kind is AxisKind.CATEGORICAL:
        if not isinstance(value, str):
            issues.add("coordinate_type_mismatch", path, "类别坐标必须是文本。")
        else:
            _text(value, path, issues)
    elif kind is AxisKind.NUMERIC:
        _number(value, path, issues)
    elif kind is AxisKind.TIME:
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH or not _rfc3339(value):
            issues.add("invalid_time_coordinate", path, "时间坐标必须是 RFC 3339 日期时间字符串。")


def _same_ordered_x(series_items: object, issues: _Issues) -> None:
    if not isinstance(series_items, (tuple, list)) or not series_items:
        return
    first = series_items[0]
    if not isinstance(first, XYSeries):
        return
    expected = tuple(point.x for point in first.points if isinstance(point, XYPoint))
    for index, series in enumerate(series_items[1:], 1):
        if isinstance(series, XYSeries) and tuple(point.x for point in series.points if isinstance(point, XYPoint)) != expected:
            issues.add("stacked_x_domain_mismatch", f"/dataset/series/{index}/points", "堆叠面积系列必须使用相同顺序的 x 坐标。")


def _validate_scatter(dataset: ScatterDataset, coordinate: object, issues: _Issues) -> None:
    if not _bounded(dataset.series, "/dataset/series", issues):
        return
    axes = _cartesian_axes(coordinate)
    if axes is not None:
        _expect_axis_kind(axes[0], AxisKind.NUMERIC, "/coordinate_system/x_axis/kind", issues)
        _expect_axis_kind(axes[1], AxisKind.NUMERIC, "/coordinate_system/y_axis/kind", issues)
    _unique_ids(dataset.series, "/dataset/series", issues)
    sizes_seen: set[bool] = set()
    for series_index, series in enumerate(dataset.series):
        path = f"/dataset/series/{series_index}"
        if not isinstance(series, ScatterSeries):
            issues.add("invalid_series", path, "散点系列结构无效。")
            continue
        _id(series.id, f"{path}/id", issues)
        _text(series.label, f"{path}/label", issues)
        if not _bounded(series.points, f"{path}/points", issues):
            continue
        for point_index, point in enumerate(series.points):
            point_path = f"{path}/points/{point_index}"
            if not isinstance(point, ScatterPoint):
                issues.add("invalid_point", point_path, "散点结构无效。")
                continue
            _number(point.x, f"{point_path}/x", issues)
            _number(point.y, f"{point_path}/y", issues)
            has_size = point.size is not None
            sizes_seen.add(has_size)
            if has_size:
                _number(point.size, f"{point_path}/size", issues, exclusive_minimum=0)
    if len(sizes_seen) > 1:
        issues.add("inconsistent_bubble_size", "/dataset/series", "size 必须在全部散点中同时提供或同时省略。")


def _validate_pie(dataset: PieDataset, issues: _Issues) -> None:
    if not _bounded(dataset.slices, "/dataset/slices", issues):
        return
    _unique_ids(dataset.slices, "/dataset/slices", issues)
    values: list[float] = []
    for index, slice_item in enumerate(dataset.slices):
        path = f"/dataset/slices/{index}"
        if not isinstance(slice_item, PieSlice):
            issues.add("invalid_pie_slice", path, "饼图扇区结构无效。")
            continue
        _text(slice_item.label, f"{path}/label", issues)
        if _number(slice_item.value, f"{path}/value", issues, minimum=0):
            values.append(float(slice_item.value))
    try:
        total = math.fsum(values)
    except OverflowError:
        total = math.inf
    if not math.isfinite(total) or total <= 0:
        issues.add("invalid_pie_total", "/dataset/slices", "饼图总值必须是有限正数。")
    ratio = dataset.inner_radius_ratio
    if ratio is not None and _number(ratio, "/dataset/inner_radius_ratio", issues, minimum=0) and ratio > 0.75:
        issues.add("inner_radius_too_large", "/dataset/inner_radius_ratio", "圆环内半径比例不得超过 0.75。")


def _validate_histogram(dataset: HistogramDataset, coordinate: object, issues: _Issues) -> None:
    if not isinstance(dataset.measure, HistogramMeasure):
        issues.add("invalid_histogram_measure", "/dataset/measure", "直方图 measure 不受支持。")
    if not _bounded(dataset.bins, "/dataset/bins", issues):
        return
    axes = _cartesian_axes(coordinate)
    if axes is not None:
        _expect_axis_kind(axes[0], AxisKind.NUMERIC, "/coordinate_system/x_axis/kind", issues)
        _expect_axis_kind(axes[1], AxisKind.NUMERIC, "/coordinate_system/y_axis/kind", issues)
    prior_end: float | None = None
    for index, bin_item in enumerate(dataset.bins):
        path = f"/dataset/bins/{index}"
        if not isinstance(bin_item, HistogramBin):
            issues.add("invalid_histogram_bin", path, "直方图区间结构无效。")
            continue
        start_ok = _number(bin_item.start, f"{path}/start", issues)
        end_ok = _number(bin_item.end, f"{path}/end", issues)
        _number(bin_item.value, f"{path}/value", issues, minimum=0)
        if start_ok and end_ok:
            if bin_item.start >= bin_item.end:
                issues.add("invalid_histogram_interval", path, "直方图区间必须满足 start < end。")
            if prior_end is not None and bin_item.start < prior_end:
                issues.add("overlapping_histogram_bins", path, "直方图区间必须有序且不得重叠。")
            prior_end = float(bin_item.end)


def _validate_box_plot(dataset: BoxPlotDataset, coordinate: object, issues: _Issues) -> None:
    if not isinstance(dataset.orientation, BarOrientation):
        issues.add("invalid_orientation", "/dataset/orientation", "箱线图方向无效。")
    if not _bounded(dataset.groups, "/dataset/groups", issues):
        return
    _unique_ids(dataset.groups, "/dataset/groups", issues)
    axes = _cartesian_axes(coordinate)
    if axes is not None:
        categorical = AxisKind.CATEGORICAL
        numeric = AxisKind.NUMERIC
        if dataset.orientation is BarOrientation.VERTICAL:
            _expect_axis_kind(axes[0], categorical, "/coordinate_system/x_axis/kind", issues)
            _expect_axis_kind(axes[1], numeric, "/coordinate_system/y_axis/kind", issues)
        elif dataset.orientation is BarOrientation.HORIZONTAL:
            _expect_axis_kind(axes[0], numeric, "/coordinate_system/x_axis/kind", issues)
            _expect_axis_kind(axes[1], categorical, "/coordinate_system/y_axis/kind", issues)
    for index, group in enumerate(dataset.groups):
        path = f"/dataset/groups/{index}"
        if not isinstance(group, BoxPlotGroup):
            issues.add("invalid_box_group", path, "箱线图分组结构无效。")
            continue
        _text(group.label, f"{path}/label", issues)
        numbers = (
            group.lower_whisker,
            group.q1,
            group.median,
            group.q3,
            group.upper_whisker,
        )
        valid = all(_number(number, f"{path}/{field}", issues) for number, field in zip(numbers, ("lower_whisker", "q1", "median", "q3", "upper_whisker")))
        if valid and not all(left <= right for left, right in zip(numbers, numbers[1:])):
            issues.add("invalid_quartile_order", path, "箱线图须满足 lower_whisker <= q1 <= median <= q3 <= upper_whisker。")
        if _bounded(group.outliers, f"{path}/outliers", issues, minimum=0):
            for outlier_index, outlier in enumerate(group.outliers):
                _number(outlier, f"{path}/outliers/{outlier_index}", issues)


def _validate_radar(dataset: RadarDataset, coordinate: object, issues: _Issues) -> None:
    if not _bounded(dataset.dimensions, "/dataset/dimensions", issues, minimum=3):
        return
    if not _bounded(dataset.series, "/dataset/series", issues):
        return
    for index, dimension in enumerate(dataset.dimensions):
        _category(dimension, f"/dataset/dimensions/{index}", issues)
    _unique_ids(dataset.dimensions, "/dataset/dimensions", issues)
    _unique_ids(dataset.series, "/dataset/series", issues)
    for index, series in enumerate(dataset.series):
        path = f"/dataset/series/{index}"
        if not isinstance(series, ValueSeries):
            issues.add("invalid_series", path, "雷达图系列结构无效。")
            continue
        _id(series.id, f"{path}/id", issues)
        _text(series.label, f"{path}/label", issues)
        if len(series.values) != len(dataset.dimensions):
            issues.add("radar_value_count_mismatch", f"{path}/values", "每个雷达系列必须为每个维度提供一个值。")
        for value_index, number in enumerate(series.values):
            _number(number, f"{path}/values/{value_index}", issues)
    if isinstance(coordinate, PolarCoordinateSystem):
        for series_index, series in enumerate(dataset.series):
            for value_index, number in enumerate(series.values):
                if type(number) in (int, float) and (number < coordinate.minimum or number > coordinate.maximum):
                    issues.add("radar_value_outside_range", f"/dataset/series/{series_index}/values/{value_index}", "雷达数据值超出声明的极坐标范围。")


def _validate_heatmap(dataset: HeatmapDataset, issues: _Issues) -> None:
    if not _bounded(dataset.x_categories, "/dataset/x_categories", issues) or not _bounded(dataset.y_categories, "/dataset/y_categories", issues):
        return
    for index, item in enumerate(dataset.x_categories):
        _category(item, f"/dataset/x_categories/{index}", issues)
    for index, item in enumerate(dataset.y_categories):
        _category(item, f"/dataset/y_categories/{index}", issues)
    _unique_ids(dataset.x_categories, "/dataset/x_categories", issues)
    _unique_ids(dataset.y_categories, "/dataset/y_categories", issues)
    if not _bounded(dataset.values, "/dataset/values", issues):
        return
    if len(dataset.values) != len(dataset.y_categories):
        issues.add("heatmap_row_count_mismatch", "/dataset/values", "热力图行数必须与 y_categories 数量相同。")
    for row_index, row in enumerate(dataset.values):
        if not _bounded(row, f"/dataset/values/{row_index}", issues):
            continue
        if len(row) != len(dataset.x_categories):
            issues.add("heatmap_column_count_mismatch", f"/dataset/values/{row_index}", "每行列数必须与 x_categories 数量相同。")
        for column_index, item in enumerate(row):
            if item is not None:
                _number(item, f"/dataset/values/{row_index}/{column_index}", issues)


def _validate_treemap(dataset: TreemapDataset, issues: _Issues) -> None:
    if not _bounded(dataset.nodes, "/dataset/nodes", issues):
        return
    _id(dataset.root_id, "/dataset/root_id", issues)
    _unique_ids(dataset.nodes, "/dataset/nodes", issues)
    nodes: dict[str, TreemapNode] = {}
    children: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []
    for index, node in enumerate(dataset.nodes):
        path = f"/dataset/nodes/{index}"
        if not isinstance(node, TreemapNode):
            issues.add("invalid_treemap_node", path, "Treemap 节点结构无效。")
            continue
        _text(node.label, f"{path}/label", issues)
        if node.value is not None:
            _number(node.value, f"{path}/value", issues, minimum=0)
        if isinstance(node.id, str):
            nodes[node.id] = node
        if node.parent_id is None:
            roots.append(node.id)
        elif isinstance(node.parent_id, str):
            children[node.parent_id].append(node.id)
        else:
            issues.add("invalid_treemap_parent", f"{path}/parent_id", "parent_id 必须是节点 ID 或 null。")
    if roots != [dataset.root_id]:
        issues.add("invalid_treemap_root", "/dataset/root_id", "Treemap 必须且只能有一个根节点，且与 root_id 一致。")
    for index, node in enumerate(dataset.nodes):
        if not isinstance(node, TreemapNode):
            continue
        if node.parent_id is not None and node.parent_id not in nodes:
            issues.add("unknown_treemap_parent", f"/dataset/nodes/{index}/parent_id", "Treemap 父节点不存在。")

    state: dict[str, int] = {}
    totals: dict[str, float | None] = {}
    cycle_nodes: set[str] = set()

    def visit(node_id: str) -> float | None:
        status = state.get(node_id, 0)
        if status == 1:
            cycle_nodes.add(node_id)
            return None
        if status == 2:
            return totals.get(node_id)
        state[node_id] = 1
        node = nodes[node_id]
        child_ids = children.get(node_id, [])
        total = 0.0
        if not child_ids:
            if node.value is None or type(node.value) not in (int, float) or node.value <= 0:
                issues.add("invalid_treemap_leaf_value", f"/dataset/nodes/{_node_index(dataset.nodes, node_id)}/value", "Treemap 叶节点必须有正数 value。")
                total = None
            else:
                total = float(node.value)
        else:
            child_values: list[float] = []
            for child_id in child_ids:
                child_value = visit(child_id)
                if child_value is not None:
                    child_values.append(child_value)
            try:
                total = math.fsum(child_values)
            except OverflowError:
                total = math.inf
            if not math.isfinite(total):
                issues.add("treemap_value_overflow", f"/dataset/nodes/{_node_index(dataset.nodes, node_id)}/value", "Treemap 子节点权重总和必须有限。")
                total = None
            if node.value is not None and total is not None:
                tolerance = 1e-9 * max(1.0, abs(float(node.value)), abs(total))
                if abs(float(node.value) - total) > tolerance:
                    issues.add("treemap_parent_total_mismatch", f"/dataset/nodes/{_node_index(dataset.nodes, node_id)}/value", "Treemap 内部节点值必须等于其后代叶节点总值。")
                else:
                    total = float(node.value)
        state[node_id] = 2
        totals[node_id] = total
        return total

    for node_id in nodes:
        visit(node_id)
    if cycle_nodes:
        first = min(cycle_nodes)
        issues.add("treemap_cycle", f"/dataset/nodes/{_node_index(dataset.nodes, first)}/parent_id", "Treemap 层级不得包含循环。")


def _node_index(nodes: tuple[object, ...], node_id: str) -> int:
    for index, node in enumerate(nodes):
        if getattr(node, "id", None) == node_id:
            return index
    return 0
