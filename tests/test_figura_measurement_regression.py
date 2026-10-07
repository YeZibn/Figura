from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from scripts.evaluate_figura_measurements import compare
from scripts.generate_figura_measurement_fixtures import FIXTURES, generate


def _bar_result(*, label="Q1", value=8):
    return {"schema_version":2,"chart_type":"bar","observations":{
        "series":[{"id":"random","label":"Series"}],
        "bars":[{"bounds_px":{"x":10,"y":20,"width":20,"height":40},
                 "series_id":"random","category_label":label,"value":value}]}}


def _reference():
    return {"chart_type":"bar","plot_area_px":[0,0,100,100],"geometry_tolerance_px":2,"numeric_tolerance":{"y":0.5},
            "targets":[{"id":"stable","position_px":[20,40],"series_label":"Series","label":"Q1","values":{"value":8}}]}


def test_matching_does_not_depend_on_object_ids_and_checks_associations():
    assert compare(_reference(),_bar_result())["passed"]
    wrong = compare(_reference(),_bar_result(label="Q2"))
    assert wrong["matched_objects"]==1
    assert not wrong["passed"]
    assert wrong["association_errors"]


def test_missing_values_and_numeric_errors_are_separate():
    missing = compare(_reference(),_bar_result(value=None))
    incorrect = compare(_reference(),_bar_result(value=12))
    assert len(missing["numeric_missing"])==1 and not missing["numeric_errors"]
    assert len(incorrect["numeric_errors"])==1 and not incorrect["numeric_missing"]


def test_one_prediction_cannot_satisfy_two_targets():
    reference=_reference()
    reference["targets"].append({**reference["targets"][0],"id":"second"})
    result=compare(reference,_bar_result())
    assert result["matched_objects"]==1 and result["missing_objects"]==1


def test_fixtures_have_exact_original_image_identity():
    original=json.loads((FIXTURES/"original_images.json").read_text())
    manifest=json.loads((FIXTURES/"manifest.json").read_text())
    hashes={i["image"]:i["sha256"] for i in original["images"]}
    assert len(manifest["cases"])==13
    assert sum(len(c["charts"]) for c in manifest["cases"])==20
    for case in manifest["cases"]:
        content=(FIXTURES/"images"/case["image"]).read_bytes()
        assert sha256(content).hexdigest()==case["sha256"]==hashes[case["image"]]
        assert (FIXTURES/case["source"]).exists()


def test_generation_reproduces_all_reference_targets_and_hashes():
    before=(FIXTURES/"manifest.json").read_text()
    generated=generate()
    assert json.loads(before)==generated
