from __future__ import annotations

import json
from dataclasses import replace

import pytest

from figura.charts.chartfigure import (
    CHART_FIGURE_SCHEMA,
    ChartFigure,
    ChartFigureItem,
    ChartFigureParseError,
    ChartFigureSerializationError,
    FigureLayout,
    MeasurementRef,
    chart_figure_digest,
    parse_chart_figure,
    parse_chart_figure_json,
    serialize_chart_figure,
    validate_chart_figure,
)
from figura.charts.chartfigure.limits import MAX_CHART_FIGURE_BYTES
from figura.charts.chartspec import ChartSpecData
from figura.shared.json_schema import validate_schema_definition


def _chart_spec(chart_type: str) -> dict[str, object]:
    if chart_type in {"bar", "box_plot"}:
        coordinate: dict[str, object] = {
            "kind": "cartesian",
            "x_axis": {"kind": "categorical"},
            "y_axis": {"kind": "numeric"},
        }
    elif chart_type in {"line", "scatter", "area", "histogram"}:
        coordinate = {
            "kind": "cartesian",
            "x_axis": {"kind": "numeric"},
            "y_axis": {"kind": "numeric"},
        }
    elif chart_type == "radar":
        coordinate = {"kind": "polar", "value_range": {"min": 0, "max": 10}}
    elif chart_type == "heatmap":
        coordinate = {"kind": "matrix"}
    elif chart_type == "treemap":
        coordinate = {"kind": "hierarchical"}
    else:
        coordinate = {"kind": "none"}

    datasets: dict[str, dict[str, object]] = {
        "bar": {
            "orientation": "vertical",
            "mode": "grouped",
            "categories": [{"id": "q1", "label": "Q1"}, {"id": "q2", "label": "Q2"}],
            "series": [{"id": "revenue", "label": "Revenue", "values": [12, 18]}],
        },
        "line": {
            "series": [{"id": "actual", "label": "Actual", "points": [{"x": 1, "y": 2}, {"x": 2, "y": 3}]}]
        },
        "scatter": {
            "series": [{"id": "sample", "label": "Sample", "points": [{"x": 1, "y": 2}, {"x": 2, "y": 4}]}]
        },
        "pie": {"slices": [{"id": "north", "label": "North", "value": 2}, {"id": "south", "label": "South", "value": 3}]},
        "area": {
            "stacking": "none",
            "series": [{"id": "actual", "label": "Actual", "points": [{"x": 1, "y": 2}, {"x": 2, "y": None}]}],
        },
        "histogram": {"measure": "count", "bins": [{"start": 0, "end": 1, "value": 4}, {"start": 1, "end": 2, "value": 6}]},
        "box_plot": {
            "orientation": "vertical",
            "groups": [{"id": "control", "label": "Control", "lower_whisker": 1, "q1": 2, "median": 3, "q3": 4, "upper_whisker": 5}],
        },
        "radar": {
            "dimensions": [{"id": "speed", "label": "Speed"}, {"id": "quality", "label": "Quality"}, {"id": "cost", "label": "Cost"}],
            "series": [{"id": "product", "label": "Product", "values": [8, 7, 6]}],
        },
        "heatmap": {
            "x_categories": [{"id": "x1", "label": "X1"}, {"id": "x2", "label": "X2"}],
            "y_categories": [{"id": "y1", "label": "Y1"}],
            "values": [[1.5, None]],
        },
        "treemap": {
            "root_id": "root",
            "nodes": [
                {"id": "root", "parent_id": None, "label": "All"},
                {"id": "a", "parent_id": "root", "label": "A", "value": 2},
                {"id": "b", "parent_id": "root", "label": "B", "value": 3},
            ],
        },
    }
    return {
        "schema_version": 2,
        "metadata": {"chart_type": chart_type, "title": chart_type.title()},
        "coordinate_system": coordinate,
        "dataset": datasets[chart_type],
    }


