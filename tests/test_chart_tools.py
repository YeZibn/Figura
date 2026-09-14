"""Tests for deterministic chart-understanding tools."""

from io import BytesIO
import json

import numpy as np
import pytest
from PIL import Image, ImageChops

from chartagent.spec import ChartSpec
from chartagent.tools import Tool, ToolRegistry, ToolResult, dispatch_observation
from chartagent.tools.chart.observation import overlays
from chartagent.tools.chart.observation.bars import measure_bars
from chartagent.tools.chart.observation.line import extract_line_series
from chartagent.tools.chart.observation.ocr import extract_text
from chartagent.tools.chart.observation.pie import extract_pie_slices
from chartagent.tools.chart.observation.scatter import extract_scatter_points
from chartagent.tools.chart.specification import assemble_spec, validate_spec
from tests.chart_fixtures import (
    annotated_bar_chart,
    grouped_bar_chart,
    line_chart,
    pie_chart,
    scatter_chart,
)


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

    monkeypatch.setattr("chartagent.tools.chart.observation.ocr._engine", lambda _path: _EmptyResult())

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
    assert result.data["bars"] == []
    assert result.data["baseline_y"] is None
    assert result.data["warnings"]
    assert result.data["confidence"]["overall"] == 0.0
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (320, 200)
        assert ImageChops.difference(Image.new("RGB", overlay.size, "white"), overlay).getbbox()


