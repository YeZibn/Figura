from __future__ import annotations

from io import BytesIO
import math

import pytest
from PIL import Image, ImageDraw

from figura.charts.chartspec.models import ChartType
from figura.tools.measurements.contracts import MeasurementResult, PreparedMeasurementImage, validate_measurement_result
from figura.tools.measurements.family_adapters import current_chart_family_adapters
from figura.tools.measurements.observation_scope import decode_scoped_image


def _chart_image(chart_type: ChartType, *, donut: bool = False) -> bytes:
    image = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(image)
    if chart_type is ChartType.BAR:
        draw.line((35, 145, 215, 145), fill="#222222", width=2)
        for x, top in ((60, 92), (110, 62), (160, 38)):
            draw.rectangle((x, top, x + 24, 144), fill="#3366cc")
    elif chart_type is ChartType.LINE:
        draw.line((35, 145, 215, 145), fill="#222222", width=2)
        draw.line((35, 30, 35, 145), fill="#222222", width=2)
        draw.line((45, 122, 85, 92, 125, 104, 165, 54, 205, 42), fill="#3366cc", width=4)
        for x, y in ((45, 122), (85, 92), (125, 104), (165, 54), (205, 42)):
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#3366cc")
    elif chart_type is ChartType.SCATTER:
        draw.line((35, 145, 215, 145), fill="#222222", width=2)
        draw.line((35, 30, 35, 145), fill="#222222", width=2)
        for x, y in ((55, 120), (90, 92), (132, 108), (165, 60), (202, 42)):
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#3366cc")
    elif chart_type is ChartType.AREA:
        draw.line((35, 145, 215, 145), fill="#222222", width=2)
        draw.line((35, 30, 35, 145), fill="#222222", width=2)
        draw.polygon(
            [(35, 145), (35, 122), (70, 104), (105, 113), (145, 72), (180, 58), (215, 35), (215, 145)],
            fill="#8ecae6",
        )
    elif chart_type is ChartType.HISTOGRAM:
        draw.line((35, 145, 215, 145), fill="#222222", width=2)
        draw.line((35, 30, 35, 145), fill="#222222", width=2)
        for x, top in ((45, 106), (84, 71), (123, 44), (162, 85)):
            draw.rectangle((x, top, x + 35, 144), fill="#3366cc")
            draw.line((x + 35, top, x + 35, 144), fill="white", width=2)
    elif chart_type is ChartType.BOX_PLOT:
        draw.line((35, 145, 215, 145), fill="#222222", width=2)
        draw.line((35, 30, 35, 145), fill="#222222", width=2)
        for center_x, top, bottom, median_y in ((70, 72, 112, 92), (125, 60, 105, 82), (180, 80, 122, 101)):
            draw.line((center_x, 45, center_x, top), fill="#222222", width=2)
            draw.line((center_x - 8, 45, center_x + 8, 45), fill="#222222", width=2)
            draw.rectangle((center_x - 12, top, center_x + 12, bottom), outline="#222222", width=2)
            draw.line((center_x - 12, median_y, center_x + 12, median_y), fill="#222222", width=2)
            draw.line((center_x, bottom, center_x, 138), fill="#222222", width=2)
            draw.line((center_x - 8, 138, center_x + 8, 138), fill="#222222", width=2)
        draw.ellipse((65, 36, 75, 42), fill="#222222")
    elif chart_type is ChartType.RADAR:
        center = (120, 90)
        for radius in (16, 32, 48, 64):
            points = [
                (round(center[0] + radius * math.sin(math.radians(angle))),
                 round(center[1] - radius * math.cos(math.radians(angle))))
                for angle in range(0, 360, 60)
            ]
            draw.polygon(points, outline="#777777", width=1)
        spokes = [
            (round(center[0] + 64 * math.sin(math.radians(angle))),
             round(center[1] - 64 * math.cos(math.radians(angle))))
            for angle in range(0, 360, 60)
        ]
        for endpoint in spokes:
            draw.line((*center, *endpoint), fill="#777777", width=1)
        values = [
            (round(center[0] + radius * math.sin(math.radians(angle))),
             round(center[1] - radius * math.cos(math.radians(angle))))
            for angle, radius in zip(range(0, 360, 60), (42, 34, 50, 38, 45, 28), strict=True)
        ]
        draw.polygon(values, outline="#3366cc", fill="#8ecae6")
    elif chart_type is ChartType.HEATMAP:
        colors = [
            ["#e53935", "#fb8c00", "#fdd835", "#43a047"],
            ["#1e88e5", "#8e24aa", "#e53935", "#fb8c00"],
            ["#fdd835", "#43a047", "#1e88e5", "#8e24aa"],
        ]
        for row_index, row in enumerate(colors):
            for column_index, color in enumerate(row):
                left, top = 38 + column_index * 42, 24 + row_index * 36
                draw.rectangle((left, top, left + 36, top + 30), fill=color)
    elif chart_type is ChartType.TREEMAP:
        for bounds, color in (
            ((38, 24, 112, 86), "#e53935"),
            ((116, 24, 202, 62), "#43a047"),
            ((116, 66, 157, 146), "#1e88e5"),
            ((161, 66, 202, 146), "#8e24aa"),
            ((38, 90, 112, 146), "#fb8c00"),
        ):
            draw.rectangle(bounds, fill=color)
    else:
        for start, end, color in ((0, 120, "#e53935"), (120, 240, "#43a047"), (240, 360, "#1e88e5")):
            draw.pieslice((60, 20, 180, 140), start, end, fill=color)
        if donut:
            draw.ellipse((99, 59, 141, 101), fill="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _prepared(chart_type: ChartType, *, donut: bool = False) -> PreparedMeasurementImage:
    content = _chart_image(chart_type, donut=donut)
    rgb, mask = decode_scoped_image(content)
    return PreparedMeasurementImage("attachment", "attachment-1", "attachment_px", 240, 180, rgb, mask)


@pytest.mark.parametrize(
    "chart_type",
    [
        ChartType.BAR,
        ChartType.LINE,
        ChartType.SCATTER,
        ChartType.PIE,
        ChartType.AREA,
        ChartType.HISTOGRAM,
        ChartType.BOX_PLOT,
        ChartType.RADAR,
        ChartType.HEATMAP,
        ChartType.TREEMAP,
    ],
)
def test_current_family_adapters_emit_a_valid_supported_result(chart_type: ChartType) -> None:
    sensor = current_chart_family_adapters()[chart_type]
    sensor_result = sensor(_prepared(chart_type))
    result = MeasurementResult(
        chart_type=chart_type,
        source_kind="attachment",
        source_id="attachment-1",
        image_size=(240, 180),
        coordinate_system="attachment_px",
        status=sensor_result.status,
        plot_area_px=sensor_result.plot_area_px,
        observations=sensor_result.observations,
        confidence=sensor_result.confidence,
        warnings=sensor_result.warnings,
        truncated=sensor_result.truncated,
    )

    from figura.tools.measurements.support import build_axis_support
    assert validate_measurement_result(build_axis_support(result.to_dict())) is None
    if chart_type is ChartType.BOX_PLOT:
        groups = sensor_result.observations["groups"]
        assert len(groups) == 3
        assert all(group["median_px"] is not None for group in groups)
        assert all(group["median"] is None for group in groups)
    elif chart_type is ChartType.RADAR:
        observations = sensor_result.observations
        assert len(observations["spokes"]) == 6
        assert observations["radial_grid"]
        assert observations["series"]
        assert all(vertex["value"] is None for item in observations["series"] for vertex in item["vertices"])


def test_area_sensor_keeps_filled_boundaries_and_line_only_geometry_is_not_promoted() -> None:
    sensors = current_chart_family_adapters()
    area_result = sensors[ChartType.AREA](_prepared(ChartType.AREA))
    line_rgb = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(line_rgb)
    draw.line((35, 145, 215, 145), fill="#222222", width=2)
    draw.line((35, 30, 35, 145), fill="#222222", width=2)
    draw.line((45, 122, 85, 92, 125, 104, 165, 54, 205, 42), fill="#3366cc", width=4)
    buffer = BytesIO()
    line_rgb.save(buffer, format="PNG")
    line_pixels, line_mask = decode_scoped_image(buffer.getvalue())
    line_image = PreparedMeasurementImage("attachment", "line-only", "attachment_px", 240, 180, line_pixels, line_mask)
    line_result = sensors[ChartType.AREA](line_image)

    assert area_result.observations["series"]
    assert area_result.observations["series"][0]["segments"][0]["upper_boundary_px"]
    assert line_result.status == "unsupported"


def test_histogram_sensor_preserves_bin_geometry_and_nulls_uncalibrated_intervals() -> None:
    sensor_result = current_chart_family_adapters()[ChartType.HISTOGRAM](_prepared(ChartType.HISTOGRAM))

    assert sensor_result.observations["bins"]
    assert all(item["interval_start"] is None or item["interval_end"] is None for item in sensor_result.observations["bins"])


def test_area_sensor_marks_a_truncated_boundary_as_partial() -> None:
    image = Image.new("RGB", (700, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.line((35, 145, 665, 145), fill="#222222", width=2)
    draw.line((35, 30, 35, 145), fill="#222222", width=2)
    draw.polygon([(35, 145), (35, 110), (250, 85), (470, 60), (665, 35), (665, 145)], fill="#8ecae6")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    rgb, mask = decode_scoped_image(buffer.getvalue())
    sensor_result = current_chart_family_adapters()[ChartType.AREA](
        PreparedMeasurementImage("attachment", "wide-area", "attachment_px", 700, 180, rgb, mask)
    )

    assert sensor_result.truncated is True
    assert sensor_result.status == "partial"
    assert len(sensor_result.observations["series"][0]["segments"][0]["upper_boundary_px"]) == 512


def test_pie_adapter_preserves_donut_hole_as_inner_radius() -> None:
    sensor_result = current_chart_family_adapters()[ChartType.PIE](_prepared(ChartType.PIE, donut=True))

    assert sensor_result.status in {"measured", "partial"}
    assert sensor_result.observations["inner_radius_px"] is not None
    assert sensor_result.observations["outer_radius_px"] > sensor_result.observations["inner_radius_px"]


def test_heatmap_sensor_groups_visible_color_regions_into_a_grid() -> None:
    sensor_result = current_chart_family_adapters()[ChartType.HEATMAP](_prepared(ChartType.HEATMAP))
    observations = sensor_result.observations

    assert sensor_result.status == "measured"
    assert len(observations["cells"]) == 12
    assert len(observations["row_labels"]) == 3
    assert len(observations["column_labels"]) == 4
    assert all(cell["value"] is None and cell["color"] is not None for cell in observations["cells"])


def test_treemap_sensor_preserves_visible_rectangle_area_without_inventing_values() -> None:
    sensor_result = current_chart_family_adapters()[ChartType.TREEMAP](_prepared(ChartType.TREEMAP))
    nodes = sensor_result.observations["nodes"]

    assert sensor_result.status == "measured"
    assert len(nodes) == 5
    assert all(node["parent_id"] is None for node in nodes)
    assert all(node["value"] is None and node["area_ratio"] is not None for node in nodes)
    assert all(node["area_ratio"] > 0 for node in nodes)
