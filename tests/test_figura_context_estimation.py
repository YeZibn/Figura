"""Local input accounting and durable display metadata regression tests."""
from dataclasses import replace
import json

import pytest
import tiktoken

from figura.providers.config import ProviderSettings
from figura.providers.models import ProviderId, ProviderToolCall, FinishReason
from figura.providers import token_estimation as tokens
from figura.agent.context_accounting import (
    RequestContextProjection,
    account_request_context,
)
from figura.providers.models import (
    FunctionTool,
    ImageBlock,
    InstructionBlock,
    InstructionRole,
    MessageRole,
    ProviderContinuation,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    TextBlock,
)
from figura.runtime.codecs.provider_requests import encode_provider_request, decode_provider_request
from figura.runtime.errors import RunError
from figura.runtime.store import FiguraRunStore
from figura.gateway.web_projection import run_summary, run_handle
from tests.test_figura_provider import _factory, _request, FakeTransport, _response as wire_response
from tests.test_figura_agent_executor import _app, _agent, _registry, _FakeFactory, _response
from tests.test_figura_execution_policy import _request_record, _temporary
from tests.test_figura_gateway import _application, _create_run, _json


@pytest.fixture
def encoding():
    result = tokens.cached_encoding()
    if result is None:
        pytest.skip("Prepare the documented o200k_base cache for real tokenizer tests")
    return result


def _agent_requests(state):
    return tuple(item for item in state.provider_requests if item.purpose == "agent_turn")


def _agent_request(state):
    requests = _agent_requests(state)
    assert requests
    return requests[0]


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


def _accounting_request(*, continuation=True):
    image = ImageBlock("image/png", b"private-image-bytes")
    resources = [{"ref": {"kind": "attachment", "id": "private-attachment-id"}}]
    return ProviderRequest(
        provider_id=ProviderId.QWEN,
        model_id="qwen3.8-flash",
        instructions=(
            InstructionBlock(InstructionRole.SYSTEM, "stable policy private-marker"),
            InstructionBlock(InstructionRole.SYSTEM, "tool and runtime rules"),
            InstructionBlock(InstructionRole.SYSTEM, '{"summary":"old context"}'),
            InstructionBlock(
                InstructionRole.SYSTEM,
                "运行资源目录\n" + json.dumps({"run_id": "private-run", "resources": resources}),
            ),
        ),
        messages=(
            ProviderMessage(MessageRole.USER, "private historical user input"),
            ProviderMessage(
                MessageRole.ASSISTANT,
                "private historical assistant response",
                tool_calls=(ProviderToolCall("private-call", "inspect", '{"value":1}'),),
                continuation=(
                    ProviderContinuation(ProviderId.QWEN, 1, "private-continuation")
                    if continuation else None
                ),
            ),
            ProviderMessage(MessageRole.TOOL, "private tool result", tool_call_id="private-call"),
            ProviderMessage(
                MessageRole.USER,
                (TextBlock("private current input"), image),
            ),
        ),
        options=ProviderOptions(max_completion_tokens=512),
        tools=(FunctionTool("inspect", {"type": "object", "properties": {"value": {"type": "integer"}}}, "private tool schema"),),
    )


def test_request_context_accounting_separates_history_current_tools_and_images(encoding):
    request = _accounting_request()
    projection = RequestContextProjection(
        history_message_indices=(0, 1, 2),
        current_input_message_index=3,
        summary_instruction_index=2,
        execution_instruction_index=3,
        resource_entries=({"ref": {"kind": "attachment", "id": "private-attachment-id"}},),
    )
    estimate = tokens.ContextEstimate(80, 100, "o200k_base-v1")

    accounting = account_request_context(request, projection, estimate)

    assert accounting.full_input_tokens == 80
    assert accounting.history_input_tokens is not None and accounting.history_input_tokens > 0
    assert accounting.raw_history_tokens is not None and accounting.raw_history_tokens > 0
    assert accounting.current_input_tokens is not None
    assert accounting.current_input_tokens >= tokens.IMAGE_TOKENS
    assert accounting.history_input_tokens < tokens.IMAGE_TOKENS
    assert accounting.summary_tokens is not None
    assert accounting.policy_tools_state_tokens is not None
    assert accounting.resource_directory_tokens is not None
    assert accounting.selected_image_count == 1
    assert accounting.image_tokens == tokens.IMAGE_TOKENS
    assert accounting.context_capacity_tokens == 100
    assert accounting.pressure_reason == "directory_reducible"

    without_continuation = account_request_context(
        _accounting_request(continuation=False), projection, estimate
    )
    assert accounting.history_input_tokens > without_continuation.history_input_tokens
    without_native_schema = account_request_context(
        replace(request, tools=()), projection, estimate
    )
    assert accounting.policy_tools_state_tokens > without_native_schema.policy_tools_state_tokens
    assert accounting.safe_diagnostic() == {
        "full_input_tokens": 80,
        "history_input_tokens": accounting.history_input_tokens,
        "current_input_tokens": accounting.current_input_tokens,
        "summary_tokens": accounting.summary_tokens,
        "raw_history_tokens": accounting.raw_history_tokens,
        "resource_directory_tokens": accounting.resource_directory_tokens,
        "policy_tools_state_tokens": accounting.policy_tools_state_tokens,
        "selected_image_count": 1,
        "image_tokens": tokens.IMAGE_TOKENS,
        "context_capacity_tokens": 100,
        "estimator_version": "o200k_base-v1",
        "pressure_reason": "directory_reducible",
    }
    diagnostic = json.dumps(accounting.safe_diagnostic())
    assert all(secret not in diagnostic for secret in (
        "private-marker", "private historical", "private current", "private-call",
        "private tool schema", "private-attachment-id", "private-continuation",
    ))


