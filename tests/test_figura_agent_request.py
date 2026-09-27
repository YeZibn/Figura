from __future__ import annotations

from dataclasses import replace

import pytest

import figura.agent.request as request_module
from figura.agent.request import AgentRequestBuilder
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    MessageRole,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.runtime import (
    ActionKind,
    DurableToolExecutor,
    FiguraRunStore,
    RunCoordinator,
    RunCreateRequest,
    RunError,
    RunErrorCode,
)
from figura.tools import ReplayEffect, ToolDefinition, ToolFailure, ToolRegistry


def _registry(*, version: str = "registry-v1") -> ToolRegistry:
    def handler(_context, arguments):
        if arguments["value"] == 2:
            raise ToolFailure("inspection_failed", "无法读取该值。", retryable=True)
        return {"value": arguments["value"]}

    return ToolRegistry(
        version,
        (
            ToolDefinition(
                name="inspect",
                description="Inspect a value.",
                parameters_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                result_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                replay_effect=ReplayEffect.REPLAY_SAFE,
                handler=handler,
            ),
        ),
    )


def _app(tmp_path):
    store = FiguraRunStore(tmp_path)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    coordinator = RunCoordinator(store, factory)
    session = coordinator.create_session()
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请分析以下图表数据。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-request-test",
        )
    )
    return store, coordinator, session, run


def _commit_tool_round(
    store,
    coordinator,
    session,
    run,
    registry: ToolRegistry,
    *,
    call_id: str,
    value: int = 1,
    content: str = "准备调用工具。",
    continuation: ProviderContinuation | None = None,
):
    state = coordinator.read_run_state(session.session_id, run.run_id)
    attempt = coordinator.begin_provider_attempt(
        session.session_id, run.run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    response = ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content=content,
        tool_calls=(ProviderToolCall(call_id, "inspect", f'{{"value":{value}}}'),),
        finish_reason=FinishReason.TOOL_CALLS,
        continuation=continuation,
    )
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        claimed.checkpoint.revision,
        response,
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )
    executor = DurableToolExecutor(store, registry)
    return executor.execute_pending(session.session_id, run.run_id)


def _request_text_bytes(request) -> int:
    total = sum(len(instruction.content.encode("utf-8")) for instruction in request.instructions)
    for message in request.messages:
        if isinstance(message.content, str):
            total += len(message.content.encode("utf-8"))
        total += sum(len(call.arguments.encode("utf-8")) for call in message.tool_calls)
        if message.continuation is not None:
            total += len(message.continuation.reasoning_content.encode("utf-8"))
    for tool in request.tools:
        total += len(tool.description.encode("utf-8"))
        total += len(request_module.canonical_json_dumps(tool.parameters).encode("utf-8"))
    return total


def test_initial_request_uses_run_selection_fixed_instruction_and_tool_projection(tmp_path) -> None:
    _store, coordinator, session, run = _app(tmp_path)
    registry = _registry()

    request = AgentRequestBuilder().build(
        coordinator.read_run_state(session.session_id, run.run_id), registry
    )

    assert request.provider_id is ProviderId.QWEN
    assert request.model_id == MODEL_IDS[ProviderId.QWEN]
    assert request.instructions[0].role.value == "system"
    assert request.instructions[0].content.startswith("你是 Figura 的图表分析助手")
    assert len(request.messages) == 1
    assert request.messages[0].role is MessageRole.USER
    assert request.messages[0].content == "请分析以下图表数据。"
    assert request.options.stream is False
    assert request.options.max_completion_tokens == 4096
    assert [tool.name for tool in request.tools] == ["inspect"]


def test_request_rebuilds_tool_round_in_order_and_attaches_continuation(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()
    continuation = ProviderContinuation(ProviderId.QWEN, 1, "private continuation")
    state = _commit_tool_round(
        store,
        coordinator,
        session,
        run,
        registry,
        call_id="call-success",
        value=1,
        continuation=continuation,
    )
    # A second call in the same provider batch proves serial observations retain
    # their exact call IDs, including a safe structured tool failure.
    started = coordinator.begin_provider_attempt(
        session.session_id, run.run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    response = ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content="先后检查两个值。",
        tool_calls=(
            ProviderToolCall("call-first", "inspect", '{"value":1}'),
            ProviderToolCall("call-second", "inspect", '{"value":2}'),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        claimed.checkpoint.revision,
        response,
        provider_attempt_id=started.attempt_id,
        registry_version=registry.version,
    )
    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)

    request = AgentRequestBuilder().build(state, registry)

    assert [message.role for message in request.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
    ]
    assert request.messages[1].continuation == continuation
    assert [call.call_id for call in request.messages[3].tool_calls] == [
        "call-first",
        "call-second",
    ]
    assert [message.tool_call_id for message in request.messages[4:]] == [
        "call-first",
        "call-second",
    ]
    assert request.messages[4].content == '{"outcome":"succeeded","result":{"value":1}}'
    assert request.messages[5].content == (
        '{"error":{"code":"inspection_failed","message":"无法读取该值。",'
        '"retryable":true},"outcome":"failed"}'
    )


def test_request_fails_closed_when_recorded_registry_is_unavailable(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    original = _registry()
    changed = _registry(version="registry-v2")
    state = _commit_tool_round(
        store,
        coordinator,
        session,
        run,
        original,
        call_id="call-registry",
    )

    with pytest.raises(RunError) as error:
        AgentRequestBuilder().build(state, changed)

    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_request_trims_only_old_complete_rounds_and_fails_when_newest_cannot_fit(
    tmp_path, monkeypatch
) -> None:
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()
    first_state = _commit_tool_round(
        store,
        coordinator,
        session,
        run,
        registry,
        call_id="call-old",
        content="o" * 700,
    )
    first_request = AgentRequestBuilder().build(first_state, registry)
    second_state = _commit_tool_round(
        store,
        coordinator,
        session,
        run,
        registry,
        call_id="call-new",
        content="n" * 700,
    )
    full_request = AgentRequestBuilder().build(second_state, registry)
    base_bytes = _request_text_bytes(
        replace(first_request, messages=first_request.messages[:1])
    )
    newest_round = full_request.messages[-2:]
    newest_bytes = _request_text_bytes(
        replace(full_request, messages=(full_request.messages[0], *newest_round))
    )
    full_bytes = _request_text_bytes(full_request)
    assert full_bytes > newest_bytes
    threshold = (newest_bytes + full_bytes) // 2
    assert base_bytes < threshold
    monkeypatch.setattr(request_module, "MAX_TOTAL_TEXT_BYTES", threshold)

    trimmed = AgentRequestBuilder().build(second_state, registry)

    assert [call.call_id for message in trimmed.messages for call in message.tool_calls] == [
        "call-new"
    ]
    assert trimmed.messages[0].role is MessageRole.USER
    monkeypatch.setattr(request_module, "MAX_TOTAL_TEXT_BYTES", newest_bytes - 1)
    with pytest.raises(RunError) as error:
        AgentRequestBuilder().build(second_state, registry)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
