from __future__ import annotations

import importlib

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
    "chartagent.runtime",
    "chartagent.runtime.factory",
    "chartagent.runtime.models",
    "chartagent.runtime.prompts",
    "chartagent.runtime.readiness",
    "chartagent.attachments",
    "chartagent.attachments.registry",
    "chartagent.attachments.policy",
    "chartagent.attachments.metadata",
    "chartagent.review",
    "chartagent.review.manager",
    "chartagent.review.models",
    "chartagent.review.policy",
    "chartagent.review.evidence",
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
