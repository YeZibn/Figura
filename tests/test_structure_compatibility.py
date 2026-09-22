from __future__ import annotations

import importlib
import json

from chartagent.review import chart_spec_digest as review_chart_spec_digest
from chartagent.spec import ChartSpec, chart_spec_digest
from chartagent.tools import Tool, ToolRegistry
from chartagent.tools.core import Tool as CanonicalTool
from chartagent.tools.integrations.openai import registry_tools
from chartagent.tools.integrations.mcp import to_mcp_tools


CANONICAL_MODULES = (
    "chartagent.agent",
    "chartagent.agent.loop",
    "chartagent.agent.messages",
    "chartagent.agent.observations",
    "chartagent.agent.review_gate",
    "chartagent.agent.tool_schema",
    "chartagent.agent.artifacts",
    "chartagent.agent.panel_routing",
    "chartagent.agent.measurement_flow",
    "chartagent.agent.recovery",
    "chartagent.agent.turn",
    "chartagent.runtime",
    "chartagent.runtime.factory",
    "chartagent.runtime.models",
    "chartagent.runtime.prompts",
    "chartagent.runtime.readiness",
    "chartagent.gateway.persistence",
    "chartagent.gateway.persistence_connection",
    "chartagent.gateway.persistence_errors",
    "chartagent.gateway.operation_journal",
    "chartagent.gateway.run_persistence",
    "chartagent.gateway.evaluation_adapter",
    "chartagent.gateway.service_evaluation",
    "chartagent.gateway.http_transport",
    "chartagent.gateway.run_observations",
    "chartagent.gateway.run_lifecycle",
    "chartagent.gateway.run_manager",
    "chartagent.attachments",
    "chartagent.attachments.registry",
    "chartagent.attachments.policy",
    "chartagent.attachments.metadata",
    "chartagent.review",
    "chartagent.review.manager",
    "chartagent.review.models",
    "chartagent.review.policy",
    "chartagent.review.evaluator",
    "chartagent.tools.core",
    "chartagent.tools.integrations",
    "chartagent.tools.adapters",
    "chartagent.tools.builtins",
    "chartagent.tools.chart.catalog",
    "chartagent.tools.chart.observation",
    "chartagent.tools",
    "chartagent.tools.core.definition",
    "chartagent.tools.core.registry",
    "chartagent.tools.core.result",
    "chartagent.tools.core.presentation",
    "chartagent.evaluation.reader_projection",
    "chartagent.evaluation.input_sources",
    "chartagent.evaluation.timeline_model",
    "chartagent.evaluation.timeline_evidence",
    "chartagent.evaluation.timeline_attribution",
    "chartagent.tools.integrations.mcp",
    "chartagent.tools.builtins.filesystem",
    "chartagent.tools.builtins.json",
    "chartagent.tools.builtins.catalog",
    "chartagent.tools.chart",
    "chartagent.tools.chart.rendering",
    "chartagent.tools.chart.observation.bars",
    "chartagent.tools.chart.observation.line",
    "chartagent.tools.chart.observation.ocr",
    "chartagent.tools.chart.observation.pie",
    "chartagent.tools.chart.observation.scatter",
    "chartagent.tools.chart.observation.foundation",
    "chartagent.tools.chart.observation.coordinates",
    "chartagent.tools.chart.observation.cartesian",
    "chartagent.tools.chart.observation.overlays",
    "chartagent.tools.chart.specification",
)


def test_canonical_module_matrix_imports() -> None:
    for module_name in CANONICAL_MODULES:
        assert importlib.import_module(module_name) is not None


def test_domain_modules_do_not_import_adapter_layer_at_definition_time() -> None:
    from chartagent.attachments import registry as attachment_registry
    from chartagent.review import manager as review_manager

    assert "tools.adapters" not in attachment_registry.__file__
    assert "tools.adapters" not in review_manager.__file__


def test_tool_core_exports_are_public() -> None:
    assert Tool is CanonicalTool


def test_chart_spec_digest_compatibility_export_is_canonical() -> None:
    spec = ChartSpec.from_dict(
        {
            "metadata": {"chart_type": "line", "title": "Sales"},
            "dataset": [{"category": "A", "value": 1}],
        }
    )
    assert chart_spec_digest is review_chart_spec_digest
    assert chart_spec_digest(spec) == review_chart_spec_digest(spec)


def test_review_package_exports_point_to_canonical_modules() -> None:
    from chartagent.review import (
        ChartCandidate,
        ReviewPolicy,
        ReviewResult,
        review_candidate_bytes,
        select_review_policy,
    )
    from chartagent.review.evaluator import review_candidate_bytes as canonical_evaluator
    from chartagent.review.models import ChartCandidate as canonical_candidate
    from chartagent.review.models import ReviewResult as canonical_result
    from chartagent.review.policy import ReviewPolicy as canonical_policy
    from chartagent.review.policy import select_review_policy as canonical_selector

    assert ChartCandidate is canonical_candidate
    assert ReviewResult is canonical_result
    assert ReviewPolicy is canonical_policy
    assert select_review_policy is canonical_selector
    assert review_candidate_bytes is canonical_evaluator


def test_review_result_json_shape_is_stable() -> None:
    from chartagent.review import ReviewIssue, ReviewResult, ReviewStatus

    result = ReviewResult(
        status=ReviewStatus.COMPLETED,
        checks={"structure": "passed"},
        issues=(ReviewIssue("warning", "labels", "可读性提示", "warning"),),
        evidence=({"kind": "encoded_artifact", "width": 320},),
        decision="pass_with_warning",
        confidence=0.8,
        review_mode="vlm",
    )
    payload = result.to_dict()

    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert payload["status"] == "completed"
    assert payload["issues"][0]["severity"] == "warning"
    assert payload["evidence"][0]["kind"] == "encoded_artifact"


def test_measurement_package_exports_point_to_canonical_modules() -> None:
    import chartagent.measurement as measurement
    from chartagent.measurement.evidence import build_measurement_evidence_refs
    from chartagent.measurement.lifecycle import MeasurementAttempt, MeasurementSession
    from chartagent.measurement.quality import audit_measurement
    from chartagent.measurement.scope import MeasurementTarget, ObservationScope

    assert measurement.MeasurementTarget is MeasurementTarget
    assert measurement.ObservationScope is ObservationScope
    assert measurement.MeasurementAttempt is MeasurementAttempt
    assert measurement.MeasurementSession is MeasurementSession
    assert measurement.audit_measurement is audit_measurement
    assert measurement.build_measurement_evidence_refs is build_measurement_evidence_refs


def test_protocol_projections_use_canonical_tool_definition() -> None:
    tool = Tool(
        "echo",
        "Echo one value.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        lambda value: {"value": value},
    )
    registry = ToolRegistry()
    registry.register(tool)

    assert registry_tools(registry)[0]["function"]["name"] == "echo"
    mcp = to_mcp_tools(registry)
    assert mcp["manifests"][0].input_schema == tool.parameters
    assert mcp["callables"]["echo"] is tool.fn
