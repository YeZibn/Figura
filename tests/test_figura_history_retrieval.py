from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from tests.figura_sources_support import (
    make_attachment_service,
    make_execution_image_reader,
    make_panel_service,
)

from figura.agent.execution_resources import (
    AttachmentContent,
    ChartRenderContent,
    ExecutionResource,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.request import AgentRequestBuilder
from figura.agent.prompting.observations import build_observation_messages
from figura.memory.retrieval import SessionHistorySearch, resource_ref_to_dict
from figura.providers import ImageBlock
from figura.tools.implementations.history import (
    history_tool_definitions,
    historical_image_tool_definition,
)
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunCreateRequest
from figura.runtime.records import SessionContextCheckpoint
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.shared.source_refs import MessageSourceRef, ToolResultSourceRef
from figura.sources.repository import SourcesRepository
from figura.tools import ReplayEffect, ToolDefinition, ToolFailure, ToolOutcome, ToolRegistry
from figura.tools.contracts import ToolContext


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
    attachments = make_attachment_service(store)
    panels = make_panel_service(store, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    image_reader = make_execution_image_reader(attachments, panels)
    return (
        store,
        coordinator,
        SessionHistorySearch(coordinator, execution_state),
        image_reader,
        execution_state,
    )


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
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
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


def _complete_text(coordinator, session_id: str, run_id: str, answer: str = "预算历史回答"):
    state = _commit_response(
        coordinator,
        session_id,
        run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            answer,
            (),
            FinishReason.STOP,
        ),
    )
    coordinator.complete_run(session_id, run_id, state.checkpoint.revision)
    return coordinator.read_run_state(session_id, run_id)


def _image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color="navy").save(buffer, format="PNG")
    return buffer.getvalue()


