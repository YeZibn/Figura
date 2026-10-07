from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from figura.tools.measurements.contracts import measurement_counts, validate_measurement_result
from figura.tools.measurements.visualization import render_measurement_overlay
from tests.figura_fixtures import measurement_result


def _png(size: tuple[int, int] = (80, 60)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format="PNG")
    return output.getvalue()


def _family_result(chart_type: str) -> dict[str, object]:
    result = measurement_result(chart_type, source_kind="panel", source_id="panel-17", status="partial")
    result["image_size"] = {"width": 80, "height": 60}
    observations = result["observations"]
    assert isinstance(observations, dict)
    bounds = {"x": 20, "y": 30, "width": 10, "height": 8}
    series = {"id": "series-1", "color": "#3572a5", "label": "样例", "label_confidence": 0.9}

    if chart_type == "bar":
        observations.update({"series": [series], "bars": [{
            "id": "bar-1", "bounds_px": bounds,
            "polygon_px": [[20, 30], [30, 30], [30, 50], [20, 50]],
            "category_id": "category-1", "category_label": "A", "series_id": "series-1",
            "pixel_length_px": 20, "value": None,
        }]})
    elif chart_type == "line":
        observations["series"] = [{**series, "segments_px": [[[5, 40], [20, 30]]], "points": [{
            "position_px": [20, 30], "x_value": None, "y_value": None,
            "point_source": "marker", "category_id": "category-1", "category_label": "A",
        }]}]
    elif chart_type == "scatter":
        observations["series"] = [{**series, "points": [{
            "center_px": [25, 34], "radius_px": 4, "x_value": None, "y_value": None,
            "series_id": "series-1", "flags": ["overlap"],
        }]}]
    elif chart_type == "pie":
        observations.update({"center_px": [40, 30], "outer_radius_px": 15, "inner_radius_px": 5,
                             "sectors": [{"start_angle_deg": 0, "sweep_angle_deg": 120, "ratio": None,
                                          "label": "A", "color": "#3572a5"}]})
    elif chart_type == "area":
        observations["series"] = [{**series, "segments": [{
            "upper_boundary_px": [[10, 30], [30, 24]], "lower_boundary_px": [[10, 50], [30, 50]],
            "upper_values": [None, None], "lower_values": [None, None], "samples": [{
                "position_px": [20, 27], "lower_position_px": [20, 50], "category_id": "category-1",
                "category_label": "A", "x_value": None, "upper_value": None,
                "lower_value": None, "series_value": None,
            }],
        }]}]
    elif chart_type == "histogram":
        observations["bins"] = [{"bounds_px": bounds, "interval_start": None, "interval_end": None, "value": None}]
    elif chart_type == "box_plot":
        observations["groups"] = [{
            "id": "group-1", "label": "A", "bounds_px": bounds,
            "lower_whisker_px": [25, 50], "q1_px": [25, 42], "median_px": [25, 38],
            "q3_px": [25, 34], "upper_whisker_px": [25, 28],
            "lower_whisker": None, "q1": None, "median": None, "q3": None,
            "upper_whisker": None, "outliers": [],
        }]
    elif chart_type == "radar":
        observations.update({
            "center_px": [40, 30],
            "spokes": [
                {"dimension_id": "dimension-1", "label": "A", "angle_deg": 0, "endpoint_px": [40, 10]},
                {"dimension_id": "dimension-2", "label": "B", "angle_deg": 120, "endpoint_px": [58, 40]},
            ],
            "series": [{**series, "vertices": [
                {"dimension_id": "dimension-1", "position_px": [40, 20], "value": None},
                {"dimension_id": "dimension-2", "position_px": None, "value": None},
            ]}],
        })
    elif chart_type == "heatmap":
        observations.update({"row_labels": ["R1"], "column_labels": ["C1"], "cells": [{
            "row_id": "row-1", "column_id": "column-1", "bounds_px": bounds,
            "color": "#3572a5", "value": None,
        }]})
    elif chart_type == "treemap":
        observations["nodes"] = [{
            "id": "node-1", "parent_id": None, "label": "A", "bounds_px": bounds,
            "value": None, "area_ratio": None, "role": "leaf",
            "area_ratio_basis": "root_plot", "area_ratio_parent_id": None,
        }]
    else:
        raise AssertionError(chart_type)

    evidence = [
        {"id": "geometry-1", "kind": "geometry", "bounds_px": bounds,
         "points_px": [[20, 30]], "ratio_denominator": None},
        {"id": "ocr-1", "kind": "ocr", "bounds_px": {"x": 2, "y": 24, "width": 12, "height": 6},
         "text": "axis tick", "confidence": 0.9},
    ]
    result["evidence"] = evidence
    coverage = result["coverage"]
    assert isinstance(coverage, dict)
    coverage["scope_kind"] = "scoped"
    coverage["requested_scope"] = {"include": [[[0, 0], [1000, 0], [1000, 1000], [0, 1000]]]}
    coverage["detected_counts"] = measurement_counts(chart_type, observations)
    return result


@pytest.mark.parametrize(
    "chart_type",
    ["bar", "line", "scatter", "pie", "area", "histogram", "box_plot", "radar", "heatmap", "treemap"],
)
def test_overlay_uses_validated_v3_panel_observations_and_evidence(chart_type: str) -> None:
    result = _family_result(chart_type)
    assert validate_measurement_result(result) is None

    rendered = render_measurement_overlay(_png(), result, "measure_chart")
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (80, 60)
        assert image.convert("RGB").getpixel((20, 30)) == (255, 140, 0)


def test_measurement_overlay_is_deterministic_and_keeps_no_evidence_visible() -> None:
    result = measurement_result("bar", source_kind="panel", source_id="panel-17", status="no_evidence")
    result["image_size"] = {"width": 80, "height": 60}
    source = _png()

    first = render_measurement_overlay(source, result, "measure_chart")
    second = render_measurement_overlay(source, result, "measure_chart")

    assert first == second
    assert first != source
    with Image.open(BytesIO(first)) as rendered:
        assert rendered.size == (80, 60)
        assert rendered.convert("RGB").getpixel((0, 0)) != (255, 255, 255)


def test_measurement_overlay_rejects_a_source_that_does_not_match_result_size() -> None:
    with pytest.raises(ValueError):
        render_measurement_overlay(
            _png((20, 20)),
            {"image_size": {"width": 30, "height": 30}, "chart_type": "line", "observations": {}},
            "measure_chart",
        )
