"""Tests for the tool system (mock-driven, no real LLM)."""

import json

import pytest

from chartagent import Tool, ToolRegistry, dispatch, to_mcp_tools
from chartagent.agent import tool_to_openai_schema
from chartagent.tools import get_tool_presentation


def _add(a: int, b: int) -> int:
    return a + b


def _boom() -> None:
    raise RuntimeError("intentional failure")


class _Unserializable:
    pass


def test_tool_definition_and_metadata():
    tool = Tool(name="add", description="sum two numbers",
                parameters={"type": "object", "properties": {"a": {"type": "integer"}}},
                fn=_add)
    assert tool.name == "add"
    assert tool.description == "sum two numbers"
    assert tool.parameters["type"] == "object"
    assert tool.fn(1, 2) == 3


def test_tool_defaults_normalize_schema_and_export_one_definition():
    tool = Tool(
        "plain",
        "Use this tool to return a bounded value when needed; do not use it for other work. The result is data, with no additional guarantees.",
        {"properties": {"value": {"type": "integer"}}},
        lambda value: value,
    )

    assert tool.display_name is None
    assert tool.group == "general"
    assert tool.parameters["type"] == "object"
    assert tool.parameters["required"] == []
    assert tool.parameters["additionalProperties"] is False
    assert tool.parameters["properties"]["value"]["description"]
    assert tool.definition() == {
        "name": "plain",
        "description": tool.description,
        "parameters": tool.parameters,
    }


def test_tool_rejects_invalid_bounded_metadata():
    with pytest.raises(ValueError):
        Tool("bad", "", {"type": "object"}, lambda: None)
    with pytest.raises(ValueError):
        Tool("bad", "valid description", {"type": "object"}, lambda: None, group="Not Valid")
    with pytest.raises(ValueError):
        Tool("bad", "valid description", {"type": "object", "properties": {"x": {}}}, lambda: None)


def test_tool_presentation_has_known_names_and_unknown_fallback():
    known = get_tool_presentation("render_chart")
    assert known.display_name == "生成图表"
    assert known.english_name == "render_chart"
    assert known.label == "生成图表 (render_chart)"

    layout = get_tool_presentation("inspect_chart_layout")
    assert layout.display_name == "检查图表布局"
    assert layout.english_name == "inspect_chart_layout"
    assert layout.label == "检查图表布局 (inspect_chart_layout)"
    assert layout.group == "chart-observation"

    unknown = get_tool_presentation("future_tool")
    assert unknown.display_name == "future_tool"
    assert unknown.english_name == "future_tool"
    assert unknown.group == "general"


def test_tool_requires_nonempty_name():
    with pytest.raises(ValueError):
        Tool(name="", description="x", parameters={}, fn=_add)


def test_register_get_list_len():
    reg = ToolRegistry()
    reg.register(Tool("add", "sum", {"type": "object"}, _add))
    assert len(reg) == 1
    assert "add" in reg
    assert reg.get("add").fn(2, 3) == 5
    assert reg.get("missing") is None
    assert [t.name for t in reg.list()] == ["add"]


def test_duplicate_registration_rejected():
    reg = ToolRegistry()
    reg.register(Tool("add", "sum", {"type": "object"}, _add))
    with pytest.raises(ValueError):
        reg.register(Tool("add", "dupe", {"type": "object"}, _add))
    assert len(reg) == 1


def test_dispatch_success_returns_json_string():
    reg = ToolRegistry()
    reg.register(Tool("add", "sum", {"type": "object"}, _add))
    out = dispatch(reg, "add", json.dumps({"a": 1, "b": 4}))
    assert json.loads(out) == 5


def test_dispatch_unknown_tool_structured_error():
    reg = ToolRegistry()
    out = dispatch(reg, "nope", "{}")
    assert json.loads(out)["error"]


def test_dispatch_fn_raises_structured_error():
    reg = ToolRegistry()
    reg.register(Tool("boom", "fails", {"type": "object"}, _boom))
    out = dispatch(reg, "boom", "{}")
    assert "intentional failure" in json.loads(out)["error"]


def test_dispatch_nonserializable_structured_error():
    reg = ToolRegistry()
    reg.register(Tool("bad", "unserializable", {"type": "object"},
                      lambda: _Unserializable()))
    out = dispatch(reg, "bad", "{}")
    assert json.loads(out)["error"]


def test_dispatch_invalid_arguments_structured_error():
    reg = ToolRegistry()
    reg.register(Tool("add", "sum", {"type": "object"}, _add))
    out = dispatch(reg, "add", "{not json")
    assert "error" in json.loads(out)


def test_mcp_conversion_shape():
    reg = ToolRegistry()
    reg.register(Tool("add", "sum two",
                      {"type": "object", "properties": {"a": {"type": "integer"}}},
                      _add))
    surface = to_mcp_tools(reg)
    assert list(surface.keys()) == ["manifests", "callables"]
    manifested = surface["manifests"]
    assert len(manifested) == 1
    m = manifested[0]
    assert m.name == "add"
    assert m.description == "sum two"
    assert m.input_schema["type"] == "object"
    assert surface["callables"]["add"](2, 3) == 5


def test_agent_and_mcp_exports_share_the_same_contract():
    tool = Tool(
        "contract_tool",
        "Use for contract checks when a value is needed; do not use for unrelated input. The result is a value and has no side effects.",
        {
            "type": "object",
            "properties": {"value": {"type": "integer", "description": "Value to return."}},
            "required": ["value"],
            "additionalProperties": False,
        },
        lambda value: value,
        display_name="契约工具",
        group="testing",
    )
    registry = ToolRegistry()
    registry.register(tool)

    openai = tool_to_openai_schema(tool)["function"]
    manifest = to_mcp_tools(registry)["manifests"][0]
    assert manifest.name == openai["name"] == tool.name
    assert manifest.description == openai["description"] == tool.description
    assert manifest.input_schema == openai["parameters"] == tool.parameters
    assert manifest.display_name == "契约工具"
    assert manifest.group == "testing"


def test_registered_tools_have_actionable_descriptions_and_explicit_schemas():
    from chartagent.review import ChartReviewManager
    from chartagent.tools.builtins.catalog import BUILTIN_TOOLS
    from chartagent.tools.chart.catalog import CHART_TOOLS

    tools = [*BUILTIN_TOOLS, *CHART_TOOLS, ChartReviewManager().review_tool()]
    assert len({tool.name for tool in tools}) == len(tools)
    for tool in tools:
        assert len(tool.description) >= 80
        assert "Use" in tool.description
        assert "do not" in tool.description
        assert "return" in tool.description or "result" in tool.description
        assert tool.group
        assert tool.parameters["type"] == "object"
        assert "required" in tool.parameters
        assert "additionalProperties" in tool.parameters
        for name, schema in tool.parameters["properties"].items():
            assert schema.get("description"), name