def test_full_window_pressure_does_not_depend_on_history_projection_size(encoding):
    request = _accounting_request()
    projection = RequestContextProjection(
        history_message_indices=(),
        current_input_message_index=3,
        summary_instruction_index=None,
        execution_instruction_index=3,
        resource_entries=(),
    )

    accounting = account_request_context(
        request,
        projection,
        tokens.ContextEstimate(80, 100, "o200k_base-v1"),
    )

    assert accounting.full_input_tokens == 80
    assert accounting.history_input_tokens is not None
    assert accounting.history_input_tokens < 80
    assert accounting.pressure_reason == "protected_content"


@pytest.mark.parametrize("capacity", [None, 0])
def test_request_context_accounting_marks_capacity_unknown(capacity, encoding):
    request = _accounting_request()
    projection = RequestContextProjection((0, 1, 2), 3, 2, 3, ())

    accounting = account_request_context(
        request, projection, tokens.ContextEstimate(80, capacity, "o200k_base-v1")
    )

    assert accounting.full_input_tokens == 80
    assert accounting.context_capacity_tokens == capacity
    assert accounting.history_input_tokens is not None
    assert accounting.pressure_reason == "estimate_unavailable"


def test_request_context_accounting_keeps_full_estimate_when_local_encoding_unavailable(monkeypatch):
    import figura.agent.context_accounting as context_accounting

    monkeypatch.setattr(context_accounting, "cached_encoding", lambda: None)
    request = _accounting_request()
    projection = RequestContextProjection((0, 1, 2), 3, 2, 3, ())

    accounting = context_accounting.account_request_context(
        request, projection, tokens.ContextEstimate(80, 100, "o200k_base-v1")
    )

    assert accounting.full_input_tokens == 80
    assert accounting.history_input_tokens is None
    assert accounting.current_input_tokens is None
    assert accounting.resource_directory_tokens is None
    assert accounting.selected_image_count == 1
    assert accounting.image_tokens == tokens.IMAGE_TOKENS
    assert accounting.pressure_reason == "estimate_unavailable"


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


def test_provider_request_codec_round_trips_and_validates_estimates(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    request = replace(_request_record(agent, initial), context_estimate=None)
    raw = encode_provider_request(request)
    assert encode_provider_request(decode_provider_request(raw)) == raw
    for estimate in (None, tokens.ContextEstimate(0, None), tokens.ContextEstimate(120, 256000)):
        request_with_estimate = replace(request, context_estimate=estimate)
        assert decode_provider_request(encode_provider_request(request_with_estimate)) == request_with_estimate
    for estimate in (tokens.ContextEstimate(True, None), tokens.ContextEstimate(-1, None),
                     tokens.ContextEstimate(1, 0), tokens.ContextEstimate(1, True), tokens.ContextEstimate(1, None, "")):
        with pytest.raises(RunError):
            encode_provider_request(replace(request, context_estimate=estimate))
    for field in ("input_tokens", "estimator_version"):
        value = json.loads(encode_provider_request(replace(request, context_estimate=tokens.ContextEstimate(1, None))))
        del value["context_estimate"][field]
        with pytest.raises(RunError):
            decode_provider_request(json.dumps(value))


def test_historical_provider_request_is_non_dispatchable_and_round_trips(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    request = replace(
        _request_record(agent, initial),
        purpose="historical_import",
        request_fingerprint="0" * 64,
        endpoint_identity="0" * 64,
        prompt_digest="0" * 64,
        tool_registry_digest="0" * 64,
        options={},
        asset_manifest={},
        generation_only=False,
    )
    assert decode_provider_request(encode_provider_request(request)) == request


def test_provider_request_pins_checkpoint_or_fallback_context_projection(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    base = _request_record(agent, initial)
    for request in (
        replace(
            base,
            context_projection="checkpoint",
            context_checkpoint_revision=2,
            context_checkpoint_operation_id="compact-op",
        ),
        replace(
            base,
            context_projection="fallback",
            context_checkpoint_operation_id="compact-op",
        ),
    ):
        assert decode_provider_request(encode_provider_request(request)) == request
    for request in (
        replace(base, context_projection="checkpoint"),
        replace(base, context_projection="fallback"),
        replace(base, context_projection="other"),
        replace(
            base,
            context_projection="full",
            context_checkpoint_revision=1,
        ),
    ):
        with pytest.raises(RunError):
            encode_provider_request(request)


def test_retry_and_restart_keep_original_estimate(tmp_path, monkeypatch, encoding):
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: "2000-01-01T00:00:00Z")
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_temporary(), _response()])
    agent = _agent(store, coordinator, _registry(), factory)
    waiting = agent.execute_slice(session.session_id, run.run_id)
    request = _agent_request(waiting)
    assert request.schema_version == 2 and request.context_estimate.input_tokens > 0
    assert FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id).provider_requests == (request,)
    monkeypatch.setattr("figura.providers.client.estimate_input", lambda *_: pytest.fail("retry re-estimated input"))
    finished = agent.execute(session.session_id, run.run_id)
    assert finished.run.status.value == "completed"
    assert finished.provider_requests == (request,)
    assert len(finished.provider_attempts) == 2


