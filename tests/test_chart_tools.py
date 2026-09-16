"""Tests for deterministic chart-understanding tools."""

from io import BytesIO
import json

import numpy as np
import pytest
from PIL import Image, ImageChops, ImageDraw

from chartagent.spec import ChartSpec
from chartagent.tools import Tool, ToolRegistry, ToolResult, dispatch_observation
from chartagent.tools.chart.observation import overlays
from chartagent.tools.chart.observation.bars import measure_bars
from chartagent.tools.chart.observation.coordinates import (
    apply_axis_transform,
    cartesian_frame,
    fit_axis_transform,
    polar_frame,
)
from chartagent.tools.chart.observation.foundation import (
    associate_series_labels,
    build_common_evidence,
)
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


def test_common_chart_evidence_separates_coordinate_models_and_calibration():
    rgb = np.zeros((40, 60, 3), dtype=np.uint8)
    frame = cartesian_frame(
        bbox=[4, 5, 50, 30],
        orientation="oblique",
        confidence=0.8,
        evidence=["x_axis"],
    )
    evidence = build_common_evidence(
        rgb,
        coordinate_system="cartesian_2d",
        frame=frame,
        confidence={"overall": 0.8},
        warnings=["calibration unavailable"],
    )
    assert evidence["image_size"] == [60, 40]
    assert evidence["coordinate_system"] == "cartesian_2d"
    assert evidence["frame"]["orientation"] == "oblique"
    assert evidence["warnings"] == ["calibration unavailable"]

    polar = polar_frame(
        {"bbox_px": [10, 8, 24, 24], "center_px": [22, 20], "radius_px": 12, "confidence": 0.9}
    )
    assert polar["coordinate_system"] == "polar_2d"
    assert polar["center_px"] == [22.0, 20.0]

    short_fit = fit_axis_transform(
        [
            {"pixel": 10, "value": 0, "point_px": [10, 20]},
            {"pixel": 20, "value": 10, "point_px": [20, 20]},
        ],
        [[10, 20], [20, 20]],
    )
    assert short_fit is not None
    assert short_fit["calibrated"] is False
    assert apply_axis_transform(short_fit, [15, 20]) is None


def test_generic_series_association_consumes_text_evidence_without_ocr():
    entries = [{"id": "series_1", "color": "#ff0000", "geometry": {"bbox_px": [8, 10, 12, 8]}}]
    associated = associate_series_labels(
        entries,
        [{"text": "Revenue", "bbox": [26, 9, 48, 12]}],
    )
    assert associated[0]["label"] == "Revenue"
    assert associated[0]["association"]["source"] == "text_evidence"
    assert associated[0]["association"]["status"] == "candidate"


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
    assert data["orientation"] == "vertical"
    assert data["bar_mode"] == "single"
    assert data["evidence"]["coordinate_system"] == "cartesian_2d"
    assert data["evidence"]["frame"]["bbox_px"]
    assert data["baseline_cross_check"]["consistent"] is True
    assert data["baseline"]["points_px"] == [[115, 426], [623, 426]]
    assert len(data["bars"]) == 3
    assert [bar["id"] for bar in data["bars"]] == [1, 2, 3]
    assert [bar["measure"]["ratio"] for bar in data["bars"]] == pytest.approx(
        [1.0, 2.0, 3.0], rel=0.1
    )
    assert all(
        bar["measure"]["value_length_px"] > 0
        and len(bar["geometry"]["bbox_px"]) == 4
        and len(bar["geometry"]["polygon_px"]) == 4
        for bar in data["bars"]
    )
    assert not any(
        field in data or field in data["bars"][0]
        for field in ("baseline_y", "h_px", "stacked", "bbox", "ratio", "stack_total_h_px")
    )
    assert "series" not in data["bars"][0]
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
    assert result.data["baseline"] is None
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
    assert {bar["series_id"] for bar in data["bars"]} == {"series_1", "series_2"}
    assert {bar["category_index"] for bar in data["bars"]} == {1, 2, 3}
    assert data["bar_mode"] == "grouped"
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
    assert data["bar_mode"] == "stacked"
    assert len(data["bars"]) == 6
    assert all(
        bar["stack"]["total_length_px"] > abs(bar["measure"]["value_length_px"])
        for bar in data["bars"]
    )
    assert data["warnings"]
    assert data["evidence"]["coordinate_system"] == "cartesian_2d"
    assert data["evidence"]["frame"]["coordinate_system"] == "cartesian_2d"
    assert "center_px" not in data["evidence"]["frame"]