def _figure(charts: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 2,
        "title": "Sales",
        "layout": {"columns": 2},
        "charts": charts if charts is not None else [
            {
                "chart_id": "revenue",
                "chart_spec": _chart_spec("bar"),
                "measurement_refs": [{"run_id": "run-1", "call_id": "call-1"}],
            },
            {"chart_id": "trend", "chart_spec": _chart_spec("line")},
        ],
    }


def test_figure_round_trip_defaults_and_preserves_chart_and_reference_order() -> None:
    raw = _figure(
        [
            {
                "chart_id": chart_type,
                "chart_spec": _chart_spec(chart_type),
                "measurement_refs": [
                    {"run_id": f"run-{index}-b", "call_id": f"call-{index}-b"},
                    {"run_id": f"run-{index}-a", "call_id": f"call-{index}-a"},
                ],
            }
            for index, chart_type in enumerate(("bar", "line", "pie", "scatter"))
        ]
    )
    raw.pop("title")
    for chart in raw["charts"]:
        chart.pop("measurement_refs")
        if chart["chart_id"] == "bar":
            chart["measurement_refs"] = [
                {"run_id": "run-b", "call_id": "call-b"},
                {"run_id": "run-a", "call_id": "call-a"},
            ]

    figure = parse_chart_figure(raw)
    serialized = serialize_chart_figure(figure)
    round_tripped = parse_chart_figure_json(serialized)

    assert figure.title == ""
    assert [chart.chart_id for chart in figure.charts] == ["bar", "line", "pie", "scatter"]
    assert [ref.run_id for ref in figure.charts[0].measurement_refs] == ["run-b", "run-a"]
    assert figure.charts[1].measurement_refs == ()
    assert round_tripped == figure
    assert validate_chart_figure(figure) == ()


def test_canonical_figure_serialization_and_digest_ignore_object_key_order() -> None:
    first = parse_chart_figure_json(json.dumps(_figure(), separators=(",", ":")))
    reversed_keys = {
        key: value
        for key, value in reversed(list(_figure().items()))
    }
    second = parse_chart_figure_json(json.dumps(reversed_keys, separators=(",", ":")))

    assert serialize_chart_figure(first) == serialize_chart_figure(second)
    assert chart_figure_digest(first) == chart_figure_digest(second)
    assert len(chart_figure_digest(first)) == 64


@pytest.mark.parametrize(
    "chart_type",
    ["bar", "line", "scatter", "pie", "area", "histogram", "box_plot", "radar", "heatmap", "treemap"],
)
def test_figure_accepts_each_v2_chart_family(chart_type: str) -> None:
    figure = parse_chart_figure(
        {
            "schema_version": 2,
            "layout": {"columns": 1},
            "charts": [{"chart_id": chart_type, "chart_spec": _chart_spec(chart_type)}],
        }
    )

    assert figure.charts[0].chart_spec.metadata.chart_type.value == chart_type


@pytest.mark.parametrize(
    ("raw", "code", "path"),
    [
        ({**_figure(), "unexpected": True}, "additional_property", "/unexpected"),
        ({**_figure(), "schema_version": True}, "invalid_schema_version", "/schema_version"),
        ({**_figure(), "schema_version": 2.0}, "invalid_schema_version", "/schema_version"),
        ({**_figure(), "layout": {"columns": 1.0}}, "invalid_columns", "/layout/columns"),
        ({**_figure(), "layout": {"columns": True}}, "invalid_columns", "/layout/columns"),
        (_figure([{"chart_id": "contains space", "chart_spec": _chart_spec("bar")}]), "pattern", "/charts/0/chart_id"),
        (_figure([{"chart_id": "ok", "chart_spec": {**_chart_spec("bar"), "extra": 1}}]), "additional_property", "/charts/0/chart_spec/extra"),
    ],
)
def test_parser_rejects_invalid_figure_shapes(raw: dict[str, object], code: str, path: str) -> None:
    with pytest.raises(ChartFigureParseError) as error:
        parse_chart_figure(raw)

    assert error.value.issue.code == code
    assert error.value.issue.field_path == path