def test_multiple_requests_use_latest_snapshot_and_missing_latest_has_no_fallback(tmp_path, encoding):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response(calls=(ProviderToolCall("call-1", "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS), _response()])
    state = _agent(store, coordinator, _registry(), factory).execute(session.session_id, run.run_id)
    first, latest = _agent_requests(state)
    assert latest.context_estimate.input_tokens > first.context_estimate.input_tokens
    public = run_summary(state)["contextUsage"]
    assert public == {"inputTokens": latest.context_estimate.input_tokens, "contextWindowTokens": None}
    assert run_summary(replace(state, provider_requests=(first, replace(latest, context_estimate=None))))["contextUsage"] is None
    assert "contextUsage" not in run_handle(state.run)


def test_gateway_reads_bound_estimate_while_request_waits_and_after_failure(tmp_path, monkeypatch):
    app, store, coordinator, _, _ = _application(tmp_path)
    try:
        session = coordinator.create_session()
        run = _create_run(coordinator, session.session_id)
        agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
        state = coordinator.read_run_state(session.session_id, run.run_id)
        request = replace(_request_record(agent, state), context_estimate=tokens.ContextEstimate(120, 100))
        attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, state.checkpoint.revision, request=request)
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
        assert "estimator_version" not in waiting.body.decode() and request.request_fingerprint not in waiting.body.decode()
    finally:
        app.close()


def test_retry_preserves_exact_provider_request_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: "2000-01-01T00:00:00Z")
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    request = _request_record(agent, initial)
    original = encode_provider_request(request)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, 1, request=request)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.fail_provider_attempt(session.session_id, run.run_id, claimed.checkpoint.revision,
        attempt.attempt_id, outcome_unknown=False, failure_code="provider_rejected", transient=True)
    reopened = FiguraRunStore(tmp_path)
    monkeypatch.setattr("figura.providers.client.estimate_input", lambda *_: pytest.fail("legacy binding was backfilled"))
    finished = _agent(reopened, coordinator, _registry(), _FakeFactory([_response()])).execute(session.session_id, run.run_id)
    assert finished.run.status.value == "completed"
    assert encode_provider_request(_agent_request(finished)) == original


def test_changed_capacity_does_not_rebase_recovered_request(tmp_path, monkeypatch, encoding):
    import figura.providers.config as config
    original = config._profile_from_env
    capacity = 100000
    monkeypatch.setattr(config, "_profile_from_env", lambda provider, env: replace(original(provider, env), context_window_tokens=capacity))
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: "2000-01-01T00:00:00Z")
    store, coordinator, session, run = _app(tmp_path)
    waiting = _agent(store, coordinator, _registry(), _FakeFactory([_temporary()])).execute_slice(session.session_id, run.run_id)
    request = _agent_request(waiting)
    assert request.context_estimate.context_window_tokens == 100000
    capacity = 200000
    reopened = FiguraRunStore(tmp_path)
    state = _agent(reopened, coordinator, _registry(), _FakeFactory([_response()])).execute(session.session_id, run.run_id)
    assert state.run.status.value == "completed"
    assert state.provider_requests == (request,)


def test_bad_estimate_claim_rolls_back_binding_and_attempt(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    request = replace(_request_record(agent, initial), context_estimate=tokens.ContextEstimate(-1, None))
    with pytest.raises(RunError):
        coordinator.begin_provider_attempt(session.session_id, run.run_id, 1, request=request)
    assert coordinator.read_run_state(session.session_id, run.run_id) == initial
