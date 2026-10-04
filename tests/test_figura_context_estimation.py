"""Local input accounting and durable display metadata regression tests."""
from dataclasses import replace
import json

import pytest
import tiktoken

from figura.providers.config import ProviderSettings
from figura.providers.models import ProviderId, ProviderToolCall, FinishReason
from figura.providers import token_estimation as tokens
from figura.runtime.codecs.bindings import encode_binding, decode_binding
from figura.runtime.errors import RunError
from figura.runtime.store import FiguraRunStore
from figura.gateway.web_projection import run_summary, run_handle
from tests.test_figura_provider import _factory, _request, FakeTransport, _response as wire_response
from tests.test_figura_agent_executor import _app, _agent, _registry, _FakeFactory, _response
from tests.test_figura_execution_policy import _binding, _temporary
from tests.test_figura_gateway import _application, _create_run, _json


@pytest.fixture
def encoding():
    result = tokens.cached_encoding()
    if result is None:
        pytest.skip("Prepare the documented o200k_base cache for real tokenizer tests")
    return result


@pytest.mark.parametrize("text", ["中文图表分析", "English words", "def f(x): return x + 1",
    '{"a":1,"series":[1,2]}', "<|endoftext|> <|endofprompt|>"])
def test_offline_encoding_matches_official_o200k(text, encoding):
    assert encoding.encode_ordinary(text) == tiktoken.get_encoding("o200k_base").encode_ordinary(text)


def test_cached_encoding_never_downloads_missing_corrupt_or_disabled_cache(tmp_path, monkeypatch):
    import tiktoken.load
    monkeypatch.setattr(tiktoken.load, "read_file", lambda *_: pytest.fail("network-capable loader called"))
    tokens.cached_encoding.cache_clear()
    try:
        monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
        assert tokens.cached_encoding() is None
        (tmp_path / tokens.hashlib.sha1(tokens._ENCODING_URL.encode()).hexdigest()).write_bytes(b"corrupt")
        tokens.cached_encoding.cache_clear()
        assert tokens.cached_encoding() is None
        monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "")
        tokens.cached_encoding.cache_clear()
        assert tokens.cached_encoding() is None
    finally:
        tokens.cached_encoding.cache_clear()


@pytest.mark.parametrize("value,expected", [("", None), ("bad", None), ("0", None),
    ("-1", None), ("1.5", None), ("true", None), ("２", None), (" 256000 ", 256000)])
def test_capacity_is_display_only_configuration(value, expected):
    profile = ProviderSettings.from_env({"FIGURA_QWEN_API_KEY": "test-key",
        "FIGURA_QWEN_BASE_URL": "https://example.test/v1",
        "FIGURA_QWEN_CONTEXT_WINDOW_TOKENS": value}).profiles[ProviderId.QWEN]
    assert profile.context_window_tokens == expected
    assert profile.availability().available


