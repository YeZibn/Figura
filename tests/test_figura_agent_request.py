from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from figura.attachments import FiguraAttachmentService
from figura.agent.request import AgentRequestBuilder
from figura.json_schema import canonical_json_dumps
import figura.providers.validation as provider_validation
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ImageBlock,
    MessageRole,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
    TextBlock,
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


def _image_bytes(color: str) -> bytes:
    content = BytesIO()
    Image.new("RGB", (2, 2), color=color).save(content, format="PNG")
    return content.getvalue()


def _app_with_attachments(tmp_path, image_contents: tuple[bytes, ...]):
    store = FiguraRunStore(tmp_path)
    attachments = FiguraAttachmentService(store)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    coordinator = RunCoordinator(store, factory)
    session = coordinator.create_session()
    metadata = tuple(
        attachments.upload(session.session_id, f"image-{index}.png", content)
        for index, content in enumerate(image_contents)
    )
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请分析这些图表。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-request-image-test",
            attachment_ids=tuple(item.attachment_id for item in metadata),
        )
    )
    return store, coordinator, session, run, attachments


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
        total += len(canonical_json_dumps(tool.parameters).encode("utf-8"))
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


def test_request_resolves_images_in_persisted_order_after_user_text(tmp_path) -> None:
    first_image = _image_bytes("red")
    second_image = _image_bytes("blue")
    _store, coordinator, session, run, attachments = _app_with_attachments(
        tmp_path, (first_image, second_image)
    )

    request = AgentRequestBuilder(attachments).build(
        coordinator.read_run_state(session.session_id, run.run_id), _registry()
    )

    blocks = request.messages[0].content
    assert isinstance(blocks, tuple)
    assert blocks[0] == TextBlock("请分析这些图表。")
    assert blocks[1:] == (
        ImageBlock("image/png", first_image),
        ImageBlock("image/png", second_image),
    )


def test_request_rebuilds_the_original_images_after_a_tool_round(tmp_path) -> None:
    first_image = _image_bytes("green")
    second_image = _image_bytes("yellow")
    store, coordinator, session, run, attachments = _app_with_attachments(
        tmp_path, (first_image, second_image)
    )
    state = _commit_tool_round(
        store,
        coordinator,
        session,
        run,
        _registry(),
        call_id="call-image-round",
    )

    request = AgentRequestBuilder(attachments).build(state, _registry())

    assert request.messages[0].content == (
        TextBlock("请分析这些图表。"),
        ImageBlock("image/png", first_image),
        ImageBlock("image/png", second_image),
    )
    assert request.messages[1].role is MessageRole.ASSISTANT


def test_request_with_attachments_requires_an_injected_session_resolver(tmp_path) -> None:
    _store, coordinator, session, run, _attachments = _app_with_attachments(
        tmp_path, (_image_bytes("red"),)
    )

    with pytest.raises(RunError) as error:
        AgentRequestBuilder().build(
            coordinator.read_run_state(session.session_id, run.run_id), _registry()
        )

    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


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


def test_request_includes_complete_prior_run_history_without_prior_continuation(tmp_path) -> None:
    _store, coordinator, session, first_run = _app(tmp_path)
    continuation = ProviderContinuation(ProviderId.QWEN, 1, "private old continuation")
    state = coordinator.read_run_state(session.session_id, first_run.run_id)
    attempt = coordinator.begin_provider_attempt(
        session.session_id, first_run.run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session.session_id, first_run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        first_run.run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "第一轮的完整回答。",
            (),
            FinishReason.STOP,
            continuation=continuation,
        ),
        provider_attempt_id=attempt.attempt_id,
    )
    first_state = coordinator.read_run_state(session.session_id, first_run.run_id)
    coordinator.complete_run(
        session.session_id, first_run.run_id, first_state.checkpoint.revision
    )
    second_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="第二轮输入。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-request-second-run",
        )
    )

    request = AgentRequestBuilder().build(
        coordinator.read_run_state(session.session_id, second_run.run_id),
        _registry(),
        coordinator.read_prior_run_states(session.session_id, second_run.run_id),
    )

    assert [message.role for message in request.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert request.messages[0].content == "请分析以下图表数据。"
    assert request.messages[1].content == "第一轮的完整回答。"
    assert request.messages[1].continuation is None
    assert request.messages[2].content == "第二轮输入。"


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


def test_request_preserves_all_complete_rounds_and_fails_when_history_cannot_fit(
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
    builder = AgentRequestBuilder()
    first_request = builder.build(first_state, registry)
    second_state = _commit_tool_round(
        store,
        coordinator,
        session,
        run,
        registry,
        call_id="call-new",
        content="n" * 700,
    )
    full_request = builder.build(second_state, registry)
    first_call_ids = [call.call_id for message in first_request.messages for call in message.tool_calls]
    assert first_call_ids == ["call-old"]
    full_call_ids = [call.call_id for message in full_request.messages for call in message.tool_calls]
    assert full_call_ids == ["call-old", "call-new"]
    full_bytes = _request_text_bytes(full_request)
    monkeypatch.setattr(provider_validation, "MAX_TOTAL_TEXT_BYTES", full_bytes - 1)
    with pytest.raises(RunError) as error:
        builder.build(second_state, registry)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
