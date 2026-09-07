"""Tests for the built-in read-only basic tools (mock/tmp-files, no LLM)."""

import json

import pytest

from chartagent import ToolRegistry, dispatch
from chartagent.tools.builtin import TOOL_NAMES, register_builtins


@pytest.fixture
def registry(tmp_path):  # noqa: ARG001 - fixture param for explicit scheme
    reg = ToolRegistry()
    register_builtins(reg)
    return reg


def test_register_builtins_exposes_all_tools(registry):
    assert len(registry) == 4
    assert TOOL_NAMES == ["read_file", "list_dir", "parse_json", "read_json_file"]
    for name in TOOL_NAMES:
        assert registry.get(name) is not None


def test_read_file_success(registry, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello world", encoding="utf-8")
    out = dispatch(registry, "read_file", json.dumps({"path": str(p)}))
    assert json.loads(out) == "hello world"


def test_read_file_missing_error(registry, tmp_path):
    out = dispatch(registry, "read_file", json.dumps({"path": str(tmp_path / "nope")}))
    assert "error" in json.loads(out)


def test_list_dir_success(registry, tmp_path):
    (tmp_path / "x.txt").write_text("", encoding="utf-8")
    (tmp_path / "y.txt").write_text("", encoding="utf-8")
    out = dispatch(registry, "list_dir", json.dumps({"path": str(tmp_path)}))
    assert json.loads(out) == ["x.txt", "y.txt"]


def test_list_dir_missing_error(registry, tmp_path):
    out = dispatch(registry, "list_dir", json.dumps({"path": str(tmp_path / "missing")}))
    assert "error" in json.loads(out)


def test_parse_json_valid(registry):
    out = dispatch(registry, "parse_json", json.dumps({"text": '{"a": 1}'}))
    assert json.loads(out) == {"a": 1}


def test_parse_json_invalid(registry):
    out = dispatch(registry, "parse_json", json.dumps({"text": "{bad"}))
    assert "error" in json.loads(out)


def test_read_json_file_success(registry, tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"k": [1, 2]}', encoding="utf-8")
    out = dispatch(registry, "read_json_file", json.dumps({"path": str(p)}))
    assert json.loads(out) == {"k": [1, 2]}


def test_read_json_file_missing_error(registry, tmp_path):
    out = dispatch(registry, "read_json_file", json.dumps({"path": str(tmp_path / "none")}))
    assert "error" in json.loads(out)


def test_read_json_file_bad_json_error(registry, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    out = dispatch(registry, "read_json_file", json.dumps({"path": str(p)}))
    assert "error" in json.loads(out)