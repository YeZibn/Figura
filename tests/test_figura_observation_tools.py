from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

import figura.tools.measurements.bars as bars_module
import figura.tools.measurements.ocr as ocr_module
import figura.tools.measurements.pie as pie_module
from figura.agent.execution_state import RunExecutionStateService
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import RunCreateRequest
from figura.runtime.run_lock import PerRunExecutionLock
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.tools import ToolContext, ToolInvocation, ToolOutcome, ToolRegistry, ToolRuntime
from figura.tools.implementations.extract_text import extract_text_definition
from figura.tools.implementations.image import image_tool_definitions
from figura.tools.implementations.measure_chart import measure_chart_definition
from figura.tools.measurements.family_adapters import current_chart_family_adapters
from figura.tools.measurements.ocr import OCRObservation, OCRSnippet
from tests.figura_sources_support import make_attachment_service, make_panel_service, make_execution_image_reader


def _image_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pie_bytes() -> bytes:
    image = Image.new("RGB", (300, 260), "white")
    draw = ImageDraw.Draw(image)
    for start, end, color in ((0, 120, "#e53935"), (120, 240, "#43a047"), (240, 360, "#1e88e5")):
        draw.pieslice((70, 40, 190, 160), start, end, fill=color)
    return _image_bytes(image)


def _setup(tmp_path, content: bytes):
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
    attachment = attachments.upload(session.session_id, "chart.png", content)
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请观察图表。",
            attachment_ids=(attachment.attachment_id,),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="observation-tool-test",
        )
    )
    panels = make_panel_service(store, attachments)
    state = RunExecutionStateService(coordinator, panels)
    reader = make_execution_image_reader(attachments, panels)
    return store, coordinator, session, run, attachments, panels, state, reader, attachment


def _invoke(runtime, name: str, arguments: dict[str, object], run_id: str, session_id: str):
    call_id = f"{name}-call"
    invocation = ToolInvocation(call_id, name, json.dumps(arguments))
    return runtime.invoke(invocation, ToolContext(run_id, session_id, call_id))


def test_extract_text_reports_available_empty_and_unavailable_observations(tmp_path, monkeypatch) -> None:
    (_store, _coordinator, session, run, attachments, panels, state, reader, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (80, 60), "white"))
    )
    runtime = ToolRuntime(ToolRegistry("ocr-tests", (extract_text_definition(state.for_run, reader),)))

    monkeypatch.setattr(ocr_module, "_engine", lambda _image: SimpleNamespace(boxes=[], txts=[], scores=[]))
    empty = _invoke(runtime, "extract_text", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
    }, run.run_id, session.session_id)
    assert empty.outcome is ToolOutcome.SUCCEEDED
    assert empty.result["available"] is True
    assert empty.result["truncated"] is False
    assert empty.result["snippets"] == ()

    class BrokenEngine:
        def __call__(self, _image):
            raise RuntimeError("engine error")

    monkeypatch.setattr(ocr_module, "_engine", BrokenEngine())
    unavailable = _invoke(runtime, "extract_text", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
    }, run.run_id, session.session_id)
    assert unavailable.outcome is ToolOutcome.SUCCEEDED
    assert unavailable.result["available"] is False
    assert unavailable.result["snippets"] == ()


