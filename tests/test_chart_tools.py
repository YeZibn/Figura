"""Tests for deterministic chart-understanding tools."""

from io import BytesIO

import pytest
from PIL import Image, ImageChops

from chartagent.spec import ChartSpec
from chartagent.tools import ToolResult
from chartagent.tools.chart import overlays
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


def test_extract_text_contains_annotations(annotated_chart_path, monkeypatch):
    labels = []
    original_tag = overlays._tag

    def recording_tag(draw, xy, text, *, image_size):
        labels.append(text)
        original_tag(draw, xy, text, image_size=image_size)

    monkeypatch.setattr(overlays, "_tag", recording_tag)
    result = extract_text(str(annotated_chart_path))

    assert isinstance(result, ToolResult)
    snippets = result.data
    assert isinstance(snippets, list)
    assert {"10", "20", "30"} <= {snippet["text"] for snippet in snippets}
    assert [snippet["id"] for snippet in snippets] == list(range(1, len(snippets) + 1))
    for snippet in snippets:
        assert len(snippet["bbox"]) == 4
        assert all(isinstance(value, int) for value in snippet["bbox"])
        assert 0.0 <= snippet["confidence"] <= 1.0
    assert len(result.images) == 1
    with Image.open(annotated_chart_path) as source, Image.open(
        BytesIO(result.images[0].content)
    ) as overlay:
        assert overlay.size == (720, 480)
        assert ImageChops.difference(source.convert("RGB"), overlay).getbbox()
    assert labels == [
        f'{snippet["id"]} {snippet["confidence"]:.2f}' for snippet in snippets
    ]


def test_extract_text_no_detections_returns_source_sized_overlay(
    annotated_chart_path, monkeypatch
):
    class _EmptyResult:
        boxes = None
        txts = None
        scores = None

    monkeypatch.setattr("chartagent.tools.chart.ocr._engine", lambda _path: _EmptyResult())

    result = extract_text(str(annotated_chart_path))

    assert isinstance(result, ToolResult)
    assert result.data == []
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (720, 480)


def test_extract_text_missing_file_is_structured_error(tmp_path):
    missing = tmp_path / "missing.png"

    assert extract_text(str(missing)) == {"error": f"image not found: {missing}"}


def test_extract_text_unreadable_file_is_structured_error(tmp_path):
    unreadable = tmp_path / "unreadable.png"
    unreadable.write_bytes(b"not an image")

    result = extract_text(str(unreadable))

    assert "error" in result
    assert str(unreadable) in result["error"]


def test_measure_bars_matches_true_ratios(annotated_chart_path, monkeypatch):
    labels = []
    original_tag = overlays._tag

    def recording_tag(draw, xy, text, *, image_size):
        labels.append(text)
        original_tag(draw, xy, text, image_size=image_size)

    monkeypatch.setattr(overlays, "_tag", recording_tag)
    result = measure_bars(str(annotated_chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert data["baseline_y"] is not None
    assert len(data["bars"]) == 3
    assert [bar["id"] for bar in data["bars"]] == [1, 2, 3]
    assert [bar["ratio"] for bar in data["bars"]] == pytest.approx(
        [1.0, 2.0, 3.0], rel=0.1
    )
    assert all(bar["h_px"] > 0 and len(bar["bbox"]) == 4 for bar in data["bars"])
    with Image.open(annotated_chart_path) as source, Image.open(
        BytesIO(result.images[0].content)
    ) as overlay:
        assert overlay.size == source.size
        assert ImageChops.difference(source.convert("RGB"), overlay.convert("RGB")).getbbox()
    assert labels == ["BASELINE", *[str(bar["id"]) for bar in data["bars"]]]


def test_measure_bars_missing_file_is_structured_error(tmp_path):
    missing = tmp_path / "missing.png"

    assert measure_bars(str(missing)) == {"error": f"image not found: {missing}"}


def test_measure_bars_unreadable_file_is_structured_error(tmp_path):
    unreadable = tmp_path / "unreadable.png"
    unreadable.write_bytes(b"not an image")

    result = measure_bars(str(unreadable))

    assert "error" in result
    assert str(unreadable) in result["error"]


def test_measure_bars_blank_image_returns_empty(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (320, 200), "white").save(blank)

    result = measure_bars(str(blank))

    assert isinstance(result, ToolResult)
    assert result.data == {"bars": [], "baseline_y": None}
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (320, 200)
        assert ImageChops.difference(Image.new("RGB", overlay.size, "white"), overlay).getbbox()


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
