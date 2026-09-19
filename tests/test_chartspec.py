"""Unit tests for the ChartSpec IR: data model, serialization round-trip,
tolerant validation, chart-type-conditional axes, optional provenance."""

from __future__ import annotations

import pytest

from chartagent.spec import (
    Axes,
    Axis,
    ChartCoverage,
    ChartFigure,
    ChartFigureItem,
    ChartMetadata,
    ChartSpec,
    ChartSpecCollection,
    ChartType,
    DataPoint,
    FigureLayout,
    FigureSource,
    ValidationIssue,
    chart_collection_digest,
    chart_figure_digest,
)


def bar_spec() -> ChartSpec:
    """The canonical U0 shape: an annotated bar chart restored to a spec."""
    return ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title="销售额"),
        axes=Axes(
            x=Axis(label="季度", categories=["春", "夏", "秋", "冬"]),
            y=Axis(label="金额", min_value=0, max_value=30),
        ),
        dataset=[
            DataPoint(category="春", value=10),
            DataPoint(category="夏", value=12),
            DataPoint(category="秋", value=7),
            DataPoint(category="冬", value=18),
        ],
    )


# --- data model & round-trip -------------------------------------------------- #
def test_round_trip_equality():
    spec = bar_spec()
    assert ChartSpec.from_dict(spec.to_dict()) == spec


def test_round_trip_line_chart_xy_points():
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.LINE, title="trend"),
        axes=Axes(x=Axis(label="t"), y=Axis(label="v")),
        dataset=[DataPoint(x=1, y=2.5), DataPoint(x=2, y=4.0)],
    )
    assert ChartSpec.from_dict(spec.to_dict()) == spec


def test_to_dict_is_plain_data():
    payload = bar_spec().to_dict()
    assert payload["metadata"]["chart_type"] == "bar"
    assert payload["dataset"][0]["category"] == "春"
    assert payload["axes"]["x"]["categories"] == ["春", "夏", "秋", "冬"]


def test_from_dict_drops_unknown_fields():
    payload = bar_spec().to_dict()
    payload["metadata"]["future_field"] = 42
    payload["dataset"][0]["mystery"] = "x"
    spec = ChartSpec.from_dict(payload)  # unknown keys ignored, no error
    assert spec == bar_spec()


def test_from_dict_missing_optional_metadata():
    spec = ChartSpec.from_dict(
        {
            "metadata": {"chart_type": "pie"},
            "dataset": [{"category": "a", "value": 1}],
        }
    )
    assert spec.axes is None
    assert spec.metadata.title == ""
    assert spec.metadata.source is None


def test_from_dict_unknown_chart_type_raises():
    with pytest.raises(ValueError):
        ChartSpec.from_dict({"metadata": {"chart_type": "sankey"}, "dataset": []})


# --- chart type enumeration ---------------------------------------------------- #
def test_chart_type_is_closed_set():
    assert {t.value for t in ChartType} == {"bar", "line", "pie", "scatter"}


def test_supported_chart_type_accepted():
    for chart_type in ChartType:
        axes = None if chart_type is ChartType.PIE else Axes(x=Axis(label="x"), y=Axis(label="y"))
        spec = ChartSpec(
            metadata=ChartMetadata(chart_type=chart_type),
            axes=axes,
            dataset=[DataPoint(category="a", value=1)],
        )
        assert spec.metadata.chart_type is chart_type
        assert not [i for i in spec.validate() if "chart type" in i.message]


# --- validation: tolerant hold, issue list ------------------------------------- #
def test_valid_spec_validates_clean():
    assert bar_spec().validate() == []


def test_invalid_data_returns_issue_list_without_raising():
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR),
        axes=Axes(x=Axis(label=""), y=Axis(label="y")),
        dataset=[
            DataPoint(category="a"),            # value missing
            DataPoint(x=1),                     # partial xy
            DataPoint(category="c", value=3, confidence=1.5),  # bad confidence
        ],
    )
    issues = spec.validate()
    assert isinstance(issues, list)
    assert all(isinstance(issue, ValidationIssue) for issue in issues)
    locations = {issue.location for issue in issues}
    assert "dataset[0].value" in locations
    assert "dataset[1]" in locations
    assert "dataset[2].confidence" in locations
    assert "axes.x.label" in locations


def test_empty_dataset_reports_issue():
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.PIE),
        dataset=[],
    )
    assert any(issue.location == "dataset" for issue in spec.validate())


# --- axes conditional on chart type (D5) ---------------------------------------- #
@pytest.mark.parametrize("chart_type", [ChartType.BAR, ChartType.LINE, ChartType.SCATTER])
def test_cartesian_without_axes_reports_axes_issue(chart_type):
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=chart_type),
        axes=None,
        dataset=[DataPoint(category="a", value=1)],
    )
    issues = spec.validate()
    assert [issue.location for issue in issues] == ["axes"]


