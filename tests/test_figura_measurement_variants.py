from __future__ import annotations

from io import BytesIO

import pytest
import numpy as np
from PIL import Image, ImageDraw

import figura.tools.measurements.bars as bar_sensor
import figura.tools.measurements.heatmap as heatmap_sensor
import figura.tools.measurements.scatter as scatter_sensor
from figura.tools.measurements.cartesian import calibrated_axis_value, fit_axis_calibration, observe_cartesian_axes
from figura.tools.measurements.contracts import PreparedMeasurementImage
from figura.tools.measurements.layout import legend_regions
from figura.tools.measurements.observation_scope import decode_scoped_image
from figura.tools.measurements.ocr import OCRObservation, OCRSnippet


def _png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    ("color", "alpha", "scale"),
    [
        ((51, 102, 204), 255, 1.0),
        ((204, 68, 51), 192, 1.0),
        ((17, 119, 85), 128, 1.5),
        ((142, 36, 170), 96, 0.75),
    ],
)
def test_bar_geometry_survives_color_alpha_and_resolution_variants(monkeypatch, color, alpha, scale) -> None:
    width, height = round(300 * scale), round(200 * scale)
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    point = lambda x, y: (round(x * scale), round(y * scale))
    draw.line((*point(30, 170), *point(270, 170)), fill=(68, 68, 68, 255), width=max(1, round(2 * scale)))
    for x, top in ((60, 90), (130, 50), (200, 110)):
        draw.rectangle((*point(x, top), *point(x + 35, 169)), fill=(*color, alpha))

    rgb, visible = decode_scoped_image(_png(image))
    monkeypatch.setattr(bar_sensor, "recognize_text", lambda *_args: OCRObservation((), True))
    result = bar_sensor.measure_bar_pixels(rgb, visible)

    assert len(result["bars"]) == 3
    ratios = [item["measure"]["ratio_to_shortest"] for item in result["bars"]]
    assert ratios == pytest.approx([4 / 3, 2.0, 1.0], rel=0.08)


def test_heatmap_keeps_adjacent_cells_separate_when_their_color_repeats(monkeypatch) -> None:
    from figura.tools.measurements import ocr

    image = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(image)
    for top in (35, 64, 93):
        for left in (45, 80, 115, 150):
            draw.rectangle((left, top, left + 27, top + 21), fill="#3366cc")
    rgb, visible = decode_scoped_image(_png(image))
    monkeypatch.setattr(heatmap_sensor, "recognize_text", lambda *_args: OCRObservation((), True))
    monkeypatch.setattr(ocr, "recognize_region", lambda *_args, **_kwargs: ())

    result = heatmap_sensor.measure_heatmap(
        PreparedMeasurementImage("attachment", "same-color-grid", "attachment_px", 240, 180, rgb, visible)
    )

    assert result.status == "measured"
    assert len(result.observations["cells"]) == 12
    assert {cell["color"] for cell in result.observations["cells"]} == {"#3366cc"}


def test_scatter_sensor_keeps_a_two_by_two_pixel_data_mark(monkeypatch) -> None:
    image = Image.new("RGB", (300, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.line((30, 170, 275, 170), fill="#444444", width=2)
    draw.line((30, 30, 30, 170), fill="#444444", width=2)
    draw.rectangle((120, 80, 121, 81), fill="#cc3344")
    rgb, visible = decode_scoped_image(_png(image))
    monkeypatch.setattr(scatter_sensor, "recognize_text", lambda *_args: OCRObservation((), True))

    result = scatter_sensor.measure_scatter_pixels(rgb, visible)

    points = [point for series in result["series"] for point in series["points"]]
    assert len(points) == 1
    assert points[0]["position_px"] == [120.5, 80.5]


def test_aligned_legend_swatches_inside_plot_bounds_are_identified_as_legend() -> None:
    image = Image.new("RGB", (240, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((190, 30, 197, 37), fill="#3366cc")
    draw.rectangle((190, 50, 197, 57), fill="#cc4433")
    snippets = (
        OCRSnippet("legend_a", "North", (202, 28, 32, 12), 0.95),
        OCRSnippet("legend_b", "South", (202, 48, 32, 12), 0.95),
    )

    regions = legend_regions(
        np.asarray(image), snippets, ((51, 102, 204), (204, 68, 51))
    )

    assert len(regions) == 2
    assert all(180 <= x < 210 and 20 <= y < 70 for x, y, _width, _height in regions)


@pytest.mark.parametrize("font_box", [(8, 10), (14, 18), (20, 24)])
def test_numeric_axis_association_survives_ocr_text_box_size_variants(font_box) -> None:
    image = Image.new("RGB", (300, 220), "white")
    ImageDraw.Draw(image).line((40, 170, 270, 170), fill="#444444", width=2)
    snippets = tuple(
        OCRSnippet(f"tick_{index}", text, (round(center - text_width / 2), 176, text_width, font_box[1]), 0.95)
        for index, (text, center) in enumerate((("0", 40), ("5", 155), ("10", 270)))
        for text_width in (font_box[0] if text == "0" else round(font_box[0] * 1.5),)
    )

    axis = observe_cartesian_axes(
        np.asarray(image), snippets, {"x": 40, "y": 20, "width": 230, "height": 150}
    )["x"]

    assert len(axis["ticks"]) == 3
    assert axis["calibration"]["calibrated"] is True


def test_reversed_nonzero_axis_keeps_its_signed_calibration() -> None:
    axis_points = [[40.0, 30.0], [40.0, 170.0]]
    ticks = [
        {"value": 80.0, "point_px": [40.0, 30.0]},
        {"value": 50.0, "point_px": [40.0, 100.0]},
        {"value": 20.0, "point_px": [40.0, 170.0]},
    ]

    calibration = fit_axis_calibration(ticks, axis_points)
    value = calibrated_axis_value([40.0, 100.0], {"points_px": axis_points, "calibration": calibration})

    assert calibration is not None and calibration["calibrated"] is True
    assert calibration["slope"] < 0
    assert value == pytest.approx(50.0)
