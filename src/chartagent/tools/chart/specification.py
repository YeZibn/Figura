"""Code-side ChartSpec assembly and independent validation tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from ..core.definition import Tool
from .validation import MAX_GENERATION_POINTS, MAX_GENERATION_LABEL_LENGTH, validate_generation

_CARTESIAN_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


def assemble_spec(
    chart_type: str,
    points: list[dict],
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    source: str | None = None,
) -> dict:
    """Validate typed arguments and construct a serialization-ready ChartSpec."""
    try:
        kind = ChartType(chart_type)
    except (TypeError, ValueError):
        return {"error": f"unknown chart_type: {chart_type!r}"}

    if not isinstance(points, list) or not points:
        return {"error": "points must be a non-empty array"}
    if kind in _CARTESIAN_TYPES and (
        not isinstance(x_label, str)
        or not x_label.strip()
        or not isinstance(y_label, str)
        or not y_label.strip()
    ):
        return {"error": f"{kind.value} charts require non-empty x_label and y_label"}

    data_points: list[DataPoint] = []
    for index, raw in enumerate(points):
        if not isinstance(raw, Mapping):
            return {"error": f"points[{index}] must be an object"}
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
        return {
            "error": validation.issues[0].message,
            "issues": validation.legacy_issues(),
        }
    return chart_spec.to_dict()


def validate_spec(spec: dict) -> dict:
    """Run the ChartSpec validator and chart-type point compatibility checks."""
    try:
        chart_spec = ChartSpec.from_dict(spec)
        issues = validate_generation(chart_spec).legacy_issues()
    except Exception as exc:  # noqa: BLE001 - critic boundary
        issues = [{"location": "spec", "message": str(exc)}]
    return {"ok": not issues, "issues": issues}


_POINT_SCHEMA = {
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

_AXIS_SCHEMA = {
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

_AXES_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {**_AXIS_SCHEMA, "description": "X-axis definition."},
        "y": {**_AXIS_SCHEMA, "description": "Y-axis definition."},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}

_CHART_SPEC_SCHEMA = {
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
        "axes": {"oneOf": [_AXES_SCHEMA, {"type": "null"}], "description": "Cartesian x/y axes; omit or use null only for pie charts."},
        "dataset": {"type": "array", "items": _POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Ordered typed data points; point shape must match the selected chart type."},
    },
    "required": ["metadata", "dataset"],
    "additionalProperties": False,
}

ASSEMBLE_SPEC = Tool(
    name="assemble_spec",
    description=(
        "Assemble a generation-ready ChartSpec from a closed chart type, optional "
        "title/source, axis labels, and typed data points. Use when extracted or "
        "user-provided values should become a structured chart specification; do "
        "not use to render an image or to bypass validation, and do not mix "
        "category/value points with x/y points. The result is normalized ChartSpec "
        "JSON or bounded located issues, and cartesian charts require non-empty "
        "x_label and y_label."
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
            "points": {"type": "array", "items": _POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Non-empty ordered point array; use category/value for bar or pie and x/y for line or scatter."},
            "source": {"type": ["string", "null"], "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional provenance label; it does not authorize a local path."},
        },
        "required": ["chart_type", "points"],
        "additionalProperties": False,
    },
    fn=assemble_spec,
    group="chart-spec",
)

VALIDATE_SPEC = Tool(
    name="validate_spec",
    description=(
        "Independently validate an existing ChartSpec against chart-type, axis, "
        "point, range, and generation constraints. Use before rendering or when "
        "diagnosing a proposed spec; do not use to assemble missing fields or to "
        "claim that a rendered image is visually correct. The result is an ok flag "
        "and bounded issues with locations; passing means the specification is "
        "generation-ready, not that an image has been rendered or reviewed."
    ),
    parameters={
        "type": "object",
        "properties": {"spec": {**_CHART_SPEC_SCHEMA, "description": "ChartSpec object to validate."}},
        "required": ["spec"],
        "additionalProperties": False,
    },
    fn=validate_spec,
    group="chart-spec",
)


__all__ = ["ASSEMBLE_SPEC", "VALIDATE_SPEC", "assemble_spec", "validate_spec"]