def test_measure_grouped_bars_preserves_series_and_categories(tmp_path):
    png_bytes, _ = grouped_bar_chart()
    chart_path = tmp_path / "grouped-bars.png"
    chart_path.write_bytes(png_bytes)

    result = measure_bars(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert len(data["bars"]) == 6
    assert {bar["series"] for bar in data["bars"]} == {"series_1", "series_2"}
    assert {bar["category_index"] for bar in data["bars"]} == {1, 2, 3}
    assert data["stacked"] is False
    assert len(result.images) == 1
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (720, 480)


def test_measure_stacked_bars_preserves_segments_and_total_height(tmp_path):
    png_bytes, _ = grouped_bar_chart(stacked=True)
    chart_path = tmp_path / "stacked-bars.png"
    chart_path.write_bytes(png_bytes)

    result = measure_bars(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert data["stacked"] is True
    assert len(data["bars"]) == 6
    assert all(bar["stack_total_h_px"] > bar["h_px"] for bar in data["bars"])
    assert data["warnings"]


def test_extract_line_series_preserves_colored_series_and_points(tmp_path, monkeypatch):
    png_bytes, _ = line_chart()
    chart_path = tmp_path / "lines.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.line.extract_text", lambda _path: ToolResult([]))

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert len(data["series"]) == 2
    assert {entry["id"] for entry in data["series"]} == {"series_1", "series_2"}
    assert all(len(entry["points"]) >= 4 for entry in data["series"])
    assert all(
        point["x_px"] < next_point["x_px"]
        for entry in data["series"]
        for point, next_point in zip(entry["points"], entry["points"][1:])
    )
    assert data["warnings"]
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (720, 480)


def test_extract_line_series_calibrates_when_tick_evidence_is_available(tmp_path, monkeypatch):
    png_bytes, _ = line_chart(values_by_series={"North": (1, 3, 2, 4, 5)})
    chart_path = tmp_path / "calibrated-line.png"
    chart_path.write_bytes(png_bytes)
    snippets = [
        {"text": "0", "bbox": [96, 418, 8, 12], "confidence": 0.99},
        {"text": "1", "bbox": [196, 418, 8, 12], "confidence": 0.99},
        {"text": "2", "bbox": [296, 418, 8, 12], "confidence": 0.99},
        {"text": "3", "bbox": [396, 418, 8, 12], "confidence": 0.99},
        {"text": "4", "bbox": [496, 418, 8, 12], "confidence": 0.99},
        {"text": "0", "bbox": [36, 398, 20, 12], "confidence": 0.99},
        {"text": "2", "bbox": [36, 298, 20, 12], "confidence": 0.99},
        {"text": "4", "bbox": [36, 198, 20, 12], "confidence": 0.99},
        {"text": "6", "bbox": [36, 98, 20, 12], "confidence": 0.99},
    ]
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult(snippets),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["axes"]["x"]["calibrated"] is True
    assert result.data["axes"]["y"]["calibrated"] is True
    points = result.data["series"][0]["points"]
    assert all("x" in point and "y" in point for point in points)
    assert not any("calibration unavailable" in warning for warning in result.warnings)


def test_extract_scatter_points_preserves_series_and_calibrated_coordinates(tmp_path, monkeypatch):
    png_bytes, _ = scatter_chart()
    chart_path = tmp_path / "scatter.png"
    chart_path.write_bytes(png_bytes)
    snippets = [
        {"text": str(value), "bbox": [left, 418, 8, 12], "confidence": 0.99}
        for left, value in zip([110, 234, 358, 482, 606], [0, 1, 2, 3, 4])
    ] + [
        {"text": str(value), "bbox": [36, top, 20, 12], "confidence": 0.99}
        for value, top in zip([0, 2, 4, 6, 8], [418, 325, 233, 140, 48])
    ]
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: ToolResult(snippets),
    )

    result = extract_scatter_points(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert len(data["series"]) == 2
    assert [entry["point_count"] for entry in data["series"]] == [5, 5]
    assert len(data["points"]) == 10
    assert data["axes"]["x"]["calibrated"] is True
    assert data["axes"]["y"]["calibrated"] is True
    assert all("x" in point and "y" in point for point in data["points"])
    observed_y_values = []
    for entry in data["series"]:
        assert [point["x"] for point in entry["points"]] == pytest.approx(
            [0, 1, 2, 3, 4], abs=0.15
        )
        observed_y_values.append([point["y"] for point in entry["points"]])
    assert any(
        values == pytest.approx([1, 3, 2, 5, 4], abs=0.15)
        for values in observed_y_values
    )
    assert any(
        values == pytest.approx([2, 4, 5, 3, 6], abs=0.15)
        for values in observed_y_values
    )
    assert 0.0 <= data["confidence"]["overall"] <= 1.0
    with Image.open(BytesIO(result.images[0].content)) as overlay, Image.open(chart_path) as source:
        assert overlay.size == source.size
        assert ImageChops.difference(source.convert("RGB"), overlay.convert("RGB")).getbbox()


def test_extract_scatter_points_preserves_pixel_evidence_when_uncalibrated(tmp_path, monkeypatch):
    png_bytes, _ = scatter_chart()
    chart_path = tmp_path / "uncalibrated-scatter.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_scatter_points(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["points"]
    assert all("x_px" in point and "y_px" in point for point in result.data["points"])
    assert not any("x" in point or "y" in point for point in result.data["points"])
    assert any("calibration unavailable" in warning for warning in result.data["warnings"])


def test_extract_scatter_points_reports_overlap_and_outlier_evidence(tmp_path, monkeypatch):
    png_bytes, _ = scatter_chart(
        values_by_series={"North": (1, 1, 2, 3, 8)},
        x_values=(0, 0.02, 1, 2, 4),
    )
    chart_path = tmp_path / "uncertain-scatter.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_scatter_points(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["points"]
    assert all("appearance" in point for point in result.data["points"])
    assert result.data["overlaps"] or any(
        point["merged_candidate"] for point in result.data["points"]
    )
    assert any(
        point["outlier_candidate"] for point in result.data["points"]
    )
    assert result.data["warnings"]


def test_extract_scatter_points_blank_image_is_inspectable(tmp_path):
    blank = tmp_path / "blank-scatter.png"
    Image.new("RGB", (320, 200), "white").save(blank)

    result = extract_scatter_points(str(blank))

    assert isinstance(result, ToolResult)
    assert result.data["series"] == []
    assert result.data["points"] == []
    assert result.data["warnings"]
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (320, 200)


def test_extract_scatter_points_missing_file_is_structured_error(tmp_path):
    missing = tmp_path / "missing-scatter.png"

    assert extract_scatter_points(str(missing)) == {"error": f"image not found: {missing}"}


def test_extract_pie_slices_measures_clean_sectors(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20))
    chart_path = tmp_path / "pie.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert len(data["slices"]) == 4
    assert [item["ratio"] for item in data["slices"]] == pytest.approx(
        [0.35, 0.25, 0.20, 0.20], abs=0.035
    )
    assert data["circle"]["radius"] > 100
    assert data["totals"]["consistent"] is True
    assert 0.0 <= data["confidence"]["overall"] <= 1.0
    with Image.open(BytesIO(result.images[0].content)) as overlay, Image.open(chart_path) as source:
        assert overlay.size == source.size
        assert ImageChops.difference(source.convert("RGB"), overlay.convert("RGB")).getbbox()


def test_extract_pie_slices_preserves_printed_values_separately(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(60, 40), labels=("Alpha", "Beta"))
    chart_path = tmp_path / "pie-labels.png"
    chart_path.write_bytes(png_bytes)
    snippets = [
        {"id": 1, "text": "60%", "bbox": [315, 240, 32, 16], "confidence": 0.98},
    ]
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult(snippets))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    printed = [item for item in result.data["slices"] if "printed_value" in item]
    assert printed
    assert printed[0]["printed_value"] == 60.0
    assert printed[0]["ratio"] != printed[0]["printed_value"]


