"""Numeric evidence integrity and invocation-local observation reuse."""
from copy import deepcopy

import numpy as np

from figura.tools.measurements.contracts import validate_measurement_result
from figura.tools.measurements.support import build_axis_support, validate_support
from figura.tools.measurements.context import shared_observation
from figura.tools.measurements.scales import color_reading
from figura.tools.measurements import ocr
from tests.figura_fixtures import measurement_result


def ratio_result():
    result = measurement_result("pie", status="measured")
    result["observations"]["sectors"] = [{"start_angle_deg": 0, "sweep_angle_deg": 90,
        "ratio": .25, "label": None, "color": "#ff0000"}]
    return build_axis_support(result)


def test_ratio_retains_local_support_and_builder_is_idempotent():
    result = ratio_result()
    assert validate_measurement_result(result) is None
    assert build_axis_support(result) == result
    assert result["evidence"][0]["ratio_denominator"] == 360


def test_ratio_value_must_match_observed_sector_sweep():
    result = ratio_result()
    result["observations"]["sectors"][0]["sweep_angle_deg"] = 180
    assert validate_support(result)[0] == "unsupported_value"


def test_axis_calibration_support_ids_must_match_readable_ticks():
    result = measurement_result("bar", status="measured")
    axis = result["observations"]["axes"]["y"]
    axis["ticks"] = [
        {"id": "tick_0", "text": "0", "value": 0, "bbox_px": [1, 15, 4, 5], "point_px": [3, 20], "confidence": .9},
        {"id": "tick_1", "text": "10", "value": 10, "bbox_px": [1, 5, 8, 5], "point_px": [5, 10], "confidence": .9},
    ]
    axis["calibration"] = {
        "slope": 1, "intercept": 0, "residual_value": 0, "support_count": 2,
        "support_tick_ids": ["tick_0", "missing"], "support_span_px": 10,
        "confidence": .9, "calibrated": True,
    }
    assert validate_support(result)[0] == "invalid_calibration_support"


def test_nonempty_values_require_unique_resolvable_support():
    result = ratio_result()
    for mutation, code in [
        (lambda r: r.update(value_provenance=[]), "missing_value_provenance"),
        (lambda r: r["value_provenance"].append(deepcopy(r["value_provenance"][0])), "invalid_value_path"),
        (lambda r: r["value_provenance"][0].update(evidence_ids=["another_source"]), "dangling_support"),
        (lambda r: r["value_provenance"][0].update(field_path="/observations/absent"), "invalid_value_path"),
        (lambda r: r["value_provenance"][0].update(method="axis_calibration"), "unsupported_value"),
    ]:
        changed = deepcopy(result)
        mutation(changed)
        assert validate_support(changed)[0] == code


def test_derived_value_cycle_is_rejected():
    result = ratio_result()
    item = result["value_provenance"][0]
    item.update(method="derived", evidence_ids=[], input_paths=[item["field_path"]])
    assert validate_support(result)[0] == "cyclic_value_support"


def test_support_truncation_clears_number_and_retains_valid_closure():
    result = ratio_result()
    raw = measurement_result("pie", status="measured")
    raw["observations"] = deepcopy(result["observations"])
    bounded = build_axis_support(raw, support_limit=0)
    assert bounded["status"] == "partial" and bounded["truncated"]
    assert bounded["observations"]["sectors"][0]["ratio"] is None
    assert bounded["issues"] and not bounded["evidence"]
    assert validate_measurement_result(bounded) is None


def test_runtime_payload_budget_truncates_readings_with_closed_support():
    raw = measurement_result("pie", status="measured")
    raw["observations"]["sectors"] = [
        {"start_angle_deg": index * 9, "sweep_angle_deg": 9, "ratio": .025,
         "label": None, "color": "#336699"}
        for index in range(40)
    ]
    bounded = build_axis_support(raw, payload_limit=8000)
    retained = [sector["ratio"] for sector in bounded["observations"]["sectors"] if sector["ratio"] is not None]
    assert 0 < len(retained) < 40
    assert bounded["status"] == "partial" and bounded["truncated"]
    assert any(issue["code"] == "support_budget_truncated" for issue in bounded["issues"])
    assert validate_measurement_result(bounded) is None


def test_ocr_reused_only_for_exact_masked_source_within_one_invocation(monkeypatch):
    calls = []
    monkeypatch.setattr(ocr, "_recognize_text", lambda rgb, mask: calls.append(rgb) or ocr.OCRObservation((), True))
    rgb = np.zeros((20, 20, 3), dtype=np.uint8)
    mask = np.ones((20, 20), dtype=bool)
    with shared_observation(rgb, mask):
        assert ocr.recognize_text(rgb, mask) is ocr.recognize_text(rgb, mask)
        ocr.recognize_text(rgb.copy(), mask)
    with shared_observation(rgb, mask):
        ocr.recognize_text(rgb, mask)
    assert len(calls) == 3


def test_color_scale_interpolates_observed_rgb_profile_and_rejects_distant_duplicate():
    calibration = {"parameters": {"slope": 2, "intercept": 1, "samples": [
        {"position_px": [0, 0], "color": "#000000"},
        {"position_px": [0, 1], "color": "#101010"},
        {"position_px": [0, 2], "color": "#202020"},
    ]}}
    assert color_reading("#181818", calibration) == 4.0

    ambiguous = {"parameters": {"slope": 1, "intercept": 0, "samples": [
        {"position_px": [0, 0], "color": "#000000"},
        {"position_px": [0, 1], "color": "#202020"},
        {"position_px": [0, 10], "color": "#000000"},
    ]}}
    assert color_reading("#000000", ambiguous) is None
