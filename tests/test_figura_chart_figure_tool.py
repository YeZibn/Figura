from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from figura.charts.chartfigure import chart_figure_digest, parse_chart_figure
from figura.shared.json_schema import normalize_json_value
from figura.tools import (
    ReplayEffect,
    ToolContext,
    ToolInvocation,
    ToolOutcome,
    ToolRegistry,
    ToolRuntime,
)
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition


def _figure(*, title: str = "Revenue", reference: tuple[str, str] | None = None) -> dict[str, object]:
    chart: dict[str, object] = {
        "chart_id": "revenue",
        "chart_spec": {
            "schema_version": 1,
            "metadata": {"chart_type": "bar", "title": "Revenue by month"},
            "axes": {"x": {"label": "Month"}, "y": {"label": "Revenue"}},
            "dataset": [{"category": "Jan", "value": 12}],
        },
    }
    if reference is not None:
        chart["measurement_refs"] = [{"run_id": reference[0], "call_id": reference[1]}]
    return {
        "schema_version": 1,
        "title": title,
        "layout": {"columns": 1},
        "charts": [chart],
    }


def _runtime(measurements=()):
    definition = assemble_chart_figure_definition(
        lambda _session_id, _run_id: SimpleNamespace(measurements=tuple(measurements))
    )
    return ToolRuntime(ToolRegistry("figura-web-v5", (definition,)))


def _invoke(runtime, figure: dict[str, object], *, call_id: str = "assembly-call"):
    return runtime.invoke(
        ToolInvocation(call_id, "assemble_chart_figure", json.dumps(figure, separators=(",", ":"))),
        ToolContext("current-run", "current-session", call_id),
    )


def _measurement(run_id: str, call_id: str, outcome: ToolOutcome = ToolOutcome.SUCCEEDED):
    return SimpleNamespace(
        run_id=run_id,
        call_id=call_id,
        tool_name="measure_bars",
        outcome=outcome,
    )


def test_tool_is_replay_safe_and_returns_only_figure_reference_digest_and_summary() -> None:
    raw = _figure(reference=("prior-run", "measure-call"))
    runtime = _runtime((_measurement("prior-run", "measure-call"),))

    result = _invoke(runtime, raw)

    assert runtime.registry.version == "figura-web-v5"
    assert runtime.registry["assemble_chart_figure"].replay_effect is ReplayEffect.REPLAY_SAFE
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert normalize_json_value(result.result) == {
        "figure_ref": {"run_id": "current-run", "call_id": "assembly-call"},
        "figure_digest": chart_figure_digest(parse_chart_figure(raw)),
        "title": "Revenue",
        "charts": [
            {"chart_id": "revenue", "chart_type": "bar", "title": "Revenue by month"}
        ],
    }


def test_empty_measurement_references_are_accepted_without_inference() -> None:
    result = _invoke(_runtime(), _figure())

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result is not None
    assert normalize_json_value(result.result["charts"]) == [
        {"chart_id": "revenue", "chart_type": "bar", "title": "Revenue by month"}
    ]


@pytest.mark.parametrize(
    ("measurements", "reference", "expected_code"),
    [
        ((_measurement("prior-run", "measure-call", ToolOutcome.FAILED),), ("prior-run", "measure-call"), "measurement_reference_not_succeeded"),
        ((), ("prior-run", "measure-call"), "measurement_reference_not_found"),
        ((), ("other-session-run", "measure-call"), "measurement_reference_not_found"),
        ((_measurement("prior-run", "measure-call"),), ("prior-run", "uncommitted-call"), "measurement_reference_not_found"),
        ((SimpleNamespace(run_id="prior-run", call_id="measure-call", tool_name="assemble_chart_figure", outcome=ToolOutcome.SUCCEEDED),), ("prior-run", "measure-call"), "measurement_reference_not_found"),
    ],
)
def test_invalid_measurement_references_reject_the_whole_figure(
    measurements, reference, expected_code: str
) -> None:
    result = _invoke(_runtime(measurements), _figure(reference=reference))

    assert result.outcome is ToolOutcome.FAILED
    assert result.error is not None
    assert result.error.code == expected_code
    assert result.error.field_path == "/charts/0/measurement_refs/0" or result.error.field_path == "/charts/0/measurement_refs/0/call_id"


def test_parser_or_semantic_errors_return_bounded_field_paths() -> None:
    malformed = _figure()
    malformed["charts"] = [
        {"chart_id": "revenue", "chart_spec": {**_figure()["charts"][0]["chart_spec"], "unexpected": True}}
    ]
    result = _invoke(_runtime(), malformed)

    assert result.outcome is ToolOutcome.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert result.error.field_path == "/charts/0/chart_spec/unexpected"


def test_figure_layout_semantics_fail_before_reference_lookup() -> None:
    raw = _figure()
    raw["layout"] = {"columns": 2}
    result = _invoke(_runtime(), raw)

    assert result.outcome is ToolOutcome.FAILED
    assert result.error is not None
    assert result.error.code == "columns_exceed_charts"
    assert result.error.field_path == "/layout/columns"
