from __future__ import annotations

import json

import pytest

from figura.agent.repeated_observations import project_repeated_observations
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import (
    ExecutionCheckpoint,
    Run,
    RunStatus,
    ToolFactKind,
)
from figura.runtime.records import (
    RunState,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolResultFact,
)
from figura.shared.media import ToolImageAttachment
from figura.shared.resource_refs import ToolResourceRef
from figura.shared.source_refs import ToolResultSourceRef
from figura.tools.contracts import ReplayEffect, ToolExecutionError, ToolOutcome

_UNSET = object()


def _state(calls: list[dict[str, object]], *, run_id: str = "run-current") -> RunState:
    facts: list[ToolExecutionFact] = []
    for index, call in enumerate(calls, start=1):
        call_id = f"call-{index}"
        attempt_id = f"attempt-{index}"
        tool_name = call.get("tool_name", "measure_chart")
        args_json = call.get("arguments_json")
        if args_json is None:
            args_json = json.dumps(call.get("arguments", {}), ensure_ascii=False)
        facts.extend(
            (
                ToolExecutionFact(
                    run_id,
                    index,
                    ToolFactKind.TOOL_CALL,
                    2,
                    ToolCallFact(
                        f"response-{index}",
                        call_id,
                        str(tool_name),
                        str(args_json),
                        registry_version=str(call.get("registry_version", "registry-v1")),
                    ),
                    f"2026-11-05T00:00:0{index}Z",
                ),
                ToolExecutionFact(
                    run_id,
                    index * 3 - 1,
                    ToolFactKind.TOOL_ATTEMPT_STARTED,
                    2,
                    ToolAttemptStartedFact(
                        index,
                        call_id,
                        attempt_id,
                        1,
                        ReplayEffect.REPLAY_SAFE,
                        str(call.get("registry_version", "registry-v1")),
                    ),
                    f"2026-11-05T00:00:0{index}Z",
                ),
                ToolExecutionFact(
                    run_id,
                    index * 3,
                    ToolFactKind.TOOL_RESULT,
                    3,
                    ToolResultFact(
                        index,
                        attempt_id,
                        call_id,
                        str(tool_name),
                        call.get("outcome", ToolOutcome.SUCCEEDED),
                        result=call.get("result", {"status": "ok", "observations": []}),
                        error=call.get("error"),
                        attachments=tuple(call.get("attachments", ())),
                    ),
                    f"2026-11-05T00:00:0{index}Z",
                ),
            )
        )
    run = Run(
        run_id,
        "session-current",
        1,
        "input-current",
        RunStatus.RUNNING,
        "qwen",
        "qwen-model",
        "2026-11-05T00:00:00Z",
        "2026-11-05T00:00:00Z",
    )
    checkpoint = ExecutionCheckpoint(
        run_id,
        0,
        0,
        len(calls) * 3,
        None,
        2,
        "2026-11-05T00:00:00Z",
    )
    return RunState(run, (), checkpoint, (), tuple(facts))


def _call(
    *,
    arguments: dict[str, object] | None = None,
    arguments_json: str | None = None,
    result: object = _UNSET,
    outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    error: ToolExecutionError | None = None,
    attachments: tuple[ToolImageAttachment, ...] = (),
    tool_name: str = "measure_chart",
    registry_version: str = "registry-v1",
) -> dict[str, object]:
    value: dict[str, object] = {
        "tool_name": tool_name,
        "registry_version": registry_version,
        "result": {"status": "ok", "observations": []} if result is _UNSET else result,
        "outcome": outcome,
        "error": error,
        "attachments": attachments,
    }
    if arguments_json is not None:
        value["arguments_json"] = arguments_json
    else:
        value["arguments"] = arguments if arguments is not None else {
            "source_kind": "attachment",
            "source_id": "image-1",
            "chart_type": "bar",
        }
    return value


def _attachment(call_id: str) -> ToolImageAttachment:
    return ToolImageAttachment(
        ToolResourceRef("measurement", "run-current", call_id),
        "measurement_annotation",
        "image/png",
        1,
        1,
        1,
        "a" * 64,
    )


