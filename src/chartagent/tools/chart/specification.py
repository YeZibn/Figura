"""Atomic ChartSpec assembly and internal validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from ...spec import (
    Axes,
    Axis,
    ChartCoverage,
    ChartFigure,
    ChartFigureItem,
    ChartMetadata,
    ChartSpec,
    ChartSpecCollection,
    ChartType,
    DataPoint,
    FigureLayout,
    FigureSource,
    MAX_COLLECTION_FIGURES,
    MAX_FIGURE_CHARTS,
    MAX_FIGURE_COLUMNS,
    ValidationIssue,
)
from ..core.definition import Tool
from .validation import MAX_GENERATION_POINTS, MAX_GENERATION_LABEL_LENGTH, validate_generation

_CARTESIAN_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


def _assembly_error(message: str, location: str) -> dict[str, Any]:
    bounded_message = str(message)[:240]
    return {
        "error": bounded_message,
        "issues": [{"location": location[:120], "message": bounded_message}],
    }


def _assemble_single_spec(
    chart_type: str,
    points: list[dict],
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    source: str | None = None,
) -> dict:
    """Atomically construct and validate a serialization-ready ChartSpec."""
    try:
        kind = ChartType(chart_type)
    except (TypeError, ValueError):
        return _assembly_error(f"unknown chart_type: {chart_type!r}", "chart_type")

    if not isinstance(points, list) or not points:
        return _assembly_error("points must be a non-empty array", "points")
    if kind in _CARTESIAN_TYPES and (
        not isinstance(x_label, str)
        or not x_label.strip()
        or not isinstance(y_label, str)
        or not y_label.strip()
    ):
        return _assembly_error(
            f"{kind.value} charts require non-empty x_label and y_label",
            "axes",
        )

    data_points: list[DataPoint] = []
    for index, raw in enumerate(points):
        if not isinstance(raw, Mapping):
            return _assembly_error(f"points[{index}] must be an object", f"points[{index}]")
        point = DataPoint.from_dict(raw)
        data_points.append(point)

    axes = None
    if kind in _CARTESIAN_TYPES:
        categories = (
            list(dict.fromkeys(
                point.category.strip()
                for point in data_points
                if isinstance(point.category, str)
            ))
            if kind is ChartType.BAR
            else None
        )
        axes = Axes(
            x=Axis(label=x_label, categories=categories),
            y=Axis(label=y_label),
        )

    chart_spec = ChartSpec(
        metadata=ChartMetadata(chart_type=kind, title=title, source=source),
        axes=axes,
        dataset=data_points,
    )
    validation = validate_generation(chart_spec)
    if validation.blocking:
        issues = validation.legacy_issues()
        return {
            "error": issues[0]["message"] if issues else "ChartSpec validation failed",
            "issues": issues,
            "validation": validation.to_dict(),
        }
    return chart_spec.to_dict()


def _collection_error(message: str, location: str, *, validation: dict | None = None) -> dict[str, Any]:
    bounded_message = str(message)[:240]
    result: dict[str, Any] = {
        "error": bounded_message,
        "issues": [{"location": location[:160], "message": bounded_message}],
    }
    if validation is not None:
        result["validation"] = validation
    return result


def _figure_child_input(child: Mapping[str, Any]) -> dict[str, Any]:
    """Translate semantic child input to the legacy single-chart assembler."""
    return {
        "chart_type": child.get("chart_type"),
        "points": child.get("points"),
        "title": child.get("title", ""),
        "x_label": child.get("x_label", ""),
        "y_label": child.get("y_label", ""),
        "source": child.get("source"),
    }


def _assemble_figure(figure: Mapping[str, Any], *, location: str = "figure") -> ChartFigure | dict[str, Any]:
    if not isinstance(figure, Mapping):
        return _collection_error("figure must be an object", location)
    source_raw = figure.get("source")
    if not isinstance(source_raw, Mapping):
        return _collection_error("figure source must include attachment_id and panel_id", f"{location}.source")
    source = FigureSource.from_dict(source_raw)
    raw_charts = figure.get("charts")
    if not isinstance(raw_charts, list) or not raw_charts:
        return _collection_error("figure charts must be a non-empty array", f"{location}.charts")
    if len(raw_charts) > MAX_FIGURE_CHARTS:
        return _collection_error("figure contains too many charts", f"{location}.charts")
    charts: list[ChartFigureItem] = []
    for index, raw_child in enumerate(raw_charts):
        child_location = f"{location}.charts[{index}]"
        if not isinstance(raw_child, Mapping):
            return _collection_error("chart item must be an object", child_location)
        chart_id = raw_child.get("chart_id")
        if not isinstance(chart_id, str) or not chart_id.strip():
            return _collection_error("chart_id must be a non-empty string", f"{child_location}.chart_id")
        child_result = _assemble_single_spec(**_figure_child_input(raw_child))
        if "error" in child_result:
            issues = [
                {
                    "location": f"{child_location}.{issue.get('location', 'spec')}",
                    "message": str(issue.get("message") or child_result.get("error"))[:240],
                }
                for issue in child_result.get("issues", [])
                if isinstance(issue, Mapping)
            ]
            return {
                "error": "ChartSpec figure assembly failed",
                "issues": issues or [{"location": child_location, "message": "child ChartSpec is invalid"}],
                "validation": child_result.get("validation", {"status": "failed"}),
            }
        try:
            child_spec = ChartSpec.from_dict(child_result)
        except (TypeError, ValueError, KeyError) as exc:
            return _collection_error(str(exc), f"{child_location}.spec")
        charts.append(
            ChartFigureItem(
                chart_id=chart_id.strip(),
                title=str(raw_child.get("display_title") or raw_child.get("title") or "")[:MAX_GENERATION_LABEL_LENGTH],
                spec=child_spec,
            )
        )
    layout_raw = figure.get("layout") or {"type": "grid", "columns": min(2, len(charts))}
    if not isinstance(layout_raw, Mapping):
        return _collection_error("figure layout must be an object", f"{location}.layout")
    layout = FigureLayout.from_dict(layout_raw)
    if layout.columns > MAX_FIGURE_COLUMNS:
        return _collection_error("figure layout columns exceed the configured limit", f"{location}.layout.columns")
    coverage_raw = figure.get("coverage")
    if not isinstance(coverage_raw, Mapping):
        return _collection_error("figure coverage is required", f"{location}.coverage")
    coverage = ChartCoverage.from_dict(coverage_raw)
    figure_id = figure.get("figure_id")
    if not isinstance(figure_id, str) or not figure_id.strip():
        return _collection_error("figure_id must be a non-empty string", f"{location}.figure_id")
    result = ChartFigure(
        figure_id=figure_id.strip(),
        source=source,
        layout=layout,
        charts=charts,
        coverage=coverage,
    )
    issues = result.validate()
    if not issues and result.coverage.status != "complete":
        issues.append(ValidationIssue("coverage.status", "figure coverage must be complete before generation"))
    if issues:
        return {
            "error": "ChartSpec figure assembly failed",
            "issues": [{"location": f"{location}.{issue.location}", "message": issue.message} for issue in issues[:32]],
            "validation": {"status": "failed", "checks": {"semantic": "failed"}},
        }
    return result


def assemble_spec(
    chart_type: str | None = None,
    points: list[dict] | None = None,
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    source: str | None = None,
    *,
    figure: dict[str, Any] | None = None,
    figures: list[dict[str, Any]] | None = None,
    collection_id: str | None = None,
) -> dict:
    """Atomically construct a single ChartSpec, figure, or collection."""
    if figure is not None and figures is not None:
        return _collection_error("provide either figure or figures, not both", "figure")
    if figures is not None:
        if not isinstance(figures, list) or not figures:
            return _collection_error("figures must be a non-empty array", "figures")
        if len(figures) > MAX_COLLECTION_FIGURES:
            return _collection_error("collection contains too many figures", "figures")
        built: list[ChartFigure] = []
        for index, item in enumerate(figures):
            result = _assemble_figure(item, location=f"figures[{index}]")
            if isinstance(result, dict):
                return result
            built.append(result)
        resolved_collection_id = collection_id or f"collection_{uuid4().hex}"
        collection = ChartSpecCollection(resolved_collection_id[:128], built)
        issues = collection.validate()
        if issues:
            return {
                "error": "ChartSpec collection assembly failed",
                "issues": [{"location": issue.location, "message": issue.message} for issue in issues[:32]],
                "validation": {"status": "failed", "checks": {"semantic": "failed"}},
            }
        return collection.to_dict()
    if figure is not None:
        result = _assemble_figure(figure)
        return result.to_dict() if isinstance(result, ChartFigure) else result
    if chart_type is None:
        return _assembly_error("chart_type is required unless figure or figures is provided", "chart_type")
    return _assemble_single_spec(chart_type, points or [], title, x_label, y_label, source)


def validate_spec(spec: dict) -> dict:
    """Run shared validation for internal callers and compatibility checks."""
    try:
        if isinstance(spec, Mapping) and spec.get("kind") == "chart_figure":
            issues = [
                {"location": issue.location, "message": issue.message}
                for issue in ChartFigure.from_dict(spec).validate()
            ]
        elif isinstance(spec, Mapping) and spec.get("kind") == "chart_spec_collection":
            issues = [
                {"location": issue.location, "message": issue.message}
                for issue in ChartSpecCollection.from_dict(spec).validate()
            ]
        else:
            chart_spec = ChartSpec.from_dict(spec)
            issues = validate_generation(chart_spec).legacy_issues()
    except Exception as exc:  # noqa: BLE001 - critic boundary
        issues = [{"location": "spec", "message": str(exc)}]
    return {"ok": not issues, "issues": issues}


POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "description": "Category label for bar or pie data; required with value for categorical charts."},
        "value": {"type": "number", "description": "Finite numeric magnitude for bar or pie data; required with category for categorical charts."},
        "x": {"type": "number", "description": "Finite numeric x coordinate for line or scatter data; required with y for coordinate charts."},
        "y": {"type": "number", "description": "Finite numeric y coordinate for line or scatter data; required with x for coordinate charts."},
        "series": {"type": "string", "description": "Optional non-empty series label used to group multi-series line or scatter data."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional extraction confidence in the inclusive range 0 to 1."},
    },
    "oneOf": [
        {"required": ["category", "value"]},
        {"required": ["x", "y"]},
    ],
    "additionalProperties": False,
}

AXIS_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Displayed axis label; required and non-empty for cartesian charts."},
        "categories": {"type": "array", "items": {"type": "string", "description": "One non-empty categorical tick label."}, "maxItems": MAX_GENERATION_POINTS, "description": "Optional ordered category labels for a categorical x-axis."},
        "min_value": {"type": "number", "description": "Optional finite lower bound for a numeric axis; must be less than max_value."},
        "max_value": {"type": "number", "description": "Optional finite upper bound for a numeric axis; must be greater than min_value."},
    },
    "required": ["label"],
    "additionalProperties": False,
}

AXES_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {**AXIS_SCHEMA, "description": "X-axis definition."},
        "y": {**AXIS_SCHEMA, "description": "Y-axis definition."},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}

CHART_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": [chart_type.value for chart_type in ChartType], "description": "Chart kind: bar, line, pie, or scatter."},
                "title": {"type": "string", "maxLength": 160, "description": "Optional bounded chart title."},
                "source": {"type": ["string", "null"], "description": "Optional source or provenance label; it is metadata, not a local path authorization."},
                "note": {"type": "string", "maxLength": 160, "description": "Optional bounded note about the chart."},
            },
            "required": ["chart_type"],
            "additionalProperties": False,
        },
        "axes": {"oneOf": [AXES_SCHEMA, {"type": "null"}], "description": "Cartesian x/y axes; omit or use null only for pie charts."},
        "dataset": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Ordered typed data points; point shape must match the selected chart type."},
    },
    "required": ["metadata", "dataset"],
    "additionalProperties": False,
}

FIGURE_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "attachment_id": {"type": "string", "description": "Exact source attachment identity."},
        "panel_id": {"type": "string", "description": "Exact source panel identity."},
    },
    "required": ["attachment_id", "panel_id"],
    "additionalProperties": False,
}

FIGURE_COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "source_series": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FIGURE_CHARTS, "description": "Series known to exist in the source panel."},
        "represented_series": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FIGURE_CHARTS, "description": "Series represented by child charts."},
        "omitted_series": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FIGURE_CHARTS, "description": "Series not represented; cannot be empty when coverage is incomplete."},
        "status": {"type": "string", "enum": ["complete", "incomplete", "unknown"], "description": "Source coverage status."},
    },
    "required": ["source_series", "represented_series", "omitted_series", "status"],
    "additionalProperties": False,
}

FIGURE_CHILD_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "chart_id": {"type": "string", "description": "Stable child chart identity within the figure."},
        "chart_type": {"type": "string", "enum": [chart_type.value for chart_type in ChartType], "description": "Child chart kind."},
        "title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional child chart title."},
        "display_title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional title shown by the composite layout."},
        "x_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Cartesian child x-axis label."},
        "y_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Cartesian child y-axis label."},
        "points": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Child chart data points."},
        "source": {"type": ["string", "null"], "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional child provenance label."},
    },
    "required": ["chart_id", "chart_type", "points"],
    "additionalProperties": False,
}

FIGURE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "figure_id": {"type": "string", "description": "Stable identity for the final composite figure."},
        "source": FIGURE_SOURCE_SCHEMA,
        "layout": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["grid"], "description": "Bounded composite layout type."},
                "columns": {"type": "integer", "minimum": 1, "maximum": MAX_FIGURE_COLUMNS, "description": "Number of grid columns."},
            },
            "required": ["type", "columns"],
            "additionalProperties": False,
        },
        "coverage": FIGURE_COVERAGE_SCHEMA,
        "charts": {"type": "array", "items": FIGURE_CHILD_INPUT_SCHEMA, "minItems": 1, "maxItems": MAX_FIGURE_CHARTS, "description": "Independent child chart descriptions."},
    },
    "required": ["figure_id", "source", "coverage", "charts"],
    "additionalProperties": False,
}

ASSEMBLE_SPEC = Tool(
    name="assemble_spec",
    description=(
        "根据已收集的证据原子地组装并校验 ChartSpec、同源 ChartFigure 或多来源 ChartSpecCollection。"
        "单图使用 chart_type 和 points；同源多子图使用 figure，必须提供 attachment_id、panel_id、coverage 和独立 charts；不同来源使用 figures。"
        "不要手写内部 IR、合并不同子图的 category/value，或把遗漏系列标记为 complete。失败会返回有界且带路径的 issues；成功结果才可交给 render_chart。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": [chart_type.value for chart_type in ChartType],
                "description": "单图或 figure 子图的图表类型：bar、line、pie 或 scatter。集合模式不填写。",
            },
            "title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional bounded chart title."},
            "x_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Required non-empty x-axis label for bar, line, and scatter charts."},
            "y_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Required non-empty y-axis label for bar, line, and scatter charts."},
            "points": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "单图数据点；bar/pie 使用 category/value，line/scatter 使用 x/y。figure 模式填写到 charts 子项。"},
            "source": {"type": ["string", "null"], "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "单图可选来源标签；不授权访问本地路径。"},
            "figure": {**FIGURE_INPUT_SCHEMA, "description": "同一 attachment_id + panel_id 下的多个独立子图及其 coverage。"},
            "figures": {"type": "array", "items": FIGURE_INPUT_SCHEMA, "minItems": 1, "maxItems": MAX_COLLECTION_FIGURES, "description": "来自多个 panel 的有序 figure 列表；不同来源不会自动合并。"},
            "collection_id": {"type": "string", "maxLength": 128, "description": "可选的稳定集合 ID。"},
        },
        "required": [],
        "additionalProperties": False,
    },
    fn=assemble_spec,
    group="chart-spec",
)

__all__ = [
    "ASSEMBLE_SPEC",
    "CHART_SPEC_SCHEMA",
    "FIGURE_INPUT_SCHEMA",
    "FIGURE_COVERAGE_SCHEMA",
    "FIGURE_CHILD_INPUT_SCHEMA",
    "FIGURE_SOURCE_SCHEMA",
    "POINT_SCHEMA",
    "assemble_spec",
    "validate_spec",
]
