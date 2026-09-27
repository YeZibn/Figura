from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from figura.attachments import FiguraAttachmentService
from figura.memory import (
    AssistantMessage,
    MemoryToolCall,
    ToolMessage,
    UserMessage,
    project_run_messages,
    project_session_history,
)
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.runtime import (
    DurableToolExecutor,
    FiguraRunStore,
    RunCoordinator,
    RunCreateRequest,
    RunError,
    RunErrorCode,
)
from figura.tools import ReplayEffect, ToolDefinition, ToolFailure, ToolRegistry


def _app(tmp_path):
    store = FiguraRunStore(tmp_path)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    return store, RunCoordinator(store, factory)


def _create_run(coordinator, session_id: str, key: str, text: str, attachment_ids=()):
    return coordinator.create_run(
        RunCreateRequest(
            session_id=session_id,
            text=text,
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key=key,
            attachment_ids=tuple(attachment_ids),
        )
    )


def _commit_response(coordinator, session_id: str, run_id: str, response, *, registry_version=None):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        response,
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry_version,
    )
    return coordinator.read_run_state(session_id, run_id)


def _complete_text_run(coordinator, session_id: str, run_id: str, *, continuation=None):
    state = _commit_response(
        coordinator,
        session_id,
        run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "已完成分析。",
            (),
            FinishReason.STOP,
            continuation=continuation,
        ),
    )
    coordinator.complete_run(session_id, run_id, state.checkpoint.revision)
    return coordinator.read_run_state(session_id, run_id)


def _registry() -> ToolRegistry:
    def inspect(_context, arguments):
        if arguments["value"] == 2:
            raise ToolFailure("inspection_failed", "无法读取该值。", retryable=True)
        return {"value": arguments["value"]}

    return ToolRegistry(
        "registry-v1",
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
                handler=inspect,
            ),
        ),
    )


def _image_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color=color).save(output, format="PNG")
    return output.getvalue()


def test_session_history_preserves_run_order_scope_and_input_attachments(tmp_path) -> None:
    store, coordinator = _app(tmp_path)
    attachments = FiguraAttachmentService(store)
    session = coordinator.create_session()
    other_session = coordinator.create_session()
    first_image = attachments.upload(session.session_id, "first.png", _image_bytes("red"))
    second_image = attachments.upload(session.session_id, "second.png", _image_bytes("blue"))

    first = _create_run(
        coordinator,
        session.session_id,
        "memory-first",
        "第一轮输入。",
        (second_image.attachment_id, first_image.attachment_id),
    )
    _complete_text_run(coordinator, session.session_id, first.run_id)
    unrelated = _create_run(coordinator, other_session.session_id, "memory-other", "其他会话。")
    target = _create_run(coordinator, session.session_id, "memory-target", "当前输入。")

    prior_states = coordinator.read_prior_run_states(session.session_id, target.run_id)
    history = project_session_history(target, prior_states)

    assert history.session_id == session.session_id
    assert history.target_run_id == target.run_id
    assert history.target_run_ordinal == 2
    assert [message.run_id for message in history.messages] == [first.run_id, first.run_id]
    user_message = history.messages[0]
    assert isinstance(user_message, UserMessage)
    assert user_message.text == "第一轮输入。"
    assert user_message.attachment_ids == (second_image.attachment_id, first_image.attachment_id)
    assert unrelated.run_id not in {message.run_id for message in history.messages}


def test_project_run_messages_maps_tool_calls_results_and_final_answer_once(tmp_path) -> None:
    store, coordinator = _app(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "memory-tools", "检查两个值。")
    registry = _registry()

    _commit_response(
        coordinator,
        session.session_id,
        run.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "依次检查两个值。",
            (
                ProviderToolCall("call-ok", "inspect", '{"value":1}'),
                ProviderToolCall("call-failed", "inspect", '{"value":2}'),
            ),
            FinishReason.TOOL_CALLS,
        ),
        registry_version=registry.version,
    )
    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)
    final_state = _commit_response(
        coordinator,
        session.session_id,
        run.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "两个值均已检查。",
            (),
            FinishReason.STOP,
        ),
    )
    coordinator.complete_run(session.session_id, run.run_id, final_state.checkpoint.revision)
    completed = coordinator.read_run_state(session.session_id, run.run_id)

    messages = project_run_messages(completed)

    assert [type(message) for message in messages] == [
        UserMessage,
        AssistantMessage,
        ToolMessage,
        ToolMessage,
        AssistantMessage,
    ]
    assistant = messages[1]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.content == "依次检查两个值。"
    assert assistant.tool_calls == (
        MemoryToolCall("call-ok", "inspect", '{"value":1}', 0, registry.version),
        MemoryToolCall("call-failed", "inspect", '{"value":2}', 1, registry.version),
    )
    assert [message.tool_call_id for message in messages[2:4] if isinstance(message, ToolMessage)] == [
        "call-ok",
        "call-failed",
    ]
    assert messages[2].content == '{"outcome":"succeeded","result":{"value":1}}'
    assert messages[3].content == (
        '{"error":{"code":"inspection_failed","message":"无法读取该值。",'
        '"retryable":true},"outcome":"failed"}'
    )
    assert messages[-1].content == "两个值均已检查。"
    assert len([message for message in messages if isinstance(message, AssistantMessage)]) == 2
    assert state.checkpoint.next_action is not None


def test_prior_continuation_is_not_projected_to_a_later_run(tmp_path) -> None:
    _store, coordinator = _app(tmp_path)
    session = coordinator.create_session()
    first = _create_run(coordinator, session.session_id, "memory-continuation", "第一轮。")
    _complete_text_run(
        coordinator,
        session.session_id,
        first.run_id,
        continuation=ProviderContinuation(ProviderId.QWEN, 1, "private prior continuation"),
    )
    target = _create_run(coordinator, session.session_id, "memory-next", "下一轮。")

    history = project_session_history(
        target,
        coordinator.read_prior_run_states(session.session_id, target.run_id),
    )

    assistant = history.messages[1]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.content == "已完成分析。"
    assert not hasattr(assistant, "continuation")
    assert "private prior continuation" not in repr(history)


def test_incomplete_tool_batch_cannot_be_projected_as_run_history(tmp_path) -> None:
    _store, coordinator = _app(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "memory-incomplete", "检查数值。")
    _commit_response(
        coordinator,
        session.session_id,
        run.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "准备检查。",
            (ProviderToolCall("call-pending", "inspect", '{"value":1}'),),
            FinishReason.TOOL_CALLS,
        ),
        registry_version="registry-v1",
    )

    with pytest.raises(RunError) as incomplete:
        project_run_messages(coordinator.read_run_state(session.session_id, run.run_id))

    assert incomplete.value.code is RunErrorCode.INVALID_TRANSITION
