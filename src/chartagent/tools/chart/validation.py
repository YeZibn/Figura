"""Shared, dependency-light validation for generation-ready ChartSpecs."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from ...spec import ChartSpec, ChartType, DataPoint

MAX_GENERATION_POINTS = 512
MAX_GENERATION_LABEL_LENGTH = 160
MAX_GENERATION_ISSUES = 32
MAX_GENERATION_ISSUE_TEXT = 240

_CATEGORICAL_TYPES = frozenset({ChartType.BAR, ChartType.PIE})
_CARTESIAN_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


@dataclass(frozen=True)
class GenerationIssue:
    """One bounded generation issue with a stable category and severity."""

    code: str
    location: str
    message: str
    severity: str = "error"
    auto_fixed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code[:64],
            "location": self.location[:120],
            "message": self.message[:MAX_GENERATION_ISSUE_TEXT],
            "severity": self.severity[:16],
            "auto_fixed": self.auto_fixed,
        }


@dataclass(frozen=True)
class GenerationValidation:
    """Semantic validation output shared by all generation entry points."""

    issues: tuple[GenerationIssue, ...] = ()

    @property
    def blocking(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    @property
    def status(self) -> str:
        return "failed" if self.blocking else "passed"

    def bounded(self) -> "GenerationValidation":
        return GenerationValidation(self.issues[:MAX_GENERATION_ISSUES])

    def to_dict(self) -> dict[str, Any]:
        bounded = self.bounded()
        return {
            "status": bounded.status,
            "checks": {
                "semantic": "failed" if bounded.blocking else "passed",
                "fidelity": "not_run",
                "layout": "not_run",
                "readability": "not_run",
                "artifact": "not_run",
            },
            "issues": [issue.to_dict() for issue in bounded.issues],
        }

    def legacy_issues(self) -> list[dict[str, str]]:
        return [
            {"location": issue.location, "message": issue.message}
            for issue in self.bounded().issues
        ]


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _series_name(point: DataPoint) -> str:
    return point.series.strip() if isinstance(point.series, str) and point.series.strip() else "数据"


def _canonical_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _issue(code: str, location: str, message: str) -> GenerationIssue:
    return GenerationIssue(code, location, message)


def _point_issues(chart_type: ChartType, point: DataPoint, index: int) -> list[GenerationIssue]:
    issues: list[GenerationIssue] = []
    location = f"dataset[{index}]"
    if chart_type in _CATEGORICAL_TYPES:
        category = _canonical_text(point.category)
        if category is None:
            issues.append(_issue("invalid_category", f"{location}.category", f"{location} requires a non-empty category"))
        elif len(category) > MAX_GENERATION_LABEL_LENGTH:
            issues.append(_issue("category_too_long", f"{location}.category", "category exceeds the size limit"))
        if not _finite(point.value):
            issues.append(_issue("invalid_value", f"{location}.value", f"{location} requires a finite numeric value"))
        if point.x is not None or point.y is not None:
            issues.append(_issue("unexpected_coordinates", location, f"{location} cannot contain x/y for {chart_type.value} charts"))
    else:
        if not _finite(point.x):
            issues.append(_issue("invalid_x", f"{location}.x", f"{location} requires finite numeric x and y values"))
        if not _finite(point.y):
            issues.append(_issue("invalid_y", f"{location}.y", f"{location} requires finite numeric x and y values"))
        if point.category is not None or point.value is not None:
            issues.append(_issue("unexpected_category_value", location, f"{location} cannot contain category/value for {chart_type.value} charts"))

    if point.series is not None and _canonical_text(point.series) is None:
        issues.append(_issue("invalid_series", f"{location}.series", "series must be a non-empty string when provided"))
    if point.confidence is not None and (
        not _finite(point.confidence) or not 0.0 <= float(point.confidence) <= 1.0
    ):
        issues.append(_issue("invalid_confidence", f"{location}.confidence", "confidence must be within [0, 1]"))
    return issues


def _axis_issues(spec: ChartSpec, chart_type: ChartType) -> list[GenerationIssue]:
    axes = spec.axes
    if axes is None:
        return []
    issues: list[GenerationIssue] = []
    for name in ("x", "y"):
        axis = getattr(axes, name, None)
        if axis is None:
            continue
        label = getattr(axis, "label", "")
        if not isinstance(label, str):
            issues.append(_issue("invalid_axis_label", f"axes.{name}.label", "axis label must be a string"))
        categories = getattr(axis, "categories", None)
        if categories is not None:
            if not isinstance(categories, list):
                issues.append(_issue("invalid_categories", f"axes.{name}.categories", "categories must be an array"))
            else:
                seen_categories: set[str] = set()
                for index, category in enumerate(categories):
                    canonical = _canonical_text(category)
                    location = f"axes.{name}.categories[{index}]"
                    if canonical is None:
                        issues.append(_issue("invalid_category", location, "category must be a non-empty string"))
                        continue
                    if len(canonical) > MAX_GENERATION_LABEL_LENGTH:
                        issues.append(_issue("category_too_long", location, "category exceeds the size limit"))
                    if canonical in seen_categories:
                        issues.append(_issue("duplicate_category", location, "category is duplicated"))
                    seen_categories.add(canonical)

        minimum = getattr(axis, "min_value", None)
        maximum = getattr(axis, "max_value", None)
        if minimum is not None and not _finite(minimum):
            issues.append(_issue("invalid_axis_range", f"axes.{name}.min_value", "axis minimum must be a finite number"))
        if maximum is not None and not _finite(maximum):
            issues.append(_issue("invalid_axis_range", f"axes.{name}.max_value", "axis maximum must be a finite number"))
        if _finite(minimum) and _finite(maximum) and float(minimum) >= float(maximum):
            issues.append(_issue("invalid_axis_range", f"axes.{name}", "axis minimum must be less than maximum"))

    if chart_type is ChartType.BAR:
        x_axis = axes.x
        if getattr(x_axis, "min_value", None) is not None or getattr(x_axis, "max_value", None) is not None:
            issues.append(_issue("unsupported_axis_range", "axes.x", "bar chart x-axis is categorical and cannot have a numeric range"))
    return issues


def _range_issues(spec: ChartSpec, chart_type: ChartType) -> list[GenerationIssue]:
    axes = spec.axes
    if axes is None or chart_type not in _CARTESIAN_TYPES:
        return []
    issues: list[GenerationIssue] = []

    def check_values(axis_name: str, values: Iterable[object]) -> None:
        axis = getattr(axes, axis_name)
        minimum = getattr(axis, "min_value", None)
        maximum = getattr(axis, "max_value", None)
        for index, value in enumerate(values):
            if not _finite(value):
                continue
            numeric = float(value)
            if _finite(minimum) and numeric < float(minimum):
                issues.append(_issue("value_outside_axis_range", f"dataset[{index}].{axis_name[0] if axis_name == 'x' else 'y'}", "value is below the declared axis minimum"))
            if _finite(maximum) and numeric > float(maximum):
                issues.append(_issue("value_outside_axis_range", f"dataset[{index}].{axis_name[0] if axis_name == 'x' else 'y'}", "value is above the declared axis maximum"))

    if chart_type is ChartType.BAR:
        check_values("y", (point.value for point in spec.dataset))
    else:
        check_values("x", (point.x for point in spec.dataset))
        check_values("y", (point.y for point in spec.dataset))
    return issues


def _categorical_issues(spec: ChartSpec, chart_type: ChartType) -> list[GenerationIssue]:
    if chart_type not in _CATEGORICAL_TYPES:
        return []
    issues: list[GenerationIssue] = []
    seen: set[tuple[str, str]] = set()
    seen_pie_categories: set[str] = set()
    total = 0.0
    categories: list[str] = []
    for index, point in enumerate(spec.dataset):
        category = _canonical_text(point.category)
        if category is None:
            continue
        categories.append(category)
        key = (category, _series_name(point))
        duplicate_key = category in seen_pie_categories if chart_type is ChartType.PIE else key in seen
        if duplicate_key:
            message = "duplicate category" if chart_type is ChartType.PIE else "duplicate category and series point"
            issues.append(_issue("duplicate_category_series", f"dataset[{index}]", message))
        seen.add(key)
        seen_pie_categories.add(category)
        if _finite(point.value):
            value = float(point.value)
            total += value
            if chart_type is ChartType.PIE and value < 0:
                issues.append(_issue("negative_pie_value", f"dataset[{index}].value", "pie values must not be negative"))

    if chart_type is ChartType.PIE:
        if total <= 0:
            issues.append(_issue("invalid_pie_total", "dataset", "pie values must have a positive total"))
        return issues

    declared = getattr(getattr(spec.axes, "x", None), "categories", None) if spec.axes else None
    if isinstance(declared, list):
        category_set = [_canonical_text(category) for category in declared]
        required_categories = [category for category in category_set if category is not None]
    else:
        required_categories = list(dict.fromkeys(categories))
    series = list(dict.fromkeys(_series_name(point) for point in spec.dataset))
    for series_name in series:
        present = {
            _canonical_text(point.category)
            for point in spec.dataset
            if _series_name(point) == series_name
        }
        for category in required_categories:
            if category not in present:
                issues.append(
                    _issue(
                        "missing_category_value",
                        "dataset",
                        f"series {series_name!r} is missing category {category!r}; provide an explicit value",
                    )
                )
    return issues


def validate_generation(spec: ChartSpec) -> GenerationValidation:
    """Collect all semantic issues required before chart generation."""
    chart_type = spec.metadata.chart_type
    issues: list[GenerationIssue] = []
    if len(spec.dataset) > MAX_GENERATION_POINTS:
        issues.append(_issue("dataset_too_large", "dataset", f"dataset exceeds {MAX_GENERATION_POINTS} points"))
    if isinstance(chart_type, ChartType):
        for index, point in enumerate(spec.dataset):
            issues.extend(_point_issues(chart_type, point, index))
        issues.extend(_axis_issues(spec, chart_type))
        issues.extend(_categorical_issues(spec, chart_type))
        issues.extend(_range_issues(spec, chart_type))
    try:
        structural_issues = spec.validate()
    except Exception as exc:  # noqa: BLE001 - malformed model data stays in the validation boundary.
        structural_issues = []
        issues.append(_issue("invalid_chart_spec", "spec", str(exc)))
    for issue in structural_issues:
        candidate = _issue("invalid_chart_spec", issue.location, issue.message)
        if not any(existing.location == candidate.location and existing.message == candidate.message for existing in issues):
            issues.append(candidate)
    return GenerationValidation(tuple(issues)).bounded()


__all__ = [
    "GenerationIssue",
    "GenerationValidation",
    "MAX_GENERATION_ISSUES",
    "MAX_GENERATION_ISSUE_TEXT",
    "MAX_GENERATION_LABEL_LENGTH",
    "MAX_GENERATION_POINTS",
    "validate_generation",
]
