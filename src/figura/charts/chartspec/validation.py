"""Pure generation-readiness validation for ChartSpecData."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from ..limits import (
    MAX_ISSUES,
    MAX_ISSUE_MESSAGE_LENGTH,
    MAX_ISSUE_PATH_BYTES,
    MAX_TEXT_LENGTH,
)
from .errors import ChartSpecIssue
from .limits import MAX_DATA_POINTS, MAX_FINITE_NUMBER
from .models import (
    Axis,
    Axes,
    CategoryValuePoint,
    ChartMetadata,
    ChartSpecData,
    ChartType,
    CoordinatePoint,
)

IssueCollector = Callable[[str, str, str], None]
CategoryPointEntry = tuple[int, CategoryValuePoint, str, str | None]
CoordinatePointEntry = tuple[int, CoordinatePoint, str | None]


class _InvalidValue:
    pass


_INVALID = _InvalidValue()


def validate_chart_spec_data(value: object) -> tuple[ChartSpecIssue, ...]:
    """Return bounded structural and semantic readiness issues in stable order."""
    issues: list[ChartSpecIssue] = []

    def add(code: str, path: str, message: str) -> None:
        if len(issues) >= MAX_ISSUES:
            return
        try:
            path_bytes = path.encode("utf-8")
        except UnicodeEncodeError:
            path = ""
            path_bytes = b""
        if len(path_bytes) > MAX_ISSUE_PATH_BYTES:
            path = ""
        issues.append(
            ChartSpecIssue(
                code=code,
                field_path=path,
                message=message[:MAX_ISSUE_MESSAGE_LENGTH],
            )
        )

    if not isinstance(value, ChartSpecData):
        add("invalid_chart_spec", "", "需要 ChartSpecData 值。")
        return tuple(issues)

    if type(value.schema_version) is not int or value.schema_version != 1:
        add("unsupported_schema_version", "/schema_version", "ChartSpec schema_version 不受支持。")

    metadata = value.metadata
    if not isinstance(metadata, ChartMetadata):
        add("invalid_metadata", "/metadata", "metadata 结构无效。")
        chart_type = None
    else:
        chart_type = metadata.chart_type if isinstance(metadata.chart_type, ChartType) else None
        if chart_type is None:
            add("unsupported_chart_type", "/metadata/chart_type", "chart_type 不受支持。")
        _validate_text(metadata.title, "/metadata/title", add, allow_empty=True)
        if metadata.source is not None:
            _validate_text(metadata.source, "/metadata/source", add, allow_empty=True)
        _validate_text(metadata.note, "/metadata/note", add, allow_empty=True)

    dataset = value.dataset
    if not isinstance(dataset, (tuple, list)):
        add("invalid_dataset", "/dataset", "dataset 必须是有序数据点列表。")
        points: Sequence[object] = ()
    else:
        points = dataset
        if not points:
            add("empty_dataset", "/dataset", "dataset 不能为空。")
        if len(points) > MAX_DATA_POINTS:
            add("too_many_data_points", "/dataset", "dataset 超过 512 个数据点限制。")
            points = points[:MAX_DATA_POINTS]

    axes = value.axes
    if chart_type is ChartType.PIE:
        if axes is not None:
            add("axes_not_allowed", "/axes", "pie 图表不能包含坐标轴。")
    elif chart_type in {ChartType.BAR, ChartType.LINE, ChartType.SCATTER}:
        if not isinstance(axes, Axes):
            add("axes_required", "/axes", "该图表类型需要 x 和 y 坐标轴。")
            axes = None

    if isinstance(axes, Axes):
        x_categories = _validate_axis(axes.x, "/axes/x", add)
        _validate_axis(axes.y, "/axes/y", add, allow_categories=False)
    else:
        x_categories = None

    valid_category_points: list[CategoryPointEntry] = []
    valid_coordinate_points: list[CoordinatePointEntry] = []
    for index, point in enumerate(points):
        point_path = f"/dataset/{index}"
        if isinstance(point, CategoryValuePoint):
            category = _validate_text(
                point.category,
                f"{point_path}/category",
                add,
                allow_empty=False,
            )
            numeric_ok = _validate_number(point.value, f"{point_path}/value", add)
            series = _validate_optional_series(point.series, f"{point_path}/series", add)
            if chart_type not in {ChartType.BAR, ChartType.PIE}:
                add("unexpected_point_shape", point_path, "该图表类型需要 x/y 坐标数据点。")
            elif category is not None and numeric_ok and series is not _INVALID:
                valid_category_points.append((index, point, category, series))
        elif isinstance(point, CoordinatePoint):
            x_ok = _validate_number(point.x, f"{point_path}/x", add)
            y_ok = _validate_number(point.y, f"{point_path}/y", add)
            series = _validate_optional_series(point.series, f"{point_path}/series", add)
            if chart_type not in {ChartType.LINE, ChartType.SCATTER}:
                add("unexpected_point_shape", point_path, "该图表类型需要 category/value 数据点。")
            elif x_ok and y_ok and series is not _INVALID:
                valid_coordinate_points.append((index, point, series))
        else:
            add("invalid_data_point", point_path, "数据点结构无效。")

    if chart_type is ChartType.BAR:
        _validate_bar(valid_category_points, x_categories, axes, add)
        _validate_ranges(valid_category_points, (), chart_type, axes, add)
    elif chart_type is ChartType.PIE:
        _validate_pie(valid_category_points, add)
    elif chart_type is ChartType.LINE:
        _validate_line(valid_coordinate_points, x_categories, axes, add)
        _validate_ranges((), valid_coordinate_points, chart_type, axes, add)
    elif chart_type is ChartType.SCATTER:
        if x_categories is not None:
            add("scatter_categories_not_supported", "/axes/x/categories", "scatter 图表不支持类别横轴。")
        _validate_ranges((), valid_coordinate_points, chart_type, axes, add)

    return tuple(issues)


def _validate_text(
    value: object,
    path: str,
    add: IssueCollector,
    *,
    allow_empty: bool,
) -> str | None:
    if not isinstance(value, str):
        add("invalid_text", path, "字段必须是文本。")
        return None
    if len(value) > MAX_TEXT_LENGTH:
        add("text_too_long", path, "文本超过 160 个字符限制。")
        return None
    normalized = value.strip()
    if not allow_empty and not normalized:
        add("empty_text", path, "文本不能为空。")
        return None
    return normalized


def _validate_optional_series(
    value: object,
    path: str,
    add: IssueCollector,
) -> str | None | _InvalidValue:
    if value is None:
        return None
    normalized = _validate_text(value, path, add, allow_empty=False)
    return normalized if normalized is not None else _INVALID


def _validate_number(value: object, path: str, add: IssueCollector) -> bool:
    if type(value) not in (int, float):
        add("invalid_number", path, "字段必须是有限 binary64 数值。")
        return False
    if type(value) is float and not math.isfinite(value):
        add("invalid_number", path, "字段必须是有限 binary64 数值。")
        return False
    try:
        in_range = abs(value) <= MAX_FINITE_NUMBER
    except OverflowError:
        in_range = False
    if not in_range:
        add("number_out_of_range", path, "数值超出有限 binary64 范围。")
        return False
    return True


def _validate_axis(
    axis: object,
    path: str,
    add: IssueCollector,
    *,
    allow_categories: bool = True,
) -> tuple[str, ...] | None:
    if not isinstance(axis, Axis):
        add("invalid_axis", path, "坐标轴结构无效。")
        return None
    _validate_text(axis.label, f"{path}/label", add, allow_empty=False)

    normalized_categories: list[str] | None = None
    if axis.categories is not None:
        if not allow_categories:
            add("axis_categories_not_supported", f"{path}/categories", "该坐标轴不支持类别列表。")
        categories = axis.categories
        if not isinstance(categories, (tuple, list)):
            add("invalid_categories", f"{path}/categories", "categories 必须是类别列表。")
        else:
            if not categories:
                add("empty_categories", f"{path}/categories", "categories 不能为空。")
            if len(categories) > MAX_DATA_POINTS:
                add("too_many_categories", f"{path}/categories", "categories 超过 512 项限制。")
            normalized_categories = []
            seen: set[str] = set()
            for index, category in enumerate(categories[:MAX_DATA_POINTS]):
                normalized = _validate_text(
                    category,
                    f"{path}/categories/{index}",
                    add,
                    allow_empty=False,
                )
                if normalized is None:
                    continue
                if normalized in seen:
                    add("duplicate_category", f"{path}/categories/{index}", "类别不能重复。")
                    continue
                seen.add(normalized)
                normalized_categories.append(normalized)

    minimum_ok = axis.min_value is None or _validate_number(
        axis.min_value,
        f"{path}/min_value",
        add,
    )
    maximum_ok = axis.max_value is None or _validate_number(
        axis.max_value,
        f"{path}/max_value",
        add,
    )
    if (
        minimum_ok
        and maximum_ok
        and axis.min_value is not None
        and axis.max_value is not None
        and axis.min_value >= axis.max_value
    ):
        add("invalid_axis_range", path, "坐标轴最小值必须小于最大值。")
    return tuple(normalized_categories) if normalized_categories is not None else None


def _validate_bar(
    points: Sequence[CategoryPointEntry],
    declared_categories: tuple[str, ...] | None,
    axes: object,
    add: IssueCollector,
) -> None:
    if isinstance(axes, Axes) and isinstance(axes.x, Axis) and (
        axes.x.min_value is not None or axes.x.max_value is not None
    ):
        add("categorical_axis_range", "/axes/x", "bar 图表的类别横轴不能设置数值范围。")

    domain = list(declared_categories) if declared_categories is not None else []
    series_order: list[str | None] = []
    seen_points: set[tuple[str, str | None]] = set()
    represented: dict[str | None, set[str]] = {}
    for _, _, category, series in points:
        if declared_categories is None and category not in domain:
            domain.append(category)
        elif declared_categories is not None and category not in declared_categories:
            # Axis validation reports malformed declared categories; this points
            # to the data that falls outside an otherwise valid declared domain.
            add("category_outside_domain", "/dataset", "数据点包含横轴类别域之外的类别。")
        key = (category, series)
        if key in seen_points:
            add("duplicate_category_series", "/dataset", "同一系列的类别数据点不能重复。")
        seen_points.add(key)
        if series not in represented:
            represented[series] = set()
            series_order.append(series)
        represented[series].add(category)

    for series in series_order:
        if any(category not in represented[series] for category in domain):
            add("missing_category_value", "/dataset", "每个系列都必须为类别域中的每个类别提供显式数值。")


def _validate_pie(points: Sequence[CategoryPointEntry], add: IssueCollector) -> None:
    seen_categories: set[str] = set()
    values: list[float] = []
    for index, point, category, _series in points:
        if category in seen_categories:
            add("duplicate_pie_category", f"/dataset/{index}/category", "pie 图表的类别不能重复。")
        seen_categories.add(category)
        if point.series is not None:
            add("pie_series_not_supported", f"/dataset/{index}/series", "pie 图表不支持 series 字段。")
        try:
            numeric = float(point.value)
        except (OverflowError, TypeError, ValueError):
            continue
        if numeric < 0:
            add("negative_pie_value", f"/dataset/{index}/value", "pie 图表的数值不能为负。")
        values.append(numeric)

    try:
        total = math.fsum(values)
    except (OverflowError, ValueError):
        total = math.inf
    if not math.isfinite(total):
        add("pie_total_overflow", "/dataset", "pie 图表的数值总和超出有限范围。")
    elif total <= 0:
        add("invalid_pie_total", "/dataset", "pie 图表的数值总和必须大于零。")


def _validate_line(
    points: Sequence[CoordinatePointEntry],
    categories: tuple[str, ...] | None,
    axes: object,
    add: IssueCollector,
) -> None:
    if categories is not None and isinstance(axes, Axes) and isinstance(axes.x, Axis) and (
        axes.x.min_value is not None or axes.x.max_value is not None
    ):
        add("categorical_axis_range", "/axes/x", "类别横轴不能设置数值范围。")

    previous: dict[str | None, float] = {}
    seen_x: dict[str | None, set[float]] = {}
    represented_positions: dict[str | None, set[int]] = {}
    series_order: list[str | None] = []

    for index, point, series in points:
        x = float(point.x)
        if series not in seen_x:
            seen_x[series] = set()
            represented_positions[series] = set()
            series_order.append(series)
        if x in seen_x[series]:
            add("duplicate_line_x", f"/dataset/{index}/x", "同一折线系列的 x 坐标不能重复。")
        seen_x[series].add(x)
        if series in previous and x < previous[series]:
            add("line_x_not_increasing", f"/dataset/{index}/x", "同一折线系列的 x 坐标必须严格递增。")
        previous[series] = x

        if categories is not None:
            if not x.is_integer():
                add("line_category_position_not_integer", f"/dataset/{index}/x", "类别折线的 x 坐标必须是整数位置。")
                continue
            position = int(x)
            if position < 0 or position >= len(categories):
                add("line_category_position_out_of_range", f"/dataset/{index}/x", "x 坐标超出类别位置范围。")
                continue
            represented_positions[series].add(position)

    if categories is not None:
        required_positions = set(range(len(categories)))
        for series in series_order:
            if not required_positions.issubset(represented_positions[series]):
                add("missing_line_category_position", "/dataset", "每个折线系列都必须表示全部声明类别。")


def _validate_ranges(
    category_points: Sequence[CategoryPointEntry],
    coordinate_points: Sequence[CoordinatePointEntry],
    chart_type: ChartType,
    axes: object,
    add: IssueCollector,
) -> None:
    if (
        not isinstance(axes, Axes)
        or not isinstance(axes.x, Axis)
        or not isinstance(axes.y, Axis)
    ):
        return

    def check(
        value: int | float,
        bound: int | float | None,
        path: str,
        *,
        minimum: bool,
    ) -> None:
        if bound is None:
            return
        if minimum and value < bound or not minimum and value > bound:
            add("value_outside_axis_range", path, "数据点超出坐标轴声明范围。")

    if chart_type is ChartType.BAR:
        for index, point, _, _ in category_points:
            check(point.value, axes.y.min_value, f"/dataset/{index}/value", minimum=True)
            check(point.value, axes.y.max_value, f"/dataset/{index}/value", minimum=False)
    else:
        for index, point, _ in coordinate_points:
            check(point.x, axes.x.min_value, f"/dataset/{index}/x", minimum=True)
            check(point.x, axes.x.max_value, f"/dataset/{index}/x", minimum=False)
            check(point.y, axes.y.min_value, f"/dataset/{index}/y", minimum=True)
            check(point.y, axes.y.max_value, f"/dataset/{index}/y", minimum=False)
