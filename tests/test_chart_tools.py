"""Tests for deterministic chart-understanding tools."""

from io import BytesIO
import json
from pathlib import Path

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
    compare_layout_with_frame,
)
from chartagent.tools.chart.observation.layout import context_frame, validate_layout_hint
from chartagent.tools.chart.observation.line import extract_line_series
from chartagent.tools.chart.observation.ocr import extract_text
from chartagent.tools.chart.observation.pie import extract_pie_slices
from chartagent.tools.chart.observation.scatter import extract_scatter_points
from chartagent.tools.chart.specification import (
    ASSEMBLE_SPEC,
    CHART_SPEC_SCHEMA,
    FIGURE_CHILD_INPUT_SCHEMA,
    POINT_SCHEMA,
    assemble_spec,
    validate_spec,
)
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


def _side_by_side_panel(png_bytes: bytes, path: Path) -> list[int]:
    """Place identical charts in adjacent panels and return the right scope."""
    with Image.open(BytesIO(png_bytes)) as source:
        chart = source.convert("RGB")
    canvas = Image.new("RGB", (chart.width * 2, chart.height), "white")
    canvas.paste(chart, (0, 0))
    canvas.paste(chart, (chart.width, 0))
    canvas.save(path)
    return [chart.width, 0, chart.width, chart.height]


def _panel_scope(bbox: list[int], coordinate_system: str = "cartesian_2d") -> dict:
    return {
        "source_attachment_id": "att_dashboard",
        "coordinate_system": coordinate_system,
        "analysis_scope": {"bbox_px": bbox, "source_origin_px": bbox[:2]},
        "validation": {"status": "accepted", "accepted_for_analysis": True},
    }


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


def test_layout_conflict_keeps_bounded_pixel_geometry_diagnostics():
    rgb = np.zeros((120, 220, 3), dtype=np.uint8)
    frame = {
        "bbox_px": [20, 20, 180, 80],
        "x_axis": {"points_px": [[20, 100], [200, 100]]},
        "y_axis": {"points_px": [[20, 100], [20, 20]]},
    }
    layout_context = {
        "measurement_frame": {"bbox_px": [100, 8, 80, 50]},
        "axes": {
            "x": {"points_px": [[100, 58], [180, 58]]},
            "y": {"points_px": [[100, 58], [100, 8]]},
        },
    }
    comparison = compare_layout_with_frame(frame, layout_context)

    assert comparison is not None
    assert comparison["status"] == "conflict"
    assert {item["field"] for item in comparison["conflicts"]} == {
        "measurement_frame",
        "x_axis",
        "y_axis",
    }
    warnings: list[str] = []
    evidence = build_common_evidence(
        rgb,
        coordinate_system="cartesian_2d",
        frame=frame,
        warnings=warnings,
        layout_context=layout_context,
    )
    assert evidence["conflicts"] == comparison["conflicts"]
    assert warnings == ["layout hint conflicts with independent pixel geometry"]


def test_partial_layout_frame_is_advisory_only():
    rgb = np.full((100, 200, 3), 255, dtype=np.uint8)
    context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "cartesian_2d",
            "confidence": 0.9,
            "measurement_frame": {"bbox_norm": [0.1, 0.1, 0.8, 0.76]},
        },
    )

    assert context["validation"]["status"] == "partial"
    assert context["measurement_frame"] is not None
    assert context_frame(context) is None


