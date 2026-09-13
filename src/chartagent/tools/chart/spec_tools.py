"""Code-side ChartSpec assembly and independent validation tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from ..tool import Tool
from .validation import validate_generation

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
        "category": {"type": "string"},
        "value": {"type": "number"},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "series": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "additionalProperties": False,
}

ASSEMBLE_SPEC = Tool(
    name="assemble_spec",
    description=(
        "Construct a ChartSpec from a chart type, labels, source, and typed "
        "data points. Use this instead of hand-writing ChartSpec JSON."
    ),
    parameters={
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": [chart_type.value for chart_type in ChartType],
            },
            "title": {"type": "string"},
            "x_label": {"type": "string"},
            "y_label": {"type": "string"},
            "points": {"type": "array", "items": _POINT_SCHEMA},
            "source": {"type": "string"},
        },
        "required": ["chart_type", "points"],
        "additionalProperties": False,
    },
    fn=assemble_spec,
)

VALIDATE_SPEC = Tool(
    name="validate_spec",
    description=(
        "Independently validate a ChartSpec and return located structural issues."
    ),
    parameters={
        "type": "object",
        "properties": {"spec": {"type": "object"}},
        "required": ["spec"],
        "additionalProperties": False,
    },
    fn=validate_spec,
)
