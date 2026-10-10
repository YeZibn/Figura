from __future__ import annotations

from tests.figura_sources_support import make_attachment_service, make_panel_service, make_execution_image_reader

import json
from figura.shared.payloads import ExecutionPayloadLimits
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from figura.agent.request import AgentRequestBuilder, _continuations_by_response
from figura.agent.execution_state import RunExecutionStateService
from figura.memory import AssistantMessage, MemoryToolCall
from figura.shared.json_schema import canonical_json_dumps
from figura.sources.chart_renders import FiguraChartRenderService
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
from figura.providers.errors import ProviderInputError
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunCreateRequest
from figura.runtime.records import RunInput, SessionContextCheckpoint
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
            "FIGURA_DEEPSEEK_API_KEY": "deepseek-secret",
            "FIGURA_DEEPSEEK_BASE_URL": "https://deepseek.example.test/v1",
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
    image_reader = make_execution_image_reader(
        selected_attachments,
        panels,
        FiguraChartRenderService(store.data_root),
    )
    return AgentRequestBuilder(
        execution_state,
        image_reader,
    )


def _image_registry(store, coordinator, attachments):
    panels = make_panel_service(store, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    return (
        panels,
        execution_state,
        ToolRegistry(
            "image-tools-v1",
            (*image_tool_definitions(execution_state.for_run, make_execution_image_reader(attachments, panels), panels), *_registry().definitions),
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


def _commit_text_response(
    coordinator,
    session_id: str,
    run_id: str,
    *,
    content: str,
    continuation: ProviderContinuation | None = None,
    provider_id: ProviderId = ProviderId.QWEN,
):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            provider_id,
            MODEL_IDS[provider_id],
            content,
            (),
            FinishReason.STOP,
            continuation=continuation,
        ),
        provider_attempt_id=attempt.attempt_id,
    )
    return coordinator.read_run_state(session_id, run_id)


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


def _execution_inventory(request) -> dict[str, object]:
    return json.loads(request.instructions[2].content.split("\n", 1)[1])


def test_initial_request_uses_run_selection_fixed_instruction_and_tool_projection(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()
    state = coordinator.read_run_state(session.session_id, run.run_id)

    request = _builder(store, coordinator).build(state, registry)

    assert request.provider_id is ProviderId.QWEN
    assert request.model_id == MODEL_IDS[ProviderId.QWEN]
    assert len(request.instructions) == 3
    assert all(instruction.role.value == "system" for instruction in request.instructions)
    assert request.instructions[0].content.startswith("# Figura 助手职责")
    assert request.instructions[1].content.startswith("当前可用工具说明")
    assert json.loads(request.instructions[1].content.split("\n", 1)[1]) == {
        "tools": [
            {"name": definition.name, "description": definition.description}
            for definition in registry
        ]
    }
    inventory = _execution_inventory(request)
    assert inventory == {"run_id": run.run_id, "resources": []}
    assert len(request.messages) == 1
    assert request.messages[0].role is MessageRole.USER
    assert request.messages[0].content == "请分析以下图表数据。"
    assert request.options.stream is False
    assert request.options.max_completion_tokens is None
    assert [tool.name for tool in request.tools] == ["inspect"]
    assert coordinator.read_run_state(session.session_id, run.run_id).records == state.records
    assert all(instruction.content not in repr(state.records) for instruction in request.instructions)


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
    inventory = _execution_inventory(request)
    resources = inventory["resources"]
    assert [item["ref"] for item in resources] == [
        {"kind": "attachment", "id": item.attachment_id}
        for item in attachments.list(session.session_id)
    ]
    filenames = [item["filename"] for item in resources]
    assert "image-0.png" in filenames and "image-1.png" in filenames
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
    filenames = [item["filename"] for item in _execution_inventory(request)["resources"]]
    assert "image-0.png" in filenames and "image-1.png" in filenames
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
    cues = [json.loads(block.text.split("\n")[1]) for block in image_message.content if isinstance(block, TextBlock)]
    assert len(cues) == 2
    assert [cue["feedback_kind"] for cue in cues] == ["original", "original"]
    assert [cue["trigger_call"]["call_id"] for cue in cues] == ["load-0", "load-1"]
    for index, image in enumerate(image_blocks):
        assert cues[index]["resource_ref"] == dict(image.source_ref)
    assert request == _builder(store, coordinator, attachments).build(state, registry)

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
    filenames = [item["filename"] for item in _execution_inventory(request)["resources"]]
    assert "image-0.png" in filenames
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


def test_request_replays_continuations_from_multiple_prior_runs_by_source_identity(tmp_path) -> None:
    _store, coordinator, session, first_run = _app(tmp_path)
    registry = _registry()
    first_tool_continuation = ProviderContinuation(
        ProviderId.QWEN, 1, "private first tool continuation"
    )
    _commit_tool_round(
        _store,
        coordinator,
        session,
        first_run,
        registry,
        call_id="first-run-tool",
        continuation=first_tool_continuation,
    )
    first_final_continuation = ProviderContinuation(
        ProviderId.QWEN, 1, "private first final continuation"
    )
    first_state = _commit_text_response(
        coordinator,
        session.session_id,
        first_run.run_id,
        content="第一轮的最终回答。",
        continuation=first_final_continuation,
    )
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
    second_continuation = ProviderContinuation(
        ProviderId.QWEN, 1, "private second run continuation"
    )
    second_state = _commit_text_response(
        coordinator,
        session.session_id,
        second_run.run_id,
        content="第二轮的最终回答。",
        continuation=second_continuation,
    )
    coordinator.complete_run(
        session.session_id, second_run.run_id, second_state.checkpoint.revision
    )
    target_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="第三轮输入。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-request-third-run",
        )
    )

    builder = _builder(_store, coordinator)
    request = builder.build(
        coordinator.read_run_state(session.session_id, target_run.run_id),
        registry,
        coordinator.read_prior_run_states(session.session_id, target_run.run_id),
    )

    assert [message.role for message in request.messages] == [
        MessageRole.USER,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    historical_inputs = json.loads(request.messages[0].content)
    assert historical_inputs["figura_context_type"] == "historical_user_inputs"
    assert historical_inputs["entries"] == [
        {
            "run_id": first_run.run_id,
            "run_ordinal": first_run.ordinal,
            "text": "请分析以下图表数据。",
            "attachment_ids": [],
            "source_ref": {
                "kind": "message",
                "run_id": first_run.run_id,
                "record_id": first_run.input_record_id,
            },
        },
        {
            "run_id": second_run.run_id,
            "run_ordinal": second_run.ordinal,
            "text": "第二轮输入。",
            "attachment_ids": [],
            "source_ref": {
                "kind": "message",
                "run_id": second_run.run_id,
                "record_id": second_run.input_record_id,
            },
        },
    ]
    assert json.loads(request.messages[1].content) == {
        "figura_context_type": "historical_run_context",
        "run_id": first_run.run_id,
        "run_ordinal": first_run.ordinal,
        "input_ref": historical_inputs["entries"][0]["source_ref"],
    }
    assert request.messages[2].continuation == first_tool_continuation
    assert request.messages[3].tool_call_id == "first-run-tool"
    assert request.messages[4].continuation == first_final_continuation
    assert json.loads(request.messages[5].content)["run_id"] == second_run.run_id
    assert request.messages[6].continuation == second_continuation
    assert request.messages[7].content == "第三轮输入。"
    assert all("第三轮输入。" not in item["text"] for item in historical_inputs["entries"])
    assert _execution_inventory(request)["resources"] == []

    target_state = _commit_text_response(
        coordinator,
        session.session_id,
        target_run.run_id,
        content="第三轮的最终回答。",
        continuation=ProviderContinuation(
            ProviderId.QWEN, 1, "private third run continuation"
        ),
    )
    coordinator.complete_run(
        session.session_id, target_run.run_id, target_state.checkpoint.revision
    )

    duplicated_state = replace(
        first_state,
        provider_continuations=(
            *first_state.provider_continuations,
            first_state.provider_continuations[0],
        ),
    )
    with pytest.raises(RunError) as duplicate_error:
        _continuations_by_response((duplicated_state,))
    assert duplicate_error.value.code is RunErrorCode.INTEGRITY_ERROR

    mismatched_fact = replace(
        first_state.provider_continuations[0], run_id="incorrect-source-run"
    )
    inconsistent_state = replace(
        first_state, provider_continuations=(mismatched_fact,)
    )
    with pytest.raises(RunError) as source_error:
        _continuations_by_response((inconsistent_state,))
    assert source_error.value.code is RunErrorCode.INTEGRITY_ERROR

    cross_provider_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="改用 DeepSeek 继续。",
            provider_id=ProviderId.DEEPSEEK.value,
            model_id=MODEL_IDS[ProviderId.DEEPSEEK],
            idempotency_key="agent-request-cross-provider-run",
        )
    )
    cross_provider_request = builder.build(
        coordinator.read_run_state(session.session_id, cross_provider_run.run_id),
        registry,
        coordinator.read_prior_run_states(session.session_id, cross_provider_run.run_id),
    )
    assert cross_provider_request.provider_id is ProviderId.DEEPSEEK
    assert all(
        message.continuation is None
        for message in cross_provider_request.messages
        if message.role is MessageRole.ASSISTANT
    )