@pytest.mark.parametrize(
    ("chart_factory", "sensor", "extract_text_path"),
    [
        (line_chart, extract_line_series, "chartagent.tools.chart.observation.line.extract_text"),
        (scatter_chart, extract_scatter_points, "chartagent.tools.chart.observation.scatter.extract_text"),
    ],
)
def test_cartesian_sensors_retain_independent_geometry_with_accepted_layout(
    tmp_path,
    monkeypatch,
    chart_factory,
    sensor,
    extract_text_path,
):
    chart_path = tmp_path / f"{sensor.__name__}-layout.png"
    chart_path.write_bytes(chart_factory()[0])
    monkeypatch.setattr(extract_text_path, lambda _path: ToolResult([]))
    with Image.open(chart_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "cartesian_2d",
            "orientation": "upright",
            "confidence": 0.95,
            "measurement_frame": {"bbox_norm": [0.10, 0.10, 0.80, 0.76]},
            "axes": {
                "x": {"points_norm": [[0.10, 0.86], [0.90, 0.86]], "confidence": 0.9},
                "y": {"points_norm": [[0.10, 0.86], [0.10, 0.10]], "confidence": 0.9},
            },
        },
    )
    assert context["validation"]["status"] == "accepted"

    result = sensor(str(chart_path), context)

    assert isinstance(result, ToolResult)
    independent = result.data["plot_frame"]["independent_geometry"]
    assert independent is not None
    assert independent["x_axis"] or independent["y_axis"]


@pytest.mark.parametrize(
    ("chart_factory", "sensor", "region_kind"),
    [
        (annotated_bar_chart, measure_bars, "baseline"),
        (line_chart, extract_line_series, "series"),
        (pie_chart, extract_pie_slices, "sectors"),
        (scatter_chart, extract_scatter_points, "points"),
    ],
)
def test_chart_sensors_preserve_targeted_focus_contract(tmp_path, chart_factory, sensor, region_kind):
    chart_path = tmp_path / f"{sensor.__name__}-target.png"
    chart_path.write_bytes(chart_factory()[0])
    with Image.open(chart_path) as image:
        source_size = [image.width, image.height]
    target = {
        "target_id": f"{region_kind}-focus",
        "panel_id": "panel_chart",
        "parent_attempt_id": "matt_parent",
        "region_kind": region_kind,
        "fields": [region_kind],
        "bbox_source_px": [20, 20, max(1, source_size[0] - 40), max(1, source_size[1] - 40)],
        "source_image_size": source_size,
    }
    result = sensor(str(chart_path), measurement_target=target)
    assert isinstance(result, ToolResult)
    assert result.data["measurement_target"]["bbox_source_px"] == target["bbox_source_px"]
    assert result.data["focus"]["requested"] is True
    assert result.data["focus"]["region_px"] == target["bbox_source_px"]


def test_generic_series_association_consumes_text_evidence_without_ocr():
    entries = [{"id": "series_1", "color": "#ff0000", "geometry": {"bbox_px": [8, 10, 12, 8]}}]
    associated = associate_series_labels(
        entries,
        [{"text": "Revenue", "bbox": [26, 9, 48, 12]}],
    )
    assert associated[0]["label"] == "Revenue"
    assert associated[0]["association"]["source"] == "text_evidence"
    assert associated[0]["association"]["status"] == "candidate"


def test_model_layout_context_is_normalized_and_validated():
    rgb = np.full((100, 200, 3), 255, dtype=np.uint8)
    rgb[84:87, 20:181] = [225, 65, 65]
    context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "cartesian_2d",
            "orientation": "upright",
            "confidence": 0.96,
            "measurement_frame": {
                "bbox_norm": [0.10, 0.10, 0.80, 0.76],
                "confidence": 0.96,
            },
            "axes": {
                "x": {"points_norm": [[0.10, 0.84], [0.90, 0.84]], "confidence": 0.9},
                "y": {"points_norm": [[0.10, 0.84], [0.10, 0.10]], "confidence": 0.9},
            },
            "annotation_regions": {
                "x_ticks": {"bbox_norm": [0.08, 0.86, 0.84, 0.12], "confidence": 0.8},
            },
        },
        palette=[np.asarray([225, 65, 65])],
    )
    assert context["validation"]["status"] == "accepted"
    assert context["validation"]["accepted_for_measurement"] is True
    assert context["measurement_frame"]["bbox_px"] == [20, 10, 160, 76]
    assert context["axes"]["x"]["points_px"][0] == [20.0, 84.0]
    assert context["annotation_regions"]["x_ticks"]["bbox_px"] == [16, 86, 168, 12]


