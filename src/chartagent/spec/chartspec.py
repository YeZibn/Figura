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
import math
from typing import Any, Dict, List, Mapping, Optional


class ChartType(str, Enum):
    """Closed set of chart kinds the IR can express (design D2)."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"


# Cartesian kinds require axes; every other kind treats axes as optional (D5).
_AXES_REQUIRED_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})

MAX_FIGURE_CHARTS = 8
MAX_FIGURE_COLUMNS = 4
MAX_COLLECTION_FIGURES = 16
MAX_FIGURE_ID_LENGTH = 128
MAX_FIGURE_SOURCE_LENGTH = 160
_FIGURE_LAYOUT_TYPES = frozenset({"grid"})
_COVERAGE_STATUSES = frozenset({"complete", "incomplete", "unknown"})
_PROVENANCE_FIELDS = ("status", "session_id", "attempt_id", "attachment_id", "panel_id", "tool", "quality")


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
    provenance: Optional[Dict[str, Any]] = None

    # -- serialization ------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "metadata": self.metadata.to_dict(),
            "axes": self.axes.to_dict() if self.axes is not None else None,
            "dataset": [point.to_dict() for point in self.dataset],
        }
        if self.provenance is not None:
            result["provenance"] = _bounded_provenance(self.provenance)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartSpec":
        """Rebuild from a plain dict; unknown keys are dropped, optional
        fields fall back to defaults. Raises ValueError only for a missing /
        unknown ``metadata.chart_type`` (the one non-guessable field)."""
        metadata = ChartMetadata.from_dict(data.get("metadata") or {})
        axes_raw = data.get("axes")
        axes = Axes.from_dict(axes_raw) if axes_raw else None
        dataset = [DataPoint.from_dict(item) for item in (data.get("dataset") or [])]
        provenance = _bounded_provenance(data.get("provenance"))
        return cls(metadata=metadata, axes=axes, dataset=dataset, provenance=provenance)

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

        if self.axes is not None and isinstance(chart_type, ChartType):
            issues.extend(_validate_x_categories(self.axes.x.categories, chart_type, self.dataset))

        if self.provenance is not None:
            if not isinstance(self.provenance, Mapping):
                issues.append(ValidationIssue("provenance", "measurement provenance must be an object"))
            else:
                for field_name in ("session_id", "attempt_id", "attachment_id"):
                    if not isinstance(self.provenance.get(field_name), str) or not self.provenance.get(field_name):
                        issues.append(ValidationIssue(f"provenance.{field_name}", "accepted measurement provenance is missing its identity"))
                if self.provenance.get("status") != "accepted":
                    issues.append(ValidationIssue("provenance.status", "measurement provenance must have accepted status"))

        return issues


def _bounded_provenance(value: object) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    result: Dict[str, Any] = {}
    for key in _PROVENANCE_FIELDS:
        if key not in value:
            continue
        item = value.get(key)
        if key == "quality" and isinstance(item, Mapping):
            result[key] = {
                "confidence": dict(item.get("confidence") or {}) if isinstance(item.get("confidence"), Mapping) else {},
                "blocking": bool(item.get("blocking", False)),
            }
        elif isinstance(item, str):
            result[key] = item[:160]
        elif isinstance(item, (int, float, bool)) or item is None:
            result[key] = item
    return result or None


@dataclass(frozen=True)
class FigureSource:
    """Exact source identity for a composite figure."""

    attachment_id: str
    panel_id: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FigureSource":
        return cls(
            attachment_id=str(data.get("attachment_id") or ""),
            panel_id=str(data.get("panel_id") or ""),
        )

    def validate(self, location: str = "source") -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        for field_name, value in (
            ("attachment_id", self.attachment_id),
            ("panel_id", self.panel_id),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.append(ValidationIssue(f"{location}.{field_name}", "source identity must not be empty"))
            elif len(value) > MAX_FIGURE_SOURCE_LENGTH:
                issues.append(ValidationIssue(f"{location}.{field_name}", "source identity exceeds the configured length limit"))
        return issues


@dataclass(frozen=True)
class FigureLayout:
    """Bounded, deterministic layout metadata for one composite figure."""

    type: str = "grid"
    columns: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "columns": self.columns}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FigureLayout":
        raw_columns = data.get("columns", 1)
        try:
            columns = int(raw_columns)
        except (TypeError, ValueError):
            columns = 0
        return cls(type=str(data.get("type") or "grid"), columns=columns)

    def validate(self, chart_count: int, location: str = "layout") -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        if self.type not in _FIGURE_LAYOUT_TYPES:
            issues.append(ValidationIssue(f"{location}.type", "layout type must be grid"))
        if not 1 <= self.columns <= MAX_FIGURE_COLUMNS:
            issues.append(ValidationIssue(f"{location}.columns", "layout columns exceed the configured bounds"))
        if chart_count > 0 and self.columns > chart_count:
            issues.append(ValidationIssue(f"{location}.columns", "layout columns cannot exceed chart count"))
        return issues


@dataclass(frozen=True)
class ChartCoverage:
    """Source-series coverage for one figure."""

    source_series: List[str]
    represented_series: List[str]
    omitted_series: List[str]
    status: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_series": list(self.source_series),
            "represented_series": list(self.represented_series),
            "omitted_series": list(self.omitted_series),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartCoverage":
        def _strings(value: Any) -> List[str]:
            return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

        return cls(
            source_series=_strings(data.get("source_series")),
            represented_series=_strings(data.get("represented_series")),
            omitted_series=_strings(data.get("omitted_series")),
            status=str(data.get("status") or "unknown"),
        )

    def validate(self, location: str = "coverage") -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        for field_name, values in (
            ("source_series", self.source_series),
            ("represented_series", self.represented_series),
            ("omitted_series", self.omitted_series),
        ):
            for index, value in enumerate(values):
                if not isinstance(value, str) or not value.strip():
                    issues.append(ValidationIssue(f"{location}.{field_name}[{index}]", "series name must not be empty"))
                elif len(value) > MAX_FIGURE_SOURCE_LENGTH:
                    issues.append(ValidationIssue(f"{location}.{field_name}[{index}]", "series name exceeds the configured length limit"))
        if self.status not in _COVERAGE_STATUSES:
            issues.append(ValidationIssue(f"{location}.status", "coverage status is invalid"))
        source = set(self.source_series)
        represented = set(self.represented_series)
        omitted = set(self.omitted_series)
        if not omitted.issubset(source):
            issues.append(ValidationIssue(f"{location}.omitted_series", "omitted series must come from source_series"))
        if self.status == "complete" and (omitted or not source.issubset(represented)):
            issues.append(ValidationIssue(f"{location}.status", "complete coverage cannot contain omitted source series"))
        return issues


@dataclass(frozen=True)
class ChartFigureItem:
    """One independently meaningful ChartSpec inside a figure."""

    chart_id: str
    spec: ChartSpec
    title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_id": self.chart_id,
            "title": self.title,
            "spec": self.spec.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartFigureItem":
        return cls(
            chart_id=str(data.get("chart_id") or ""),
            title=str(data.get("title") or ""),
            spec=ChartSpec.from_dict(data.get("spec") or {}),
        )


@dataclass(frozen=True)
class ChartFigure:
    """One final canvas containing independent child ChartSpecs."""

    figure_id: str
    source: FigureSource
    layout: FigureLayout
    charts: List[ChartFigureItem]
    coverage: ChartCoverage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "chart_figure",
            "figure_id": self.figure_id,
            "source": self.source.to_dict(),
            "layout": self.layout.to_dict(),
            "charts": [chart.to_dict() for chart in self.charts],
            "coverage": self.coverage.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartFigure":
        return cls(
            figure_id=str(data.get("figure_id") or ""),
            source=FigureSource.from_dict(data.get("source") or {}),
            layout=FigureLayout.from_dict(data.get("layout") or {}),
            charts=[ChartFigureItem.from_dict(item) for item in (data.get("charts") or []) if isinstance(item, Mapping)],
            coverage=ChartCoverage.from_dict(data.get("coverage") or {}),
        )

    def validate(self) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        if not isinstance(self.figure_id, str) or not self.figure_id.strip():
            issues.append(ValidationIssue("figure_id", "figure ID must not be empty"))
        elif len(self.figure_id) > MAX_FIGURE_ID_LENGTH:
            issues.append(ValidationIssue("figure_id", "figure ID exceeds the configured length limit"))
        issues.extend(self.source.validate())
        if not self.charts:
            issues.append(ValidationIssue("charts", "figure must contain at least one chart"))
        elif len(self.charts) > MAX_FIGURE_CHARTS:
            issues.append(ValidationIssue("charts", "figure contains too many charts"))
        chart_ids: set[str] = set()
        for index, chart in enumerate(self.charts):
            location = f"charts[{index}]"
            if not chart.chart_id.strip():
                issues.append(ValidationIssue(f"{location}.chart_id", "chart ID must not be empty"))
            elif len(chart.chart_id) > MAX_FIGURE_ID_LENGTH:
                issues.append(ValidationIssue(f"{location}.chart_id", "chart ID exceeds the configured length limit"))
            elif chart.chart_id in chart_ids:
                issues.append(ValidationIssue(f"{location}.chart_id", "chart ID must be unique within a figure"))
            chart_ids.add(chart.chart_id)
            for issue in chart.spec.validate():
                issues.append(ValidationIssue(f"{location}.spec.{issue.location}", issue.message))
        issues.extend(self.layout.validate(len(self.charts)))
        issues.extend(self.coverage.validate())
        return issues


@dataclass(frozen=True)
class ChartSpecCollection:
    """One ordered batch of figures from one or more source panels."""

    collection_id: str
    figures: List[ChartFigure]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "chart_spec_collection",
            "collection_id": self.collection_id,
            "figures": [figure.to_dict() for figure in self.figures],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartSpecCollection":
        return cls(
            collection_id=str(data.get("collection_id") or ""),
            figures=[ChartFigure.from_dict(item) for item in (data.get("figures") or []) if isinstance(item, Mapping)],
        )

    def validate(self) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        if not self.collection_id.strip():
            issues.append(ValidationIssue("collection_id", "collection ID must not be empty"))
        elif len(self.collection_id) > MAX_FIGURE_ID_LENGTH:
            issues.append(ValidationIssue("collection_id", "collection ID exceeds the configured length limit"))
        if not self.figures:
            issues.append(ValidationIssue("figures", "collection must contain at least one figure"))
        elif len(self.figures) > MAX_COLLECTION_FIGURES:
            issues.append(ValidationIssue("figures", "collection contains too many figures"))
        figure_ids: set[str] = set()
        source_keys: set[tuple[str, str]] = set()
        for index, figure in enumerate(self.figures):
            location = f"figures[{index}]"
            if figure.figure_id in figure_ids:
                issues.append(ValidationIssue(f"{location}.figure_id", "figure ID must be unique within a collection"))
            figure_ids.add(figure.figure_id)
            source_key = (figure.source.attachment_id, figure.source.panel_id)
            if source_key in source_keys:
                issues.append(ValidationIssue(f"{location}.source", "source key must be unique within a collection"))
            source_keys.add(source_key)
            for issue in figure.validate():
                issues.append(ValidationIssue(f"{location}.{issue.location}", issue.message))
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


def _validate_x_categories(
    categories: object,
    chart_type: ChartType,
    dataset: List[DataPoint],
) -> List[ValidationIssue]:
    """Validate the ordered x-axis category domain and line positions."""
    if categories is None:
        return []
    if not isinstance(categories, list):
        return [ValidationIssue("axes.x.categories", "categories must be a list")]

    issues: List[ValidationIssue] = []
    normalized: List[str] = []
    seen: set[str] = set()
    for index, category in enumerate(categories):
        if not isinstance(category, str) or not category.strip():
            issues.append(
                ValidationIssue(
                    f"axes.x.categories[{index}]",
                    "category must be a non-empty string",
                )
            )
            continue
        normalized_category = category.strip()
        if normalized_category in seen:
            issues.append(
                ValidationIssue(
                    f"axes.x.categories[{index}]",
                    "category must be unique",
                )
            )
        seen.add(normalized_category)
        normalized.append(normalized_category)

    if not categories:
        issues.append(ValidationIssue("axes.x.categories", "categories must not be empty when provided"))

    if chart_type in {ChartType.LINE, ChartType.SCATTER} and normalized:
        positions = {
            float(point.x)
            for point in dataset
            if _finite_number(point.x)
        }
        if len(positions) != len(normalized):
            issues.append(
                ValidationIssue(
                    "axes.x.categories",
                    "category count must match the distinct numeric x positions",
                )
            )
    return issues


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
