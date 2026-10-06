from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from figura.tools.measurements.visualization import render_measurement_overlay


def _png(size: tuple[int, int] = (80, 60)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format="PNG")
    return output.getvalue()


def test_measurement_overlay_is_deterministic_and_keeps_no_evidence_visible() -> None:
    source = _png()
    result = {
        "schema_version": 2,
        "chart_type": "bar",
        "image_size": {"width": 80, "height": 60},
        "status": "no_evidence",
        "warnings": ["no chart geometry was detected"],
        "observations": {
            "orientation": "unknown", "mode": "unknown", "axes": {},
            "baseline_px": None, "baseline_value": None, "bars": [], "series": [],
        },
    }

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