def test_invalid_model_layout_context_is_rejected_without_fabricated_frame():
    rgb = np.full((80, 120, 3), 255, dtype=np.uint8)
    context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "cartesian_2d",
            "confidence": 0.9,
            "measurement_frame": {"bbox_norm": [0.8, 0.8, 0.4, 0.4]},
        },
    )
    assert context["validation"]["status"] == "rejected"
    assert context["measurement_frame"] is None
    assert context["validation"]["accepted_for_measurement"] is False


def test_model_layout_aliases_are_normalized_to_shared_fields():
    rgb = np.full((100, 200, 3), 255, dtype=np.uint8)
    rgb[83:86, 20:181] = [225, 65, 65]
    context = validate_layout_hint(
        rgb,
        {
            "plot_area": [0.10, 0.10, 0.80, 0.76],
            "x_axis": [0.10, 0.84, 0.80, 0.10],
            "y_axis": [0.02, 0.10, 0.08, 0.74],
            "title": [0.30, 0.01, 0.40, 0.05],
            "legend": [0.30, 0.06, 0.40, 0.04],
            "confidence": 0.9,
        },
        palette=[np.asarray([225, 65, 65])],
        chart_type="line",
    )
    assert context["measurement_frame"]["bbox_norm"] == [0.1, 0.1, 0.8, 0.76]
    assert context["axes"]["x"]["points_norm"] == [[0.1, 0.84], [0.9, 0.84]]
    assert context["axes"]["y"]["points_norm"] == [[0.1, 0.1], [0.1, 0.84]]
    assert context["annotation_regions"]["legend"]["bbox_norm"] == [0.3, 0.06, 0.4, 0.04]
    assert context["validation"]["status"] == "accepted"


def test_flat_model_axis_endpoints_are_normalized():
    rgb = np.full((100, 200, 3), 255, dtype=np.uint8)
    rgb[84:87, 20:181] = [225, 65, 65]
    context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "cartesian_2d",
            "confidence": 0.96,
            "measurement_frame": {"bbox_norm": [0.10, 0.10, 0.80, 0.76]},
            "axes": {
                "x": {"points_norm": [0.10, 0.84, 0.90, 0.84]},
                "y": {"points_norm": [0.10, 0.84, 0.10, 0.10]},
            },
        },
        palette=[np.asarray([225, 65, 65])],
        chart_type="line",
    )
    assert context["axes"]["x"]["points_norm"] == [[0.1, 0.84], [0.9, 0.84]]
    assert context["axes"]["y"]["points_norm"] == [[0.1, 0.84], [0.1, 0.1]]
    assert context["validation"]["status"] == "accepted"


def test_real_rotated_label_line_chart_uses_true_axes_and_anchor_sampling():
    image_path = Path(__file__).parents[1] / "photo" / "股东人数与前复权股价折线图.png"
    if not image_path.is_file():
        pytest.skip("real chart attachment is not present")
    result = extract_line_series(str(image_path))
    assert isinstance(result, ToolResult)
    data = result.data
    assert data["orientation"] == "upright"
    assert abs(data["plot_frame"]["y_axis"]["slope"]) < 0.02
    assert data["x_anchors"]
    assert all(point["source"] == "tick_sample" for series in data["series"] for point in series["points"])
    assert not any("斜" in warning for warning in data["warnings"])


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


def test_measure_bars_scope_excludes_adjacent_panel(tmp_path):
    png_bytes, _ = annotated_bar_chart()
    chart_path = tmp_path / "adjacent-bars.png"
    scope = _side_by_side_panel(png_bytes, chart_path)

    result = measure_bars(str(chart_path), _panel_scope(scope))

    assert isinstance(result, ToolResult)
    assert result.data["bars"]
    assert all(bar["geometry"]["bbox_px"][0] >= scope[0] for bar in result.data["bars"])
    assert result.data["evidence"]["layout_context"]["analysis_scope"]["bbox_px"] == scope


