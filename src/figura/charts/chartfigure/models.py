"""Immutable multi-chart canvas values owned by the Charts domain."""

from __future__ import annotations

from dataclasses import dataclass

from ..chartspec.models import ChartSpecData
from .limits import CHART_FIGURE_SCHEMA_VERSION


@dataclass(frozen=True)
class MeasurementRef:
    run_id: str
    call_id: str

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "call_id": self.call_id}


@dataclass(frozen=True)
class FigureLayout:
    columns: int

    def to_dict(self) -> dict[str, object]:
        return {"columns": self.columns}


@dataclass(frozen=True)
class ChartFigureItem:
    chart_id: str
    chart_spec: ChartSpecData
    measurement_refs: tuple[MeasurementRef, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.measurement_refs, list):
            object.__setattr__(self, "measurement_refs", tuple(self.measurement_refs))

    def to_dict(self) -> dict[str, object]:
        return {
            "chart_id": self.chart_id,
            "chart_spec": self.chart_spec.to_dict(),
            "measurement_refs": [reference.to_dict() for reference in self.measurement_refs],
        }


@dataclass(frozen=True)
class ChartFigure:
    layout: FigureLayout
    charts: tuple[ChartFigureItem, ...]
    title: str = ""
    schema_version: int = CHART_FIGURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.charts, list):
            object.__setattr__(self, "charts", tuple(self.charts))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "layout": self.layout.to_dict(),
            "charts": [chart.to_dict() for chart in self.charts],
        }

    @classmethod
    def from_dict(cls, value: object) -> "ChartFigure":
        from .codec import parse_chart_figure

        return parse_chart_figure(value)

    @classmethod
    def from_json(cls, value: str) -> "ChartFigure":
        from .codec import parse_chart_figure_json

        return parse_chart_figure_json(value)

    def to_json(self) -> str:
        from .codec import serialize_chart_figure

        return serialize_chart_figure(self)