def test_search_pages_and_reads_source_messages_without_cross_session_content(tmp_path):
    _store, coordinator, history, _image_reader, _execution_state = _app(tmp_path)
    session = coordinator.create_session()
    unrelated_session = coordinator.create_session()
    first = _create_run(coordinator, session.session_id, "history-first", "预算历史输入")
    first_state = _complete_text(coordinator, session.session_id, first.run_id)
    target = _create_run(coordinator, session.session_id, "history-target", "查询当前预算")
    unrelated = _create_run(coordinator, unrelated_session.session_id, "history-other", "私密预算")

    first_page = history.search(
        session.session_id,
        target.run_id,
        "预算",
        page_size=1,
        run_id=first.run_id,
        source_kind="message",
    )
    assert first_page["has_more"] is True
    first_match = first_page["matches"][0]
    assert first_match["reference"] == MessageSourceRef(
        first.run_id, first_state.records[0].record_id
    ).to_dict()
    read = history.read(session.session_id, target.run_id, first_match["reference"])
    assert read["trust"] == "untrusted_history"
    assert read["content"]["content"] == "预算历史输入"

    second_page = history.search(
        session.session_id,
        target.run_id,
        "预算",
        page_size=1,
        cursor=first_page["next_cursor"],
        run_id=first.run_id,
        source_kind="message",
    )
    assert len(second_page["matches"]) == 1
    assert second_page["matches"][0]["reference"]["run_id"] == first.run_id
    with pytest.raises(RunError) as error:
        history.read(
            session.session_id,
            target.run_id,
            MessageSourceRef(unrelated.run_id, "missing-record").to_dict(),
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    with pytest.raises(RunError) as error:
        history.search(
            session.session_id,
            target.run_id,
            "预算",
            cursor=first_page["next_cursor"],
            run_id=unrelated.run_id,
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_search_and_read_exclude_later_runs_from_completed_target_prefix(tmp_path):
    _store, coordinator, history, _image_reader, _execution_state = _app(tmp_path)
    session = coordinator.create_session()
    first = _create_run(coordinator, session.session_id, "prefix-first", "早期决策")
    _complete_text(coordinator, session.session_id, first.run_id, "早期结论")
    target = _create_run(coordinator, session.session_id, "prefix-target", "中间问题")
    target_state = _complete_text(coordinator, session.session_id, target.run_id, "中间结论")
    later = _create_run(coordinator, session.session_id, "prefix-later", "未来秘密")

    result = history.search(session.session_id, target.run_id, "未来秘密")
    assert result["matches"] == []
    with pytest.raises(RunError) as error:
        history.read(
            session.session_id,
            target.run_id,
            MessageSourceRef(later.run_id, later.input_record_id).to_dict(),
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert history.read(
        session.session_id,
        target.run_id,
        MessageSourceRef(target.run_id, target_state.records[0].record_id).to_dict(),
    )["content"]["content"] == "中间问题"


def test_history_tools_use_the_durable_current_run_audit_path(tmp_path):
    store, coordinator, history, _image_reader, _execution_state = _app(tmp_path)
    session = coordinator.create_session()
    source = _create_run(coordinator, session.session_id, "audit-source", "历史预算问题")
    _complete_text(coordinator, session.session_id, source.run_id, "历史预算回答")
    target = _create_run(coordinator, session.session_id, "audit-target", "触发查询")
    registry = ToolRegistry("history-tools-v2", history_tool_definitions(history))

    _commit_response(
        coordinator,
        session.session_id,
        target.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "查找历史预算。",
            (ProviderToolCall("search-audit-call", "search_history", '{"query":"预算"}'),),
            FinishReason.TOOL_CALLS,
        ),
        registry_version=registry.version,
    )
    state = DurableToolExecutor(store, registry).execute_pending(
        session.session_id, target.run_id
    )
    result_facts = [
        fact.payload for fact in state.tool_facts
        if fact.fact_kind.value == "tool_result"
    ]

    assert len(result_facts) == 1
    assert result_facts[0].outcome.value == "succeeded"
    assert result_facts[0].result["trust"] == "untrusted_history"
    assert any(
        match["reference"]["run_id"] == source.run_id
        for match in result_facts[0].result["matches"]
    )
    assert state.checkpoint.last_committed_tool_sequence == 3


def test_search_reads_committed_tool_result_without_reexecution(tmp_path):
    store, coordinator, history, _image_reader, _execution_state = _app(tmp_path)
    session = coordinator.create_session()

    def inspect(_context: ToolContext, _arguments):
        return {"value": 42, "note": "已提交观察"}

    registry = ToolRegistry(
        "history-tools-v1",
        (
            ToolDefinition(
                "inspect",
                "读取一个值。",
                {"type": "object", "properties": {}, "additionalProperties": False},
                {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"},
                        "note": {"type": "string"},
                    },
                    "required": ["value", "note"],
                    "additionalProperties": False,
                },
                ReplayEffect.REPLAY_SAFE,
                inspect,
            ),
        ),
    )
    run = _create_run(coordinator, session.session_id, "history-result", "查看预算数值")
    _commit_response(
        coordinator,
        session.session_id,
        run.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "检查结果。",
            (ProviderToolCall("historical-call", "inspect", "{}"),),
            FinishReason.TOOL_CALLS,
        ),
        registry_version=registry.version,
    )
    DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)
    after_tool = store.read_run_state(session.session_id, run.run_id)
    _commit_response(
        coordinator,
        session.session_id,
        run.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "数值已检查。",
            (),
            FinishReason.STOP,
        ),
    )
    final = store.read_run_state(session.session_id, run.run_id)
    coordinator.complete_run(session.session_id, run.run_id, final.checkpoint.revision)
    completed = store.read_run_state(session.session_id, run.run_id)
    target = _create_run(coordinator, session.session_id, "history-result-target", "继续分析")

    found = history.search(
        session.session_id, target.run_id, "已提交观察", source_kind="tool_result"
    )
    reference = found["matches"][0]["reference"]
    assert reference == ToolResultSourceRef(run.run_id, "historical-call").to_dict()
    result = history.read(session.session_id, target.run_id, reference)
    assert result["status"] == "committed"
    assert result["content"]["result"] == {"note": "已提交观察", "value": 42}
    assert len(after_tool.tool_facts) == 3
    assert store.read_run_state(session.session_id, run.run_id) == completed