def test_extract_pie_slices_associates_legend_color_and_label(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(60, 40), labels=("Alpha", "Beta"), show_labels=False)
    chart_path = tmp_path / "pie-legend.png"
    chart_path.write_bytes(png_bytes)
    snippets = [
        {"id": 1, "text": "Alpha", "bbox": [435, 201, 40, 14], "confidence": 0.96},
        {"id": 2, "text": "Beta", "bbox": [435, 226, 32, 14], "confidence": 0.96},
    ]
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult(snippets))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert any(entry.get("slice_id") for entry in result.data["legend"])
    assert {item.get("label") for item in result.data["slices"]} >= {"Alpha", "Beta"}


def test_extract_pie_slices_reports_incomplete_sector_totals(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(60, 40), labels=("Alpha", "Beta"), show_labels=False)
    chart_path = tmp_path / "incomplete-pie.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.pie._sample_labels",
        lambda _rgb, _circle, _palette: (
            np.concatenate([np.zeros(360, dtype=int), np.full(360, -1, dtype=int)]),
            0.5,
        ),
    )

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["slices"]
    assert result.data["totals"]["consistent"] is False
    assert any("totals" in warning for warning in result.data["warnings"])


def test_extract_pie_slices_blank_image_is_inspectable(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (320, 200), "white").save(blank)

    result = extract_pie_slices(str(blank))

    assert isinstance(result, ToolResult)
    assert result.data["slices"] == []
    assert result.data["warnings"]
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (320, 200)


def test_assemble_and_validate_axis_free_pie_spec():
    spec = assemble_spec(
        "pie",
        [{"category": "Alpha", "value": 0.6}, {"category": "Beta", "value": 0.4}],
    )

    assert spec["axes"] is None
    assert validate_spec(spec) == {"ok": True, "issues": []}


def test_cartesian_tool_observation_serializes_warnings_and_overlay(tmp_path):
    png_bytes, _ = grouped_bar_chart(stacked=True)
    chart_path = tmp_path / "stacked-bars.png"
    chart_path.write_bytes(png_bytes)
    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure",
            {"type": "object", "properties": {"image_path": {"type": "string"}}},
            lambda image_path: measure_bars(image_path),
        )
    )

    observation = dispatch_observation(
        registry,
        "measure_bars",
        json.dumps({"image_path": str(chart_path)}),
    )
    payload = json.loads(observation.content)

    assert payload["data"]["confidence"]["overall"] <= 1.0
    assert payload["warnings"]
    assert len(observation.images) == 1


@pytest.mark.parametrize(
    ("chart_type", "points"),
    [
        ("bar", [{"category": "A", "value": 12}]),
        ("line", [{"x": 1, "y": 12}, {"x": 2, "y": 18}]),
        ("scatter", [{"x": 1, "y": 12}, {"x": 2, "y": 18}]),
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


def test_assemble_spec_preserves_series_and_confidence():
    result = assemble_spec(
        "line",
        [
            {"x": 0, "y": 1, "series": "North", "confidence": 0.9},
            {"x": 0, "y": 2, "series": "South", "confidence": 0.8},
        ],
        x_label="X",
        y_label="Y",
    )

    assert result["dataset"][0]["series"] == "North"
    assert result["dataset"][1]["confidence"] == 0.8
    assert validate_spec(result) == {"ok": True, "issues": []}


def test_assemble_spec_deduplicates_multi_series_bar_categories():
    result = assemble_spec(
        "bar",
        [
            {"category": "A", "value": 1, "series": "North"},
            {"category": "B", "value": 2, "series": "North"},
            {"category": "A", "value": 3, "series": "South"},
            {"category": "B", "value": 4, "series": "South"},
        ],
        x_label="Category",
        y_label="Value",
    )

    assert "error" not in result
    assert result["axes"]["x"]["categories"] == ["A", "B"]
    assert validate_spec(result)["ok"] is True


def test_assemble_spec_rejects_empty_series():
    result = assemble_spec(
        "line", [{"x": 0, "y": 1, "series": ""}], x_label="X", y_label="Y"
    )

    assert "series must be a non-empty string" in result["error"]


def test_assemble_spec_rejects_missing_cartesian_axes():
    result = assemble_spec("bar", [{"category": "A", "value": 1}])

    assert "require non-empty x_label and y_label" in result["error"]

    scatter_result = assemble_spec("scatter", [{"x": 1, "y": 2}])
    assert "require non-empty x_label and y_label" in scatter_result["error"]


def test_validate_spec_rejects_scatter_without_axes():
    result = validate_spec(
        {
            "metadata": {"chart_type": "scatter"},
            "dataset": [{"x": 1, "y": 2}],
        }
    )

    assert result["ok"] is False
    assert any(issue["location"] == "axes" for issue in result["issues"])


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