def test_measure_bars_keeps_independent_baseline_when_layout_is_offset(
    annotated_chart_path,
):
    with Image.open(annotated_chart_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    layout_context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "cartesian_2d",
            "orientation": "upright",
            "confidence": 0.95,
            "measurement_frame": {
                "bbox_norm": [0.30, 0.12, 0.60, 0.68],
                "confidence": 0.95,
            },
        },
    )
    assert layout_context["validation"]["status"] == "partial"

    result = measure_bars(str(annotated_chart_path), layout_context)

    assert isinstance(result, ToolResult)
    assert len(result.data["bars"]) == 3
    assert result.data["baseline"]["points_px"] == [[115, 426], [623, 426]]
    assert any(
        conflict["field"] == "measurement_frame"
        for conflict in result.data["evidence"]["conflicts"]
    )
    assert "layout hint conflicts with independent pixel geometry" in result.data["warnings"]


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


def test_extract_line_series_scope_excludes_adjacent_panel(tmp_path, monkeypatch):
    png_bytes, _ = line_chart()
    chart_path = tmp_path / "adjacent-lines.png"
    scope = _side_by_side_panel(png_bytes, chart_path)
    monkeypatch.setattr("chartagent.tools.chart.observation.line.extract_text", lambda _path: ToolResult([]))

    result = extract_line_series(str(chart_path), _panel_scope(scope))

    assert isinstance(result, ToolResult)
    assert result.data["series"]
    assert all(
        point["x_px"] >= scope[0]
        for series in result.data["series"]
        for point in series["points"]
    )
    assert result.data["evidence"]["layout_context"]["analysis_scope"]["bbox_px"] == scope


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


def test_extract_line_series_preserves_ocr_calibration_conflict(tmp_path, monkeypatch):
    png_bytes, _ = line_chart()
    chart_path = tmp_path / "conflicting-line-ticks.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line._ocr_snippets",
        lambda _path: [
            {"text": "0", "bbox": [45, 90, 12, 12], "confidence": 0.95},
            {"text": "50", "bbox": [45, 210, 16, 12], "confidence": 0.95},
            {"text": "0", "bbox": [45, 330, 12, 12], "confidence": 0.95},
        ],
    )

    result = extract_line_series(str(chart_path))

    assert isinstance(result, ToolResult)
    conflicts = result.data["evidence"]["conflicts"]
    assert any(conflict["field"] == "y_axis_calibration" for conflict in conflicts)
    assert "OCR y-axis tick candidates conflict with pixel calibration" in result.data["warnings"]
    assert result.data["axes"]["y"]["ticks"]


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


def test_extract_scatter_points_scope_excludes_adjacent_panel(tmp_path, monkeypatch):
    png_bytes, _ = scatter_chart()
    chart_path = tmp_path / "adjacent-scatter.png"
    scope = _side_by_side_panel(png_bytes, chart_path)
    monkeypatch.setattr("chartagent.tools.chart.observation.scatter.extract_text", lambda _path: ToolResult([]))

    result = extract_scatter_points(str(chart_path), _panel_scope(scope))

    assert isinstance(result, ToolResult)
    assert result.data["points"]
    assert all(point["x_px"] >= scope[0] for point in result.data["points"])
    assert result.data["evidence"]["layout_context"]["analysis_scope"]["bbox_px"] == scope


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


def test_extract_pie_slices_scope_excludes_adjacent_panel(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20))
    chart_path = tmp_path / "adjacent-pies.png"
    scope = _side_by_side_panel(png_bytes, chart_path)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))

    result = extract_pie_slices(str(chart_path), _panel_scope(scope, "polar_2d"))

    assert isinstance(result, ToolResult)
    assert result.data["sectors"]
    assert result.data["plot_region"]["bbox_px"][0] >= scope[0]
    assert result.data["evidence"]["layout_context"]["analysis_scope"]["bbox_px"] == scope


