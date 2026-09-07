"""Tests for the tool system (mock-driven, no real LLM)."""

import json

import pytest

from chartagent import Tool, ToolRegistry, dispatch, to_mcp_tools


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