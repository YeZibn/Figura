"""Pure structural and semantic validation for ChartFigure values."""

from __future__ import annotations

import re
from collections.abc import Sequence

from figura.shared.json_schema import JsonValueError, canonical_json_dumps

from ..chartspec.models import ChartSpecData
from ..chartspec.validation import validate_chart_spec_data
from ..limits import (
    MAX_ISSUES,
    MAX_ISSUE_MESSAGE_LENGTH,
    MAX_ISSUE_PATH_BYTES,
    MAX_TEXT_LENGTH,
)
from .errors import ChartFigureIssue
from .limits import (
    CHART_FIGURE_SCHEMA_VERSION,
    MAX_CHART_FIGURE_BYTES,
    MAX_CHART_FIGURE_ITEMS,
    MAX_CHART_ID_LENGTH,
    MAX_FIGURE_COLUMNS,
    MAX_MEASUREMENT_REFS_PER_CHART,
)
from .models import ChartFigure, ChartFigureItem, FigureLayout, MeasurementRef


_CHART_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def validate_chart_figure(value: object) -> tuple[ChartFigureIssue, ...]:
    """Return bounded Figure issues in stable order without mutating the value."""
    issues: list[ChartFigureIssue] = []

    def add(code: str, path: str, message: str) -> None:
        if len(issues) >= MAX_ISSUES:
            return
        try:
            path_size = len(path.encode("utf-8"))
        except UnicodeEncodeError:
            path = ""
            path_size = 0
        if path_size > MAX_ISSUE_PATH_BYTES:
            path = ""
        issues.append(
            ChartFigureIssue(
                code=code,
                field_path=path,
                message=message[:MAX_ISSUE_MESSAGE_LENGTH],
            )
        )

    if not isinstance(value, ChartFigure):
        add("invalid_chart_figure", "", "需要 ChartFigure 值。")
        return tuple(issues)

    if type(value.schema_version) is not int or value.schema_version != CHART_FIGURE_SCHEMA_VERSION:
        add("unsupported_schema_version", "/schema_version", "ChartFigure schema_version 不受支持。")
    if not isinstance(value.title, str):
        add("invalid_title", "/title", "Figure 标题必须是文本。")
    elif len(value.title) > MAX_TEXT_LENGTH:
        add("title_too_long", "/title", "Figure 标题超过 160 个字符限制。")

    charts = value.charts
    if not isinstance(charts, (tuple, list)):
        add("invalid_charts", "/charts", "charts 必须是有序图表列表。")
        chart_items: Sequence[object] = ()
    else:
        chart_items = charts
        if not chart_items:
            add("empty_charts", "/charts", "Figure 至少需要一个图表。")
        if len(chart_items) > MAX_CHART_FIGURE_ITEMS:
            add("too_many_charts", "/charts", "Figure 最多支持四个图表。")

    if not isinstance(value.layout, FigureLayout):
        add("invalid_layout", "/layout", "Figure layout 结构无效。")
    else:
        columns = value.layout.columns
        if type(columns) is not int:
            add("invalid_columns", "/layout/columns", "layout.columns 必须是整数。")
        elif not 1 <= columns <= MAX_FIGURE_COLUMNS:
            add("invalid_columns", "/layout/columns", "layout.columns 必须是 1 或 2。")
        elif chart_items and columns > len(chart_items):
            add("columns_exceed_charts", "/layout/columns", "layout.columns 不能大于图表数量。")

    chart_ids: set[str] = set()
    for index, chart in enumerate(chart_items[:MAX_CHART_FIGURE_ITEMS]):
        path = f"/charts/{index}"
        if not isinstance(chart, ChartFigureItem):
            add("invalid_chart", path, "Figure 子图结构无效。")
            continue

        chart_id = chart.chart_id
        if not isinstance(chart_id, str) or not chart_id.isascii() or not _CHART_ID_PATTERN.fullmatch(chart_id):
            add("invalid_chart_id", f"{path}/chart_id", "chart_id 必须匹配 [A-Za-z0-9_-]{1,64}。")
        elif chart_id in chart_ids:
            add("duplicate_chart_id", f"{path}/chart_id", "chart_id 在同一 Figure 中必须唯一。")
        else:
            chart_ids.add(chart_id)

        if not isinstance(chart.chart_spec, ChartSpecData):
            add("invalid_chart_spec", f"{path}/chart_spec", "子图必须包含 ChartSpecData。")
        else:
            for child_issue in validate_chart_spec_data(chart.chart_spec):
                child_path = f"{path}/chart_spec{child_issue.field_path}"
                add(child_issue.code, child_path, child_issue.message)

        references = chart.measurement_refs
        if not isinstance(references, (tuple, list)):
            add("invalid_measurement_refs", f"{path}/measurement_refs", "measurement_refs 必须是列表。")
            continue
        if len(references) > MAX_MEASUREMENT_REFS_PER_CHART:
            add("too_many_measurement_refs", f"{path}/measurement_refs", "每个图表最多支持 16 个测量引用。")

        seen_references: set[tuple[str, str]] = set()
        for ref_index, reference in enumerate(references[:MAX_MEASUREMENT_REFS_PER_CHART]):
            ref_path = f"{path}/measurement_refs/{ref_index}"
            if not isinstance(reference, MeasurementRef):
                add("invalid_measurement_ref", ref_path, "测量引用结构无效。")
                continue
            if not isinstance(reference.run_id, str) or not reference.run_id:
                add("invalid_run_id", f"{ref_path}/run_id", "run_id 必须是非空文本。")
            if not isinstance(reference.call_id, str) or not reference.call_id:
                add("invalid_call_id", f"{ref_path}/call_id", "call_id 必须是非空文本。")
            if (
                isinstance(reference.run_id, str)
                and reference.run_id
                and isinstance(reference.call_id, str)
                and reference.call_id
            ):
                key = (reference.run_id, reference.call_id)
                if key in seen_references:
                    add("duplicate_measurement_ref", ref_path, "同一子图不能重复引用测量结果。")
                seen_references.add(key)

    if not issues:
        try:
            encoded = canonical_json_dumps(value.to_dict()).encode("utf-8")
        except (JsonValueError, UnicodeEncodeError, AttributeError, TypeError, RecursionError, OverflowError):
            add("invalid_chart_figure", "", "ChartFigure 无法序列化为 JSON。")
        else:
            if len(encoded) > MAX_CHART_FIGURE_BYTES:
                add("content_too_large", "", "ChartFigure 内容超过 64 KiB 限制。")

    return tuple(issues)