def _axis_bar_chart(*, horizontal: bool = False, mixed: bool = False) -> Image.Image:
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    color = "#4c78a8"
    if horizontal:
        draw.line((100, 60, 100, 370), fill="black", width=2)
        draw.line((100, 370, 600, 370), fill="black", width=2)
        for y, length in ((100, 180), (180, 330), (260, 250)):
            draw.rectangle((100, y, 100 + length, y + 38), fill=color)
    else:
        draw.line((80, 220, 600, 220), fill="black", width=2)
        draw.line((80, 40, 80, 360), fill="black", width=2)
        if mixed:
            for x, length in ((140, 100), (270, 50)):
                draw.rectangle((x, 220 - length, x + 70, 220), fill=color)
            for x, length in ((400, 70), (510, 130)):
                draw.rectangle((x, 220, x + 70, 220 + length), fill=color)
        else:
            for x, length in ((140, 100), (270, 200), (400, 150)):
                draw.rectangle((x, 220 - length, x + 70, 220), fill=color)
    return image


def test_measure_bars_supports_horizontal_value_axis(tmp_path):
    path = tmp_path / "horizontal-bars.png"
    _axis_bar_chart(horizontal=True).save(path)

    result = measure_bars(str(path))

    assert isinstance(result, ToolResult)
    assert result.data["orientation"] == "horizontal"
    assert result.data["baseline"]["points_px"] == [[100, 100], [100, 299]]
    assert [bar["measure"]["ratio"] for bar in result.data["bars"]] == pytest.approx(
        [1.0, 1.83, 1.39], rel=0.03
    )


def test_measure_bars_preserves_signed_mixed_values(tmp_path):
    path = tmp_path / "mixed-bars.png"
    _axis_bar_chart(mixed=True).save(path)

    result = measure_bars(str(path))

    assert isinstance(result, ToolResult)
    lengths = [bar["measure"]["value_length_px"] for bar in result.data["bars"]]
    assert lengths[0] > 0 and lengths[1] > 0
    assert lengths[2] < 0 and lengths[3] < 0


def test_measure_bars_preserves_rotated_candidates(tmp_path):
    png_bytes, _ = annotated_bar_chart()
    source = Image.open(BytesIO(png_bytes)).convert("RGB")
    path = tmp_path / "rotated-bars.png"
    source.rotate(4, resample=Image.Resampling.BICUBIC, fillcolor="white").save(path)

    result = measure_bars(str(path))

    assert isinstance(result, ToolResult)
    assert result.data["orientation"] == "oblique"
    assert len(result.data["bars"]) == 3
    assert result.data["baseline"]["points_px"][0][1] != result.data["baseline"]["points_px"][1][1]


def test_measure_bars_bounds_perspective_like_geometry(tmp_path):
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.line((80, 300, 600, 300), fill="black", width=2)
    draw.line((80, 40, 80, 360), fill="black", width=2)
    for x in (130, 300, 470):
        draw.polygon(
            [(x + 50, 100), (x + 60, 100), (x + 120, 300), (x, 300)],
            fill="#4c78a8",
        )
    path = tmp_path / "perspective-like-bars.png"
    image.save(path)

    result = measure_bars(str(path))

    assert isinstance(result, ToolResult)
    assert result.data["baseline"] is None
    assert any("perspective" in warning for warning in result.data["warnings"])
    assert all(bar["measure"]["ratio"] is None for bar in result.data["bars"])


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


def _line_tick_snippets():
    return [
        {"text": str(value), "bbox": [left, 418, 8, 12], "confidence": 0.99}
        for left, value in zip([96, 196, 296, 396, 496], [0, 1, 2, 3, 4])
    ] + [
        {"text": str(value), "bbox": [36, top, 20, 12], "confidence": 0.99}
        for value, top in zip([0, 2, 4, 6], [398, 298, 198, 98])
    ]


def test_extract_line_series_returns_trace_and_marker_sources(tmp_path, monkeypatch):
    png_bytes, _ = line_chart()
    chart_path = tmp_path / "trace-lines.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert data["orientation"] == "upright"
    assert data["evidence"]["coordinate_system"] == "cartesian_2d"
    assert data["evidence"]["frame"]["coordinate_system"] == "cartesian_2d"
    assert "center_px" not in data["evidence"]["frame"]
    assert data["plot_frame"]["polygon_px"]
    assert all(entry["trace"]["polyline_px"] for entry in data["series"])
    assert all(point["source"] == "marker" for entry in data["series"] for point in entry["points"])
    assert all("x" not in point and "y" not in point for entry in data["series"] for point in entry["points"])


