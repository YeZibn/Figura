"""Unit tests for the LLM client layer (config, normalization, tools,
reasoning isolation, knobs, retry, observation).

All tests run offline against a fake transport injected via ``_openai_factory``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import chartagent.client as client_mod
from chartagent.client import LLMClient, append_to_history, assistant_history_entry, resolve_config
from chartagent.client.client import normalize_non_streaming, _collect_streaming_deltas
from chartagent.client.config import DEFAULT_BASE_URL, DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, load_environment
from .conftest import non_streaming, streaming, streaming_with_tool_calls, tool_call

_PROVIDER_ENV_NAMES = (
    "CHARTAGENT_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_TIMEOUT",
    "OPENAI_MAX_RETRIES",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "DASH_MODEL",
    "QWEN_API_KEY",
    "QWEN_BASE_URL",
    "QWEN_MODEL",
    "QWEN_TIMEOUT",
    "QWEN_MAX_RETRIES",
    "QWEN_ENABLE_THINKING",
)


# --- 1. config layering ------------------------------------------------------- #
def test_config_explicit_beats_env_beats_default():
    env = {"QWEN_API_KEY": "env-key", "QWEN_BASE_URL": "http://env"}
    cfg = resolve_config(provider="qwen", api_key="explicit", base_url=None, timeout=None, env=env)
    assert cfg.api_key == "explicit"
    assert cfg.base_url == "http://env"  # env fills the key omitted explicitly
    assert cfg.timeout == DEFAULT_TIMEOUT  # default fills the rest


def test_config_canonical_openai_env_beats_legacy_env():
    cfg = resolve_config(
        env={
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_BASE_URL": "http://openai",
            "OPENAI_MODEL": "openai-model",
            "DASHSCOPE_API_KEY": "legacy-key",
            "DASHSCOPE_BASE_URL": "http://legacy",
            "DASH_MODEL": "legacy-model",
        }
    )
    assert cfg.api_key == "openai-key"
    assert cfg.base_url == "http://openai"
    assert cfg.model == "openai-model"


def test_config_all_from_env():
    cfg = resolve_config(
        env={
            "CHARTAGENT_PROVIDER": "qwen",
            "DASHSCOPE_API_KEY": "k",
            "DASHSCOPE_BASE_URL": "http://e",
            "DASH_MODEL": "m",
            "QWEN_TIMEOUT": "9",
            "QWEN_MAX_RETRIES": "7",
        }
    )
    assert cfg.api_key == "k"
    assert cfg.base_url == "http://e"
    assert cfg.model == "m"
    assert cfg.timeout == 9.0
    assert cfg.max_retries == 7


def test_config_zero_numeric_values_are_preserved():
    cfg = resolve_config(env={"OPENAI_TIMEOUT": "0", "OPENAI_MAX_RETRIES": "0"})
    assert cfg.timeout == 0.0
    assert cfg.max_retries == 0

    explicit = resolve_config(timeout=0, max_retries=0, env={"OPENAI_TIMEOUT": "9", "OPENAI_MAX_RETRIES": "7"})
    assert explicit.timeout == 0
    assert explicit.max_retries == 0


def test_config_model_from_env_default():
    cfg = resolve_config(env={})
    assert cfg.model == ""


def test_config_defaults_when_nothing_set():
    cfg = resolve_config(env={})
    assert cfg.api_key is None
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.timeout == DEFAULT_TIMEOUT
    assert cfg.max_retries == DEFAULT_MAX_RETRIES


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unsupported provider"):
        resolve_config(provider="anthropic", env={})


def test_qwen_uses_scoped_configuration_and_thinking_default():
    cfg = resolve_config(
        provider="qwen",
        env={
            "QWEN_API_KEY": "qwen-key",
            "QWEN_BASE_URL": "http://qwen",
            "QWEN_MODEL": "qwen3.8-flash",
        },
    )
    assert cfg.provider == "qwen"
    assert cfg.api_key == "qwen-key"
    assert cfg.base_url == "http://qwen"
    assert cfg.model == "qwen3.8-flash"
    assert cfg.enable_thinking is True


def test_openai_does_not_fallback_to_dashscope():
    cfg = resolve_config(
        provider="openai",
        env={"DASHSCOPE_API_KEY": "qwen-key", "DASHSCOPE_BASE_URL": "http://qwen"},
    )
    assert cfg.api_key is None
    assert cfg.base_url == DEFAULT_BASE_URL


def test_qwen_thinking_can_be_disabled():
    cfg = resolve_config(provider="qwen", enable_thinking=False, env={})
    assert cfg.enable_thinking is False


def test_environment_file_contract_is_stable_across_launch_directories(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHARTAGENT_PROVIDER=qwen\nDASHSCOPE_API_KEY=file-key\nDASHSCOPE_BASE_URL=http://file\nDASH_MODEL=file-model\n",
        encoding="utf-8",
    )
    for directory in (tmp_path, tmp_path / "frontend"):
        directory.mkdir(exist_ok=True)
        for name in _PROVIDER_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CHARTAGENT_ENV_FILE", str(env_file))
        monkeypatch.chdir(directory)
        load_environment()
        config = resolve_config()
        assert config.api_key == "file-key"
        assert config.base_url == "http://file"
        assert config.model == "file-model"


def test_process_environment_beats_environment_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CHARTAGENT_PROVIDER=qwen\nDASHSCOPE_API_KEY=file-key\nDASHSCOPE_BASE_URL=http://file\n", encoding="utf-8")
    for name in _PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHARTAGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "process-key")
    load_environment()
    config = resolve_config()
    assert config.api_key == "process-key"
    assert config.base_url == "http://file"


# --- 3. normalization --------------------------------------------------------- #
def test_normalize_plain_non_streaming():
    res = normalize_non_streaming(non_streaming(content="hello", reasoning="r"))
    assert res.content == "hello"
    assert res.reasoning == "r"
    assert res.tool_calls == []  # empty, not missing
    assert res.finish_reason == "stop"
    assert res.usage.total_tokens == 15
    assert res.raw is not None  # raw always preserved


def test_normalize_standard_reply_without_textual_reasoning():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
    )
    res = normalize_non_streaming(completion)
    assert res.content == "hello"
    assert res.reasoning == ""
    assert res.usage.total_tokens == 3


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


def test_standard_reasoning_and_completion_limit_propagate(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")])
    client.chat(
        [{"role": "user", "content": "x"}],
        stream=False,
        model="m",
        reasoning_effort="medium",
        max_completion_tokens=123,
    )
    assert backend.calls[0]["reasoning_effort"] == "medium"
    assert backend.calls[0]["max_completion_tokens"] == 123
    assert "extra_body" not in backend.calls[0]
    assert "max_tokens" not in backend.calls[0]


def test_reasoning_effort_from_config_when_call_omits(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")], reasoning_effort="high")
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m")
    assert backend.calls[0]["reasoning_effort"] == "high"
    assert "extra_body" not in backend.calls[0]


def test_streaming_request_requests_usage(backend_factory):
    client, backend = backend_factory([lambda _: streaming(["ok"])])
    client.chat([{"role": "user", "content": "x"}], model="m")
    assert backend.calls[0]["stream"] is True
    assert backend.calls[0]["stream_options"] == {"include_usage": True}


def test_tool_definitions_propagate(backend_factory):
    client, backend = backend_factory([lambda _: non_streaming("ok")])
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    client.chat([{"role": "user", "content": "x"}], stream=False, model="m", tools=tools)
    assert backend.calls[0]["tools"] == tools


def test_qwen_request_uses_thinking_without_openai_only_fields(backend_factory):
    client, backend = backend_factory(
        [lambda _: streaming(["ok"])],
        provider="qwen",
        model="qwen3.8-flash",
        reasoning_effort="high",
    )
    client.chat([{"role": "user", "content": "x"}], stream=True, model="qwen3.8-flash")
    request = backend.calls[0]
    assert request["extra_body"] == {"enable_thinking": True}
    assert "reasoning_effort" not in request
    assert "stream_options" not in request


def test_qwen_request_omits_thinking_when_disabled(backend_factory):
    client, backend = backend_factory(
        [lambda _: non_streaming("ok")],
        provider="qwen",
        enable_thinking=False,
    )
    client.chat([{"role": "user", "content": "x"}], stream=False, model="qwen3.8-flash")
    assert "extra_body" not in backend.calls[0]


def test_qwen_preserves_multimodal_tool_call_contract(backend_factory):
    deltas = [
        [SimpleNamespace(index=0, id="qwen-call", function=SimpleNamespace(name="inspect", arguments='{"image_id":"'))],
        [SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='att_1"}'))],
    ]
    tools = [{"type": "function", "function": {"name": "inspect", "parameters": {}}}]
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "检查图片"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,hidden"}},
        ],
    }]
    client, backend = backend_factory(
        [lambda _: streaming_with_tool_calls(deltas)],
        provider="qwen",
        enable_thinking=False,
    )

    result = client.chat(messages, stream=True, model="qwen3.8-flash", tools=tools)

    assert result.tool_calls[0].id == "qwen-call"
    assert result.tool_calls[0].name == "inspect"
    assert result.tool_calls[0].arguments == '{"image_id":"att_1"}'
    assert backend.calls[0]["messages"] == messages
    assert backend.calls[0]["tools"] == tools


def test_provider_request_trace_does_not_copy_exception_details(backend_factory):
    traces = []
    client, _ = backend_factory(
        [lambda _: (_ for _ in ()).throw(RuntimeError("endpoint=https://provider.invalid api_key=sentinel-secret"))],
        provider="qwen",
        trace_sink=traces.append,
    )

    with pytest.raises(RuntimeError):
        client.chat([{"role": "user", "content": "x"}], stream=False, model="qwen3.8-flash")

    encoded = json.dumps([event.to_dict() for event in traces], ensure_ascii=False)
    assert "sentinel-secret" not in encoded
    assert "provider.invalid" not in encoded
    assert traces[-1].payload["error_code"] == "provider_request_failed"


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
    assert entry["provider"] == "openai"
    assert entry["model"] == "m"
    assert entry["content_len"] == 2
    assert entry["reasoning_len"] == 1
    assert entry["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert "api_key" not in entry


def test_missing_api_key_raises(monkeypatch):
    # Isolate ambient credentials from both canonical and legacy sources.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