def test_abnormal_unstarted_tool_call_is_searchable_as_not_started(tmp_path):
    _store, coordinator, history, _image_reader, _execution_state = _app(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "history-abnormal", "测量前中断")
    state = _commit_response(
        coordinator,
        session.session_id,
        run.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "接下来测量预算。",
            (ProviderToolCall("unstarted-call", "inspect", "{}"),),
            FinishReason.TOOL_CALLS,
        ),
        registry_version="history-tools-v1",
    )
    coordinator.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
    target = _create_run(coordinator, session.session_id, "history-abnormal-target", "恢复分析")

    result = history.search(session.session_id, target.run_id, "预算", source_kind="tool_result")
    match = next(item for item in result["matches"] if item["reference"]["call_id"] == "unstarted-call")
    assert match["outcome"] == "not_started"
    read = history.read(session.session_id, target.run_id, match["reference"])
    assert read["status"] == "unresolved"
    assert read["call_state"] == "not_started"
    assert read["content"] is None


def test_image_search_returns_typed_attachment_reference_and_verified_bytes(tmp_path):
    store, coordinator, history, image_reader, _execution_state = _app(tmp_path)
    attachments = make_attachment_service(store)
    session = coordinator.create_session()
    attachment = attachments.upload(session.session_id, "monthly-budget.png", _image_bytes())
    source = _create_run(
        coordinator,
        session.session_id,
        "history-image-source",
        "分析预算图",
        (attachment.attachment_id,),
    )
    _complete_text(coordinator, session.session_id, source.run_id)
    target = _create_run(coordinator, session.session_id, "history-image-target", "找回图片")

    result = history.search(
        session.session_id,
        target.run_id,
        "monthly-budget.png",
        source_kind="attachment",
    )
    reference = result["matches"][0]["reference"]
    assert reference == {"kind": "attachment", "id": attachment.attachment_id}
    execution, typed_reference = history.image_resource(
        session.session_id, target.run_id, reference
    )
    image, width, height = image_reader.read(session.session_id, execution, typed_reference)
    assert image == _image_bytes()
    assert (width, height) == (3, 2)


def test_historical_image_tool_attaches_verified_image_on_next_request(tmp_path):
    store, coordinator, history, image_reader, execution_state_service = _app(tmp_path)
    attachments = make_attachment_service(store)
    session = coordinator.create_session()
    image_data = _image_bytes()
    attachment = attachments.upload(session.session_id, "source.png", image_data)
    source = _create_run(
        coordinator,
        session.session_id,
        "image-tool-source",
        "查看旧图像",
        (attachment.attachment_id,),
    )
    _complete_text(coordinator, session.session_id, source.run_id, "图像已记录")
    middle = _create_run(coordinator, session.session_id, "image-tool-middle", "中间历史")
    middle_state = _complete_text(coordinator, session.session_id, middle.run_id)
    target = _create_run(coordinator, session.session_id, "image-tool-target", "读取旧图")
    registry = ToolRegistry(
        "history-image-v1",
        (historical_image_tool_definition(history, image_reader),),
    )
    _commit_response(
        coordinator,
        session.session_id,
        target.run_id,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "读取已授权的附件。",
            (
                ProviderToolCall(
                    "read-image-call",
                    "read_resource_image",
                    '{"resource_ref":{"kind":"attachment","id":"' + attachment.attachment_id + '"}}',
                ),
            ),
            FinishReason.TOOL_CALLS,
        ),
        registry_version=registry.version,
    )
    state = DurableToolExecutor(store, registry).execute_pending(
        session.session_id, target.run_id
    )
    execution = execution_state_service.build(
        state, coordinator.read_prior_run_states(session.session_id, target.run_id)
    )
    messages = build_observation_messages(state, execution, image_reader)
    image_blocks = [
        block for message in messages
        for block in message.content
        if isinstance(block, ImageBlock)
    ]

    assert len(image_blocks) == 1
    assert image_blocks[0].image_bytes == image_data
    assert image_blocks[0].media_type == "image/png"
    assert image_blocks[0].source_ref["kind"] == "attachment"

    checkpoint = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=middle.run_id,
        covered_run_ordinal=middle.ordinal,
        covered_record_sequence=middle_state.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=middle_state.checkpoint.last_committed_tool_sequence,
        summary_contract_version=1,
        summary={"items": [], "run_outcomes": []},
        source_refs=(MessageSourceRef(middle.run_id, middle.input_record_id),),
    )
    request = AgentRequestBuilder(execution_state_service, image_reader).build(
        state,
        registry,
        coordinator.read_prior_run_states(session.session_id, target.run_id),
        context_checkpoint=checkpoint,
    )
    request_image_blocks = [
        block
        for message in request.messages
        if isinstance(message.content, tuple)
        for block in message.content
        if isinstance(block, ImageBlock)
    ]
    assert len(request_image_blocks) == 1
    assert request_image_blocks[0].image_bytes == image_data


