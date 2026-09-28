from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

import figura.tools.measurements.bars as bar_sensor
from figura.tools.measurements.bars import measure_bar_image


def _png(draw_chart, size: tuple[int, int] = (300, 200)) -> bytes:
    image = Image.new("RGB", size, "white")
    draw_chart(ImageDraw.Draw(image))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _vertical_chart(draw: ImageDraw.ImageDraw) -> None:
    draw.line((30, 170, 270, 170), fill="black", width=2)
    draw.rectangle((60, 90, 95, 169), fill="#3366cc")
    draw.rectangle((130, 50, 165, 169), fill="#3366cc")
    draw.rectangle((200, 110, 235, 169), fill="#3366cc")


def test_measures_vertical_bars_in_source_pixel_coordinates() -> None:
    result = measure_bar_image(_png(_vertical_chart))

    assert result["image_size"] == {"width": 300, "height": 200}
    assert result["status"] == "measured"
    assert result["orientation"] == "vertical"
    assert result["bar_mode"] == "single"
    assert [bar["geometry"]["bbox_px"] for bar in result["bars"]] == [
        [60, 90, 36, 80], [130, 50, 36, 120], [200, 110, 36, 60]
    ]
    assert [bar["measure"]["value_length_px"] for bar in result["bars"]] == [80.0, 120.0, 60.0]
    assert [bar["measure"]["ratio_to_shortest"] for bar in result["bars"]] == [1.333333, 2.0, 1.0]
    assert result["bars"][0]["geometry"]["polygon_px"] == [
        [60, 90], [96, 90], [96, 170], [60, 170]
    ]


def test_measures_horizontal_bars_and_finds_the_vertical_baseline() -> None:
    def draw(draw_context: ImageDraw.ImageDraw) -> None:
        draw_context.line((40, 20, 40, 180), fill="black", width=2)
        draw_context.rectangle((41, 35, 180, 59), fill="#3366cc")
        draw_context.rectangle((41, 85, 240, 109), fill="#3366cc")
        draw_context.rectangle((41, 135, 120, 159), fill="#3366cc")

    result = measure_bar_image(_png(draw))

    assert result["status"] == "measured"
    assert result["orientation"] == "horizontal"
    assert [bar["measure"]["value_length_px"] for bar in result["bars"]] == [140.0, 200.0, 80.0]


def test_distinguishes_grouped_and_stacked_bar_modes() -> None:
    def grouped(draw: ImageDraw.ImageDraw) -> None:
        draw.line((20, 180, 280, 180), fill="black", width=2)
        draw.rectangle((40, 100, 57, 179), fill="#cc4433")
        draw.rectangle((62, 75, 79, 179), fill="#3366cc")
        draw.rectangle((155, 60, 172, 179), fill="#cc4433")
        draw.rectangle((177, 110, 194, 179), fill="#3366cc")

    def stacked(draw: ImageDraw.ImageDraw) -> None:
        draw.line((20, 180, 280, 180), fill="black", width=2)
        draw.rectangle((95, 110, 145, 179), fill="#cc4433")
        draw.rectangle((95, 50, 145, 109), fill="#3366cc")

    grouped_result = measure_bar_image(_png(grouped))
    stacked_result = measure_bar_image(_png(stacked))

    assert grouped_result["bar_mode"] == "grouped"
    assert [bar["category_index"] for bar in grouped_result["bars"]] == [1, 1, 2, 2]
    assert stacked_result["bar_mode"] == "stacked"
    assert {bar["category_index"] for bar in stacked_result["bars"]} == {1}
    assert all("stack" in bar for bar in stacked_result["bars"])
    assert {bar["stack"]["segment_index"] for bar in stacked_result["bars"]} == {1, 2}


def test_reports_oblique_baseline_orientation() -> None:
    def draw(draw_context: ImageDraw.ImageDraw) -> None:
        draw_context.line((30, 175, 270, 151), fill="black", width=2)
        draw_context.polygon(((55, 105), (90, 105), (90, 169), (55, 173)), fill="#3366cc")
        draw_context.polygon(((130, 75), (165, 75), (165, 161), (130, 165)), fill="#3366cc")
        draw_context.polygon(((205, 110), (240, 110), (240, 153), (205, 156)), fill="#3366cc")

    result = measure_bar_image(_png(draw))

    assert result["status"] == "measured"
    assert result["orientation"] == "oblique"
    assert result["baseline"]["axis"] == "y"
    assert result["baseline"]["slope"] < 0


def test_keeps_geometry_when_baseline_is_missing_or_unsupported() -> None:
    single_bar = _png(lambda draw: draw.rectangle((100, 45, 145, 160), fill="#3366cc"))

    def perspective(draw: ImageDraw.ImageDraw) -> None:
        draw.polygon(((110, 55), (139, 55), (165, 165), (85, 165)), fill="#3366cc")

    uncertain = measure_bar_image(single_bar)
    unsupported = measure_bar_image(_png(perspective))

    assert uncertain["status"] == "partial"
    assert uncertain["baseline"] is None
    assert uncertain["bars"][0]["measure"] == {"value_length_px": None, "ratio_to_shortest": None}
    assert unsupported["status"] == "unsupported"
    assert unsupported["bars"]
    assert unsupported["bars"][0]["measure"]["value_length_px"] is None


def test_nulls_measurements_when_baseline_confidence_is_uncertain(monkeypatch) -> None:
    monkeypatch.setattr(bar_sensor, "_fit_baseline", lambda *_args: {"confidence": 0.55})

    result = measure_bar_image(_png(_vertical_chart))

    assert result["status"] == "partial"
    assert result["baseline"] is None
    assert all(bar["measure"]["value_length_px"] is None for bar in result["bars"])
    assert all(bar["measure"]["ratio_to_shortest"] is None for bar in result["bars"])


def test_returns_empty_observation_for_readable_image_without_bars() -> None:
    result = measure_bar_image(_png(lambda draw: draw.text((80, 80), "no chart", fill="black")))

    assert result["status"] == "no_evidence"
    assert result["bars"] == []
    assert result["series"] == []
    assert result["plot_area_px"] is None
    assert result["baseline"] is None
    assert result["warnings"]
