from __future__ import annotations

import json

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
from figura.charts.chartspec import ChartMetadata, ChartSpecData, ChartType
from figura.shared.json_schema import validate_schema_definition


def _chart_spec(chart_type: str) -> dict[str, object]:
    axes = None if chart_type == "pie" else {
        "x": {"label": "X"},
        "y": {"label": "Y"},
    }
    point = {"category": "A", "value": 2} if chart_type in {"bar", "pie"} else {"x": 1, "y": 2}
    return {
        "schema_version": 1,
        "metadata": {"chart_type": chart_type, "title": chart_type.title()},
        "axes": axes,
        "dataset": [point],
    }


def _figure(charts: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
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
    second = parse_chart_figure_json(
        '{"charts":[{"measurement_refs":[{"call_id":"call-1","run_id":"run-1"}],'
        '"chart_spec":{"dataset":[{"value":2,"category":"A"}],"axes":{"y":{"label":"Y"},'
        '"x":{"label":"X"}},"metadata":{"title":"Bar","chart_type":"bar"},"schema_version":1},'
        '"chart_id":"revenue"},{"chart_spec":{"dataset":[{"y":2,"x":1}],"axes":{"y":{"label":"Y"},'
        '"x":{"label":"X"}},"metadata":{"title":"Line","chart_type":"line"},"schema_version":1},'
        '"chart_id":"trend"}],"layout":{"columns":2},"title":"Sales","schema_version":1}'
    )

    assert serialize_chart_figure(first) == serialize_chart_figure(second)
    assert chart_figure_digest(first) == chart_figure_digest(second)
    assert len(chart_figure_digest(first)) == 64


@pytest.mark.parametrize(
    ("raw", "code", "path"),
    [
        ({**_figure(), "unexpected": True}, "additional_property", "/unexpected"),
        ({**_figure(), "schema_version": True}, "invalid_schema_version", "/schema_version"),
        ({**_figure(), "schema_version": 1.0}, "invalid_schema_version", "/schema_version"),
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
        parse_chart_figure_json('{"schema_version":1,"schema_version":1,"layout":{"columns":1},"charts":[]}')
    with pytest.raises(ChartFigureParseError) as non_finite:
        parse_chart_figure_json(
            '{"schema_version":1,"layout":{"columns":1},"charts":[{"chart_id":"pie",'
            '"chart_spec":{"schema_version":1,"metadata":{"chart_type":"pie"},"axes":null,'
            '"dataset":[{"category":"A","value":NaN}]}}]}'
        )

    assert duplicate.value.issue.code == "duplicate_key"
    assert non_finite.value.issue.code == "non_finite_number"


def test_figure_schema_is_supported() -> None:
    validate_schema_definition(CHART_FIGURE_SCHEMA, require_object=True)


def test_semantic_validation_checks_layout_unique_ids_measurement_refs_and_nested_chart_spec() -> None:
    invalid_bar = ChartSpecData(
        ChartMetadata(ChartType.BAR),
        None,
        (ChartSpecData.from_dict(_chart_spec("line")).dataset[0],),
    )
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


def test_figure_validation_rejects_columns_exceeding_chart_count() -> None:
    figure = parse_chart_figure(
        {
            "schema_version": 1,
            "layout": {"columns": 2},
            "charts": [{"chart_id": "one", "chart_spec": _chart_spec("pie")}],
        }
    )

    assert any(issue.code == "columns_exceed_charts" for issue in validate_chart_figure(figure))


def test_parser_and_serializer_enforce_the_figure_content_limit() -> None:
    large_chart = _chart_spec("pie")
    large_chart["dataset"] = [
        {"category": f"category-{index}-{'x' * 140}", "value": index + 1}
        for index in range(512)
    ]
    oversized = {
        "schema_version": 1,
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
