from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from figura.charts.chartspec import (
    CHART_SPEC_DATA_SCHEMA,
    Axis,
    Axes,
    CategoryValuePoint,
    ChartMetadata,
    ChartSpecData,
    ChartSpecParseError,
    ChartSpecSerializationError,
    ChartType,
    CoordinatePoint,
    parse_chart_spec_data,
    validate_chart_spec_data,
)
from figura.charts.chartspec.limits import MAX_CHART_SPEC_DATA_BYTES
from figura.charts.limits import MAX_ISSUES
from figura.shared.json_schema import validate_instance, validate_schema_definition


def _bar(
    dataset: tuple[CategoryValuePoint | CoordinatePoint, ...],
    *,
    categories: tuple[str, ...] | None = None,
    y_min: int | float | None = None,
    y_max: int | float | None = None,
) -> ChartSpecData:
    return ChartSpecData(
        metadata=ChartMetadata(ChartType.BAR),
        axes=Axes(
            Axis("Quarter", categories=categories),
            Axis("Revenue", min_value=y_min, max_value=y_max),
        ),
        dataset=dataset,
    )


def _line(
    dataset: tuple[CategoryValuePoint | CoordinatePoint, ...],
    *,
    categories: tuple[str, ...] | None = None,
) -> ChartSpecData:
    return ChartSpecData(
        metadata=ChartMetadata(ChartType.LINE),
        axes=Axes(Axis("Month", categories=categories), Axis("Value")),
        dataset=dataset,
    )


def _codes(spec: ChartSpecData) -> set[str]:
    return {issue.code for issue in validate_chart_spec_data(spec)}


def _category_point(
    category: str,
    value: int | float,
    series: str | None = None,
) -> CategoryValuePoint:
    return CategoryValuePoint(category, value, series)


def _coordinate_point(
    x: int | float,
    y: int | float,
    series: str | None = None,
) -> CoordinatePoint:
    return CoordinatePoint(x, y, series)


def test_valid_content_round_trips_and_preserves_order() -> None:
    raw = {
        "schema_version": 1,
        "metadata": {"chart_type": "bar", "title": "Sales"},
        "axes": {
            "x": {"label": "Quarter", "categories": ["Q2", "Q1"]},
            "y": {"label": "Value", "min_value": 0},
        },
        "dataset": [
            {"category": "Q2", "value": 15},
            {"category": "Q1", "value": 12},
        ],
    }

    spec = ChartSpecData.from_dict(raw)

    assert spec.metadata.title == "Sales"
    assert spec.metadata.source is None
    assert spec.metadata.note == ""
    assert spec.axes is not None
    assert spec.axes.x.categories == ("Q2", "Q1")
    assert [point.category for point in spec.dataset] == ["Q2", "Q1"]
    assert ChartSpecData.from_json(spec.to_json()) == spec
    assert spec.to_dict()["metadata"] == {
        "chart_type": "bar",
        "title": "Sales",
        "source": None,
        "note": "",
    }
    assert validate_chart_spec_data(spec) == ()


def test_nested_collections_are_immutable_snapshots() -> None:
    categories = ["A", "B"]
    dataset = [_category_point("A", 1)]
    axes = Axes(Axis("Category", categories=categories), Axis("Value"))
    spec = ChartSpecData(ChartMetadata(ChartType.BAR), axes, dataset)
    categories.append("C")
    dataset.append(_category_point("B", 2))

    assert axes.x.categories == ("A", "B")
    assert len(spec.dataset) == 1
    with pytest.raises(FrozenInstanceError):
        spec.metadata.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("chart_type", "axes", "dataset"),
    [
        ("bar", {"x": {"label": "Category"}, "y": {"label": "Value"}}, [{"category": "A", "value": 1}]),
        ("line", {"x": {"label": "X"}, "y": {"label": "Y"}}, [{"x": 0, "y": 1}]),
        ("pie", None, [{"category": "A", "value": 1}]),
        ("scatter", {"x": {"label": "X"}, "y": {"label": "Y"}}, [{"x": 1, "y": 2}]),
    ],
)
def test_each_supported_chart_type_parses(
    chart_type: str,
    axes: dict[str, object] | None,
    dataset: list[dict[str, object]],
) -> None:
    spec = parse_chart_spec_data(
        {"schema_version": 1, "metadata": {"chart_type": chart_type}, "axes": axes, "dataset": dataset}
    )

    assert spec.metadata.chart_type.value == chart_type
    assert validate_chart_spec_data(spec) == ()