def test_extract_text_authorizes_source_and_keeps_scoped_boxes_in_source_coordinates(tmp_path, monkeypatch) -> None:
    (_store, coordinator, session, run, attachments, _panels, state, reader, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (100, 80), "white"))
    )
    other = coordinator.create_session()
    foreign = attachments.upload(other.session_id, "foreign.png", _image_bytes(Image.new("RGB", (100, 80), "white")))
    reads: list[str] = []
    original_resolve = type(attachments).resolve

    def track_resolve(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original_resolve(service, session_id, attachment_id)

    monkeypatch.setattr(type(attachments), "resolve", track_resolve)
    runtime = ToolRuntime(ToolRegistry("ocr-source-tests", (extract_text_definition(state.for_run, reader),)))
    rejected = _invoke(runtime, "extract_text", {
        "source_kind": "attachment", "source_id": foreign.attachment_id,
    }, run.run_id, session.session_id)
    assert rejected.outcome is ToolOutcome.FAILED
    assert rejected.error.code == "image_not_available"
    assert reads == []

    monkeypatch.setattr(ocr_module, "_engine", lambda _image: SimpleNamespace(
        boxes=[
            [(10, 12), (25, 12), (25, 24), (10, 24)],
            [(70, 12), (85, 12), (85, 24), (70, 24)],
        ],
        txts=["inside", "outside"],
        scores=[0.91, 0.9],
    ))
    result = _invoke(runtime, "extract_text", {
        "source_kind": "attachment",
        "source_id": attachment.attachment_id,
        "observation_scope": {"include": [[[0, 0], [500, 0], [500, 1000], [0, 1000]]]},
    }, run.run_id, session.session_id)
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["image_size"] == {"width": 100, "height": 80}
    assert result.result["coordinate_system"] == "attachment_px"
    assert [item["text"] for item in result.result["snippets"]] == ["inside"]
    assert result.result["snippets"][0]["bbox_px"] == (10, 12, 15, 12)


def test_extract_text_enforces_text_and_candidate_truncation_limits(tmp_path, monkeypatch) -> None:
    (_store, _coordinator, session, run, _attachments, _panels, state, reader, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (100, 80), "white"))
    )
    runtime = ToolRuntime(ToolRegistry("ocr-bounds", (extract_text_definition(state.for_run, reader),)))
    monkeypatch.setattr(ocr_module, "_engine", lambda _image: SimpleNamespace(
        boxes=[[(2, 2), (8, 2), (8, 8), (2, 8)]], txts=["t" * 140], scores=[0.8],
    ))
    result = _invoke(runtime, "extract_text", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
    }, run.run_id, session.session_id)
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["truncated"] is True
    assert len(result.result["snippets"]) == 1
    assert len(result.result["snippets"][0]["text"]) == 128

    monkeypatch.setattr(ocr_module, "_engine", lambda _image: SimpleNamespace(
        boxes=[[(2, 2), (8, 2), (8, 8), (2, 8)]] * 513,
        txts=["short"] * 513,
        scores=[0.8] * 513,
    ))
    count_limited = _invoke(runtime, "extract_text", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
    }, run.run_id, session.session_id)
    assert count_limited.outcome is ToolOutcome.SUCCEEDED
    assert count_limited.result["truncated"] is True
    assert len(count_limited.result["snippets"]) == 512
    assert len({item["snippet_id"] for item in count_limited.result["snippets"]}) == 512


def test_measure_chart_authorizes_attachment_and_requires_a_valid_scope(tmp_path, monkeypatch) -> None:
    (_store, coordinator, session, run, attachments, _panels, state, reader, attachment) = _setup(tmp_path, _pie_bytes())
    other = coordinator.create_session()
    foreign = attachments.upload(other.session_id, "foreign.png", _pie_bytes())
    reads: list[str] = []
    original_resolve = type(attachments).resolve

    def track_resolve(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original_resolve(service, session_id, attachment_id)

    monkeypatch.setattr(type(attachments), "resolve", track_resolve)
    monkeypatch.setattr(pie_module, "recognize_text", lambda *_args: OCRObservation((), True))
    definition = measure_chart_definition(state.for_run, reader, current_chart_family_adapters())
    runtime = ToolRuntime(ToolRegistry("figura-web-v9", (definition,)))
    rejected = _invoke(runtime, "measure_chart", {
        "source_kind": "attachment", "source_id": foreign.attachment_id, "chart_type": "pie",
    }, run.run_id, session.session_id)
    assert rejected.outcome is ToolOutcome.FAILED
    assert rejected.error.code == "image_not_available"
    assert reads == []

    invalid_scope = _invoke(runtime, "measure_chart", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
        "chart_type": "pie", "observation_scope": {"exclude": [[[0, 0], [1000, 0], [1000, 1000], [0, 1000]]]},
    }, run.run_id, session.session_id)
    assert invalid_scope.outcome is ToolOutcome.FAILED
    assert invalid_scope.error.code == "invalid_observation_scope"

    valid = _invoke(runtime, "measure_chart", {
        "source_kind": "attachment", "source_id": attachment.attachment_id, "chart_type": "pie",
    }, run.run_id, session.session_id)
    assert valid.outcome is ToolOutcome.SUCCEEDED
    assert valid.result["schema_version"] == 2
    assert valid.result["chart_type"] == "pie"
    assert valid.result["source_id"] == attachment.attachment_id
    assert valid.result["coordinate_system"] == "attachment_px"
    assert valid.result["observations"]["sectors"]
    assert "image_bytes" not in valid.result
    assert reads == [attachment.attachment_id, attachment.attachment_id]


