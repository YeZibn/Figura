from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from figura.attachments import FiguraAttachmentService
from figura.panels import FiguraPanelService, PanelPoint, RunExecutionStateService
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime import (
    ActionKind,
    DurableToolExecutor,
    FiguraRunStore,
    RunCoordinator,
    RunCreateRequest,
    RunError,
    RunErrorCode,
    ToolFactKind,
    ToolResultFact,
)
from figura.runtime._run_lock import PerRunExecutionLock
from figura.tools import ToolContext, ToolInvocation, ToolOutcome, ToolRegistry, ToolRuntime
from figura.tools.image_tools import image_tool_definitions


def _image_bytes(width: int = 10, height: int = 10) -> bytes:
    content = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(content, format="PNG")
    return content.getvalue()


def _setup(tmp_path, attachment_count: int = 1, image_content: bytes | None = None):
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
    attachments = FiguraAttachmentService(store)
    content = image_content if image_content is not None else _image_bytes()
    uploaded = tuple(attachments.upload(session.session_id, f"chart-{index}.png", content) for index in range(attachment_count))
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请分析图表。",
            attachment_ids=tuple(item.attachment_id for item in uploaded),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="panel-tools-run",
        )
    )
    panels = FiguraPanelService(store.data_root, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    registry = ToolRegistry(
        "panel-tools-v1", image_tool_definitions(execution_state, attachments, panels)
    )
    return store, coordinator, session, run, attachments, panels, execution_state, registry


def _commit_tool_call(coordinator, session_id: str, run_id: str, registry, call: ProviderToolCall):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "开始观察图表。",
            (call,),
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )


def _decompose_call(call_id: str, attachment_id: str, panels: list[dict[str, object]]) -> ProviderToolCall:
    return ProviderToolCall(
        call_id,
        "decompose_chart_image",
        json.dumps({"attachment_id": attachment_id, "panels": panels}, separators=(",", ":")),
    )


def test_decomposition_persists_ordered_independent_polygon_pngs(tmp_path) -> None:
    store, coordinator, session, run, attachments, panels, state_service, registry = _setup(tmp_path)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    proposals = [
        {
            "name": "矩形区域",
            "points": [{"x": 100, "y": 100}, {"x": 600, "y": 100}, {"x": 600, "y": 600}, {"x": 100, "y": 600}],
        },
        {
            "name": "三角区域",
            "points": [{"x": 400, "y": 400}, {"x": 900, "y": 400}, {"x": 650, "y": 900}],
        },
    ]
    _commit_tool_call(coordinator, session.session_id, run.run_id, registry, _decompose_call("decompose-1", attachment_id, proposals))

    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)
    records = state_service.for_run(session.session_id, run.run_id).panels

    assert [record.name for record in records] == ["矩形区域", "三角区域"]
    assert [record.points[0] for record in records] == [PanelPoint(100, 100), PanelPoint(400, 400)]
    first_record, first_image, width, height = panels.resolve(session.session_id, records[0].panel_id)
    assert (width, height) == (5, 5)
    assert Image.open(io.BytesIO(first_image.image_bytes)).getpixel((0, 0))[3] == 255
    _record, triangle_image, width, height = panels.resolve(session.session_id, records[1].panel_id)
    triangle = Image.open(io.BytesIO(triangle_image.image_bytes))
    assert (width, height) == (5, 5)
    assert triangle.mode == "RGBA"
    assert triangle.getpixel((4, 4))[3] == 0
    assert first_record.panel_id == hashlib.sha256(f"{hashlib.sha256(json.dumps([run.run_id, 'decompose-1'], separators=(',', ':')).encode()).hexdigest()}:0".encode()).hexdigest()

    result_fact = next(
        fact.payload for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact)
    )
    assert result_fact.outcome is ToolOutcome.SUCCEEDED
    assert [item["panel_id"] for item in result_fact.result["panels"]] == [item.panel_id for item in records]
    assert set(result_fact.result) == {"panels"}
    assert all(set(item) == {"panel_id", "name", "source_attachment_id"} for item in result_fact.result["panels"])
    assert all(str(tmp_path / "panels") not in repr(item) for item in result_fact.result["panels"])


