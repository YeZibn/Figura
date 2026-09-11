"""Code-side ChartSpec assembly and independent validation tools."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ...spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint
from ..tool import Tool

_CATEGORICAL_TYPES = frozenset({ChartType.BAR, ChartType.PIE})
_CARTESIAN_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point_error(chart_type: ChartType, point: DataPoint, index: int) -> str | None:
    prefix = f"points[{index}]"
    if chart_type in _CATEGORICAL_TYPES:
        if not isinstance(point.category, str) or not point.category.strip():
            return f"{prefix} requires a non-empty category"
        if not _is_number(point.value):
            return f"{prefix} requires a finite numeric value"
        if point.x is not None or point.y is not None:
            return f"{prefix} cannot contain x/y for {chart_type.value} charts"
    else:
        if not _is_number(point.x) or not _is_number(point.y):
            return f"{prefix} requires finite numeric x and y values"
        if point.category is not None or point.value is not None:
            return f"{prefix} cannot contain category/value for {chart_type.value} charts"
    return None


def _confidence_error(point: DataPoint, index: int) -> str | None:
    if point.confidence is None:
        return None
    if not _is_number(point.confidence) or not 0.0 <= point.confidence <= 1.0:
        return f"points[{index}].confidence must be a number within [0, 1]"
    return None


def _series_error(point: DataPoint, index: int) -> str | None:
    if point.series is None:
        return None
    if not isinstance(point.series, str) or not point.series.strip():
        return f"points[{index}].series must be a non-empty string when provided"
    return None


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
        error = (
            _point_error(kind, point, index)
            or _series_error(point, index)
            or _confidence_error(point, index)
        )
        if error:
            return {"error": error}
        data_points.append(point)

    axes = None
    if kind in _CARTESIAN_TYPES:
        categories = (
            [point.category for point in data_points]
            if kind is ChartType.BAR
            else None
        )
        axes = Axes(
            x=Axis(label=x_label, categories=categories),
            y=Axis(label=y_label),
        )

    return ChartSpec(
        metadata=ChartMetadata(chart_type=kind, title=title, source=source),
        axes=axes,
        dataset=data_points,
    ).to_dict()


def validate_spec(spec: dict) -> dict:
    """Run the ChartSpec validator and chart-type point compatibility checks."""
    try:
        chart_spec = ChartSpec.from_dict(spec)
        issues = [
            {"location": issue.location, "message": issue.message}
            for issue in chart_spec.validate()
        ]
        for index, point in enumerate(chart_spec.dataset):
            error = (
                _point_error(chart_spec.metadata.chart_type, point, index)
                or _series_error(point, index)
                or _confidence_error(point, index)
            )
            if error:
                issues.append({"location": f"dataset[{index}]", "message": error})
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
