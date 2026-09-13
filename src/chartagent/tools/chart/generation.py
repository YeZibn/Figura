"""Deterministic ChartSpec-to-image generation for the Agent tool surface."""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO
import math
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from ...spec import ChartSpec, ChartType, DataPoint
from ..result import GeneratedImage, ToolResult
from ..tool import Tool

DEFAULT_CHART_WIDTH = 1200
DEFAULT_CHART_HEIGHT = 800
MAX_CHART_WIDTH = 2400
MAX_CHART_HEIGHT = 1600
MAX_CHART_BYTES = 10 * 1024 * 1024
MAX_CHART_POINTS = 512
MAX_TITLE_LENGTH = 240
MAX_LABEL_LENGTH = 160


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _series_name(point: DataPoint) -> str:
    return point.series.strip() if isinstance(point.series, str) and point.series.strip() else "数据"


def _unique(values: Iterable[str]) -> list[str]:
    return list(OrderedDict.fromkeys(values))


def _validate_generation(spec: ChartSpec) -> list[dict[str, str]]:
    issues = [
        {"location": issue.location, "message": issue.message}
        for issue in spec.validate()
    ]
    chart_type = spec.metadata.chart_type
    if len(spec.dataset) > MAX_CHART_POINTS:
        issues.append({"location": "dataset", "message": f"dataset exceeds {MAX_CHART_POINTS} points"})
    if chart_type in {ChartType.BAR, ChartType.PIE}:
        seen: set[tuple[str, str]] = set()
        total = 0.0
        for index, point in enumerate(spec.dataset):
            location = f"dataset[{index}]"
            if not isinstance(point.category, str) or not point.category.strip():
                issues.append({"location": f"{location}.category", "message": "category must be a non-empty string"})
            elif len(point.category.strip()) > MAX_LABEL_LENGTH:
                issues.append({"location": f"{location}.category", "message": "category exceeds the size limit"})
            if not _finite(point.value):
                issues.append({"location": f"{location}.value", "message": "value must be a finite number"})
                continue
            value = float(point.value)
            if chart_type is ChartType.PIE and value < 0:
                issues.append({"location": f"{location}.value", "message": "pie values must not be negative"})
            total += value
            key = (point.category or "", _series_name(point))
            if chart_type is ChartType.BAR and key in seen:
                issues.append({"location": location, "message": "duplicate category and series point"})
            seen.add(key)
        if chart_type is ChartType.PIE and total <= 0:
            issues.append({"location": "dataset", "message": "pie values must have a positive total"})
    else:
        for index, point in enumerate(spec.dataset):
            location = f"dataset[{index}]"
            if not _finite(point.x):
                issues.append({"location": f"{location}.x", "message": "x must be a finite number"})
            if not _finite(point.y):
                issues.append({"location": f"{location}.y", "message": "y must be a finite number"})
    return issues


def _group_points(points: list[DataPoint]) -> OrderedDict[str, list[DataPoint]]:
    groups: OrderedDict[str, list[DataPoint]] = OrderedDict()
    for point in points:
        groups.setdefault(_series_name(point), []).append(point)
    return groups


def _configure_axes(ax: Any, spec: ChartSpec) -> None:
    if spec.metadata.title:
        ax.set_title(spec.metadata.title[:MAX_TITLE_LENGTH])
    if spec.axes is not None:
        ax.set_xlabel(spec.axes.x.label[:MAX_LABEL_LENGTH])
        ax.set_ylabel(spec.axes.y.label[:MAX_LABEL_LENGTH])
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)