def test_historical_user_input_and_ordered_attachments_survive_compaction_cutoff(tmp_path) -> None:
    store, coordinator, session, first_run, attachments = _app_with_attachments(
        tmp_path, (_image_bytes("red"), _image_bytes("blue"))
    )
    attachment_ids = tuple(
        item.attachment_id for item in attachments.list(session.session_id)
    )
    completed = _commit_text_response(
        coordinator,
        session.session_id,
        first_run.run_id,
        content="历史 Run 已完成。",
    )
    coordinator.complete_run(
        session.session_id, first_run.run_id, completed.checkpoint.revision
    )
    target_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请继续当前问题。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-request-after-compaction-cutoff",
        )
    )
    checkpoint = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=first_run.run_id,
        covered_run_ordinal=first_run.ordinal,
        covered_record_sequence=completed.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=completed.checkpoint.last_committed_tool_sequence,
        summary_contract_version=2,
        summary={"trust": "untrusted_history", "facts": []},
    )

    builder = _builder(store, coordinator, attachments)
    target_state = coordinator.read_run_state(session.session_id, target_run.run_id)
    request = builder.build(
        target_state,
        _registry(),
        coordinator.read_prior_run_states(session.session_id, target_run.run_id),
        context_checkpoint=checkpoint,
    )

    history = json.loads(request.messages[0].content)
    assert history["figura_context_type"] == "historical_user_inputs"
    assert history["entries"] == [{
        "run_id": first_run.run_id,
        "run_ordinal": first_run.ordinal,
        "text": "请分析这些图表。",
        "attachment_ids": list(attachment_ids),
        "source_ref": {
            "kind": "message",
            "run_id": first_run.run_id,
            "record_id": first_run.input_record_id,
        },
    }]
    assert [message.content for message in request.messages[1:]] == ["请继续当前问题。"]

    provider_factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    client = provider_factory.create(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN])
    complete_estimate = client.prepare(request).context_estimate
    without_history_inputs = replace(request, messages=request.messages[1:])
    current_only_estimate = client.prepare(without_history_inputs).context_estimate
    if complete_estimate is None or current_only_estimate is None:
        pytest.skip("local tiktoken encoding is unavailable")
    assert complete_estimate.input_tokens > current_only_estimate.input_tokens

    provider_factory.payload_limits = ExecutionPayloadLimits(
        _request_text_bytes(request) - 1
    )
    with pytest.raises(ProviderInputError):
        provider_factory.create(
            ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN]
        ).prepare(request)