def test_decomposition_preserves_source_transparency_inside_panel(tmp_path) -> None:
    source = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    source.putpixel((4, 4), (0, 0, 255, 0))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    _store, _coordinator, session, run, attachments, panels, _state, _registry = _setup(
        tmp_path, image_content=buffer.getvalue()
    )
    attachment = attachments.list(session.session_id)[0]
    points = (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(1000, 1000), PanelPoint(0, 1000))

    record = panels.decompose(
        session.session_id,
        run.run_id,
        attachment.attachment_id,
        (("透明图像", points),),
        "d" * 64,
    )[0]
    _record, image, _width, _height = panels.resolve(session.session_id, record.panel_id)
    panel_image = Image.open(io.BytesIO(image.image_bytes))

    assert panel_image.getpixel((4, 4))[3] == 0
    assert panel_image.getpixel((5, 5))[3] == 255


def test_uncommitted_panel_is_hidden_and_cross_session_attachment_is_rejected(tmp_path) -> None:
    store, coordinator, session, run, attachments, panels, state_service, registry = _setup(tmp_path)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    record = panels.decompose(
        session.session_id,
        run.run_id,
        attachment_id,
        (("未提交", (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(0, 1000))),),
        "a" * 64,
    )[0]
    state = state_service.for_run(session.session_id, run.run_id)

    assert record not in state.panels
    assert state_service.list_session_panels(session.session_id) == ()

    runtime = ToolRuntime(registry)
    missing_image = runtime.invoke(
        ToolInvocation(
            "load-missing",
            "load_image",
            json.dumps({"source_kind": "attachment", "source_id": "0" * 32}),
        ),
        ToolContext(run.run_id, session.session_id, "load-missing"),
    )
    assert missing_image.outcome is ToolOutcome.FAILED
    assert missing_image.error is not None and missing_image.error.code == "image_not_available"

    uncommitted_panel = runtime.invoke(
        ToolInvocation(
            "load-uncommitted",
            "load_image",
            json.dumps({"source_kind": "panel", "source_id": record.panel_id}),
        ),
        ToolContext(run.run_id, session.session_id, "load-uncommitted"),
    )
    assert uncommitted_panel.outcome is ToolOutcome.FAILED
    assert uncommitted_panel.error is not None and uncommitted_panel.error.code == "image_not_available"

    other = coordinator.create_session("另一个会话")
    foreign = attachments.upload(other.session_id, "foreign.png", _image_bytes())
    result = runtime.invoke(
        ToolInvocation("load-foreign", "load_image", json.dumps({"source_kind": "attachment", "source_id": foreign.attachment_id})),
        ToolContext(run.run_id, session.session_id, "load-foreign"),
    )
    assert result.outcome is ToolOutcome.FAILED
    assert result.error is not None and result.error.code == "image_not_available"


def test_attachment_inventory_uses_earlier_run_then_current_input_order(tmp_path) -> None:
    store, coordinator, session, first_run, attachments, _panels, state_service, _registry = _setup(tmp_path, 2)
    first, second = attachments.list(session.session_id)
    state = coordinator.read_run_state(session.session_id, first_run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, first_run.run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session.session_id, first_run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        first_run.run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "已分析。", (), FinishReason.STOP),
        provider_attempt_id=attempt.attempt_id,
    )
    terminal = coordinator.read_run_state(session.session_id, first_run.run_id)
    coordinator.complete_run(session.session_id, first_run.run_id, terminal.checkpoint.revision)
    current = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="继续比较。",
            attachment_ids=(second.attachment_id, first.attachment_id),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="panel-tools-next-run",
        )
    )

    execution_state = state_service.for_run(session.session_id, current.run_id)

    assert [item.attachment_id for item in execution_state.available_attachments] == [
        first.attachment_id,
        second.attachment_id,
    ]
    assert [item.filename for item in execution_state.available_attachments] == [
        "chart-0.png",
        "chart-1.png",
    ]


