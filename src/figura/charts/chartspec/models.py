"""Immutable, versioned chart content values owned by Figura."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .limits import CHART_SPEC_SCHEMA_VERSION


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"


@dataclass(frozen=True)
class ChartMetadata:
    chart_type: ChartType
    title: str = ""
    source: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        chart_type = self.chart_type.value if isinstance(self.chart_type, ChartType) else self.chart_type
        return {
            "chart_type": chart_type,
            "title": self.title,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True)
class Axis:
    label: str
    categories: tuple[str, ...] | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.categories, list):
            object.__setattr__(self, "categories", tuple(self.categories))

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"label": self.label}
        if self.categories is not None:
            result["categories"] = list(self.categories)
        if self.min_value is not None:
            result["min_value"] = self.min_value
        if self.max_value is not None:
            result["max_value"] = self.max_value
        return result


@dataclass(frozen=True)
class Axes:
    x: Axis
    y: Axis

    def to_dict(self) -> dict[str, object]:
        return {"x": self.x.to_dict(), "y": self.y.to_dict()}


@dataclass(frozen=True)
class CategoryValuePoint:
    category: str
    value: int | float
    series: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"category": self.category, "value": self.value}
        if self.series is not None:
            result["series"] = self.series
        return result


@dataclass(frozen=True)
class CoordinatePoint:
    x: int | float
    y: int | float
    series: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"x": self.x, "y": self.y}
        if self.series is not None:
            result["series"] = self.series
        return result


DataPoint: TypeAlias = CategoryValuePoint | CoordinatePoint


@dataclass(frozen=True)
class ChartSpecData:
    metadata: ChartMetadata
    axes: Axes | None
    dataset: tuple[DataPoint, ...]
    schema_version: int = CHART_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.dataset, list):
            object.__setattr__(self, "dataset", tuple(self.dataset))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "metadata": self.metadata.to_dict(),
            "axes": self.axes.to_dict() if self.axes is not None else None,
            "dataset": [point.to_dict() for point in self.dataset],
        }

    @classmethod
    def from_dict(cls, value: object) -> "ChartSpecData":
        from .codec import parse_chart_spec_data

        return parse_chart_spec_data(value)

    @classmethod
    def from_json(cls, value: str) -> "ChartSpecData":
        from .codec import parse_chart_spec_data_json

        return parse_chart_spec_data_json(value)

    def to_json(self) -> str:
        from .codec import serialize_chart_spec_data

        return serialize_chart_spec_data(self)