def test_extract_pie_slices_surfaces_independent_center_conflict(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20))
    chart_path = tmp_path / "conflicting-pie-layout.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: ToolResult([]))
    with Image.open(chart_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    layout_context = validate_layout_hint(
        rgb,
        {
            "coordinate_system": "polar_2d",
            "confidence": 0.95,
            "measurement_frame": {"bbox_norm": [0.02, 0.05, 0.75, 0.90]},
            "polar_region": {
                "center_norm": [0.70, 0.40],
                "radius_norm": 0.08,
                "confidence": 0.95,
            },
        },
        chart_type="pie",
    )
    assert layout_context["validation"]["status"] == "accepted"

    result = extract_pie_slices(str(chart_path), layout_context)

    assert isinstance(result, ToolResult)
    assert len(result.data["sectors"]) == 4
    assert any(conflict["field"] == "polar_geometry" for conflict in result.data["evidence"]["conflicts"])
    assert "polar layout hint conflicts with detected circle geometry" in result.data["warnings"]


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


def test_extract_pie_slices_surfaces_ocr_ratio_conflict(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(60, 40), labels=("Alpha", "Beta"))
    chart_path = tmp_path / "conflicting-pie-value.png"
    chart_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.pie.extract_text",
        lambda _path: ToolResult(
            [{"id": 1, "text": "99%", "bbox": [250, 190, 32, 16], "confidence": 0.98}]
        ),
    )

    result = extract_pie_slices(str(chart_path))

    assert isinstance(result, ToolResult)
    assert any(conflict["field"].endswith("_ratio") for conflict in result.data["evidence"]["conflicts"])
    assert any("OCR printed ratio conflicts with geometry" in warning for warning in result.data["warnings"])


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
        ("pie", [{"category": "A", "value": 0.6}, {"category": "B", "value": 0.4}]),
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


def test_assemble_spec_preserves_line_category_evidence():
    result = assemble_spec(
        "line",
        [
            {"x": 1, "y": 420, "series": "Orders"},
            {"x": 2, "y": 480, "series": "Orders"},
            {"x": 3, "y": 520, "series": "Orders"},
        ],
        x_label="Month",
        y_label="Orders",
        x_categories=["Jan", "Feb", "Mar"],
    )

    assert "error" not in result
    assert result["axes"]["x"]["label"] == "Month"
    assert result["axes"]["x"]["categories"] == ["Jan", "Feb", "Mar"]
    assert validate_spec(result) == {"ok": True, "issues": []}


def test_assemble_spec_keeps_figure_child_category_domains_isolated():
    figure = {
        "figure_id": "dashboard",
        "source": {"attachment_id": "att_dashboard", "panel_id": "panel_dashboard"},
        "layout": {"type": "grid", "columns": 2},
        "coverage": {
            "source_series": ["Orders", "Revenue"],
            "represented_series": ["Orders", "Revenue"],
            "omitted_series": [],
            "status": "complete",
        },
        "charts": [
            {
                "chart_id": "orders",
                "chart_type": "line",
                "x_label": "Month",
                "y_label": "Orders",
                "x_categories": ["Jan", "Feb"],
                "points": [{"x": 1, "y": 10}, {"x": 2, "y": 12}],
            },
            {
                "chart_id": "revenue",
                "chart_type": "line",
                "x_label": "Quarter",
                "y_label": "Revenue",
                "x_categories": ["Q1", "Q2"],
                "points": [{"x": 1, "y": 20}, {"x": 2, "y": 25}],
            },
        ],
    }

    result = assemble_spec(figure=figure)

    assert result["charts"][0]["spec"]["axes"]["x"]["categories"] == ["Jan", "Feb"]
    assert result["charts"][1]["spec"]["axes"]["x"]["categories"] == ["Q1", "Q2"]


def test_assemble_spec_without_line_categories_keeps_numeric_axis():
    result = assemble_spec(
        "line",
        [{"x": 1, "y": 10}, {"x": 2, "y": 12}],
        x_label="Index",
        y_label="Value",
    )

    assert "error" not in result
    assert result["axes"]["x"]["categories"] is None


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


def test_assemble_spec_failure_is_atomic_and_structured():
    result = assemble_spec(
        "line",
        [{"category": "A", "value": 1}],
        x_label="X",
        y_label="Y",
    )

    assert "error" in result
    assert "metadata" not in result
    assert "dataset" not in result
    assert result["issues"]
    assert result["validation"]["status"] == "failed"
    assert result["validation"]["checks"]["semantic"] == "failed"
    assert all(set(issue) == {"location", "message"} for issue in result["issues"])