@pytest.mark.parametrize(
    ("raw", "code", "path"),
    [
        ({"schema_version": 2, "metadata": {"chart_type": "bar"}, "axes": None, "dataset": []}, "unsupported_schema_version", "/schema_version"),
        ({"schema_version": True, "metadata": {"chart_type": "bar"}, "axes": None, "dataset": []}, "invalid_schema_version", "/schema_version"),
        ({"schema_version": 1, "metadata": {"chart_type": "other"}, "axes": None, "dataset": []}, "unsupported_chart_type", "/metadata/chart_type"),
        ({"schema_version": 1, "metadata": {"chart_type": "bar"}, "axes": None}, "required", "/dataset"),
        ({"schema_version": 1, "metadata": {"chart_type": "bar", "run_id": "secret"}, "axes": None, "dataset": []}, "additional_property", "/metadata/run_id"),
        ({"schema_version": 1, "metadata": {"chart_type": "bar"}, "axes": None, "dataset": [{"category": "A"}]}, "required", "/dataset/0/value"),
        ({"schema_version": 1, "metadata": {"chart_type": "bar"}, "axes": None, "dataset": [{"category": "A", "value": True}]}, "type", "/dataset/0/value"),
        ({"schema_version": 1, "metadata": {"chart_type": "bar"}, "axes": None, "dataset": [{"category": "A", "value": "1"}]}, "type", "/dataset/0/value"),
    ],
)
def test_parser_rejects_invalid_shapes_without_echoing_values(
    raw: dict[str, object], code: str, path: str
) -> None:
    with pytest.raises(ChartSpecParseError) as error:
        ChartSpecData.from_dict(raw)

    assert error.value.issue.code == code
    assert error.value.issue.field_path == path
    assert "secret" not in str(error.value)


def test_json_parser_rejects_duplicate_keys_and_non_finite_values() -> None:
    with pytest.raises(ChartSpecParseError) as duplicate:
        ChartSpecData.from_json(
            '{"schema_version":1,"metadata":{"chart_type":"bar","chart_type":"pie"},"axes":null,"dataset":[]}'
        )
    with pytest.raises(ChartSpecParseError) as non_finite:
        ChartSpecData.from_json(
            '{"schema_version":1,"metadata":{"chart_type":"bar"},"axes":null,"dataset":[{"category":"A","value":NaN}]}'
        )

    assert duplicate.value.issue.code == "duplicate_key"
    assert non_finite.value.issue.code == "non_finite_number"
    assert non_finite.value.issue.field_path == "/dataset/0/value"


def test_parser_rejects_wrong_chart_point_shape_semantically() -> None:
    spec = ChartSpecData.from_dict(
        {
            "schema_version": 1,
            "metadata": {"chart_type": "line"},
            "axes": {"x": {"label": "X"}, "y": {"label": "Y"}},
            "dataset": [{"category": "A", "value": 1}],
        }
    )

    issues = validate_chart_spec_data(spec)

    assert any(issue.code == "unexpected_point_shape" for issue in issues)
    assert any(issue.field_path == "/dataset/0" for issue in issues)


def test_parser_enforces_text_point_count_and_content_byte_limits() -> None:
    with pytest.raises(ChartSpecParseError) as long_text:
        ChartSpecData.from_dict(
            {
                "schema_version": 1,
                "metadata": {"chart_type": "bar", "title": "x" * 161},
                "axes": None,
                "dataset": [{"category": "A", "value": 1}],
            }
        )
    with pytest.raises(ChartSpecParseError) as too_many:
        ChartSpecData.from_dict(
            {
                "schema_version": 1,
                "metadata": {"chart_type": "bar"},
                "axes": None,
                "dataset": [{"category": str(index), "value": index} for index in range(513)],
            }
        )
    with pytest.raises(ChartSpecParseError) as too_large:
        ChartSpecData.from_dict({"x" * (MAX_CHART_SPEC_DATA_BYTES + 1): "payload"})

    assert long_text.value.issue.code == "max_length"
    assert too_many.value.issue.code == "max_items"
    assert too_large.value.issue.code == "content_too_large"


def test_canonical_serializer_enforces_content_byte_limit() -> None:
    spec = ChartSpecData(
        ChartMetadata(ChartType.PIE, title="x" * (MAX_CHART_SPEC_DATA_BYTES + 1)),
        None,
        (_category_point("A", 1),),
    )

    with pytest.raises(ChartSpecSerializationError) as error:
        spec.to_json()

    assert error.value.issue.code == "content_too_large"