def test_complete_input_projection_and_images_are_counted_without_wire_bytes(encoding):
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 200_000, "detail": "high"}}
    payload = {"model": "ignored", "timeout": 3600, "max_completion_tokens": 1,
        "messages": [{"role": "system", "content": "instructions"},
            {"role": "assistant", "content": None, "reasoning_content": "private-replay",
             "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "inspect", "arguments": '{"a":1}'}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            {"role": "user", "content": [{"type": "text", "text": "<|endoftext|> 中文"}, image, image]}],
        "tools": [{"type": "function", "function": {"name": "inspect", "description": "tool description", "parameters": {"type": "object"}}}]}
    original = json.dumps(payload)
    projection, images = tokens.input_projection(payload)
    text = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert "base64" not in text and "A" * 100 not in text
    assert "private-replay" in text and "call-1" in text and "tool description" in text
    assert images == 2
    estimate = tokens.estimate_input(payload, 1, encoding)
    assert estimate.input_tokens == len(encoding.encode_ordinary(text)) + 2048
    assert estimate.context_window_tokens == 1  # No admission constraint.
    assert json.dumps(payload) == original
    assert tokens.estimate_input({**payload, "timeout": 1, "model": "another", "max_completion_tokens": 999}, 1, encoding) == estimate


def test_prepare_estimation_is_independent_of_fingerprint_and_usage(encoding, monkeypatch):
    transport = FakeTransport(wire_response())
    client = _factory(transport).create(ProviderId.QWEN, "qwen3.8-flash")
    request = _request(ProviderId.QWEN)
    measured = client.prepare(request)
    assert measured.context_estimate.input_tokens > 0
    omitted = client.prepare(request, estimate_context=False)
    assert omitted.context_estimate is None
    assert omitted.payload == measured.payload and omitted.descriptor == measured.descriptor
    client._encoding = None
    disabled = client.prepare(request)
    assert disabled.descriptor == measured.descriptor
    assert client.dispatch(disabled).usage.prompt_tokens == 12
    class BrokenEncoding:
        def encode_ordinary(self, _text):
            raise ValueError("private text must not be logged")
    assert tokens.estimate_input(measured.payload, None, BrokenEncoding()) is None


def test_binding_versions_preserve_legacy_encoding_and_validate_estimates(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    legacy = _binding(agent, initial)
    raw = encode_binding(legacy)
    assert "context_estimate" not in json.loads(raw)
    assert encode_binding(decode_binding(raw)) == raw
    for estimate in (None, tokens.ContextEstimate(0, None), tokens.ContextEstimate(120, 256000)):
        binding = replace(legacy, schema_version=2, context_estimate=estimate)
        assert decode_binding(encode_binding(binding)) == binding
    for estimate in (tokens.ContextEstimate(True, None), tokens.ContextEstimate(-1, None),
                     tokens.ContextEstimate(1, 0), tokens.ContextEstimate(1, True), tokens.ContextEstimate(1, None, "")):
        with pytest.raises(RunError):
            encode_binding(replace(legacy, schema_version=2, context_estimate=estimate))
    for field in ("input_tokens", "estimator_version"):
        value = json.loads(encode_binding(replace(legacy, schema_version=2, context_estimate=tokens.ContextEstimate(1, None))))
        del value["context_estimate"][field]
        with pytest.raises(RunError):
            decode_binding(json.dumps(value))


def test_retry_and_restart_keep_original_estimate(tmp_path, monkeypatch, encoding):
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: "2000-01-01T00:00:00Z")
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_temporary(), _response()])
    agent = _agent(store, coordinator, _registry(), factory)
    waiting = agent.execute_slice(session.session_id, run.run_id)
    binding = waiting.provider_request_bindings[0]
    assert binding.schema_version == 2 and binding.context_estimate.input_tokens > 0
    assert FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id).provider_request_bindings == (binding,)
    monkeypatch.setattr("figura.providers.client.estimate_input", lambda *_: pytest.fail("retry re-estimated input"))
    finished = agent.execute(session.session_id, run.run_id)
    assert finished.run.status.value == "completed"
    assert finished.provider_request_bindings == (binding,)
    assert len(finished.provider_attempts) == 2