def test_json_parser_rejects_duplicate_keys_and_non_finite_values() -> None:
    with pytest.raises(ChartFigureParseError) as duplicate:
        parse_chart_figure_json('{"schema_version":2,"schema_version":2,"layout":{"columns":1},"charts":[]}')
    with pytest.raises(ChartFigureParseError) as non_finite:
        raw = _figure([{"chart_id": "pie", "chart_spec": _chart_spec("pie")}])
        raw["charts"][0]["chart_spec"]["dataset"]["slices"][0]["value"] = float("nan")
        parse_chart_figure_json(json.dumps(raw))

    assert duplicate.value.issue.code == "duplicate_key"
    assert non_finite.value.issue.code == "non_finite_number"


def test_figure_schema_is_supported() -> None:
    validate_schema_definition(CHART_FIGURE_SCHEMA, require_object=True)


def test_semantic_validation_checks_layout_unique_ids_measurement_refs_and_nested_chart_spec() -> None:
    bar_spec = ChartSpecData.from_dict(_chart_spec("bar"))
    line_spec = ChartSpecData.from_dict(_chart_spec("line"))
    invalid_bar = replace(bar_spec, dataset=line_spec.dataset)
    figure = ChartFigure(
        layout=FigureLayout(columns=2),
        charts=(
            ChartFigureItem(
                chart_id="same",
                chart_spec=invalid_bar,
                measurement_refs=(
                    MeasurementRef("run-1", "call-1"),
                    MeasurementRef("run-1", "call-1"),
                ),
            ),
            ChartFigureItem(chart_id="same", chart_spec=ChartSpecData.from_dict(_chart_spec("bar"))),
        ),
    )

    issues = validate_chart_figure(figure)
    issue_paths = {issue.field_path for issue in issues}

    assert "/charts/1/chart_id" in issue_paths
    assert "/charts/0/measurement_refs/1" in issue_paths
    assert any(path.startswith("/charts/0/chart_spec") for path in issue_paths)


def test_parser_rejects_columns_exceeding_chart_count() -> None:
    with pytest.raises(ChartFigureParseError) as error:
        parse_chart_figure(
            {
                "schema_version": 2,
                "layout": {"columns": 2},
                "charts": [{"chart_id": "one", "chart_spec": _chart_spec("pie")}],
            }
        )

    assert error.value.issue.code == "columns_exceed_charts"


def test_parser_rejects_v1_figure_and_v1_child_chart_spec() -> None:
    old_figure = _figure()
    old_figure["schema_version"] = 1
    with pytest.raises(ChartFigureParseError) as figure_error:
        parse_chart_figure(old_figure)

    old_child = _figure([{"chart_id": "bar", "chart_spec": {**_chart_spec("bar"), "schema_version": 1}}])
    with pytest.raises(ChartFigureParseError) as chart_error:
        parse_chart_figure(old_child)

    assert figure_error.value.issue.code == "unsupported_schema_version"
    assert chart_error.value.issue.code == "unsupported_schema_version"


def test_parser_and_serializer_enforce_the_figure_content_limit() -> None:
    large_chart = _chart_spec("pie")
    large_chart["dataset"] = {
        "slices": [
            {"id": f"category-{index}", "label": f"category-{index}-{'x' * 140}", "value": index + 1}
            for index in range(512)
        ]
    }
    oversized = {
        "schema_version": 2,
        "layout": {"columns": 1},
        "charts": [{"chart_id": "large", "chart_spec": large_chart}],
    }
    with pytest.raises(ChartFigureParseError) as parse_error:
        parse_chart_figure(oversized)

    too_large_directly = ChartFigure(
        layout=FigureLayout(columns=1),
        charts=(ChartFigureItem("large", ChartSpecData.from_dict(large_chart)),),
    )
    with pytest.raises(ChartFigureSerializationError) as serialize_error:
        serialize_chart_figure(too_large_directly)

    assert parse_error.value.issue.code == "content_too_large"
    assert serialize_error.value.issue.code == "content_too_large"
    assert MAX_CHART_FIGURE_BYTES == 64 * 1024
