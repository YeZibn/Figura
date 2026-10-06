from __future__ import annotations

from dataclasses import replace

import pytest

from figura.charts.chartspec import (
    CHART_SPEC_DATA_SCHEMA,
    ChartSpecData,
    ChartSpecParseError,
    ChartSpecSerializationError,
    PieDataset,
    PieSlice,
    parse_chart_spec_data,
    validate_chart_spec_data,
)
from figura.charts.chartspec.limits import MAX_CHART_SPEC_DATA_BYTES
from figura.charts.limits import MAX_ISSUES
from figura.shared.json_schema import validate_instance, validate_schema_definition


def _raw(chart_type: str) -> dict[str, object]:
    if chart_type in {"bar", "box_plot"}:
        coordinate: dict[str, object] = {
            "kind": "cartesian",
            "x_axis": {"kind": "categorical"},
            "y_axis": {"kind": "numeric"},
        }
    elif chart_type in {"line", "scatter", "area", "histogram"}:
        coordinate: dict[str, object] = {
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
        "metadata": {"chart_type": chart_type, "title": "Demo"},
        "coordinate_system": coordinate,
        "dataset": datasets[chart_type],
    }


def _codes(spec: ChartSpecData) -> set[str]:
    return {issue.code for issue in validate_chart_spec_data(spec)}


@pytest.mark.parametrize(
    "chart_type",
    ["bar", "line", "scatter", "pie", "area", "histogram", "box_plot", "radar", "heatmap", "treemap"],
)
def test_all_v2_chart_families_round_trip(chart_type: str) -> None:
    spec = ChartSpecData.from_dict(_raw(chart_type))

    assert spec.metadata.chart_type.value == chart_type
    assert validate_chart_spec_data(spec) == ()
    assert ChartSpecData.from_json(spec.to_json()) == spec


def test_scatter_bubble_size_channel_is_preserved_and_consistent() -> None:
    raw = _raw("scatter")
    raw["dataset"] = {
        "series": [{
            "id": "bubble",
            "label": "Bubble",
            "points": [
                {"x": 1, "y": 2, "size": 3},
                {"x": 2, "y": 4, "size": 9},
            ],
        }]
    }

    spec = ChartSpecData.from_dict(raw)
    restored = ChartSpecData.from_json(spec.to_json())

    assert validate_chart_spec_data(restored) == ()
    assert [point.size for point in restored.dataset.series[0].points] == [3, 9]

    raw["dataset"]["series"][0]["points"][1].pop("size")  # type: ignore[index,union-attr]
    inconsistent = ChartSpecData.from_dict(raw)
    assert "inconsistent_bubble_size" in _codes(inconsistent)


def test_schema_is_valid_and_accepts_typed_family_branches() -> None:
    validate_schema_definition(CHART_SPEC_DATA_SCHEMA, require_object=True)
    for chart_type in ("bar", "line", "scatter", "pie", "area", "histogram", "box_plot", "radar", "heatmap", "treemap"):
        assert validate_instance(_raw(chart_type), CHART_SPEC_DATA_SCHEMA) is None


def test_v1_is_rejected_without_compatibility_fallback() -> None:
    raw = _raw("bar")
    raw["schema_version"] = 1

    with pytest.raises(ChartSpecParseError) as error:
        ChartSpecData.from_dict(raw)

    assert error.value.issue.code == "unsupported_schema_version"
    assert error.value.issue.field_path == "/schema_version"


@pytest.mark.parametrize(
    ("raw", "path"),
    [
        ({**_raw("bar"), "unexpected": True}, "/unexpected"),
        ({**_raw("bar"), "dataset": {"orientation": "vertical", "mode": "grouped", "categories": [], "series": [], "extra": 1}}, "/dataset/categories"),
        ({**_raw("bar"), "dataset": {"slices": [{"id": "a", "label": "A", "value": 1}]}}, "/dataset/orientation"),
    ],
)
def test_parser_rejects_unknown_or_wrong_family_fields(raw: dict[str, object], path: str) -> None:
    with pytest.raises(ChartSpecParseError) as error:
        ChartSpecData.from_dict(raw)

    assert error.value.issue.field_path.startswith(path)