def _figure_input(*, panel_id: str = "panel_1", include_q2: bool = True) -> dict:
    charts = [
        {
            "chart_id": "q1",
            "chart_type": "pie",
            "title": "Q1 2024",
            "points": [
                {"category": "North America", "value": 0.9},
                {"category": "Europe", "value": 0.5},
            ],
        },
    ]
    if include_q2:
        charts.append(
            {
                "chart_id": "q2",
                "chart_type": "pie",
                "title": "Q2 2024",
                "points": [
                    {"category": "North America", "value": 1.1},
                    {"category": "Europe", "value": 0.6},
                ],
            }
        )
    return {
        "figure_id": "revenue-by-region",
        "source": {"attachment_id": "att_dashboard", "panel_id": panel_id},
        "layout": {"type": "grid", "columns": 2 if include_q2 else 1},
        "coverage": {
            "source_series": ["Q1 2024", "Q2 2024"],
            "represented_series": ["Q1 2024", "Q2 2024"] if include_q2 else ["Q1 2024"],
            "omitted_series": [] if include_q2 else ["Q2 2024"],
            "status": "complete" if include_q2 else "incomplete",
        },
        "charts": charts,
    }


def test_assemble_spec_builds_one_same_source_figure_from_multiple_children():
    result = assemble_spec(figure=_figure_input())

    assert result["kind"] == "chart_figure"
    assert result["source"] == {"attachment_id": "att_dashboard", "panel_id": "panel_1"}
    assert [item["chart_id"] for item in result["charts"]] == ["q1", "q2"]
    assert result["coverage"]["status"] == "complete"
    assert validate_spec(result) == {"ok": True, "issues": []}


def test_assemble_spec_builds_collection_without_merging_different_panels():
    first = _figure_input(panel_id="panel_1")
    second = _figure_input(panel_id="panel_2")
    second["figure_id"] = "orders"
    result = assemble_spec(figures=[first, second], collection_id="dashboard-result")

    assert result["kind"] == "chart_spec_collection"
    assert [figure["source"]["panel_id"] for figure in result["figures"]] == ["panel_1", "panel_2"]
    assert validate_spec(result) == {"ok": True, "issues": []}


def test_assemble_spec_rejects_incomplete_coverage_atomically():
    result = assemble_spec(figure=_figure_input(include_q2=False))

    assert result["error"] == "ChartSpec figure assembly failed"
    assert result["issues"]
    assert any(issue["location"].endswith("coverage.status") for issue in result["issues"])
    assert "charts" not in result


def test_assemble_spec_rejects_invalid_child_with_located_issue():
    figure = _figure_input()
    figure["charts"][1]["points"] = [{"category": "North America"}]

    result = assemble_spec(figure=figure)

    assert result["error"] == "ChartSpec figure assembly failed"
    assert any("charts[1]" in issue["location"] for issue in result["issues"])
    assert "charts" not in result


def test_chart_spec_schema_is_shared_by_assembly_and_rendering():
    from chartagent.tools.chart.rendering import RENDER_CHART

    assembly_point_schema = ASSEMBLE_SPEC.parameters["properties"]["points"]["items"]
    render_spec_schema = RENDER_CHART.parameters["properties"]["spec"]
    render_point_schema = render_spec_schema["properties"]["dataset"]["items"]

    assert assembly_point_schema["properties"] == POINT_SCHEMA["properties"]
    assert render_point_schema["properties"] == POINT_SCHEMA["properties"]
    assert render_point_schema["oneOf"] == POINT_SCHEMA["oneOf"]
    assert render_spec_schema["properties"]["metadata"]["properties"]["chart_type"] == CHART_SPEC_SCHEMA["properties"]["metadata"]["properties"]["chart_type"]
    assert "x_categories" in ASSEMBLE_SPEC.parameters["properties"]
    assert "x_categories" in FIGURE_CHILD_INPUT_SCHEMA["properties"]


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