def test_extract_line_series_associates_legend_labels(tmp_path, monkeypatch):
    png_bytes, _ = line_chart()
    chart_path = tmp_path / "legend-lines.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult(
            [
                {"text": "North", "bbox": [149, 70, 52, 20], "confidence": 0.99},
                {"text": "South", "bbox": [149, 95, 55, 20], "confidence": 0.99},
            ]
        ),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert {entry["label"] for entry in result.data["series"]} == {"North", "South"}
    assert {entry["label"] for entry in result.data["legend"]} == {"North", "South"}


def test_extract_line_series_anchors_markerless_points_to_ticks(tmp_path, monkeypatch):
    png_bytes, _ = line_chart(values_by_series={"North": (1, 3, 2, 4, 5)}, markers=False)
    chart_path = tmp_path / "markerless-lines.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult(_line_tick_snippets()),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    entry = result.data["series"][0]
    assert len(entry["trace"]["polyline_px"]) > len(entry["points"])
    assert len(entry["points"]) == 5
    assert {point["source"] for point in entry["points"]} == {"tick_sample"}
    assert all("x" in point and "y" in point for point in entry["points"])


@pytest.mark.parametrize("angle", [-4, 4])
def test_extract_line_series_preserves_rotated_trace_geometry(tmp_path, monkeypatch, angle):
    png_bytes, _ = line_chart()
    source = Image.open(BytesIO(png_bytes)).convert("RGB")
    chart_path = tmp_path / f"rotated-line-{angle}.png"
    source.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white").save(chart_path)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["orientation"] == "oblique"
    assert result.data["plot_frame"]["x_axis"]["points_px"][0] != result.data["plot_frame"]["x_axis"]["points_px"][1]
    assert all(entry["trace"]["polyline_px"] for entry in result.data["series"])
    assert result.data["plot_frame"]["x_axis"]["residual_px"] >= 0
    assert result.data["plot_frame"]["y_axis"]["residual_px"] >= 0
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (720, 480)


def test_extract_line_series_excludes_filled_bar_geometry(tmp_path, monkeypatch):
    png_bytes, _ = annotated_bar_chart()
    chart_path = tmp_path / "bars-as-lines.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["series"] == []
    assert any("filled" in warning or "line series" in warning for warning in result.data["warnings"])
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (720, 480)


def test_extract_line_series_invalid_inputs_are_bounded(tmp_path):
    missing = tmp_path / "missing-line.png"
    unreadable = tmp_path / "unreadable-line.png"
    unreadable.write_bytes(b"not an image")

    assert extract_line_series(str(missing)) == {"error": "line image could not be resolved"}
    malformed = extract_line_series(str(unreadable))
    assert malformed == {"error": "extract_line_series failed: UnidentifiedImageError"}


def test_extract_line_series_bounds_crossing_and_signed_traces(tmp_path, monkeypatch):
    png_bytes, _ = line_chart(
        values_by_series={
            "North": (-2, 2, -1, 3, 1),
            "South": (2, -1, 2, -2, 3),
        }
    )
    chart_path = tmp_path / "crossing-signed-lines.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert len(result.data["series"]) == 2
    assert all(entry["trace"]["polyline_px"] for entry in result.data["series"])
    assert all(
        point["source"] == "marker"
        and "x" not in point
        and "y" not in point
        for entry in result.data["series"]
        for point in entry["points"]
    )
    assert any("cross or overlap" in warning for warning in result.data["warnings"])


def test_extract_line_series_marks_occluded_dense_trace_as_partial(tmp_path, monkeypatch):
    png_bytes, _ = line_chart(
        values_by_series={
            "North": tuple(float(index % 4 + 1) for index in range(12)),
            "South": tuple(float((index + 2) % 5 + 1) for index in range(12)),
        },
        x_values=tuple(range(12)),
        markers=False,
    )
    image = Image.open(BytesIO(png_bytes)).convert("RGB")
    ImageDraw.Draw(image).rectangle((315, 120, 405, 370), fill="white")
    chart_path = tmp_path / "occluded-dense-lines.png"
    image.save(chart_path)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["series"]
    assert any(
        len(entry["trace"]["fragments"]) > 1 for entry in result.data["series"]
    )
    assert any("fragmented" in warning for warning in result.data["warnings"])
    assert all(
        "x" not in point and "y" not in point
        for entry in result.data["series"]
        for point in entry["points"]
    )