def test_historical_input_section_keeps_duplicate_and_empty_text_as_distinct_runs(tmp_path) -> None:
    store, coordinator, session, first = _app(tmp_path)
    first_state = _commit_text_response(
        coordinator, session.session_id, first.run_id, content="完成第一轮。"
    )
    coordinator.complete_run(session.session_id, first.run_id, first_state.checkpoint.revision)
    second = coordinator.create_run(RunCreateRequest(
        session_id=session.session_id,
        text="请分析以下图表数据。",
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        idempotency_key="duplicate-historical-input",
    ))
    second_state = _commit_text_response(
        coordinator, session.session_id, second.run_id, content="完成第二轮。"
    )
    coordinator.complete_run(session.session_id, second.run_id, second_state.checkpoint.revision)
    third = coordinator.create_run(RunCreateRequest(
        session_id=session.session_id,
        text="将由已保存输入投影为空文本的历史 Run。",
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        idempotency_key="empty-historical-input",
    ))
    third_state = _commit_text_response(
        coordinator, session.session_id, third.run_id, content="完成第三轮。"
    )
    coordinator.complete_run(session.session_id, third.run_id, third_state.checkpoint.revision)
    third_complete = coordinator.read_run_state(session.session_id, third.run_id)
    target = coordinator.create_run(RunCreateRequest(
        session_id=session.session_id,
        text="当前问题",
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        idempotency_key="duplicate-empty-input-target",
    ))
    prior = coordinator.read_prior_run_states(session.session_id, target.run_id)
    third_input = replace(third_complete.records[0].payload, text="")
    assert isinstance(third_input, RunInput)
    prior = (*prior[:-1], replace(
        third_complete,
        records=(replace(third_complete.records[0], payload=third_input), *third_complete.records[1:]),
    ))

    request = _builder(store, coordinator).build(
        coordinator.read_run_state(session.session_id, target.run_id),
        _registry(),
        prior,
    )

    payload = json.loads(request.messages[0].content)
    assert [entry["text"] for entry in payload["entries"]] == [
        "请分析以下图表数据。",
        "请分析以下图表数据。",
        "",
    ]
    assert [entry["run_ordinal"] for entry in payload["entries"]] == [1, 2, 3]
    assert request.messages[-1].content == "当前问题"


