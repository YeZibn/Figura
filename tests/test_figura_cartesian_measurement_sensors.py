from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

import figura.tools.measurements.lines as line_sensor
import figura.tools.measurements.scatter as scatter_sensor
from figura.tools.measurements.lines import measure_line_image
from figura.tools.measurements.ocr import OCRObservation, OCRSnippet
from figura.tools.measurements.scatter import measure_scatter_image


def _png(draw_chart, size: tuple[int, int] = (300, 220)) -> bytes:
    image = Image.new("RGB", size, "white")
    draw_chart(ImageDraw.Draw(image))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _axes(draw: ImageDraw.ImageDraw) -> None:
    draw.line((30, 170, 275, 170), fill="#444444", width=2)
    draw.line((30, 30, 30, 170), fill="#444444", width=2)


def test_line_sensor_preserves_fragments_and_explicit_markers(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        color = "#cc3344"
        image.line((50, 140, 100, 110), fill=color, width=2)
        image.line((115, 102, 165, 125), fill=color, width=2)
        image.line((180, 135, 260, 60), fill=color, width=2)
        for point in ((50, 140), (100, 110), (165, 125), (260, 60)):
            image.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), fill=color)

    monkeypatch.setattr(line_sensor, "recognize_text", lambda _image: OCRObservation((), True))

    result = measure_line_image(_png(draw))

    assert result["status"] == "partial"
    assert len(result["series"]) == 1
    assert len(result["series"][0]["trace"]) >= 2
    assert result["series"][0]["points"]
    assert {point["source"] for point in result["series"][0]["points"]} == {"marker"}
    assert all(point["x_value"] is None or isinstance(point["x_value"], float) for point in result["series"][0]["points"])


def test_line_sensor_samples_only_recognized_x_ticks_when_markers_are_absent(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        image.line((45, 145, 255, 55), fill="#cc3344", width=2)

    snippets = (
        OCRSnippet("x0", "Jan", (40, 174, 24, 12), 0.95),
        OCRSnippet("x1", "Feb", (140, 174, 24, 12), 0.95),
        OCRSnippet("x2", "Mar", (240, 174, 24, 12), 0.95),
    )
    monkeypatch.setattr(line_sensor, "recognize_text", lambda _image: OCRObservation(snippets, True))

    result = measure_line_image(_png(draw))

    points = result["series"][0]["points"]
    assert len(points) == 3
    assert all(point["source"] == "axis_tick_sample" for point in points)
    assert [point["x_tick_id"] for point in points] == ["x_x0", "x_x1", "x_x2"]
    assert [point["x_category_label"] for point in points] == ["Jan", "Feb", "Mar"]


def test_line_sensor_returns_calibrated_marker_coordinates(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        image.line((50, 140, 150, 100, 250, 50), fill="#cc3344", width=2)
        for point in ((50, 140), (150, 100), (250, 50)):
            image.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), fill="#cc3344")

    snippets = (
        OCRSnippet("x0", "0", (44, 174, 12, 12), 0.95),
        OCRSnippet("x5", "5", (144, 174, 12, 12), 0.95),
        OCRSnippet("x10", "10", (244, 174, 16, 12), 0.95),
        OCRSnippet("y0", "0", (11, 164, 12, 12), 0.95),
        OCRSnippet("y5", "5", (11, 94, 12, 12), 0.95),
        OCRSnippet("y10", "10", (8, 24, 16, 12), 0.95),
    )
    monkeypatch.setattr(line_sensor, "recognize_text", lambda _image: OCRObservation(snippets, True))

    result = measure_line_image(_png(draw))

    points = result["series"][0]["points"]
    assert result["status"] == "measured"
    assert all(point["x_value"] is not None and point["y_value"] is not None for point in points)


def test_line_sensor_returns_no_evidence_for_a_blank_chart(monkeypatch) -> None:
    monkeypatch.setattr(line_sensor, "recognize_text", lambda _image: OCRObservation((), False))

    result = measure_line_image(_png(lambda _image: None))

    assert result["status"] == "no_evidence"
    assert result["series"] == []