def test_multiple_requests_use_latest_snapshot_and_missing_latest_has_no_fallback(tmp_path, encoding):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response(calls=(ProviderToolCall("call-1", "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS), _response()])
    state = _agent(store, coordinator, _registry(), factory).execute(session.session_id, run.run_id)
    first, latest = state.provider_request_bindings
    assert latest.context_estimate.input_tokens > first.context_estimate.input_tokens
    public = run_summary(state)["contextUsage"]
    assert public == {"inputTokens": latest.context_estimate.input_tokens, "contextWindowTokens": None}
    assert run_summary(replace(state, provider_request_bindings=(first, replace(latest, context_estimate=None))))["contextUsage"] is None
    assert "contextUsage" not in run_handle(state.run)


def test_gateway_reads_bound_estimate_while_request_waits_and_after_failure(tmp_path, monkeypatch):
    app, store, coordinator, _, _ = _application(tmp_path)
    try:
        session = coordinator.create_session()
        run = _create_run(coordinator, session.session_id)
        agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
        state = coordinator.read_run_state(session.session_id, run.run_id)
        binding = replace(_binding(agent, state), schema_version=2, context_estimate=tokens.ContextEstimate(120, 100))
        attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, state.checkpoint.revision, binding=binding)
        monkeypatch.setattr("figura.providers.client.estimate_input", lambda *_: pytest.fail("read rebuilt request"))
        monkeypatch.setattr(tokens, "cached_encoding", lambda: pytest.fail("read loaded tokenizer"))
        path = f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/history"
        expected = {"inputTokens": 120, "contextWindowTokens": 100}
        waiting = app.handle("GET", path, {}, b"")
        assert waiting.status == 200 and _json(waiting)["run"]["contextUsage"] == expected
        claimed = coordinator.read_run_state(session.session_id, run.run_id)
        coordinator.fail_provider_attempt(session.session_id, run.run_id, claimed.checkpoint.revision,
            attempt.attempt_id, outcome_unknown=False, failure_code="provider_rejected")
        assert _json(app.handle("GET", path, {}, b""))["run"]["contextUsage"] == expected
        assert _json(app.handle("GET", f"/api/v1/sessions/{session.session_id}", {}, b""))["runs"][0]["contextUsage"] == expected
        reopened = FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id)
        assert run_summary(reopened)["contextUsage"] == expected
        assert "estimator_version" not in waiting.body.decode() and binding.request_fingerprint not in waiting.body.decode()
    finally:
        app.close()


def test_legacy_retry_preserves_exact_binding_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: "2000-01-01T00:00:00Z")
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    binding = _binding(agent, initial)
    original = encode_binding(binding)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, 1, binding=binding)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.fail_provider_attempt(session.session_id, run.run_id, claimed.checkpoint.revision,
        attempt.attempt_id, outcome_unknown=False, failure_code="provider_rejected", transient=True)
    reopened = FiguraRunStore(tmp_path)
    monkeypatch.setattr("figura.providers.client.estimate_input", lambda *_: pytest.fail("legacy binding was backfilled"))
    finished = _agent(reopened, coordinator, _registry(), _FakeFactory([_response()])).execute(session.session_id, run.run_id)
    assert finished.run.status.value == "completed"
    assert encode_binding(finished.provider_request_bindings[0]) == original
    assert finished.provider_request_bindings[0].context_estimate is None


def test_changed_capacity_does_not_rebase_recovered_request(tmp_path, monkeypatch, encoding):
    import figura.providers.config as config
    original = config._profile_from_env
    capacity = 100000
    monkeypatch.setattr(config, "_profile_from_env", lambda provider, env: replace(original(provider, env), context_window_tokens=capacity))
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: "2000-01-01T00:00:00Z")
    store, coordinator, session, run = _app(tmp_path)
    waiting = _agent(store, coordinator, _registry(), _FakeFactory([_temporary()])).execute_slice(session.session_id, run.run_id)
    binding = waiting.provider_request_bindings[0]
    assert binding.context_estimate.context_window_tokens == 100000
    capacity = 200000
    reopened = FiguraRunStore(tmp_path)
    state = _agent(reopened, coordinator, _registry(), _FakeFactory([_response()])).execute(session.session_id, run.run_id)
    assert state.run.status.value == "completed"
    assert state.provider_request_bindings == (binding,)


def test_bad_estimate_claim_rolls_back_binding_and_attempt(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    binding = replace(_binding(agent, initial), schema_version=2, context_estimate=tokens.ContextEstimate(-1, None))
    with pytest.raises(RunError):
        coordinator.begin_provider_attempt(session.session_id, run.run_id, 1, binding=binding)
    assert coordinator.read_run_state(session.session_id, run.run_id) == initial
