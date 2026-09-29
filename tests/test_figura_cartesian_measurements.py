from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

import figura.tools.measurements.ocr as ocr
from figura.tools.measurements.cartesian import (
    calibrated_axis_value,
    fit_axis_calibration,
    observe_cartesian_axes,
    parse_numeric_text,
    associate_legend_labels,
)
from figura.tools.measurements.ocr import OCRSnippet, recognize_text


def test_ocr_returns_bounded_text_boxes_and_confidence(monkeypatch) -> None:
    fake_engine = lambda _image: SimpleNamespace(
        boxes=[[(8, 9), (34, 9), (34, 21), (8, 21)]],
        txts=[" 12.5 "],
        scores=[0.93],
    )
    monkeypatch.setattr(ocr, "_engine", fake_engine)

    result = recognize_text(np.zeros((40, 60, 3), dtype=np.uint8))

    assert result.available is True
    assert result.snippets == (OCRSnippet("text_1", "12.5", (8, 9, 26, 12), 0.93),)


def test_ocr_failure_is_missing_evidence_not_a_sensor_exception(monkeypatch) -> None:
    class BrokenEngine:
        def __call__(self, _image):
            raise RuntimeError("private engine detail")

    monkeypatch.setattr(ocr, "_engine", BrokenEngine())

    result = recognize_text(np.zeros((40, 60, 3), dtype=np.uint8))

    assert result.available is False
    assert result.snippets == ()


def test_ocr_bounds_candidate_count_and_text_length(monkeypatch) -> None:
    fake_engine = lambda _image: SimpleNamespace(
        boxes=[[(1, 1), (8, 1), (8, 8), (1, 8)]] * 513,
        txts=["x" * 200] * 513,
        scores=[0.9] * 513,
    )
    monkeypatch.setattr(ocr, "_engine", fake_engine)

    result = recognize_text(np.zeros((40, 60, 3), dtype=np.uint8))

    assert result.available is True
    assert result.truncated is True
    assert len(result.snippets) == 512
    assert len(result.snippets[0].text) == 128


def test_ocr_drops_boxes_that_cross_or_leave_the_observation_scope(monkeypatch) -> None:
    fake_engine = lambda _image: SimpleNamespace(
        boxes=[
            [(4, 4), (14, 4), (14, 14), (4, 14)],
            [(24, 4), (34, 4), (34, 14), (24, 14)],
        ],
        txts=["inside", "crossing"],
        scores=[0.9, 0.8],
    )
    monkeypatch.setattr(ocr, "_engine", fake_engine)
    mask = np.zeros((40, 60), dtype=bool)
    mask[:, :30] = True

    result = recognize_text(np.zeros((40, 60, 3), dtype=np.uint8), mask)

    assert [snippet.text for snippet in result.snippets] == ["inside"]


def test_numeric_tick_parser_accepts_common_numeric_labels_only() -> None:
    assert parse_numeric_text("−1,250.5%") == -1250.5
    assert parse_numeric_text("$2,000") == 2000
    assert parse_numeric_text("Q1") is None
    assert parse_numeric_text("1e6") is None


def test_calibration_projects_ticks_along_a_tilted_axis() -> None:
    axis_points = [[20.0, 180.0], [220.0, 160.0]]
    ticks = [
        {"value": 0.0, "point_px": axis_points[0]},
        {"value": 5.0, "point_px": [120.0, 170.0]},
        {"value": 10.0, "point_px": axis_points[1]},
    ]

    calibration = fit_axis_calibration(ticks, axis_points)
    value = calibrated_axis_value([170.0, 165.0], {
        "points_px": axis_points,
        "calibration": calibration,
    })

    assert calibration is not None
    assert calibration["calibrated"] is True
    assert value == 7.5


def test_calibration_rejects_short_support_and_conflicting_tick_values() -> None:
    axis_points = [[0.0, 100.0], [200.0, 80.0]]
    short_ticks = [
        {"value": 0.0, "point_px": [0.0, 100.0]},
        {"value": 10.0, "point_px": [30.0, 97.0]},
    ]
    conflicting_ticks = [
        {"value": 0.0, "point_px": [0.0, 100.0]},
        {"value": 5.0, "point_px": [100.0, 90.0]},
        {"value": 30.0, "point_px": [200.0, 80.0]},
    ]

    short = fit_axis_calibration(short_ticks, axis_points)
    conflict = fit_axis_calibration(conflicting_ticks, axis_points)

    assert short is not None and short["calibrated"] is False
    assert conflict is not None and conflict["calibrated"] is False


def test_detects_horizontal_axis_and_associates_numeric_ticks() -> None:
    image = Image.new("RGB", (300, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.line((40, 170, 270, 170), fill="#444444", width=2)
    rgb = np.asarray(image)
    snippets = (
        OCRSnippet("text_1", "0", (38, 176, 8, 12), 0.96),
        OCRSnippet("text_2", "5", (146, 176, 8, 12), 0.95),
        OCRSnippet("text_3", "10", (262, 176, 16, 12), 0.94),
        OCRSnippet("text_4", "Month", (137, 202, 40, 12), 0.88),
    )

    axes = observe_cartesian_axes(rgb, snippets, {"x": 40, "y": 20, "width": 230, "height": 150})

    assert axes["x"]["points_px"] is not None
    assert axes["x"]["kind"] == "numeric"
    assert len(axes["x"]["ticks"]) == 3
    assert axes["x"]["calibration"]["calibrated"] is True
    assert axes["x"]["label_text"] == "Month"


def test_axis_without_ocr_candidates_has_no_calibration() -> None:
    image = Image.new("RGB", (120, 100), "white")
    axes = observe_cartesian_axes(np.asarray(image), (), None)

    assert axes["x"]["kind"] == "unknown"
    assert axes["x"]["ticks"] == []
    assert axes["x"]["calibration"] is None


def test_categorical_ticks_are_preserved_without_numeric_calibration() -> None:
    image = Image.new("RGB", (300, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.line((40, 170, 270, 170), fill="#444444", width=2)
    snippets = (
        OCRSnippet("jan", "Jan", (66, 178, 24, 12), 0.94),
        OCRSnippet("feb", "Feb", (166, 178, 24, 12), 0.92),
        OCRSnippet("mar", "Mar", (250, 178, 24, 12), 0.90),
    )

    axis = observe_cartesian_axes(np.asarray(image), snippets, {"x": 40, "y": 20, "width": 230, "height": 150})["x"]

    assert axis["kind"] == "categorical"
    assert [tick["text"] for tick in axis["ticks"]] == ["Jan", "Feb", "Mar"]
    assert all(tick["value"] is None for tick in axis["ticks"])
    assert axis["calibration"] is None


def test_ocr_text_is_associated_with_adjacent_color_legend_swatch() -> None:
    image = Image.new("RGB", (140, 60), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 22, 34, 34), fill="#cc3344")
    snippets = (OCRSnippet("legend", "Revenue", (40, 22, 60, 12), 0.9),)

    labels = associate_legend_labels(np.asarray(image), snippets, ((204, 51, 68),))

    assert labels["#cc3344"] == ("Revenue", 0.9)