def test_historical_image_tool_supports_panel_annotations_and_chart_render():
    attachment_ref = ImageResourceRef("attachment", "attachment-source")
    refs_and_contents = (
        (
            attachment_ref,
            AttachmentContent("session-1", "source.png", "image/png", 1, "2026-01-01T00:00:00Z"),
            "source.png",
            "image/png",
        ),
        (
            ImageResourceRef("panel", "panel-1"),
            PanelContent("session-1", "source-run", "attachment-source", "Panel A", ()),
            "Panel A",
            "image/png",
        ),
        (
            ToolResourceRef("ocr", "source-run", "ocr-call"),
            OcrContent("attempt-ocr", attachment_ref, None, ToolOutcome.SUCCEEDED, {"text": "x"}),
            "OCR annotation",
            "image/png",
        ),
        (
            ToolResourceRef("measurement", "source-run", "measure-call"),
            MeasurementContent(
                "attempt-measure", "measure_bars", attachment_ref, None,
                ToolOutcome.SUCCEEDED, {"bars": []},
            ),
            "measure_bars annotation",
            "image/png",
        ),
        (
            ToolResourceRef("chart_render", "source-run", "render-call"),
            ChartRenderContent(
                "attempt-render",
                ToolResourceRef("chart_figure", "source-run", "figure-call"),
                ToolOutcome.SUCCEEDED,
                {"width": 16, "height": 9},
            ),
            "ChartRender",
            "image/png",
        ),
    )
    execution = RunExecutionState(
        "current-run",
        tuple(ExecutionResource(ref, content) for ref, content, _name, _media in refs_and_contents),
    )

    def reference_key(reference):
        if "id" in reference:
            return reference["kind"], reference["id"]
        return reference["kind"], reference["run_id"], reference["call_id"]

    by_reference = {
        reference_key(resource_ref_to_dict(ref)): ref
        for ref, *_ in refs_and_contents
    }

    class History:
        def image_resource(self, _session_id, _run_id, raw_reference):
            return execution, by_reference[reference_key(raw_reference)]

    class ImageReader:
        def read(self, _session_id, _execution, _reference):
            return b"verified-image", 16, 9

    definition = historical_image_tool_definition(History(), ImageReader())
    context = ToolContext("current-run", "session-1", "history-image-call")
    for ref, _content, expected_name, expected_media_type in refs_and_contents:
        result = definition.handler(
            context,
            {"resource_ref": resource_ref_to_dict(ref)},
        )
        assert result["trust"] == "untrusted_history"
        assert result["name"] == expected_name
        assert result["media_type"] == expected_media_type
        assert (result["width"], result["height"]) == (16, 9)