def test_schema_is_supported_and_matches_local_content_shape() -> None:
    validate_schema_definition(CHART_SPEC_DATA_SCHEMA, require_object=True)
    valid = {
        "schema_version": 1,
        "metadata": {"chart_type": "scatter"},
        "axes": {"x": {"label": "X"}, "y": {"label": "Y"}},
        "dataset": [{"x": 1, "y": 2, "series": "s1"}],
    }

    assert validate_instance(valid, CHART_SPEC_DATA_SCHEMA) is None
    assert ChartSpecData.from_dict(valid).to_dict()["dataset"] == valid["dataset"]
    assert validate_instance({**valid, "unexpected": True}, CHART_SPEC_DATA_SCHEMA).code == "additional_property"


def test_bar_checks_pair_uniqueness_domain_and_missing_series_values() -> None:
    valid_grouped = _bar(
        (
            _category_point("Q1", 1, "A"),
            _category_point("Q2", 2, "A"),
            _category_point("Q1", 3, "B"),
            _category_point("Q2", 4, "B"),
        ),
        categories=("Q1", "Q2"),
    )
    missing = _bar(
        (_category_point("Q1", 1, "A"), _category_point("Q2", 3, "B")),
        categories=("Q1", "Q2"),
    )
    duplicate = _bar((_category_point("Q1", 1), _category_point("Q1", 2)))

    assert validate_chart_spec_data(valid_grouped) == ()
    assert "missing_category_value" in _codes(missing)
    assert "duplicate_category_series" in _codes(duplicate)


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ((_category_point("A", -1),), "negative_pie_value"),
        ((_category_point("A", 0),), "invalid_pie_total"),
        ((_category_point("A", 1), _category_point("A", 2)), "duplicate_pie_category"),
        ((_category_point("A", 1, "series"),), "pie_series_not_supported"),
        ((_category_point("A", 1e308), _category_point("B", 1e308)), "pie_total_overflow"),
    ],
)
def test_pie_semantics(points: tuple[CategoryValuePoint, ...], expected: str) -> None:
    spec = ChartSpecData(ChartMetadata(ChartType.PIE), None, points)
    assert expected in _codes(spec)


def test_line_requires_order_and_category_positions_for_every_series() -> None:
    valid = _line(
        (
            _coordinate_point(0, 2, "A"),
            _coordinate_point(1, 3, "A"),
            _coordinate_point(0, 1, "B"),
            _coordinate_point(1, 2, "B"),
        ),
        categories=("Jan", "Feb"),
    )
    missing = _line(
        (_coordinate_point(0, 2),),
        categories=("Jan", "Feb"),
    )
    unordered = _line((_coordinate_point(1, 2), _coordinate_point(0, 1)))
    fractional = _line((_coordinate_point(0.5, 2),), categories=("Jan",))

    assert validate_chart_spec_data(valid) == ()
    assert "missing_line_category_position" in _codes(missing)
    assert "line_x_not_increasing" in _codes(unordered)
    assert "line_category_position_not_integer" in _codes(fractional)


def test_scatter_allows_repeated_coordinates_and_rejects_categories() -> None:
    repeated = ChartSpecData(
        ChartMetadata(ChartType.SCATTER),
        Axes(Axis("X"), Axis("Y")),
        (_coordinate_point(1, 2), _coordinate_point(1, 2)),
    )
    categorical = ChartSpecData(
        ChartMetadata(ChartType.SCATTER),
        Axes(Axis("X", categories=("one",)), Axis("Y")),
        (_coordinate_point(0, 2),),
    )

    assert validate_chart_spec_data(repeated) == ()
    assert "scatter_categories_not_supported" in _codes(categorical)


def test_axis_ranges_are_ordered_applicable_and_cover_values() -> None:
    below_minimum = _bar((_category_point("Q1", -1),), y_min=0)
    invalid_bounds = _bar((_category_point("Q1", 1),), y_min=5, y_max=2)
    categorical_x_range = ChartSpecData(
        ChartMetadata(ChartType.BAR),
        Axes(Axis("Quarter", min_value=0), Axis("Revenue")),
        (_category_point("Q1", 1),),
    )

    assert "value_outside_axis_range" in _codes(below_minimum)
    assert "invalid_axis_range" in _codes(invalid_bounds)
    assert "categorical_axis_range" in _codes(categorical_x_range)


def test_issue_output_is_bounded_and_validation_keeps_input_unchanged() -> None:
    points = tuple(_category_point("same", -1) for _ in range(80))
    spec = ChartSpecData(ChartMetadata(ChartType.PIE), None, points)
    before = spec.to_dict()

    issues = validate_chart_spec_data(spec)

    assert len(issues) == MAX_ISSUES
    assert all(len(issue.message) <= 240 for issue in issues)
    assert all(len(issue.field_path.encode("utf-8")) <= 256 for issue in issues)
    assert spec.to_dict() == before
