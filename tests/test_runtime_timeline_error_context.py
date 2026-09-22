from __future__ import annotations

import json
from pathlib import Path

from chartagent.client.client import classify_provider_error
from chartagent.decision_timeline import enrich_event_payload
from chartagent.gateway.run_lifecycle import ManagedRun
from chartagent.spec import generation_context_schema, normalize_generation_context
from chartagent.tools.chart.specification import assemble_spec


FIXTURE = Path(__file__).parent / "fixtures" / "decision_timeline_runtime.json"


class ProviderError(RuntimeError):
    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = {"error": {"code": "provider_error", "message": message}}


def test_runtime_lifecycle_envelope_uses_bounded_process_identity() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    events = [
        enrich_event_payload(item["kind"], item["payload"], run_id=fixture["run_id"], sequence=item["sequence"])
        for item in fixture["events"]
    ]

    assert events[1]["process_id"] == "turn:1"
    assert events[2]["process_id"] == "turn:1"
    assert events[3]["process_id"] == "operation:model:1"
    assert events[4]["result"]["issues"][0]["location"] == "generation_context.source_scope"
    assert events[5]["failure_code"] == "provider_balance_required"
    assert events[5]["provider_status"] == 402
    assert events[5]["outcome_known"] is True
    assert "sequence" not in events[5]["process_id"]


def test_provider_failure_classification_separates_rejection_and_uncertain() -> None:
    balance = classify_provider_error(ProviderError(402, "Insufficient Balance"))
    timeout = classify_provider_error(ProviderError(None, "connection reset"))

    assert balance["failure_category"] == "provider_balance"
    assert balance["failure_code"] == "provider_balance_required"
    assert balance["outcome_known"] is True
    assert balance["retryable"] is False
    assert timeout["failure_category"] == "transport_uncertain"
    assert timeout["outcome_known"] is False
    assert timeout["retryable"] is True


def test_managed_run_adds_one_process_identity_to_lifecycle_events() -> None:
    run = ManagedRun("session-runtime", run_id="run-runtime")
    started = run.publish("run_started", {"status": "running"})
    failed = run.publish(
        "run_failed",
        {
            "failure_category": "provider_balance",
            "failure_code": "provider_balance_required",
            "safe_message": "Insufficient Balance",
            "outcome_known": True,
        },
    )

    assert started is not None and failed is not None
    assert started.payload["process_id"] == "run"
    assert failed.payload["process_id"] == "run"


def test_generation_context_schema_and_runtime_binding_agree() -> None:
    context = normalize_generation_context(
        {
            "mode": "reconstruct",
            "coverage": {"basis": "full_source", "status": "complete"},
            "selection_basis": "agent_resolved",
            "goal_summary": "重建当前 panel",
        },
        source_scope_hint={"attachment_id": "att-1", "panel_ids": ["panel-left"]},
    )

    assert context is not None
    assert context.validate() == []
    assert context.source_scope is not None
    assert context.source_scope.panel_ids == ("panel-left",)
    schema = generation_context_schema()
    any_of = schema.get("anyOf")
    assert any_of
    assert any("source_scope" in item.get("required", []) for item in any_of)


def test_assemble_binds_unique_figure_source_when_context_omits_scope() -> None:
    result = assemble_spec(
        figure={
            "figure_id": "figure-1",
            "source": {"attachment_id": "att-1", "panel_id": "panel-left"},
            "layout": {"type": "grid", "columns": 1},
            "coverage": {
                "source_series": ["Revenue"],
                "represented_series": ["Revenue"],
                "omitted_series": [],
                "basis": "full_source",
                "status": "complete",
            },
            "generation_context": {
                "mode": "reconstruct",
                "coverage": {"basis": "full_source", "status": "complete"},
                "selection_basis": "agent_resolved",
                "goal_summary": "重建当前 panel",
            },
            "charts": [{
                "chart_id": "chart-1",
                "chart_type": "bar",
                "points": [{"category": "A", "value": 1}],
                "x_label": "类别",
                "y_label": "值",
            }],
        }
    )

    assert result["generation_context"]["source_scope"] == {
        "attachment_id": "att-1",
        "panel_ids": ["panel-left"],
    }