def test_extract_line_series_preserves_marker_evidence_for_categorical_x(tmp_path, monkeypatch):
    png_bytes, _ = line_chart()
    chart_path = tmp_path / "categorical-lines.png"
    chart_path.write_bytes(png_bytes)
    snippets = [
        {"text": label, "bbox": [left, 438, 30, 15], "confidence": 0.99}
        for left, label in zip([100, 225, 350, 475, 600], ["Jan", "Feb", "Mar", "Apr", "May"])
    ]
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: ToolResult(snippets),
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["series"]
    assert all(
        "x" not in point and "y" not in point
        for entry in result.data["series"]
        for point in entry["points"]
    )
    assert any("x-axis calibration unavailable" in warning for warning in result.data["warnings"])


def test_extract_line_series_blank_image_returns_inspectable_partial_result(tmp_path):
    blank = tmp_path / "blank-line.png"
    Image.new("RGB", (320, 200), "white").save(blank)

    result = extract_line_series(str(blank))

    assert isinstance(result, ToolResult)
    assert result.data["series"] == []
    assert result.data["warnings"]
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (320, 200)


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
    assert data["orientation"] == "upright"
    assert data["evidence"]["coordinate_system"] == "cartesian_2d"
    assert "center_px" not in data["evidence"]["frame"]
    assert data["plot_frame"]["polygon_px"]
    assert data["plot_frame"]["x_axis"]["direction"]
    assert data["plot_frame"]["y_axis"]["direction"]
    assert data["axes"]["x"]["transform"]["support"] >= 2
    assert data["axes"]["y"]["transform"]["support_span_px"] > 40
    assert "plot_area" not in data
    assert all("x" in point and "y" in point for point in data["points"])
    assert all(
        point["calibration"] == "both_axes"
        and point["geometry"]["center_px"]
        and point["series_id"]
        for point in data["points"]
    )
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


@pytest.mark.parametrize("angle", [-4, 4])
def test_extract_scatter_points_preserves_rotated_source_geometry(tmp_path, monkeypatch, angle):
    png_bytes, _ = scatter_chart()
    source = Image.open(BytesIO(png_bytes)).convert("RGB")
    chart_path = tmp_path / f"rotated-scatter-{angle}.png"
    source.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white").save(chart_path)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: ToolResult([]),
    )

    result = extract_scatter_points(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert data["orientation"] == "oblique"
    assert len(data["points"]) == 10
    assert data["plot_frame"]["x_axis"]["points_px"][0] != data["plot_frame"]["x_axis"]["points_px"][1]
    assert data["plot_frame"]["y_axis"]["points_px"][0] != data["plot_frame"]["y_axis"]["points_px"][1]
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == source.size


def test_extract_scatter_points_ids_and_partial_fields_are_stable(tmp_path, monkeypatch):
    png_bytes, _ = scatter_chart()
    chart_path = tmp_path / "stable-scatter.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: ToolResult([]),
    )

    first = extract_scatter_points(str(chart_path))
    second = extract_scatter_points(str(chart_path))

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    first_points = [(item["id"], item["x_px"], item["y_px"]) for item in first.data["points"]]
    second_points = [(item["id"], item["x_px"], item["y_px"]) for item in second.data["points"]]
    assert first_points == second_points
    assert all(item["calibration"] == "pixel_only" for item in first.data["points"])
    assert all("x" not in item and "y" not in item for item in first.data["points"])
    assert all("overlap_candidate" in item for item in first.data["points"])


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

    result = extract_scatter_points(str(missing))

    assert result == {"error": "extract_scatter_points: image could not be resolved"}
    assert str(missing) not in result["error"]


def test_extract_scatter_points_malformed_input_redacts_path(tmp_path):
    malformed = tmp_path / "malformed-scatter.png"
    malformed.write_bytes(b"not an image")

    result = extract_scatter_points(str(malformed))

    assert result == {"error": "extract_scatter_points: input is not a readable image (UnidentifiedImageError)"}
    assert str(malformed) not in result["error"]


