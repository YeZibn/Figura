from __future__ import annotations

from copy import deepcopy
import json

from figura.agent.execution_state import _observation_content
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.records import ToolCallFact, ToolResultFact
from figura.tools import ToolOutcome
import pytest
from tests.figura_fixtures import measurement_result


def test_frozen_v2_measurement_fact_is_validated_but_not_projected_or_rewritten():
    historical = measurement_result("pie", status="measured")
    historical["schema_version"] = 2
    for field in ("coverage", "issues", "evidence", "calibrations", "value_provenance"):
        historical.pop(field)
    original = deepcopy(historical)
    call = ToolCallFact(
        response_record_id="response-1",
        call_id="legacy-measurement-call",
        tool_name="measure_chart",
        arguments_json=json.dumps({
            "source_kind": "attachment",
            "source_id": "attachment-1",
            "chart_type": "pie",
        }),
        position=0,
        registry_version="figura-web-v9",
    )
    result = ToolResultFact(
        tool_call_sequence=1,
        attempt_id="legacy-attempt",
        call_id=call.call_id,
        tool_name=call.tool_name,
        outcome=ToolOutcome.SUCCEEDED,
        result=historical,
    )

    content = _observation_content(
        call,
        result,
        frozenset({"attachment-1"}),
        frozenset(),
        {},
        (0, 1, 0),
    )

    assert content is None
    assert historical == original


def test_measurement_result_cannot_borrow_a_different_authorized_source():
    result_value = measurement_result("pie")
    result_value["source_id"] = "another-attachment"
    call = ToolCallFact(
        response_record_id="response-1",
        call_id="measurement-call",
        tool_name="measure_chart",
        arguments_json=json.dumps({
            "source_kind": "attachment",
            "source_id": "attachment-1",
            "chart_type": "pie",
        }),
        position=0,
        registry_version="figura-web-v10",
    )
    result = ToolResultFact(
        tool_call_sequence=1,
        attempt_id="attempt-1",
        call_id=call.call_id,
        tool_name=call.tool_name,
        outcome=ToolOutcome.SUCCEEDED,
        result=result_value,
    )

    with pytest.raises(RunError) as raised:
        _observation_content(call, result, frozenset({"attachment-1"}), frozenset(), {}, (0, 1, 0))

    assert raised.value.code is RunErrorCode.INTEGRITY_ERROR
