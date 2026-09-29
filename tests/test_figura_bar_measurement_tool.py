from __future__ import annotations

import json

import pytest
from PIL import Image, ImageDraw

from figura.agent.execution_state import RunExecutionStateService
from figura.agent.request import AgentRequestBuilder
from figura.providers import FinishReason, ImageBlock, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunCreateRequest, ToolFactKind
from figura.runtime.run_lock import PerRunExecutionLock
from figura.runtime.records import ToolAttemptStartedFact, ToolResultFact
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.tools import ReplayEffect, ToolContext, ToolInvocation, ToolOutcome, ToolRegistry, ToolRuntime
from figura.tools.limits import MAX_RESULT_BYTES
from figura.tools.implementations.image import image_tool_definitions
from figura.tools.implementations.measure_bars import measure_bars_definition
from figura.tools.implementations.measure_lines import measure_lines_definition
from figura.tools.implementations.measure_scatter import measure_scatter_definition


def _chart_bytes() -> bytes:
    import io

    image = Image.new("RGB", (300, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.line((25, 175, 275, 175), fill="black", width=2)
    draw.rectangle((55, 100, 90, 174), fill="#3366cc")
    draw.rectangle((130, 60, 165, 174), fill="#3366cc")
    draw.rectangle((205, 115, 240, 174), fill="#3366cc")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _blank_bytes() -> bytes:
    import io

    output = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(output, format="PNG")
    return output.getvalue()


def _setup(tmp_path, image_bytes: bytes | None = None):
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
    repository = SourcesRepository(store.database)
    attachments = FiguraAttachmentService(repository, store.data_root)
    attachment = attachments.upload(session.session_id, "bars.png", image_bytes or _chart_bytes())
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请观察柱状图。",
            attachment_ids=(attachment.attachment_id,),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="measure-tool-run",
        )
    )
    panels = FiguraPanelService(repository, store.data_root, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    definition = measure_bars_definition(execution_state.for_run, attachments, panels)
    registry = ToolRegistry("figura-web-v2", (definition,))
    runtime = ToolRuntime(registry)
    return store, coordinator, session, run, attachments, panels, execution_state, registry, runtime, attachment


def _invoke(
    runtime,
    run_id: str,
    session_id: str,
    source_kind: str,
    source_id: str,
    call_id: str = "measure-call",
    tool_name: str = "measure_bars",
):
    invocation = ToolInvocation(
        call_id,
        tool_name,
        json.dumps({"source_kind": source_kind, "source_id": source_id}),
    )
    return runtime.invoke(invocation, ToolContext(run_id, session_id, call_id))


def _finish_run(coordinator, session_id: str, run_id: str) -> None:
    state = coordinator.read_run_state(session_id, run_id)
    provider_attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "已完成。", (), FinishReason.STOP),
        provider_attempt_id=provider_attempt.attempt_id,
    )
    terminal = coordinator.read_run_state(session_id, run_id)
    coordinator.complete_run(session_id, run_id, terminal.checkpoint.revision)


def _commit_decomposition(store, coordinator, session_id, run_id, execution_state, attachments, panels) -> str:
    definitions = image_tool_definitions(execution_state.for_run, attachments, panels)
    registry = ToolRegistry("panel-tools", definitions)
    source_id = attachments.list(session_id)[0].attachment_id
    arguments = json.dumps({
        "attachment_id": source_id,
        "panels": [{
            "name": "主图",
            "points": [{"x": 0, "y": 0}, {"x": 1000, "y": 0}, {"x": 1000, "y": 1000}, {"x": 0, "y": 1000}],
        }],
    })
    call = ProviderToolCall("decompose-call", "decompose_chart_image", arguments)
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "分解图表。", (call,), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )
    DurableToolExecutor(
        store,
        registry,
        execution_lock=PerRunExecutionLock(store.data_root),
    ).execute_pending(session_id, run_id)
    return execution_state.for_run(session_id, run_id).panels[0].panel_id


def _commit_measurements(store, coordinator, session_id, run_id, registry, calls) -> None:
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "测量图表。", tuple(calls), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )
    DurableToolExecutor(
        store,
        registry,
        execution_lock=PerRunExecutionLock(store.data_root),
    ).execute_pending(session_id, run_id)