def _render_bar(ax: Any, spec: ChartSpec) -> None:
    categories = _unique(
        [
            category
            for category in (spec.axes.x.categories if spec.axes and spec.axes.x.categories else [])
            if isinstance(category, str)
        ]
        + [point.category or "" for point in spec.dataset]
    )
    groups = _group_points(spec.dataset)
    explicit_series = any(point.series for point in spec.dataset)
    positions = np.arange(len(categories), dtype=float)
    width = 0.8 / max(1, len(groups))
    colors = plt.get_cmap("tab10")
    for group_index, (series, points) in enumerate(groups.items()):
        values = {point.category: float(point.value) for point in points}
        offset = (group_index - (len(groups) - 1) / 2) * width
        bars = ax.bar(
            positions + offset,
            [values.get(category, 0.0) for category in categories],
            width,
            label=series,
            color=colors(group_index % 10),
        )
        for bar in bars:
            value = bar.get_height()
            ax.annotate(
                f"{value:g}",
                (bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    ax.set_xticks(positions, categories)
    if explicit_series:
        ax.legend()


def _render_line(ax: Any, spec: ChartSpec) -> None:
    groups = _group_points(spec.dataset)
    colors = plt.get_cmap("tab10")
    explicit_series = any(point.series for point in spec.dataset)
    for index, (series, points) in enumerate(groups.items()):
        ax.plot(
            [float(point.x) for point in points],
            [float(point.y) for point in points],
            marker="o",
            label=series,
            color=colors(index % 10),
        )
    if explicit_series:
        ax.legend()


def _render_scatter(ax: Any, spec: ChartSpec) -> None:
    groups = _group_points(spec.dataset)
    colors = plt.get_cmap("tab10")
    explicit_series = any(point.series for point in spec.dataset)
    for index, (series, points) in enumerate(groups.items()):
        ax.scatter(
            [float(point.x) for point in points],
            [float(point.y) for point in points],
            label=series,
            color=colors(index % 10),
            alpha=0.86,
        )
    if explicit_series:
        ax.legend()


def _render_pie(ax: Any, spec: ChartSpec) -> None:
    labels = [point.category or "" for point in spec.dataset]
    values = [float(point.value) for point in spec.dataset]
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")


def render_chart(
    spec: dict[str, Any],
    width: int = DEFAULT_CHART_WIDTH,
    height: int = DEFAULT_CHART_HEIGHT,
) -> ToolResult | dict[str, Any]:
    """Render a validated ChartSpec as a bounded PNG-backed ToolResult."""
    try:
        chart_spec = ChartSpec.from_dict(spec if isinstance(spec, dict) else {})
        issues = _validate_generation(chart_spec)
        width = int(width)
        height = int(height)
        if not 1 <= width <= MAX_CHART_WIDTH or not 1 <= height <= MAX_CHART_HEIGHT:
            issues.append(
                {
                    "location": "dimensions",
                    "message": f"dimensions must be within {MAX_CHART_WIDTH}x{MAX_CHART_HEIGHT}",
                }
            )
        if issues:
            return {"error": "ChartSpec cannot be rendered", "issues": issues}

        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        try:
            chart_type = chart_spec.metadata.chart_type
            if chart_type is ChartType.BAR:
                _render_bar(ax, chart_spec)
            elif chart_type is ChartType.LINE:
                _render_line(ax, chart_spec)
            elif chart_type is ChartType.PIE:
                _render_pie(ax, chart_spec)
            elif chart_type is ChartType.SCATTER:
                _render_scatter(ax, chart_spec)
            else:  # pragma: no cover - ChartType.from_dict closes this set.
                return {"error": f"unsupported chart type: {chart_type}"}
            _configure_axes(ax, chart_spec)
            fig.tight_layout()
            output = BytesIO()
            fig.savefig(output, format="png", dpi=100)
            content = output.getvalue()
        finally:
            plt.close(fig)

        if len(content) > MAX_CHART_BYTES:
            return {"error": "rendered chart exceeds the configured byte limit"}
        with Image.open(BytesIO(content)) as image:
            actual_width, actual_height = image.size
        title = chart_spec.metadata.title[:MAX_TITLE_LENGTH] or f"{chart_spec.metadata.chart_type.value} chart"
        data = {
            "kind": "generated_chart",
            "chart_type": chart_spec.metadata.chart_type.value,
            "title": title,
            "media_type": "image/png",
            "byte_count": len(content),
            "width": actual_width,
            "height": actual_height,
            "point_count": len(chart_spec.dataset),
            "series": _unique(_series_name(point) for point in chart_spec.dataset),
        }
        return ToolResult(
            data=data,
            images=(
                GeneratedImage(
                    content=content,
                    media_type="image/png",
                    caption=f"生成图表：{title}",
                    metadata={
                        "kind": "generated_chart",
                        "chart_type": chart_spec.metadata.chart_type.value,
                        "title": title,
                        "width": actual_width,
                        "height": actual_height,
                    },
                ),
            ),
        )
    except (TypeError, ValueError, KeyError) as exc:
        return {"error": f"ChartSpec cannot be rendered: {str(exc)[:240]}"}
    except Exception as exc:  # noqa: BLE001 - renderer failures stay inside the tool boundary.
        return {"error": f"chart renderer unavailable: {str(exc)[:240]}"}


_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {"type": "object"},
        "axes": {"type": ["object", "null"]},
        "dataset": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["metadata", "dataset"],
    "additionalProperties": False,
}

RENDER_CHART = Tool(
    name="render_chart",
    description=(
        "Render a validated ChartSpec as a bounded PNG chart. Use after "
        "assembling or validating chart data when a visual chart output is useful."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spec": _SPEC_SCHEMA,
            "width": {"type": "integer", "minimum": 1, "maximum": MAX_CHART_WIDTH},
            "height": {"type": "integer", "minimum": 1, "maximum": MAX_CHART_HEIGHT},
        },
        "required": ["spec"],
        "additionalProperties": False,
    },
    fn=render_chart,
)


__all__ = [
    "DEFAULT_CHART_HEIGHT",
    "DEFAULT_CHART_WIDTH",
    "MAX_CHART_BYTES",
    "MAX_CHART_HEIGHT",
    "MAX_CHART_POINTS",
    "MAX_CHART_WIDTH",
    "RENDER_CHART",
    "render_chart",
]