def test_decomposition_replay_reuses_panel_ids_after_tool_result_commit_failure(tmp_path, monkeypatch) -> None:
    store, coordinator, session, run, attachments, panels, state_service, registry = _setup(tmp_path)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    call = _decompose_call("crash-after-write", attachment_id, [{
        "name": "主图",
        "points": [{"x": 0, "y": 0}, {"x": 1000, "y": 0}, {"x": 1000, "y": 1000}, {"x": 0, "y": 1000}],
    }])
    _commit_tool_call(coordinator, session.session_id, run.run_id, registry, call)
    executor = DurableToolExecutor(store, registry, execution_lock=PerRunExecutionLock(store.data_root))
    original_commit = FiguraRunStore.commit_tool_result
    fail_once = True

    def fail_first_result_commit(self, *args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RunError(RunErrorCode.STORAGE_ERROR)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(FiguraRunStore, "commit_tool_result", fail_first_result_commit)
    with pytest.raises(RunError):
        executor.execute_pending(session.session_id, run.run_id)
    uncommitted = state_service.for_run(session.session_id, run.run_id)
    assert uncommitted.panels == ()
    first_ids = [item.panel_id for item in panels.list(session.session_id)]
    assert len(first_ids) == 1

    monkeypatch.setattr(FiguraRunStore, "commit_tool_result", original_commit)
    recovered = executor.recover_unknown_attempt(session.session_id, run.run_id)
    visible = state_service.for_run(session.session_id, run.run_id).panels

    assert recovered.checkpoint.next_action.action_kind is ActionKind.MODEL
    assert [item.panel_id for item in visible] == first_ids
    assert len(panels.list(session.session_id)) == 1


def test_invalid_polygon_is_rejected_without_creating_any_panel(tmp_path) -> None:
    store, coordinator, session, run, attachments, panels, _state, registry = _setup(tmp_path)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    call = _decompose_call("invalid-poly", attachment_id, [{
        "name": "越界",
        "points": [{"x": 0, "y": 0}, {"x": 1200, "y": 0}, {"x": 0, "y": 1000}],
    }])
    _commit_tool_call(coordinator, session.session_id, run.run_id, registry, call)

    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)

    result = next(fact.payload for fact in state.tool_facts if fact.fact_kind is ToolFactKind.TOOL_RESULT)
    assert result.outcome is ToolOutcome.FAILED
    assert result.error is not None and result.error.code == "invalid_arguments"
    assert panels.list(session.session_id) == ()


def test_degenerate_geometry_and_resource_limits_are_rejected(tmp_path, monkeypatch) -> None:
    _store, _coordinator, session, run, attachments, panels, _state, _registry = _setup(tmp_path)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    collinear = (
        PanelPoint(0, 0),
        PanelPoint(500, 500),
        PanelPoint(1000, 1000),
    )

    with pytest.raises(RunError) as error:
        panels.decompose(session.session_id, run.run_id, attachment_id, (("无面积", collinear),), "b" * 64)
    assert error.value.code is RunErrorCode.INVALID_REQUEST
    assert panels.list(session.session_id) == ()

    monkeypatch.setattr("figura.panels.service._MAX_PANEL_PIXELS", 1)
    with pytest.raises(RunError) as error:
        panels.decompose(
            session.session_id,
            run.run_id,
            attachment_id,
            (("超出资源上限", (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(0, 1000))),),
            "c" * 64,
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert panels.list(session.session_id) == ()


def test_startup_removes_unregistered_panel_files_and_staging_directories(tmp_path) -> None:
    store, _coordinator, _session, _run, attachments, _panels, _state, _registry = _setup(tmp_path)
    panel_root = Path(store.data_root) / "panels"
    orphan = panel_root / ("f" * 64 + ".png")
    orphan.write_bytes(b"interrupted file installation")
    staging = panel_root / "staging-interrupted-write"
    staging.mkdir()
    (staging / "partial.png").write_bytes(b"partial")

    FiguraPanelService(store.data_root, attachments)

    assert not orphan.exists()
    assert not staging.exists()
