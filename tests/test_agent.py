"""Tests for the ReAct Agent loop (fake LLM client, no real API).

A fake client gives deterministic, scripted turns so the loop's behavior —
final answer, serial tool observations, error feedback, budget cap, reset,
history shape — is verified offline.
"""

from __future__ import annotations

from typing import Any, Dict, List

from chartagent import Agent, ToolRegistry, register_builtins
from chartagent.agent import _assistant_entry, registry_tools
from chartagent.client.models import NormalizedResult, ToolCall


class ScriptedClient:
    """Fake LLMClient: plays a scripted list of results, one per chat() call."""

    def __init__(self, script: List[NormalizedResult]) -> None:
        self.script = list(script)
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, **kwargs):
        self.calls.append({
            "n_messages": len(messages),
            "messages": list(messages),
            "tools": kwargs.get("tools"),
        })
        assert self.script, "script exhausted"
        return self.script.pop(0)


def _final(text: str = "done") -> NormalizedResult:
    return NormalizedResult(content=text, tool_calls=[])


def _call(name: str, arguments: str, call_id: str = "call_1") -> NormalizedResult:
    return NormalizedResult(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def _registry():
    reg = ToolRegistry()
    register_builtins(reg)
    return reg


def test_final_answer_returned_no_tools():
    client = ScriptedClient([_final("hello")])
    agent = Agent(client, ToolRegistry(), system="sys")
    assert agent.run("hi") == "hello"


def test_multi_step_tool_loop(tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"n": 3}', encoding="utf-8")
    script = [
        _call("read_json_file", '{"path": "%s"}' % p),
        _final('{"n": 3}'),
    ]
    client = ScriptedClient(script)
    got = Agent(client, _registry()).run("read it")
    assert got == '{"n": 3}'
    # history before final turn: user + assistant(tool_calls) + tool obs = 3
    assert client.calls[-1]["n_messages"] == 3


def test_tool_error_fed_back_as_observation():
    script = [
        _call("read_file", '{"path": "/definitely/missing/xyz"}'),
        _final("recovered"),
    ]
    client = ScriptedClient(script)
    got = Agent(client, ToolRegistry()).run("try")
    assert got == "recovered"
    assert len(client.calls) == 2  # error observation did not abort the loop


def test_max_steps_budget():
    client = ScriptedClient([_call("read_file", '{"path": "x"}') for _ in range(50)])
    agent = Agent(client, _registry(), max_steps=3)
    out = agent.run("loop")
    assert out == "*stopped: max_steps reached*"
    assert len(client.calls) == 3


def test_reset_clears_history():
    client = ScriptedClient([_final("one")])
    agent = Agent(client, ToolRegistry())
    agent.run("a")
    agent.reset()
    assert agent.messages == []


def test_assistant_history_keeps_tool_calls_strips_reasoning():
    result = NormalizedResult(
        content="hi",
        reasoning="SECRET_THOUGHT",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments='{"path":"x"}')],
    )
    entry = _assistant_entry(result)
    assert entry["content"] == "hi"
    assert "SECRET_THOUGHT" not in entry
    assert entry["tool_calls"][0]["id"] == "c1"


def test_registry_tools_lists_openai_schema():
    tools = registry_tools(_registry())
    assert len(tools) == 4
    assert tools[0]["type"] == "function"
    assert "name" in tools[0]["function"]


def test_multimodal_input_passes_through_unchanged():
    content = [
        {"type": "text", "text": "read this chart"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    client = ScriptedClient([_final("a bar chart")])
    agent = Agent(client, ToolRegistry(), system="sys")
    assert agent.run(content) == "a bar chart"
    # history: system + user(content list), unchanged
    user_entries = [m for m in agent.messages if m["role"] == "user"]
    assert user_entries[0]["content"] == content
    # the client received the same list verbatim on the first turn
    sent = client.calls[0]["messages"]
    assert [m for m in sent if m["role"] == "user"][0]["content"] == content