def test_measure_bars_definition_exposes_only_opaque_source_identity() -> None:
    definition = measure_bars_definition(lambda *_: None, None, None)
    registry = ToolRegistry("measure-schema", (definition,))

    assert definition.replay_effect is ReplayEffect.REPLAY_SAFE
    assert set(definition.parameters_schema["properties"]) == {"source_kind", "source_id"}
    assert len(registry) == 1


def test_line_and_scatter_tools_use_the_same_authorized_source_contract(tmp_path) -> None:
    (
        _store, _coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    definitions = (
        measure_lines_definition(execution_state.for_run, attachments, panels),
        measure_scatter_definition(execution_state.for_run, attachments, panels),
    )
    registry = ToolRegistry("measure-v3", definitions)
    runtime = ToolRuntime(registry)

    for definition in definitions:
        assert set(definition.parameters_schema["properties"]) == {"source_kind", "source_id"}
        execution = _invoke(
            runtime,
            run.run_id,
            session.session_id,
            "attachment",
            attachment.attachment_id,
            tool_name=definition.name,
        )
        assert execution.outcome is ToolOutcome.SUCCEEDED
        assert execution.result["source_kind"] == "attachment"
        assert execution.result["source_id"] == attachment.attachment_id
        assert execution.result["coordinate_system"] == "attachment_px"
        assert "axes" in execution.result
        assert "image_bytes" not in execution.result
        assert "overlay" not in execution.result


def test_line_and_scatter_reject_cross_session_sources_before_reading(tmp_path, monkeypatch) -> None:
    (
        _store, coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, _attachment,
    ) = _setup(tmp_path)
    other_session = coordinator.create_session("另一个会话")
    foreign = attachments.upload(other_session.session_id, "foreign.png", _chart_bytes())
    definitions = (
        measure_lines_definition(execution_state.for_run, attachments, panels),
        measure_scatter_definition(execution_state.for_run, attachments, panels),
    )
    runtime = ToolRuntime(ToolRegistry("measure-v3", definitions))
    original_resolve = FiguraAttachmentService.resolve
    reads: list[str] = []

    def track_resolve(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original_resolve(service, session_id, attachment_id)

    monkeypatch.setattr(FiguraAttachmentService, "resolve", track_resolve)
    for definition in definitions:
        execution = _invoke(
            runtime,
            run.run_id,
            session.session_id,
            "attachment",
            foreign.attachment_id,
            tool_name=definition.name,
        )
        assert execution.outcome is ToolOutcome.FAILED
        assert execution.error.code == "image_not_available"
    assert reads == []


def test_oversized_measurement_result_is_rejected_without_truncation(tmp_path, monkeypatch) -> None:
    import figura.tools.implementations.measure_lines as line_implementation

    (
        _store, _coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    monkeypatch.setattr(line_implementation, "measure_line_image", lambda _image: {"payload": "x" * MAX_RESULT_BYTES})
    runtime = ToolRuntime(ToolRegistry(
        "measure-v3",
        (measure_lines_definition(execution_state.for_run, attachments, panels),),
    ))

    execution = _invoke(
        runtime,
        run.run_id,
        session.session_id,
        "attachment",
        attachment.attachment_id,
        tool_name="measure_lines",
    )

    assert execution.outcome is ToolOutcome.FAILED
    assert execution.error.code == "result_too_large"


def test_measures_an_authorized_attachment_without_returning_private_payloads(tmp_path) -> None:
    (
        _store, _coordinator, session, run, _attachments, _panels, _state,
        _registry, runtime, attachment,
    ) = _setup(tmp_path)

    execution = _invoke(runtime, run.run_id, session.session_id, "attachment", attachment.attachment_id)

    assert execution.outcome is ToolOutcome.SUCCEEDED
    result = execution.result
    assert result["source_kind"] == "attachment"
    assert result["source_id"] == attachment.attachment_id
    assert result["coordinate_system"] == "attachment_px"
    assert result["image_size"] == {"width": 300, "height": 200}
    assert result["status"] == "partial"
    serialized = json.dumps(result, default=lambda value: dict(value) if hasattr(value, "items") else list(value))
    assert str(tmp_path) not in serialized
    assert "image_bytes" not in serialized
    assert "overlay" not in serialized
    assert "image/png" not in serialized


def test_can_measure_an_attachment_referenced_by_a_prior_run(tmp_path) -> None:
    (
        store, coordinator, session, first_run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    _finish_run(coordinator, session.session_id, first_run.run_id)
    second_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="继续观察先前的图表。",
            attachment_ids=(),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="measure-prior-run",
        )
    )
    runtime = ToolRuntime(ToolRegistry(
        "figura-web-v2",
        (measure_bars_definition(execution_state.for_run, attachments, panels),),
    ))

    execution = _invoke(runtime, second_run.run_id, session.session_id, "attachment", attachment.attachment_id)

    assert execution.outcome is ToolOutcome.SUCCEEDED
    assert execution.result["coordinate_system"] == "attachment_px"
    assert execution.result["source_id"] == attachment.attachment_id


def test_rejects_cross_session_source_before_reading_its_image(tmp_path, monkeypatch) -> None:
    _store, coordinator, session, run, attachments, _panels, _state, _registry, runtime, _attachment = _setup(tmp_path)
    other_session = coordinator.create_session("另一个会话")
    foreign = attachments.upload(other_session.session_id, "foreign.png", _chart_bytes())
    original_resolve = FiguraAttachmentService.resolve
    reads: list[str] = []

    def track_resolve(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original_resolve(service, session_id, attachment_id)

    monkeypatch.setattr(FiguraAttachmentService, "resolve", track_resolve)
    execution = _invoke(runtime, run.run_id, session.session_id, "attachment", foreign.attachment_id)

    assert execution.outcome is ToolOutcome.FAILED
    assert execution.error.code == "image_not_available"
    assert reads == []


def test_measures_only_committed_panels_in_panel_coordinates(tmp_path) -> None:
    (
        store, coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, _attachment,
    ) = _setup(tmp_path)
    panel_id = _commit_decomposition(
        store, coordinator, session.session_id, run.run_id, execution_state, attachments, panels
    )
    runtime = ToolRuntime(ToolRegistry(
        "figura-web-v2",
        (measure_bars_definition(execution_state.for_run, attachments, panels),),
    ))

    execution = _invoke(runtime, run.run_id, session.session_id, "panel", panel_id)

    assert execution.outcome is ToolOutcome.SUCCEEDED
    assert execution.result["source_kind"] == "panel"
    assert execution.result["source_id"] == panel_id
    assert execution.result["coordinate_system"] == "panel_px"
    assert execution.result["image_size"] == {"width": 300, "height": 200}


def test_maps_source_read_errors_to_bounded_tool_failures(tmp_path, monkeypatch) -> None:
    (
        _store, _coordinator, session, run, _attachments, _panels, _state,
        _registry, runtime, attachment,
    ) = _setup(tmp_path)

    def unavailable(_service, _session_id, _attachment_id):
        raise RunError(RunErrorCode.STORAGE_ERROR)

    monkeypatch.setattr(FiguraAttachmentService, "resolve", unavailable)
    execution = _invoke(runtime, run.run_id, session.session_id, "attachment", attachment.attachment_id)

    assert execution.outcome is ToolOutcome.FAILED
    assert execution.error.code == "image_unavailable"
    assert execution.error.retryable is True
    assert str(tmp_path) not in execution.error.message


def test_execution_state_projects_ordered_committed_measurements_across_runs(tmp_path, monkeypatch) -> None:
    (
        store, coordinator, session, first_run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    registry = ToolRegistry(
        "figura-web-v3",
        (
            *image_tool_definitions(execution_state.for_run, attachments, panels),
            measure_bars_definition(execution_state.for_run, attachments, panels),
            measure_lines_definition(execution_state.for_run, attachments, panels),
            measure_scatter_definition(execution_state.for_run, attachments, panels),
        ),
    )
    arguments = json.dumps({"source_kind": "attachment", "source_id": attachment.attachment_id})
    first_calls = (
        ProviderToolCall("measure-first", "measure_bars", arguments),
        ProviderToolCall("measure-second", "measure_bars", arguments),
    )
    _commit_measurements(store, coordinator, session.session_id, first_run.run_id, registry, first_calls)

    first_projection = execution_state.for_run(session.session_id, first_run.run_id).measurements
    assert [item.call_id for item in first_projection] == ["measure-first", "measure-second"]
    assert all(item.outcome is ToolOutcome.SUCCEEDED for item in first_projection)
    assert all(item.attempt_id for item in first_projection)
    with pytest.raises(TypeError):
        first_projection[0].result["source_id"] = "changed"

    _finish_run(coordinator, session.session_id, first_run.run_id)
    second_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="继续读取之前的图表。",
            attachment_ids=(),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="measurement-projection-next-run",
        )
    )
    _commit_measurements(
        store,
        coordinator,
        session.session_id,
        second_run.run_id,
        registry,
        (
            ProviderToolCall("measure-line", "measure_lines", arguments),
            ProviderToolCall("measure-scatter", "measure_scatter", arguments),
        ),
    )
    prior_and_current = execution_state.for_run(session.session_id, second_run.run_id).measurements
    assert [item.call_id for item in prior_and_current] == [
        "measure-first", "measure-second", "measure-line", "measure-scatter"
    ]
    assert [item.tool_name for item in prior_and_current] == [
        "measure_bars", "measure_bars", "measure_lines", "measure_scatter"
    ]
    (store.data_root / "attachments" / f"{attachment.attachment_id}.bin").unlink()
    failed_call = ProviderToolCall("measure-read-failed", "measure_bars", arguments)
    _commit_measurements(store, coordinator, session.session_id, second_run.run_id, registry, (failed_call,))

    with_failure = execution_state.for_run(session.session_id, second_run.run_id).measurements
    assert [item.call_id for item in with_failure] == [
        "measure-first", "measure-second", "measure-line", "measure-scatter", "measure-read-failed"
    ]
    assert with_failure[-1].outcome is ToolOutcome.FAILED
    assert with_failure[-1].error.code == "image_unavailable"

    other_session = coordinator.create_session("隔离的会话")
    foreign = attachments.upload(other_session.session_id, "foreign.png", _chart_bytes())
    unauthorized = ProviderToolCall(
        "measure-foreign",
        "measure_bars",
        json.dumps({"source_kind": "attachment", "source_id": foreign.attachment_id}),
    )
    _commit_measurements(store, coordinator, session.session_id, second_run.run_id, registry, (unauthorized,))
    with_unauthorized = execution_state.for_run(session.session_id, second_run.run_id).measurements
    assert [item.call_id for item in with_unauthorized] == [
        "measure-first", "measure-second", "measure-line", "measure-scatter", "measure-read-failed"
    ]

    unresolved = ProviderToolCall("measure-unresolved", "measure_bars", arguments)
    state = coordinator.read_run_state(session.session_id, second_run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, second_run.run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session.session_id, second_run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        second_run.run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "再次测量。", (unresolved,), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )

    def fail_result_commit(_store, **_kwargs):
        raise RunError(RunErrorCode.STORAGE_ERROR)

    monkeypatch.setattr(FiguraRunStore, "commit_tool_result", fail_result_commit)
    with pytest.raises(RunError):
        DurableToolExecutor(
            store,
            registry,
            execution_lock=PerRunExecutionLock(store.data_root),
        ).execute_pending(session.session_id, second_run.run_id)
    unresolved_state = coordinator.read_run_state(session.session_id, second_run.run_id)
    assert any(
        fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
        and isinstance(fact.payload, ToolAttemptStartedFact)
        and fact.payload.call_id == "measure-unresolved"
        for fact in unresolved_state.tool_facts
    )
    assert not any(
        fact.fact_kind is ToolFactKind.TOOL_RESULT
        and isinstance(fact.payload, ToolResultFact)
        and fact.payload.call_id == "measure-unresolved"
        for fact in unresolved_state.tool_facts
    )
    assert [item.call_id for item in execution_state.for_run(session.session_id, second_run.run_id).measurements] == [
        "measure-first", "measure-second", "measure-line", "measure-scatter", "measure-read-failed"
    ]


def test_measurement_feedback_uses_latest_batch_order_and_is_not_repeated(tmp_path) -> None:
    (
        store, coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    registry = ToolRegistry(
        "figura-web-v3",
        (
            *image_tool_definitions(execution_state.for_run, attachments, panels),
            measure_bars_definition(execution_state.for_run, attachments, panels),
            measure_lines_definition(execution_state.for_run, attachments, panels),
            measure_scatter_definition(execution_state.for_run, attachments, panels),
        ),
    )
    source = json.dumps({"source_kind": "attachment", "source_id": attachment.attachment_id})
    calls = (
        ProviderToolCall("load-first", "load_image", source),
        ProviderToolCall("bar-feedback", "measure_bars", source),
        ProviderToolCall("load-duplicate", "load_image", source),
        ProviderToolCall("line-feedback", "measure_lines", source),
        ProviderToolCall("scatter-feedback", "measure_scatter", source),
    )
    _commit_measurements(store, coordinator, session.session_id, run.run_id, registry, calls)

    request = AgentRequestBuilder(attachments, execution_state).build(
        coordinator.read_run_state(session.session_id, run.run_id), registry
    )

    image_message = request.messages[-1]
    assert image_message.role.value == "user"
    blocks = image_message.content
    assert isinstance(blocks, tuple)
    image_blocks = [block for block in blocks if getattr(block, "media_type", None) == "image/png"]
    texts = [block.text for block in blocks if hasattr(block, "text")]
    assert len(image_blocks) == 4
    assert "已加载图像" in texts[0]
    assert [next(token for token in ("bar-feedback", "line-feedback", "scatter-feedback") if token in text) for text in texts[1:]] == [
        "bar-feedback", "line-feedback", "scatter-feedback"
    ]
    assert image_blocks[0].image_bytes == attachments.resolve(session.session_id, attachment.attachment_id).image_bytes
    assert all(block.image_bytes != image_blocks[0].image_bytes for block in image_blocks[1:])
    assert [item.tool_name for item in execution_state.for_run(session.session_id, run.run_id).measurements] == [
        "measure_bars", "measure_lines", "measure_scatter"
    ]

    _commit_measurements(
        store,
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        (ProviderToolCall("later-load", "load_image", source),),
    )
    later_request = AgentRequestBuilder(attachments, execution_state).build(
        coordinator.read_run_state(session.session_id, run.run_id), registry
    )
    assert "测量结果图像回看" not in " ".join(
        block.text
        for message in later_request.messages
        for block in (message.content if isinstance(message.content, tuple) else ())
        if hasattr(block, "text")
    )
    assert len([
        block
        for message in later_request.messages
        for block in (message.content if isinstance(message.content, tuple) else ())
        if isinstance(block, ImageBlock)
    ]) == 1


def test_measurement_history_assembles_with_the_retained_registry_version(tmp_path) -> None:
    (
        store, coordinator, session, first_run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    registry = ToolRegistry(
        "figura-web-v2",
        (
            *image_tool_definitions(execution_state.for_run, attachments, panels),
            measure_bars_definition(execution_state.for_run, attachments, panels),
        ),
    )
    _commit_measurements(
        store,
        coordinator,
        session.session_id,
        first_run.run_id,
        registry,
        (ProviderToolCall(
            "historical-measurement",
            "measure_bars",
            json.dumps({"source_kind": "attachment", "source_id": attachment.attachment_id}),
        ),),
    )
    _finish_run(coordinator, session.session_id, first_run.run_id)
    next_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="继续分析。",
            attachment_ids=(),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="measurement-history-next-run",
        )
    )
    next_registry = ToolRegistry(
        "figura-web-v3",
        (
            *image_tool_definitions(execution_state.for_run, attachments, panels),
            measure_bars_definition(execution_state.for_run, attachments, panels),
            measure_lines_definition(execution_state.for_run, attachments, panels),
            measure_scatter_definition(execution_state.for_run, attachments, panels),
        ),
    )
    request = AgentRequestBuilder(attachments, execution_state).build(
        coordinator.read_run_state(session.session_id, next_run.run_id),
        next_registry,
        coordinator.read_prior_run_states(session.session_id, next_run.run_id),
    )

    assert request.messages[1].role.value == "assistant"
    assert request.messages[1].tool_calls[0].name == "measure_bars"
    assert request.messages[2].role.value == "tool"
    assert request.messages[2].tool_call_id == "historical-measurement"
    assert "当前 Session 图像清单" in request.messages[-1].content
    assert "measurements" not in request.messages[-1].content
    assert [tool.name for tool in request.tools][-3:] == [
        "measure_bars", "measure_lines", "measure_scatter"
    ]
    assert all(
        not isinstance(block, ImageBlock)
        for message in request.messages
        for block in (message.content if isinstance(message.content, tuple) else ())
    )


def test_no_evidence_measurement_still_gets_a_status_overlay(tmp_path) -> None:
    (
        store, coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path, _blank_bytes())
    registry = ToolRegistry(
        "figura-web-v3",
        (measure_bars_definition(execution_state.for_run, attachments, panels),),
    )
    arguments = json.dumps({"source_kind": "attachment", "source_id": attachment.attachment_id})
    _commit_measurements(
        store,
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        (ProviderToolCall("empty-measurement", "measure_bars", arguments),),
    )

    request = AgentRequestBuilder(attachments, execution_state).build(
        coordinator.read_run_state(session.session_id, run.run_id), registry
    )
    observation = execution_state.for_run(session.session_id, run.run_id).measurements[-1]
    blocks = request.messages[-1].content

    assert observation.result["status"] == "no_evidence"
    assert isinstance(blocks, tuple)
    assert "empty-measurement" in blocks[0].text
    assert isinstance(blocks[1], ImageBlock)
    assert blocks[1].image_bytes != attachments.resolve(session.session_id, attachment.attachment_id).image_bytes


def test_measurement_feedback_fails_if_authorized_source_disappears(tmp_path) -> None:
    (
        store, coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    registry = ToolRegistry(
        "figura-web-v3",
        (measure_bars_definition(execution_state.for_run, attachments, panels),),
    )
    arguments = json.dumps({"source_kind": "attachment", "source_id": attachment.attachment_id})
    _commit_measurements(
        store,
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        (ProviderToolCall("source-disappears", "measure_bars", arguments),),
    )
    prior_attempts = coordinator.read_run_state(session.session_id, run.run_id).provider_attempts
    (store.data_root / "attachments" / f"{attachment.attachment_id}.bin").unlink()

    with pytest.raises(RunError):
        AgentRequestBuilder(attachments, execution_state).build(
            coordinator.read_run_state(session.session_id, run.run_id), registry
        )
    assert coordinator.read_run_state(session.session_id, run.run_id).provider_attempts == prior_attempts


def test_measurement_feedback_keeps_multiple_source_images_in_call_order(tmp_path) -> None:
    (
        store, coordinator, session, first_run, attachments, panels, execution_state,
        _registry, _runtime, first_attachment,
    ) = _setup(tmp_path)
    _finish_run(coordinator, session.session_id, first_run.run_id)
    second_attachment = attachments.upload(session.session_id, "second.png", _chart_bytes())
    second_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="继续测量两张图。",
            attachment_ids=(second_attachment.attachment_id,),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="measurement-multiple-sources",
        )
    )
    registry = ToolRegistry(
        "figura-web-v3",
        (
            measure_bars_definition(execution_state.for_run, attachments, panels),
            measure_scatter_definition(execution_state.for_run, attachments, panels),
        ),
    )
    calls = (
        ProviderToolCall(
            "first-source",
            "measure_bars",
            json.dumps({"source_kind": "attachment", "source_id": first_attachment.attachment_id}),
        ),
        ProviderToolCall(
            "second-source",
            "measure_scatter",
            json.dumps({"source_kind": "attachment", "source_id": second_attachment.attachment_id}),
        ),
    )
    _commit_measurements(store, coordinator, session.session_id, second_run.run_id, registry, calls)

    request = AgentRequestBuilder(attachments, execution_state).build(
        coordinator.read_run_state(session.session_id, second_run.run_id),
        registry,
        coordinator.read_prior_run_states(session.session_id, second_run.run_id),
    )
    blocks = request.messages[-1].content

    assert isinstance(blocks, tuple)
    assert [block.text for block in blocks if hasattr(block, "text")] == [
        "测量结果图像回看：measure_bars；调用 ID：first-source。",
        "测量结果图像回看：measure_scatter；调用 ID：second-source。",
    ]
    assert len([block for block in blocks if isinstance(block, ImageBlock)]) == 2


def test_measurement_overlay_obeys_provider_image_count_limit(tmp_path, monkeypatch) -> None:
    import figura.providers.validation as provider_validation

    (
        store, coordinator, session, run, attachments, panels, execution_state,
        _registry, _runtime, attachment,
    ) = _setup(tmp_path)
    registry = ToolRegistry(
        "figura-web-v3",
        (
            *image_tool_definitions(execution_state.for_run, attachments, panels),
            measure_bars_definition(execution_state.for_run, attachments, panels),
        ),
    )
    arguments = json.dumps({"source_kind": "attachment", "source_id": attachment.attachment_id})
    _commit_measurements(
        store,
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        (
            ProviderToolCall("load-for-limit", "load_image", arguments),
            ProviderToolCall("measure-for-limit", "measure_bars", arguments),
        ),
    )
    monkeypatch.setattr(provider_validation, "MAX_IMAGE_COUNT", 1)

    with pytest.raises(RunError) as error:
        AgentRequestBuilder(attachments, execution_state).build(
            coordinator.read_run_state(session.session_id, run.run_id), registry
        )

    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