def test_json_parser_rejects_duplicate_keys_and_non_finite_values() -> None:
    with pytest.raises(ChartSpecParseError) as duplicate:
        ChartSpecData.from_json(
            '{"schema_version":2,"metadata":{"chart_type":"bar","chart_type":"pie"},'
            '"coordinate_system":{"kind":"cartesian","x_axis":{"kind":"categorical"},'
            '"y_axis":{"kind":"numeric"}},"dataset":{}}'
        )
    with pytest.raises(ChartSpecParseError) as non_finite:
        raw = _raw("bar")
        raw["dataset"] = {
            "orientation": "vertical",
            "mode": "grouped",
            "categories": [{"id": "a", "label": "A"}],
            "series": [{"id": "s", "label": "S", "values": [float("nan")]}],
        }
        ChartSpecData.from_json(__import__("json").dumps(raw))

    assert duplicate.value.issue.code == "duplicate_key"
    assert non_finite.value.issue.code == "non_finite_number"


def test_bool_numeric_and_numeric_string_are_rejected() -> None:
    for invalid in (True, "1"):
        raw = _raw("pie")
        raw["dataset"] = {"slices": [{"id": "a", "label": "A", "value": invalid}]}
        with pytest.raises(ChartSpecParseError):
            ChartSpecData.from_dict(raw)


def test_semantic_validation_checks_coordinate_family_and_axis_kinds() -> None:
    raw = _raw("bar")
    raw["dataset"] = {
        "orientation": "horizontal",
        "mode": "grouped",
        "categories": [{"id": "a", "label": "A"}],
        "series": [{"id": "s", "label": "S", "values": [1]}],
    }
    spec = ChartSpecData.from_dict(raw)

    assert "axis_kind_mismatch" in _codes(spec)
    assert validate_chart_spec_data(replace(spec, schema_version=1))[0].code == "unsupported_schema_version"


def test_family_semantics_cover_heatmap_box_histogram_and_treemap() -> None:
    histogram = _raw("histogram")
    histogram["dataset"] = {"measure": "count", "bins": [{"start": 0, "end": 2, "value": 1}, {"start": 1, "end": 3, "value": 2}]}
    box = _raw("box_plot")
    box["dataset"] = {"orientation": "vertical", "groups": [{"id": "g", "label": "G", "lower_whisker": 4, "q1": 3, "median": 2, "q3": 5, "upper_whisker": 6}]}
    heatmap = _raw("heatmap")
    heatmap["dataset"] = {**heatmap["dataset"], "values": [[1]]}  # type: ignore[arg-type]
    treemap = _raw("treemap")
    treemap["dataset"] = {"root_id": "root", "nodes": [{"id": "root", "parent_id": None, "label": "Root", "value": 99}, {"id": "leaf", "parent_id": "root", "label": "Leaf", "value": 1}]}

    assert "overlapping_histogram_bins" in _codes(ChartSpecData.from_dict(histogram))
    assert "invalid_quartile_order" in _codes(ChartSpecData.from_dict(box))
    assert "heatmap_column_count_mismatch" in _codes(ChartSpecData.from_dict(heatmap))
    assert "treemap_parent_total_mismatch" in _codes(ChartSpecData.from_dict(treemap))


def test_stacked_area_requires_matching_x_and_no_gaps() -> None:
    raw = _raw("area")
    raw["dataset"] = {
        "stacking": "stacked",
        "series": [
            {"id": "a", "label": "A", "points": [{"x": 1, "y": 1}, {"x": 2, "y": 2}]},
            {"id": "b", "label": "B", "points": [{"x": 1, "y": 1}, {"x": 3, "y": None}]},
        ],
    }

    codes = _codes(ChartSpecData.from_dict(raw))

    assert "stacked_x_domain_mismatch" in codes
    assert "null_stacked_value" in codes


def test_chart_spec_bounds_and_issue_list_are_bounded() -> None:
    too_large = {"unexpected": "x" * MAX_CHART_SPEC_DATA_BYTES}
    with pytest.raises(ChartSpecParseError) as error:
        ChartSpecData.from_dict(too_large)
    assert error.value.issue.code == "content_too_large"

    parsed = ChartSpecData.from_dict(_raw("pie"))
    invalid = replace(
        parsed,
        dataset=PieDataset(tuple(PieSlice("same", "x", -1) for _ in range(80))),
    )
    issues = validate_chart_spec_data(invalid)
    assert len(issues) <= MAX_ISSUES


def test_invalid_manual_model_does_not_serialize() -> None:
    spec = ChartSpecData.from_dict(_raw("pie"))
    invalid = replace(spec, schema_version=1)

    with pytest.raises(ChartSpecSerializationError):
        invalid.to_json()
