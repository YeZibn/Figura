"""Tests for deterministic chart-understanding tools."""

from io import BytesIO

import pytest
from PIL import Image

from chartagent.spec import ChartSpec
from chartagent.tools.chart.geometry import measure_bars
from chartagent.tools.chart.ocr import extract_text
from chartagent.tools.chart.spec_tools import assemble_spec, validate_spec
from tests.chart_fixtures import annotated_bar_chart


def test_annotated_bar_chart_fixture_is_valid_png(tmp_path):
    png_bytes, ground_truth = annotated_bar_chart()
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(png_bytes)

    assert chart_path.is_file()
    with Image.open(BytesIO(png_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (720, 480)
    assert [point["value"] for point in ground_truth["dataset"]] == [10, 20, 30]


@pytest.fixture
def annotated_chart_path(tmp_path):
    png_bytes, _ = annotated_bar_chart()
    path = tmp_path / "annotated-bars.png"
    path.write_bytes(png_bytes)
    return path


def test_extract_text_contains_annotations(annotated_chart_path):
    snippets = extract_text(str(annotated_chart_path))

    assert isinstance(snippets, list)
    assert {"10", "20", "30"} <= {snippet["text"] for snippet in snippets}
    for snippet in snippets:
        assert len(snippet["bbox"]) == 4
        assert all(isinstance(value, int) for value in snippet["bbox"])
        assert 0.0 <= snippet["confidence"] <= 1.0


def test_extract_text_missing_file_is_structured_error(tmp_path):
    missing = tmp_path / "missing.png"

    assert extract_text(str(missing)) == {"error": f"image not found: {missing}"}


def test_measure_bars_matches_true_ratios(annotated_chart_path):
    result = measure_bars(str(annotated_chart_path))

    assert result["baseline_y"] is not None
    assert len(result["bars"]) == 3
    assert [bar["ratio"] for bar in result["bars"]] == pytest.approx(
        [1.0, 2.0, 3.0], rel=0.1
    )
    assert all(bar["h_px"] > 0 and len(bar["bbox"]) == 4 for bar in result["bars"])


def test_measure_bars_missing_file_is_structured_error(tmp_path):
    missing = tmp_path / "missing.png"

    assert measure_bars(str(missing)) == {"error": f"image not found: {missing}"}


def test_measure_bars_blank_image_returns_empty(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (320, 200), "white").save(blank)

    assert measure_bars(str(blank)) == {"bars": [], "baseline_y": None}


@pytest.mark.parametrize(
    ("chart_type", "points"),
    [
        ("bar", [{"category": "A", "value": 12}]),
        ("line", [{"x": 1, "y": 12}, {"x": 2, "y": 18}]),
    ],
)
def test_assemble_spec_valid_specs_round_trip(chart_type, points):
    result = assemble_spec(
        chart_type=chart_type,
        title="Example",
        x_label="X",
        y_label="Y",
        points=points,
        source="fixture.png",
    )

    assert "error" not in result
    assert ChartSpec.from_dict(result).to_dict() == result
    assert result["metadata"]["source"] == "fixture.png"


def test_assemble_spec_rejects_missing_cartesian_axes():
    result = assemble_spec("bar", [{"category": "A", "value": 1}])

    assert "require non-empty x_label and y_label" in result["error"]


def test_assemble_spec_rejects_unknown_type():
    assert "unknown chart_type" in assemble_spec("radar", [{"x": 1, "y": 2}])["error"]


@pytest.mark.parametrize(
    ("chart_type", "points", "error_text"),
    [
        ("bar", [{"category": "A"}], "numeric value"),
        ("bar", [{"category": "A", "value": 1, "x": 1, "y": 2}], "cannot contain x/y"),
        ("line", [{"category": "A", "value": 1}], "numeric x and y"),
    ],
)
def test_assemble_spec_rejects_malformed_points(chart_type, points, error_text):
    result = assemble_spec(chart_type, points, x_label="X", y_label="Y")

    assert error_text in result["error"]


def test_validate_spec_passes_clean_spec():
    spec = assemble_spec(
        "bar",
        [{"category": "A", "value": 1}],
        x_label="Category",
        y_label="Value",
    )

    assert validate_spec(spec) == {"ok": True, "issues": []}


def test_validate_spec_reports_empty_dataset():
    _, spec = annotated_bar_chart()
    spec["dataset"] = []

    result = validate_spec(spec)

    assert result["ok"] is False
    assert any(issue["location"] == "dataset" for issue in result["issues"])


def test_validate_spec_reports_mixed_point_shapes():
    _, spec = annotated_bar_chart()
    spec["dataset"].append({"x": 1, "y": 2})

    result = validate_spec(spec)

    assert result["ok"] is False
    assert any(issue["location"] == "dataset[3]" for issue in result["issues"])


def test_validate_spec_never_raises_for_malformed_input():
    result = validate_spec({"metadata": {"chart_type": "radar"}})

    assert result["ok"] is False
    assert result["issues"][0]["location"] == "spec"
