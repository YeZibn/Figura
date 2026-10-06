"""Immutable, versioned chart content values owned by Figura."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .limits import CHART_SPEC_SCHEMA_VERSION


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    PIE = "pie"
    AREA = "area"
    HISTOGRAM = "histogram"
    BOX_PLOT = "box_plot"
    RADAR = "radar"
    HEATMAP = "heatmap"
    TREEMAP = "treemap"


class AxisKind(str, Enum):
    CATEGORICAL = "categorical"
    NUMERIC = "numeric"
    TIME = "time"


class CoordinateSystemKind(str, Enum):
    CARTESIAN = "cartesian"
    POLAR = "polar"
    MATRIX = "matrix"
    HIERARCHICAL = "hierarchical"
    NONE = "none"


class BarOrientation(str, Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


class BarMode(str, Enum):
    GROUPED = "grouped"
    STACKED = "stacked"


class HistogramMeasure(str, Enum):
    COUNT = "count"
    FREQUENCY = "frequency"
    PROBABILITY = "probability"
    DENSITY = "density"
    UNKNOWN = "unknown"


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
class CartesianAxis:
    kind: AxisKind
    label: str | None = None

    def to_dict(self) -> dict[str, object]:
        kind = self.kind.value if isinstance(self.kind, AxisKind) else self.kind
        result: dict[str, object] = {"kind": kind}
        if self.label is not None:
            result["label"] = self.label
        return result


@dataclass(frozen=True)
class CartesianCoordinateSystem:
    x_axis: CartesianAxis
    y_axis: CartesianAxis
    kind: CoordinateSystemKind = CoordinateSystemKind.CARTESIAN

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value if isinstance(self.kind, CoordinateSystemKind) else self.kind,
            "x_axis": self.x_axis.to_dict(),
            "y_axis": self.y_axis.to_dict(),
        }


@dataclass(frozen=True)
class PolarCoordinateSystem:
    minimum: int | float
    maximum: int | float
    kind: CoordinateSystemKind = CoordinateSystemKind.POLAR

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value if isinstance(self.kind, CoordinateSystemKind) else self.kind,
            "value_range": {"min": self.minimum, "max": self.maximum},
        }


@dataclass(frozen=True)
class SimpleCoordinateSystem:
    kind: CoordinateSystemKind

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value if isinstance(self.kind, CoordinateSystemKind) else self.kind}


CoordinateSystem: TypeAlias = CartesianCoordinateSystem | PolarCoordinateSystem | SimpleCoordinateSystem


@dataclass(frozen=True)
class ChartCategory:
    id: str
    label: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label}


@dataclass(frozen=True)
class ValueSeries:
    id: str
    label: str
    values: tuple[int | float, ...]

    def __post_init__(self) -> None:
        if isinstance(self.values, list):
            object.__setattr__(self, "values", tuple(self.values))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label, "values": list(self.values)}


@dataclass(frozen=True)
class BarDataset:
    orientation: BarOrientation
    mode: BarMode
    categories: tuple[ChartCategory, ...]
    series: tuple[ValueSeries, ...]

    def __post_init__(self) -> None:
        if isinstance(self.categories, list):
            object.__setattr__(self, "categories", tuple(self.categories))
        if isinstance(self.series, list):
            object.__setattr__(self, "series", tuple(self.series))

    def to_dict(self) -> dict[str, object]:
        return {
            "orientation": self.orientation.value if isinstance(self.orientation, BarOrientation) else self.orientation,
            "mode": self.mode.value if isinstance(self.mode, BarMode) else self.mode,
            "categories": [item.to_dict() for item in self.categories],
            "series": [item.to_dict() for item in self.series],
        }


@dataclass(frozen=True)
class XYPoint:
    x: str | int | float
    y: int | float | None

    def to_dict(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class XYSeries:
    id: str
    label: str
    points: tuple[XYPoint, ...]

    def __post_init__(self) -> None:
        if isinstance(self.points, list):
            object.__setattr__(self, "points", tuple(self.points))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label, "points": [point.to_dict() for point in self.points]}


@dataclass(frozen=True)
class LineDataset:
    series: tuple[XYSeries, ...]

    def __post_init__(self) -> None:
        if isinstance(self.series, list):
            object.__setattr__(self, "series", tuple(self.series))

    def to_dict(self) -> dict[str, object]:
        return {"series": [item.to_dict() for item in self.series]}


@dataclass(frozen=True)
class AreaDataset:
    stacking: str
    series: tuple[XYSeries, ...]

    def __post_init__(self) -> None:
        if isinstance(self.series, list):
            object.__setattr__(self, "series", tuple(self.series))

    def to_dict(self) -> dict[str, object]:
        return {"stacking": self.stacking, "series": [item.to_dict() for item in self.series]}


@dataclass(frozen=True)
class ScatterPoint:
    x: int | float
    y: int | float
    size: int | float | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"x": self.x, "y": self.y}
        if self.size is not None:
            result["size"] = self.size
        return result


@dataclass(frozen=True)
class ScatterSeries:
    id: str
    label: str
    points: tuple[ScatterPoint, ...]

    def __post_init__(self) -> None:
        if isinstance(self.points, list):
            object.__setattr__(self, "points", tuple(self.points))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label, "points": [point.to_dict() for point in self.points]}


@dataclass(frozen=True)
class ScatterDataset:
    series: tuple[ScatterSeries, ...]

    def __post_init__(self) -> None:
        if isinstance(self.series, list):
            object.__setattr__(self, "series", tuple(self.series))

    def to_dict(self) -> dict[str, object]:
        return {"series": [item.to_dict() for item in self.series]}


@dataclass(frozen=True)
class PieSlice:
    id: str
    label: str
    value: int | float

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label, "value": self.value}


@dataclass(frozen=True)
class PieDataset:
    slices: tuple[PieSlice, ...]
    inner_radius_ratio: int | float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.slices, list):
            object.__setattr__(self, "slices", tuple(self.slices))

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"slices": [item.to_dict() for item in self.slices]}
        if self.inner_radius_ratio is not None:
            result["inner_radius_ratio"] = self.inner_radius_ratio
        return result


@dataclass(frozen=True)
class HistogramBin:
    start: int | float
    end: int | float
    value: int | float

    def to_dict(self) -> dict[str, object]:
        return {"start": self.start, "end": self.end, "value": self.value}


@dataclass(frozen=True)
class HistogramDataset:
    measure: HistogramMeasure
    bins: tuple[HistogramBin, ...]

    def __post_init__(self) -> None:
        if isinstance(self.bins, list):
            object.__setattr__(self, "bins", tuple(self.bins))

    def to_dict(self) -> dict[str, object]:
        return {
            "measure": self.measure.value if isinstance(self.measure, HistogramMeasure) else self.measure,
            "bins": [item.to_dict() for item in self.bins],
        }


@dataclass(frozen=True)
class BoxPlotGroup:
    id: str
    label: str
    lower_whisker: int | float
    q1: int | float
    median: int | float
    q3: int | float
    upper_whisker: int | float
    outliers: tuple[int | float, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.outliers, list):
            object.__setattr__(self, "outliers", tuple(self.outliers))

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "label": self.label,
            "lower_whisker": self.lower_whisker,
            "q1": self.q1,
            "median": self.median,
            "q3": self.q3,
            "upper_whisker": self.upper_whisker,
        }
        if self.outliers:
            result["outliers"] = list(self.outliers)
        return result


@dataclass(frozen=True)
class BoxPlotDataset:
    orientation: BarOrientation
    groups: tuple[BoxPlotGroup, ...]

    def __post_init__(self) -> None:
        if isinstance(self.groups, list):
            object.__setattr__(self, "groups", tuple(self.groups))

    def to_dict(self) -> dict[str, object]:
        return {
            "orientation": self.orientation.value if isinstance(self.orientation, BarOrientation) else self.orientation,
            "groups": [item.to_dict() for item in self.groups],
        }


@dataclass(frozen=True)
class RadarDimension:
    id: str
    label: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label}


@dataclass(frozen=True)
class RadarDataset:
    dimensions: tuple[RadarDimension, ...]
    series: tuple[ValueSeries, ...]

    def __post_init__(self) -> None:
        if isinstance(self.dimensions, list):
            object.__setattr__(self, "dimensions", tuple(self.dimensions))
        if isinstance(self.series, list):
            object.__setattr__(self, "series", tuple(self.series))

    def to_dict(self) -> dict[str, object]:
        return {
            "dimensions": [item.to_dict() for item in self.dimensions],
            "series": [item.to_dict() for item in self.series],
        }


@dataclass(frozen=True)
class HeatmapDataset:
    x_categories: tuple[ChartCategory, ...]
    y_categories: tuple[ChartCategory, ...]
    values: tuple[tuple[int | float | None, ...], ...]

    def __post_init__(self) -> None:
        if isinstance(self.x_categories, list):
            object.__setattr__(self, "x_categories", tuple(self.x_categories))
        if isinstance(self.y_categories, list):
            object.__setattr__(self, "y_categories", tuple(self.y_categories))
        if isinstance(self.values, list):
            object.__setattr__(self, "values", tuple(tuple(row) for row in self.values))

    def to_dict(self) -> dict[str, object]:
        return {
            "x_categories": [item.to_dict() for item in self.x_categories],
            "y_categories": [item.to_dict() for item in self.y_categories],
            "values": [list(row) for row in self.values],
        }


@dataclass(frozen=True)
class TreemapNode:
    id: str
    parent_id: str | None
    label: str
    value: int | float | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"id": self.id, "parent_id": self.parent_id, "label": self.label}
        if self.value is not None:
            result["value"] = self.value
        return result


@dataclass(frozen=True)
class TreemapDataset:
    root_id: str
    nodes: tuple[TreemapNode, ...]

    def __post_init__(self) -> None:
        if isinstance(self.nodes, list):
            object.__setattr__(self, "nodes", tuple(self.nodes))

    def to_dict(self) -> dict[str, object]:
        return {"root_id": self.root_id, "nodes": [item.to_dict() for item in self.nodes]}


ChartDataset: TypeAlias = (
    BarDataset
    | LineDataset
    | AreaDataset
    | ScatterDataset
    | PieDataset
    | HistogramDataset
    | BoxPlotDataset
    | RadarDataset
    | HeatmapDataset
    | TreemapDataset
)


@dataclass(frozen=True)
class ChartSpecData:
    metadata: ChartMetadata
    coordinate_system: CoordinateSystem
    dataset: ChartDataset
    schema_version: int = CHART_SPEC_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "metadata": self.metadata.to_dict(),
            "coordinate_system": self.coordinate_system.to_dict(),
            "dataset": self.dataset.to_dict(),
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