def test_line_sensor_keeps_geometry_when_axis_geometry_is_unsupported(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        image.line((30, 170, 275, 115), fill="#444444", width=2)
        image.line((30, 170, 95, 30), fill="#444444", width=2)
        image.line((50, 145, 260, 55), fill="#cc3344", width=2)

    monkeypatch.setattr(line_sensor, "recognize_text", lambda _image: OCRObservation((), False))

    result = measure_line_image(_png(draw))

    assert result["series"]
    assert result["status"] == "partial"
    assert all(point["x_value"] is None and point["y_value"] is None for series in result["series"] for point in series["points"])
    assert result["warnings"]


def test_scatter_sensor_returns_points_and_marks_visible_overlap(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        image.ellipse((74, 104, 84, 114), fill="#cc3344")
        image.ellipse((154, 74, 164, 84), fill="#cc3344")
        image.ellipse((80, 108, 90, 118), fill="#2277cc")

    snippets = (
        OCRSnippet("x0", "0", (42, 174, 12, 12), 0.95),
        OCRSnippet("x1", "5", (144, 174, 12, 12), 0.95),
        OCRSnippet("x2", "10", (246, 174, 16, 12), 0.95),
        OCRSnippet("y0", "0", (11, 164, 12, 12), 0.95),
        OCRSnippet("y5", "5", (11, 94, 12, 12), 0.95),
        OCRSnippet("y10", "10", (8, 24, 16, 12), 0.95),
    )
    monkeypatch.setattr(scatter_sensor, "recognize_text", lambda _image: OCRObservation(snippets, True))

    result = measure_scatter_image(_png(draw))

    points = [point for series in result["series"] for point in series["points"]]
    assert len(result["series"]) == 2
    assert len(points) == 3
    assert any(point["flags"] for point in points)
    assert any(point["x_value"] is not None and point["y_value"] is not None for point in points)
    assert "_bbox" not in points[0]


def test_scatter_sensor_keeps_uncalibrated_points_in_pixel_coordinates(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        image.ellipse((74, 104, 84, 114), fill="#cc3344")

    monkeypatch.setattr(scatter_sensor, "recognize_text", lambda _image: OCRObservation((), False))

    result = measure_scatter_image(_png(draw))

    point = result["series"][0]["points"][0]
    assert result["status"] == "partial"
    assert point["position_px"] == [79.0, 109.0]
    assert point["x_value"] is None
    assert point["y_value"] is None


def test_scatter_sensor_keeps_independently_calibrated_coordinates(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        image.ellipse((114, 94, 124, 104), fill="#cc3344")

    snippets = (
        OCRSnippet("x0", "0", (44, 174, 12, 12), 0.95),
        OCRSnippet("x5", "5", (144, 174, 12, 12), 0.95),
        OCRSnippet("x10", "10", (244, 174, 16, 12), 0.95),
    )
    monkeypatch.setattr(scatter_sensor, "recognize_text", lambda _image: OCRObservation(snippets, True))

    result = measure_scatter_image(_png(draw))

    point = result["series"][0]["points"][0]
    assert result["axes"]["x"]["calibration"]["calibrated"] is True
    assert point["x_value"] is not None
    assert point["y_value"] is None


def test_scatter_sensor_flags_dense_components_and_no_evidence(monkeypatch) -> None:
    def dense_chart(image: ImageDraw.ImageDraw) -> None:
        _axes(image)
        image.ellipse((110, 80, 150, 120), fill="#cc3344")

    monkeypatch.setattr(scatter_sensor, "recognize_text", lambda _image: OCRObservation((), False))
    dense = measure_scatter_image(_png(dense_chart))
    empty = measure_scatter_image(_png(lambda _image: None))

    assert {"merged", "dense"}.issubset(set(dense["series"][0]["points"][0]["flags"]))
    assert dense["status"] == "partial"
    assert empty["status"] == "no_evidence"
    assert empty["series"] == []


def test_scatter_sensor_preserves_points_for_unsupported_axis_geometry(monkeypatch) -> None:
    def draw(image: ImageDraw.ImageDraw) -> None:
        image.line((30, 170, 275, 115), fill="#444444", width=2)
        image.line((30, 170, 95, 30), fill="#444444", width=2)
        image.ellipse((145, 90, 155, 100), fill="#cc3344")

    monkeypatch.setattr(scatter_sensor, "recognize_text", lambda _image: OCRObservation((), False))

    result = measure_scatter_image(_png(draw))

    point = result["series"][0]["points"][0]
    assert result["status"] == "partial"
    assert point["position_px"] == [150.0, 95.0]
    assert point["x_value"] is None and point["y_value"] is None
    assert result["warnings"]
