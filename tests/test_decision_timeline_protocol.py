from __future__ import annotations

import json
from pathlib import Path

from chartagent.decision_timeline import enrich_event_payload


FIXTURE = Path(__file__).parent / "fixtures" / "decision_timeline_test4.json"


def test_test4_replay_reconstructs_closed_units_and_collection_lineage():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    events = [
        enrich_event_payload(
            item["kind"],
            item["payload"],
            run_id=fixture["run_id"],
            sequence=item["sequence"],
        )
        for item in fixture["events"]
    ]

    measurement_ids = {
        event["unit_id"]
        for event in events[:4]
    }
    assert measurement_ids == {"measurement:matt-test4"}
    assert all(event["unit_type"] == "measurement" for event in events[:4])

    generation_events = events[4:7]
    assert {event["unit_id"] for event in generation_events} == {"generation:candidate-test4"}
    assert all(event["unit_type"] == "generation" for event in generation_events)

    review_events = [
        event
        for item, event in zip(fixture["events"], events)
        if item["kind"].startswith("review_")
    ]
    assert {event["unit_id"] for event in review_events} == {
        "review:review-test4",
        "review:review-test4-retry",
    }
    assert {event["parent_unit_id"] for event in review_events} == {"review:collection:collection-test4"}
    assert {event["unit_type"] for event in review_events} == {"review"}

    repair_measurement_events = events[11:15]
    assert {event["unit_id"] for event in repair_measurement_events} == {"measurement:matt-test4-repair"}
    assert repair_measurement_events[0]["next_action"]["required"] is True

    retry_generation_events = events[15:18]
    assert {event["unit_id"] for event in retry_generation_events} == {"generation:candidate-test4-retry"}
    assert all(event["unit_type"] == "generation" for event in retry_generation_events)

    publication = events[-1]
    assert publication["unit_id"] == "publication:candidate-test4-retry"
    assert publication["parent_unit_id"] == "review:review-test4-retry"
    assert publication["phase"] == "publish"


def test_test4_replay_is_idempotent_for_repeated_snapshot_and_safe_for_legacy_event():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["events"][2]
    first = enrich_event_payload(
        source["kind"], source["payload"], run_id=fixture["run_id"], sequence=source["sequence"]
    )
    replay = enrich_event_payload(
        source["kind"], first, run_id=fixture["run_id"], sequence=source["sequence"]
    )
    assert replay == first

    legacy = enrich_event_payload(
        "run_failed",
        {"code": "history_gap"},
        run_id=fixture["run_id"],
        sequence=99,
    )
    assert legacy == {"code": "history_gap"}
