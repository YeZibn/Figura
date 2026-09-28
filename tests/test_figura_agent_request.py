from __future__ import annotations

from tests.figura_sources_support import make_attachment_service, make_panel_service

import json
from io import BytesIO

import pytest
from PIL import Image

from figura.agent.request import AgentRequestBuilder
from figura.agent.execution_state import RunExecutionStateService
from figura.shared.json_schema import canonical_json_dumps
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
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunCreateRequest
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.tools import ReplayEffect, ToolDefinition, ToolFailure, ToolRegistry
from figura.tools.implementations.image import image_tool_definitions


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
    attachments = make_attachment_service(store)
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


def _builder(store, coordinator, attachments=None) -> AgentRequestBuilder:
    selected_attachments = attachments or make_attachment_service(store)
    panels = make_panel_service(store, selected_attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    return AgentRequestBuilder(selected_attachments, execution_state)


def _image_registry(store, coordinator, attachments):
    panels = make_panel_service(store, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    return (
        panels,
        execution_state,
        ToolRegistry(
            "image-tools-v1",
            (*image_tool_definitions(execution_state.for_run, attachments, panels), *_registry().definitions),
        ),
    )


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


def _commit_tool_calls(store, coordinator, session, run, registry, calls):
    state = coordinator.read_run_state(session.session_id, run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "显式读取图像。",
            tuple(calls),
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )
    return DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)


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
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()

    request = _builder(store, coordinator).build(
        coordinator.read_run_state(session.session_id, run.run_id), registry
    )

    assert request.provider_id is ProviderId.QWEN
    assert request.model_id == MODEL_IDS[ProviderId.QWEN]
    assert request.instructions[0].role.value == "system"
    assert request.instructions[0].content.startswith("你是 Figura 的图表分析助手")
    assert len(request.messages) == 2
    assert request.messages[0].role is MessageRole.USER
    assert request.messages[0].content == "请分析以下图表数据。"
    assert "无可用附件" in request.messages[1].content
    assert request.options.stream is False
    assert request.options.max_completion_tokens == 4096
    assert [tool.name for tool in request.tools] == ["inspect"]


def test_initial_request_lists_images_without_resolving_or_sending_bytes(tmp_path) -> None:
    first_image = _image_bytes("red")
    second_image = _image_bytes("blue")
    _store, coordinator, session, run, attachments = _app_with_attachments(
        tmp_path, (first_image, second_image)
    )

    request = _builder(_store, coordinator, attachments).build(
        coordinator.read_run_state(session.session_id, run.run_id), _registry()
    )

    attachment_ids = [item.attachment_id for item in attachments.list(session.session_id)]
    assert request.messages[0].content == (
        f"请分析这些图表。\n\n本条消息附件 ID：{', '.join(attachment_ids)}"
    )
    inventory = request.messages[-1].content
    assert "image-0.png" in inventory and "image-1.png" in inventory
    assert all(not isinstance(block, ImageBlock) for message in request.messages for block in (message.content if isinstance(message.content, tuple) else ()))


def test_request_does_not_resend_original_images_after_an_unrelated_tool_round(tmp_path) -> None:
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

    request = _builder(store, coordinator, attachments).build(state, _registry())

    assert all(not isinstance(block, ImageBlock) for message in request.messages for block in (message.content if isinstance(message.content, tuple) else ()))
    assert "image-0.png" in request.messages[-1].content
    assert request.messages[1].role is MessageRole.ASSISTANT


def test_latest_load_batch_attaches_multiple_images_once_in_tool_order(tmp_path) -> None:
    first_image = _image_bytes("red")
    second_image = _image_bytes("blue")
    store, coordinator, session, run, attachments = _app_with_attachments(
        tmp_path, (first_image, second_image)
    )
    _panels, _execution_state, registry = _image_registry(store, coordinator, attachments)
    attachment_ids = [item.attachment_id for item in attachments.list(session.session_id)]
    loads = [
        ProviderToolCall(f"load-{index}", "load_image", json.dumps({"source_kind": "attachment", "source_id": attachment_id}))
        for index, attachment_id in enumerate((attachment_ids[1], attachment_ids[0], attachment_ids[1]))
    ]
    state = _commit_tool_calls(store, coordinator, session, run, registry, loads)

    request = _builder(store, coordinator, attachments).build(state, registry)
    image_message = request.messages[-1]
    assert image_message.role is MessageRole.USER
    assert isinstance(image_message.content, tuple)
    image_blocks = [block for block in image_message.content if isinstance(block, ImageBlock)]
    assert image_blocks == [ImageBlock("image/png", second_image), ImageBlock("image/png", first_image)]
    assert sum("已加载图像" in block.text for block in image_message.content if isinstance(block, TextBlock)) == 2

    later_state = _commit_tool_round(
        store, coordinator, session, run, registry, call_id="later-inspect", value=1
    )
    later_request = _builder(store, coordinator, attachments).build(later_state, registry)
    assert all(
        not isinstance(block, ImageBlock)
        for message in later_request.messages
        for block in (message.content if isinstance(message.content, tuple) else ())
    )


def test_request_with_attachments_uses_inventory_without_a_legacy_image_mode(tmp_path) -> None:
    store, coordinator, session, run, attachments = _app_with_attachments(
        tmp_path, (_image_bytes("red"),)
    )

    request = _builder(store, coordinator, attachments).build(
        coordinator.read_run_state(session.session_id, run.run_id), _registry()
    )
    assert "image-0.png" in request.messages[-1].content
    assert all(not isinstance(message.content, tuple) for message in request.messages)


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

    request = _builder(store, coordinator).build(state, registry)

    assert [message.role for message in request.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
        MessageRole.USER,
    ]
    assert request.messages[1].continuation == continuation
    assert [call.call_id for call in request.messages[3].tool_calls] == [
        "call-first",
        "call-second",
    ]
    assert [message.tool_call_id for message in request.messages[4:6]] == [
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

    request = _builder(_store, coordinator).build(
        coordinator.read_run_state(session.session_id, second_run.run_id),
        _registry(),
        coordinator.read_prior_run_states(session.session_id, second_run.run_id),
    )

    assert [message.role for message in request.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.USER,
    ]
    assert request.messages[0].content == "请分析以下图表数据。"
    assert request.messages[1].content == "第一轮的完整回答。"
    assert request.messages[1].continuation is None
    assert request.messages[2].content == "第二轮输入。"
    assert "无可用附件" in request.messages[3].content


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
        _builder(store, coordinator).build(state, changed)

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
    builder = _builder(store, coordinator)
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