def test_pie_without_axes_validates_clean():
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.PIE, title="share"),
        axes=None,
        dataset=[DataPoint(category="a", value=0.6), DataPoint(category="b", value=0.4)],
    )
    assert spec.validate() == []


def test_pie_with_axes_is_tolerated():
    spec = bar_spec()
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.PIE),
        axes=spec.axes,
        dataset=spec.dataset,
    )
    assert spec.validate() == []


# --- provenance optional --------------------------------------------------------- #
def test_provenance_optional_both_clean():
    with_prov = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, source="chart.png"),
        axes=Axes(x=Axis(label="x"), y=Axis(label="y")),
        dataset=[DataPoint(category="a", value=1, confidence=0.95)],
    )
    without_prov = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR),
        axes=Axes(x=Axis(label="x"), y=Axis(label="y")),
        dataset=[DataPoint(category="a", value=1)],
    )
    assert with_prov.validate() == []
    assert without_prov.validate() == []
    assert with_prov.metadata.source == "chart.png"
    assert with_prov.dataset[0].confidence == 0.95


def pie_spec(title: str, values: list[tuple[str, float]]) -> ChartSpec:
    return ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.PIE, title=title),
        dataset=[DataPoint(category=category, value=value) for category, value in values],
    )


def test_figure_and_collection_round_trip_preserve_child_order_and_coverage():
    figure = ChartFigure(
        figure_id="figure_sales",
        source=FigureSource("attachment_1", "panel_1"),
        layout=FigureLayout(columns=2),
        charts=[
            ChartFigureItem("q1", pie_spec("Q1", [("北美", 1), ("欧洲", 2)])),
            ChartFigureItem("q2", pie_spec("Q2", [("北美", 3), ("欧洲", 4)])),
        ],
        coverage=ChartCoverage(
            source_series=["Q1", "Q2"],
            represented_series=["Q1", "Q2"],
            omitted_series=[],
            status="complete",
        ),
    )
    collection = ChartSpecCollection("collection_1", [figure])

    rebuilt = ChartSpecCollection.from_dict(collection.to_dict())

    assert rebuilt == collection
    assert [item.chart_id for item in rebuilt.figures[0].charts] == ["q1", "q2"]
    assert rebuilt.validate() == []
    assert chart_figure_digest(rebuilt.figures[0]) == chart_figure_digest(figure)
    assert chart_collection_digest(rebuilt) == chart_collection_digest(collection)


def test_figure_validation_locates_invalid_child_and_incomplete_coverage():
    figure = ChartFigure(
        figure_id="figure_bad",
        source=FigureSource("attachment_1", "panel_1"),
        layout=FigureLayout(columns=2),
        charts=[
            ChartFigureItem(
                "bad",
                ChartSpec(
                    metadata=ChartMetadata(chart_type=ChartType.BAR),
                    dataset=[DataPoint(category="A", value=1)],
                ),
            ),
        ],
        coverage=ChartCoverage(
            source_series=["Q1", "Q2"],
            represented_series=["Q1"],
            omitted_series=["Q2"],
            status="incomplete",
        ),
    )

    locations = {issue.location for issue in figure.validate()}

    assert "charts[0].spec.axes" in locations
    assert figure.coverage.omitted_series == ["Q2"]


def test_complete_coverage_cannot_hide_omitted_series():
    figure = ChartFigure(
        figure_id="figure_incomplete",
        source=FigureSource("attachment_1", "panel_1"),
        layout=FigureLayout(columns=1),
        charts=[ChartFigureItem("q1", pie_spec("Q1", [("A", 1)]))],
        coverage=ChartCoverage(
            source_series=["Q1", "Q2"],
            represented_series=["Q1"],
            omitted_series=["Q2"],
            status="complete",
        ),
    )

    assert any(issue.location == "coverage.status" for issue in figure.validate())


def test_collection_rejects_duplicate_source_figures():
    figure = ChartFigure(
        figure_id="figure_1",
        source=FigureSource("attachment_1", "panel_1"),
        layout=FigureLayout(),
        charts=[ChartFigureItem("chart", pie_spec("Q1", [("A", 1)]))],
        coverage=ChartCoverage(["Q1"], ["Q1"], [], "complete"),
    )
    duplicate = ChartFigure(
        figure_id="figure_2",
        source=FigureSource("attachment_1", "panel_1"),
        layout=FigureLayout(),
        charts=[ChartFigureItem("chart", pie_spec("Q2", [("A", 2)]))],
        coverage=ChartCoverage(["Q2"], ["Q2"], [], "complete"),
    )

    assert any(issue.location == "figures[1].source" for issue in ChartSpecCollection("c", [figure, duplicate]).validate())
