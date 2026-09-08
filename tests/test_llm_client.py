"""Unit tests for the LLM client layer (config, normalization, tools,
reasoning isolation, knobs, retry, observation).

All tests run offline against a fake transport injected via ``_openai_factory``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import chartagent.client as client_mod
from chartagent.client import LLMClient, append_to_history, assistant_history_entry, resolve_config
from chartagent.client.client import normalize_non_streaming, _collect_streaming_deltas
from chartagent.client.config import DEFAULT_BASE_URL, DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT
from .conftest import non_streaming, streaming, streaming_with_tool_calls, tool_call


# --- 1. config layering ------------------------------------------------------- #
def test_config_explicit_beats_env_beats_default():
    env = {"DASHSCOPE_API_KEY": "env-key", "DASHSCOPE_BASE_URL": "http://env"}
    cfg = resolve_config(api_key="explicit", base_url=None, timeout=None, env=env)
    assert cfg.api_key == "explicit"
    assert cfg.base_url == "http://env"  # env fills the key omitted explicitly
    assert cfg.timeout == DEFAULT_TIMEOUT  # default fills the rest


def test_config_all_from_env():
    cfg = resolve_config(
        env={
            "DASHSCOPE_API_KEY": "k",
            "DASHSCOPE_BASE_URL": "http://e",
            "DASH_MODEL": "m",
            "OPENAI_TIMEOUT": "9",
            "OPENAI_MAX_RETRIES": "7",
        }
    )
    assert cfg.api_key == "k"
    assert cfg.base_url == "http://e"
    assert cfg.model == "m"
    assert cfg.timeout == 9.0
    assert cfg.max_retries == 7


def test_config_model_from_env_default():
    cfg = resolve_config(env={})
    assert cfg.model == ""


def test_config_defaults_when_nothing_set():
    cfg = resolve_config(env={})
    assert cfg.api_key is None
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.timeout == DEFAULT_TIMEOUT
    assert cfg.max_retries == DEFAULT_MAX_RETRIES


# --- 3. normalization --------------------------------------------------------- #
def test_normalize_plain_non_streaming():
    res = normalize_non_streaming(non_streaming(content="hello", reasoning="r"))
    assert res.content == "hello"
    assert res.reasoning == "r"
    assert res.tool_calls == []  # empty, not missing
    assert res.finish_reason == "stop"
    assert res.usage.total_tokens == 15
    assert res.raw is not None  # raw always preserved


def test_normalize_tool_calls_non_streaming():
    comp = non_streaming(content=None, tool_calls=[tool_call("call_1", "get_weather", '{"city":"bj"}')])
    res = normalize_non_streaming(comp)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "get_weather"
    assert res.tool_calls[0].arguments == '{"city":"bj"}'


def test_normalize_streaming_aggregates_reasoning_and_content():
    res = _collect_streaming_deltas(
        streaming(content_parts=["Hel", "lo"], reasoning_parts=["think", "ing"])
    )
    assert res.content == "Hello"
    assert res.reasoning == "thinking"
    assert res.finish_reason == "stop"
    assert res.usage.total_tokens == 8


def test_normalize_streaming_tool_calls():
    deltas = [
        [SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="get_", arguments='{"a"'))],
        [SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="weather", arguments=':1}'))],
    ]
    res = _collect_streaming_deltas(streaming_with_tool_calls(deltas))
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].name == "get_weather"
    assert res.tool_calls[0].arguments == '{"a":1}'


def test_normalize_streaming_multiple_tool_calls_ordered_by_index():
    # 两个 tool_calls 的分片交错到达，index 分别为 0 和 1。
    deltas = [
        [SimpleNamespace(index=1, id="call_2", function=SimpleNamespace(name="read_file", arguments='{"path":'))],
        [SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="list_dir", arguments='{"path":'))],
        [
            SimpleNamespace(index=1, id=None, function=SimpleNamespace(name=None, arguments='"a.txt"}')),
            SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='"/"}')),
        ],
    ]
    res = _collect_streaming_deltas(streaming_with_tool_calls(deltas))
    assert len(res.tool_calls) == 2
    # 无论分片到达顺序如何，结果都按 index 升序排列。
    assert res.tool_calls[0].name == "list_dir"
    assert res.tool_calls[0].arguments == '{"path":"/"}'
    assert res.tool_calls[1].name == "read_file"
    assert res.tool_calls[1].arguments == '{"path":"a.txt"}'


# --- client end-to-end via fake transport ------------------------------------- #
def test_client_chat_normalizes(backend_factory):
    client, _ = backend_factory([lambda _: non_streaming("hi")])
    res = client.chat([{"role": "user", "content": "hello"}], stream=False, model="m")
    assert res.content == "hi"


def test_thinking_toggle_call_time_compiles_to_extra_body(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")])
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m", enable_thinking=True)
    assert backend.calls[0]["extra_body"] == {"enable_thinking": True}


def test_thinking_toggle_from_config_when_call_omits(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")], enable_thinking=True)
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m")
    assert backend.calls[0]["extra_body"] == {"enable_thinking": True}


def test_tool_definitions_propagate(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")])
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m", tools=tools)
    assert backend.calls[0]["tools"] == tools


def test_retry_and_timeout_passed_as_explicit_conn(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")], max_retries=5, timeout=3.5)
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m")
    assert backend.conn_kwargs["max_retries"] == 5
    assert backend.conn_kwargs["timeout"] == 3.5


def test_observation_sink_emitted_without_secrets(backend_factory):
    seen = []

    def sink(entry):
        seen.append(entry)

    client, _ = backend_factory([lambda _: non_streaming("hi", reasoning="r")])
    client._observe = sink
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m")
    entry = seen[0]
    assert entry["model"] == "m"
    assert entry["content_len"] == 2
    assert entry["reasoning_len"] == 1
    assert "api_key" not in entry


def test_missing_api_key_raises(monkeypatch):
    # Isolate: ambient plugins (deepeval/langsmith) or a real shell may have
    # loaded DASHSCOPE_API_KEY into os.environ; the test asserts the key is
    # absent from all sources.
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        LLMClient(api_key=None, base_url="http://x")


# --- 5. reasoning isolation & history ----------------------------------------- #
def test_assistant_history_entry_contains_only_content():
    res = client_mod.NormalizedResult(content="answer", reasoning="secret-reasoning")
    entry = assistant_history_entry(res)
    assert entry == {"role": "assistant", "content": "answer"}


def test_append_to_history_strips_reasoning():
    messages = [{"role": "user", "content": "q"}]
    res = client_mod.NormalizedResult(content="answer", reasoning="secret")
    out = append_to_history(messages, res)
    assert out[1] == {"role": "assistant", "content": "answer"}
    assert "secret" not in repr(out)