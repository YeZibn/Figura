from __future__ import annotations

from chartagent.decision_timeline import enrich_event_payload


def test_measurement_call_and_result_share_one_canonical_tool_unit():
    call = enrich_event_payload(
        "tool_call",
        {
            "unit_id": "measurement:call_1",
            "unit_type": "measurement",
            "phase": "action",
            "actor": "tool",
            "role": "action",
            "call_id": "call_1",
            "tool_name": "measure_bars",
            "state": "running",
            "transition_id": "measurement:call_1:started",
            "arguments": {"attachment_id": "att_source", "panel_id": "panel_bars"},
        },
        run_id="run_measurement",
        sequence=1,
    )
    result = enrich_event_payload(
        "tool_result",
        {
            "unit_id": "measurement:call_1",
            "unit_type": "measurement",
            "phase": "action",
            "actor": "tool",
            "role": "action",
            "call_id": "call_1",
            "tool_name": "measure_bars",
            "state": "completed",
            "status": "success",
            "transition_id": "measurement:call_1:completed",
            "result": {
                "measurement": {
                    "status": "partial",
                    "reference": {"session_id": "ms_1", "attempt_id": "matt_1"},
                    "evidence": {"refs": [{"ref": "B1"}]},
                }
            },
        },
        run_id="run_measurement",
        sequence=2,
    )

    assert call["unit_id"] == result["unit_id"] == "measurement:call_1"
    assert call["call_id"] == result["call_id"] == "call_1"
    assert call["phase"] == result["phase"] == "action"
    assert result["result"]["measurement"]["evidence"]["refs"] == [{"ref": "B1"}]
    assert "next_action" not in call
    assert "next_action" not in result


def test_tool_result_enrichment_is_idempotent():
    payload = {
        "unit_id": "measurement:call_2",
        "unit_type": "measurement",
        "phase": "action",
        "actor": "tool",
        "role": "action",
        "call_id": "call_2",
        "tool_name": "extract_line_series",
        "status": "success",
        "state": "completed",
        "transition_id": "measurement:call_2:completed",
        "result": {"measurement": {"status": "complete", "evidence": {"refs": []}}},
    }
    first = enrich_event_payload("tool_result", payload, run_id="run_1", sequence=3)
    replay = enrich_event_payload("tool_result", first, run_id="run_1", sequence=3)

    assert replay == first