def test_measurement_registry_has_no_family_specific_legacy_aliases(tmp_path) -> None:
    (_store, _coordinator, _session, _run, _attachments, _panels, state, reader, _attachment) = _setup(tmp_path, _pie_bytes())
    definitions = (
        extract_text_definition(state.for_run, reader),
        measure_chart_definition(state.for_run, reader, current_chart_family_adapters()),
    )
    registry = ToolRegistry("figura-web-v9", definitions)

    assert registry.version == "figura-web-v9"
    assert {item.name for item in registry} == {"extract_text", "measure_chart"}
    assert all("observation_scope" in item.parameters_schema["properties"] for item in definitions)
    assert registry.get("measure_bars") is None
    assert registry.get("measure_lines") is None
    assert registry.get("measure_scatter") is None
    assert registry.get("measure_pie") is None


def test_panel_crop_hidden_pixels_are_removed_before_measurement(tmp_path, monkeypatch) -> None:
    from figura.sources.imaging import crop_panel
    from figura.sources.models import PanelPoint

    content = crop_panel(_image_bytes(Image.new("RGB", (100, 80), (220, 30, 40))), (
        PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(0, 1000),
    ))
    store, coordinator, session, run, attachments, panels, state, reader, _attachment = _setup(tmp_path, content)
    definitions = image_tool_definitions(state.for_run, reader, panels)
    registry = ToolRegistry("panel-tools", definitions)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    call = ProviderToolCall("panel-call", "decompose_chart_image", json.dumps({
        "attachment_id": attachment_id,
        "panels": [{"name": "主图", "points": [
            {"x": 0, "y": 0}, {"x": 1000, "y": 0},
            {"x": 1000, "y": 1000}, {"x": 0, "y": 1000},
        ]}],
    }))
    current = coordinator.read_run_state(session.session_id, run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, current.checkpoint.revision)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.commit_model_response(
        session.session_id, run.run_id, claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "拆分图表。", (call,), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id, registry_version=registry.version,
    )
    DurableToolExecutor(
        store, registry, execution_lock=PerRunExecutionLock(store.data_root),
    ).execute_pending(session.session_id, run.run_id)
    panel_id = state.for_run(session.session_id, run.run_id).list("panel")[0].ref.id

    observed: list[np.ndarray] = []

    def detect(rgb):
        observed.append(rgb.copy())
        return SimpleNamespace(boxes=[], txts=[], scores=[])

    monkeypatch.setattr(ocr_module, "_engine", detect)
    definition = measure_chart_definition(state.for_run, reader, current_chart_family_adapters())
    result = _invoke(ToolRuntime(ToolRegistry("panel-measure", (definition,))), "measure_chart", {
        "source_kind": "panel", "source_id": panel_id, "chart_type": "bar",
    }, run.run_id, session.session_id)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["coordinate_system"] == "panel_px"
    assert observed
    assert tuple(observed[0][79, 99]) == (255, 255, 255)


def test_transparent_chart_is_rejected_before_measurement_sensor_runs(tmp_path, monkeypatch) -> None:
    (_store, _coordinator, session, run, _attachments, _panels, state, reader, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGBA", (100, 80), (220, 30, 40, 0)))
    )
    detected: list[bool] = []

    def detect(*_args, **_kwargs):
        detected.append(True)
        raise AssertionError("transparent input must be rejected before sensor execution")

    monkeypatch.setattr(bars_module, "recognize_text", detect)
    monkeypatch.setattr(ocr_module, "_engine", detect)
    definition = measure_chart_definition(state.for_run, reader, current_chart_family_adapters())
    runtime = ToolRuntime(ToolRegistry("transparent-measure", (definition,)))
    result = _invoke(runtime, "measure_chart", {
        "source_kind": "attachment", "source_id": attachment.attachment_id, "chart_type": "bar",
    }, run.run_id, session.session_id)

    assert result.outcome is ToolOutcome.FAILED
    assert result.error.code == "image_unavailable"
    assert detected == []