def test_extract_pie_slices_measures_clean_sectors(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20))
    chart_path = tmp_path / "pie.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    data = result.data
    assert len(data["sectors"]) == 4
    assert [item["measure"]["ratio"] for item in data["sectors"]] == pytest.approx(
        [0.35, 0.25, 0.20, 0.20], abs=0.035
    )
    assert data["plot_region"]["radius_px"] > 100
    assert data["plot_region"]["bbox_px"]
    assert data["transform"]["kind"] == "circular_invariant"
    assert data["evidence"]["coordinate_system"] == "polar_2d"
    assert data["evidence"]["frame"]["center_px"] == data["plot_region"]["center_px"]
    assert "x_axis" not in data["evidence"]["frame"]
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
    printed = [item for item in result.data["sectors"] if "printed" in item]
    assert printed
    assert printed[0]["printed"]["value"] == 60.0
    assert printed[0]["measure"]["ratio"] != printed[0]["printed"]["value"]


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
    assert any(entry.get("association", {}).get("sector_id") for entry in result.data["legend"])
    assert {item.get("association", {}).get("label") for item in result.data["sectors"]} >= {"Alpha", "Beta"}


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
            np.ones(720, dtype=float) * 0.8,
            0.8,
        ),
    )

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["sectors"]
    assert result.data["totals"]["consistent"] is False
    assert any("totals" in warning for warning in result.data["warnings"])


def test_extract_pie_slices_blank_image_is_inspectable(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (320, 200), "white").save(blank)

    result = extract_pie_slices(str(blank))

    assert isinstance(result, ToolResult)
    assert result.data["sectors"] == []
    assert result.data["warnings"]
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == (320, 200)


def test_extract_pie_slices_preserves_geometry_after_translation_resize_and_rotation(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20), show_labels=False)
    source = Image.open(BytesIO(png_bytes)).convert("RGB")
    shifted = Image.new("RGB", (source.width + 80, source.height + 40), "white")
    shifted.paste(source, (40, 20))
    transformed = shifted.rotate(13, expand=True, fillcolor="white")
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))

    chart_path = tmp_path / "transformed-pie.png"
    transformed.save(chart_path)
    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert len(result.data["sectors"]) == 4
    assert result.data["totals"]["consistent"] is True
    assert result.data["plot_region"]["status"] == "supported"
    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert overlay.size == transformed.size


def test_extract_pie_slices_preserves_narrow_sector_evidence(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(2, 38, 30, 30), show_labels=False)
    chart_path = tmp_path / "narrow-pie.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert len(result.data["sectors"]) == 4
    assert min(item["measure"]["angle_deg"] for item in result.data["sectors"]) < 12.0
    assert all("support" in item["measure"] for item in result.data["sectors"])


def test_extract_pie_slices_keeps_external_label_association_uncertain(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(60, 40), labels=("Alpha", "Beta"), show_labels=False)
    chart_path = tmp_path / "external-label-pie.png"
    chart_path.write_bytes(png_bytes)
    snippets = [{"id": 1, "text": "Alpha", "bbox": [315, 84, 42, 16], "confidence": 0.91}]
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult(snippets))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    labels = [item["association"] for item in result.data["sectors"] if item["association"].get("label") == "Alpha"]
    assert labels
    assert labels[0]["source"] == "ocr_external"
    assert labels[0]["status"] == "candidate"


def test_extract_pie_slices_marks_donut_geometry_unsupported(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20), show_labels=False)
    image = Image.open(BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    center = (image.width // 3, image.height // 2)
    draw.ellipse((center[0] - 48, center[1] - 48, center[0] + 48, center[1] + 48), fill="white")
    chart_path = tmp_path / "donut-pie.png"
    image.save(chart_path)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert result.data["sectors"] == []
    assert result.data["plot_region"]["status"] == "unsupported"
    assert any("donut" in warning for warning in result.data["warnings"])


def test_extract_pie_slices_redacts_missing_and_malformed_paths(tmp_path):
    missing = tmp_path / "missing-pie.png"
    missing_result = extract_pie_slices(str(missing))
    assert missing_result == {"error": "extract_pie_slices: image could not be resolved"}
    assert str(missing) not in missing_result["error"]

    malformed = tmp_path / "malformed-pie.png"
    malformed.write_bytes(b"not an image")
    malformed_result = extract_pie_slices(str(malformed))
    assert malformed_result == {"error": "extract_pie_slices: input is not a readable image (UnidentifiedImageError)"}
    assert str(malformed) not in malformed_result["error"]


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
