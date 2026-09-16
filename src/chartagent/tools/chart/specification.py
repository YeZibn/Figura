"""Atomic ChartSpec assembly and internal validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from ..core.definition import Tool
from .validation import MAX_GENERATION_POINTS, MAX_GENERATION_LABEL_LENGTH, validate_generation

_CARTESIAN_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


def _assembly_error(message: str, location: str) -> dict[str, Any]:
    bounded_message = str(message)[:240]
    return {
        "error": bounded_message,
        "issues": [{"location": location[:120], "message": bounded_message}],
    }


def assemble_spec(
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


def validate_spec(spec: dict) -> dict:
    """Run shared validation for internal callers and compatibility checks."""
    try:
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

ASSEMBLE_SPEC = Tool(
    name="assemble_spec",
    description=(
        "Atomically assemble and validate a generation-ready ChartSpec from a "
        "closed chart type, optional title/source, axis labels, and typed data "
        "points. Use after the relevant chart evidence has been collected; do "
        "not hand-write IR JSON, render an image, or mix category/value points "
        "with x/y points. A successful result has passed the semantic generation "
        "constraints; a failure returns bounded located issues and no usable spec. "
        "Cartesian charts require non-empty x_label and y_label."
    ),
    parameters={
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": [chart_type.value for chart_type in ChartType],
                "description": "Chart kind; choose exactly one of bar, line, pie, or scatter.",
            },
            "title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional bounded chart title."},
            "x_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Required non-empty x-axis label for bar, line, and scatter charts."},
            "y_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Required non-empty y-axis label for bar, line, and scatter charts."},
            "points": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Non-empty ordered point array; use category/value for bar or pie and x/y for line or scatter."},
            "source": {"type": ["string", "null"], "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional provenance label; it does not authorize a local path."},
        },
        "required": ["chart_type", "points"],
        "additionalProperties": False,
    },
    fn=assemble_spec,
    group="chart-spec",
)

__all__ = [
    "ASSEMBLE_SPEC",
    "CHART_SPEC_SCHEMA",
    "POINT_SCHEMA",
    "assemble_spec",
    "validate_spec",
]