def test_repeated_observation_ignores_json_format_and_attachment_identity():
    calls = [
        _call(arguments_json='{"source_kind":"attachment", "source_id":"image-1", "chart_type":"bar"}',
              attachments=(_attachment("annotation-1"),)),
        _call(arguments_json=' { "chart_type" : "bar", "source_id" : "image-1", "source_kind" : "attachment" } ',
              result={"observations": [], "status": "ok"},
              attachments=(_attachment("annotation-2"),)),
    ]

    notices = project_repeated_observations(_state(calls))

    assert len(notices) == 1
    assert notices[0].tool_name == "measure_chart"
    assert notices[0].matching_call_count == 2
    assert notices[0].recent_result_refs == (
        ToolResultSourceRef("run-current", "call-1"),
        ToolResultSourceRef("run-current", "call-2"),
    )


@pytest.mark.parametrize(
    "second",
    [
        _call(arguments={"source_kind": "attachment", "source_id": "image-2", "chart_type": "bar"}),
        _call(arguments={"source_kind": "attachment", "source_id": "image-1", "chart_type": "line"}),
        _call(arguments={"source_kind": "attachment", "source_id": "image-1", "chart_type": "bar",
                         "observation_scope": {"include": [[[0, 0], [1, 0], [1, 1]]]}}),
        _call(registry_version="registry-v2"),
        _call(result={"status": "ok", "observations": [{"value": 2}]}),
    ],
)
def test_meaningfully_different_action_or_result_does_not_match(second):
    assert project_repeated_observations(
        _state([_call(), second])
    ) == ()


def test_array_order_is_part_of_action_and_observation_identity():
    arguments = {"source_kind": "attachment", "source_id": "image-1", "chart_type": "bar",
                 "observation_scope": {"include": [[[0, 0], [1, 0], [1, 1]]]}}
    reversed_arguments = {"source_kind": "attachment", "source_id": "image-1", "chart_type": "bar",
                          "observation_scope": {"include": [[[1, 1], [1, 0], [0, 0]]]}}
    assert project_repeated_observations(_state([
        _call(arguments=arguments), _call(arguments=reversed_arguments),
    ])) == ()

    first_result = {"status": "ok", "observations": [{"series": [1, 2]}]}
    second_result = {"status": "ok", "observations": [{"series": [2, 1]}]}
    assert project_repeated_observations(_state([
        _call(result=first_result), _call(result=second_result),
    ])) == ()


def test_nonconsecutive_matching_group_counts_only_latest_observation():
    a = {"status": "ok", "observations": [{"value": 1}]}
    b = {"status": "ok", "observations": [{"value": 2}]}

    assert project_repeated_observations(_state([
        _call(result=a),
        _call(tool_name="extract_text", arguments={"source_kind": "attachment", "source_id": "image-1"}),
        _call(result=a),
        _call(result=b),
    ])) == ()

    notices = project_repeated_observations(_state([
        _call(result=a),
        _call(result=b),
        _call(result=a),
    ]))
    assert len(notices) == 1
    assert notices[0].matching_call_count == 2
    assert notices[0].recent_result_refs == (
        ToolResultSourceRef("run-current", "call-1"),
        ToolResultSourceRef("run-current", "call-3"),
    )


def test_third_matching_call_updates_one_group_and_latest_references():
    notices = project_repeated_observations(_state([_call(), _call(), _call()]))

    assert len(notices) == 1
    assert notices[0].matching_call_count == 3
    assert notices[0].recent_result_refs == (
        ToolResultSourceRef("run-current", "call-2"),
        ToolResultSourceRef("run-current", "call-3"),
    )


def test_failed_or_other_run_calls_do_not_contribute():
    failed = _call(outcome=ToolOutcome.FAILED, result=None,
                   error=ToolExecutionError("measurement_failed", "观察失败。", False))
    success = _call()
    assert project_repeated_observations(_state([failed, success])) == ()
    assert project_repeated_observations(_state([_call()], run_id="run-old")) == ()


def test_partial_and_empty_successful_observations_are_counted():
    result = {"status": "unsupported", "observations": [], "warnings": ["no visible mark"]}
    notices = project_repeated_observations(_state([_call(result=result), _call(result=result)]))

    assert len(notices) == 1
    assert notices[0].matching_call_count == 2


def test_malformed_successful_result_raises_integrity_error():
    call = _call(result=None)
    call["result"] = None
    with pytest.raises(RunError) as error:
        project_repeated_observations(_state([call]))
    assert error.value.code is RunErrorCode.INTEGRITY_ERROR