def test_request_keeps_fully_resolved_history_from_a_prior_registry_version(tmp_path) -> None:
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

    request = _builder(store, coordinator).build(state, changed)

    assert request.messages[1].tool_calls[0].name == "inspect"
    assert request.messages[2].role is MessageRole.TOOL
    assert request.messages[2].tool_call_id == "call-registry"


def test_request_fails_closed_for_unresolved_call_from_an_older_registry_version(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    builder = _builder(store, coordinator)
    unresolved = AssistantMessage(
        run_id="prior-run",
        run_ordinal=1,
        source_record_id="prior-response",
        content="",
        tool_calls=(MemoryToolCall(
            "old-pie-call",
            "extract_pie_slices",
            '{"image_path":"/private/chart.png"}',
            0,
            "figura-web-v3",
        ),),
    )

    with pytest.raises(RunError) as error:
        builder._provider_messages(
            (unresolved,),
            selected_provider=ProviderId.QWEN,
            continuations={},
            registry=_registry(version="figura-web-v4"),
            historical_inputs={},
        )

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
    original_records = second_state.records
    original_tool_facts = second_state.tool_facts
    request = builder.build(second_state, registry)
    provider_factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    provider_factory.payload_limits = ExecutionPayloadLimits(full_bytes - 1)
    client = provider_factory.create(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN])
    with pytest.raises(ProviderInputError):
        client.prepare(request)
    unchanged = coordinator.read_run_state(session.session_id, run.run_id)
    assert unchanged.records == original_records
    assert unchanged.tool_facts == original_tool_facts
