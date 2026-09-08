"""ChartSpec: the shared intermediate representation (IR).

Both directions of ChartAgent exchange chart semantics through this model:
- the understanding side restores a chart image INTO a ChartSpec;
- the generation side renders a ChartSpec INTO a chart.

Design contract (see openspec change add-chartspec):
- Zero new dependencies: dataclasses + enum only.
- Round-trips through plain dicts via ``to_dict`` / ``from_dict``.
- ``validate()`` reports problems as data (a list of ``ValidationIssue``),
  never raises, so noisy understanding-side results can still be held
  (tolerant-hold semantics).
- Axes presence is conditional on chart type: cartesian types (bar/line/
  scatter) require axes; pie may omit them (design D5).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional


class ChartType(str, Enum):
    """Closed set of chart kinds the IR can express (design D2)."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"


# Cartesian kinds require axes; every other kind treats axes as optional (D5).
_AXES_REQUIRED_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


@dataclass(frozen=True)
class ValidationIssue:
    """One structural problem: where it is and what is wrong."""

    location: str
    message: str


@dataclass
class DataPoint:
    """One plotted point.

    Two shapes are supported:
    - categorical: ``category`` + ``value`` (bar / pie);
    - coordinate:  ``x`` + ``y`` (line / scatter).

    ``series`` and ``confidence`` are optional: multi-series extension and
    understanding-side provenance respectively.
    """

    category: Optional[str] = None
    value: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    series: Optional[str] = None
    confidence: Optional[float] = None

    _FIELDS = ("category", "value", "x", "y", "series", "confidence")

    def to_dict(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in self._FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataPoint":
        kwargs = {name: data.get(name) for name in cls._FIELDS if name in data}
        return cls(**kwargs)


@dataclass
class Axis:
    """One axis: its label plus optional category list / numeric range."""

    label: str = ""
    categories: Optional[List[str]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    _FIELDS = ("label", "categories", "min_value", "max_value")

    def to_dict(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in self._FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Axis":
        kwargs = {name: data.get(name) for name in cls._FIELDS if name in data}
        return cls(**kwargs)


@dataclass
class Axes:
    """The x/y pair of a cartesian chart."""

    x: Axis
    y: Axis

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x.to_dict(), "y": self.y.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Axes":
        return cls(
            x=Axis.from_dict(data.get("x") or {}),
            y=Axis.from_dict(data.get("y") or {}),
        )


@dataclass
class ChartMetadata:
    """Chart-level information (design D3).

    ``source`` is understanding-side provenance (e.g. the image the data was
    restored from); it is optional and never required by the generation side.
    """

    chart_type: ChartType
    title: str = ""
    source: Optional[str] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        chart_type = self.chart_type.value if isinstance(self.chart_type, ChartType) else self.chart_type
        return {
            "chart_type": chart_type,
            "title": self.title,
            "source": self.source,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartMetadata":
        if "chart_type" not in data:
            raise ValueError("metadata.chart_type is required")
        raw = data["chart_type"]
        try:
            chart_type = ChartType(raw)
        except ValueError:
            raise ValueError(f"unknown chart_type: {raw!r}") from None
        return cls(
            chart_type=chart_type,
            title=data.get("title", ""),
            source=data.get("source"),
            note=data.get("note", ""),
        )


@dataclass
class ChartSpec:
    """The IR: metadata + optional axes + dataset (spec: data model)."""

    metadata: ChartMetadata
    dataset: List[DataPoint]
    axes: Optional[Axes] = None

    # -- serialization ------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "axes": self.axes.to_dict() if self.axes is not None else None,
            "dataset": [point.to_dict() for point in self.dataset],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartSpec":
        """Rebuild from a plain dict; unknown keys are dropped, optional
        fields fall back to defaults. Raises ValueError only for a missing /
        unknown ``metadata.chart_type`` (the one non-guessable field)."""
        metadata = ChartMetadata.from_dict(data.get("metadata") or {})
        axes_raw = data.get("axes")
        axes = Axes.from_dict(axes_raw) if axes_raw else None
        dataset = [DataPoint.from_dict(item) for item in (data.get("dataset") or [])]
        return cls(metadata=metadata, axes=axes, dataset=dataset)

    # -- validation --------------------------------------------------------- #
    def validate(self) -> List[ValidationIssue]:
        """Collect every structural problem; never raises (tolerant-hold)."""
        issues: List[ValidationIssue] = []
        chart_type = self.metadata.chart_type

        if not isinstance(chart_type, ChartType):
            issues.append(
                ValidationIssue("metadata.chart_type", f"unknown chart type: {chart_type!r}")
            )
        else:
            if chart_type in _AXES_REQUIRED_TYPES and self.axes is None:
                issues.append(
                    ValidationIssue(
                        "axes", f"{chart_type.value} charts require axes but none were provided"
                    )
                )

        if not self.dataset:
            issues.append(ValidationIssue("dataset", "dataset must not be empty"))
        for index, point in enumerate(self.dataset):
            issues.extend(_validate_point(point, f"dataset[{index}]"))

        if self.axes is not None and isinstance(chart_type, ChartType) and chart_type in _AXES_REQUIRED_TYPES:
            for name in ("x", "y"):
                axis = getattr(self.axes, name)
                if not (axis.label or "").strip():
                    issues.append(
                        ValidationIssue(f"axes.{name}.label", "axis label must not be empty")
                    )

        return issues


def _validate_point(point: DataPoint, loc: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    has_xy = point.x is not None and point.y is not None
    partial_xy = (point.x is not None) != (point.y is not None)
    has_cat = point.category is not None
    has_val = point.value is not None

    if partial_xy:
        issues.append(ValidationIssue(loc, "x and y must be provided together"))
    if not has_xy and not partial_xy:
        if has_cat and not has_val:
            issues.append(ValidationIssue(f"{loc}.value", "categorical point is missing a value"))
        elif has_val and not has_cat:
            issues.append(ValidationIssue(f"{loc}.category", "value provided without a category"))
        elif not has_cat and not has_val:
            issues.append(
                ValidationIssue(loc, "point carries neither category/value nor x/y")
            )
    if point.confidence is not None and not (0.0 <= point.confidence <= 1.0):
        issues.append(
            ValidationIssue(f"{loc}.confidence", "confidence must be within [0, 1]")
        )
    return issues