from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

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
from figura.tools.implementations.measure_pie import measure_pie_definition
from figura.tools.implementations.measure_bars import measure_bars_definition
from figura.tools.implementations.measure_lines import measure_lines_definition
from figura.tools.implementations.measure_scatter import measure_scatter_definition
from figura.tools.measurements.ocr import OCRObservation, OCRSnippet
from figura.tools.measurements.pie import measure_pie_image
from tests.figura_sources_support import make_attachment_service, make_panel_service, make_execution_image_reader


def _image_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pie_bytes(*, ellipse: bool = False, donut: bool = False, exploded: bool = False) -> bytes:
    image = Image.new("RGB", (300, 260), "white")
    draw = ImageDraw.Draw(image)
    bounds = (55, 50, 205, 170) if ellipse else (70, 40, 190, 160)
    for start, end, color in (
        (0, 120, "#e53935"),
        (120, 240, "#43a047"),
        (240, 360, "#1e88e5"),
    ):
        if exploded:
            import math

            middle = math.radians((start + end) / 2)
            dx, dy = round(8 * math.cos(middle)), round(8 * math.sin(middle))
            sector_bounds = tuple(value + delta for value, delta in zip(bounds, (dx, dy, dx, dy), strict=True))
        else:
            sector_bounds = bounds
        draw.pieslice(sector_bounds, start, end, fill=color)
    if donut:
        left, top, right, bottom = bounds
        cx, cy = (left + right) // 2, (top + bottom) // 2
        draw.ellipse((cx - 23, cy - 23, cx + 23, cy + 23), fill="white")
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
    execution_state = RunExecutionStateService(coordinator, panels)
    return store, coordinator, session, run, attachments, panels, execution_state, attachment


def _invoke(runtime, name: str, arguments: dict[str, object], run_id: str, session_id: str):
    call_id = f"{name}-call"
    invocation = ToolInvocation(call_id, name, json.dumps(arguments))
    return runtime.invoke(invocation, ToolContext(run_id, session_id, call_id))


def test_extract_text_returns_available_empty_and_unavailable_observations(tmp_path, monkeypatch) -> None:
    (_store, _coordinator, session, run, attachments, panels, state, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (80, 60), "white"))
    )
    definition = extract_text_definition(state.for_run, make_execution_image_reader(attachments, panels))
    runtime = ToolRuntime(ToolRegistry("ocr-tests", (definition,)))

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
    (_store, coordinator, session, run, attachments, panels, state, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (100, 80), "white"))
    )
    other = coordinator.create_session()
    foreign = attachments.upload(other.session_id, "foreign.png", _image_bytes(Image.new("RGB", (100, 80), "white")))
    original_resolve = type(attachments).resolve
    reads: list[str] = []

    def track_resolve(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original_resolve(service, session_id, attachment_id)

    monkeypatch.setattr(type(attachments), "resolve", track_resolve)
    runtime = ToolRuntime(ToolRegistry("ocr-source-tests", (extract_text_definition(state.for_run, make_execution_image_reader(attachments, panels)),)))
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


def test_extract_text_applies_both_output_truncation_limits(tmp_path, monkeypatch) -> None:
    (_store, _coordinator, session, run, attachments, panels, state, attachment) = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (100, 80), "white"))
    )
    runtime = ToolRuntime(ToolRegistry("ocr-bounds", (extract_text_definition(state.for_run, make_execution_image_reader(attachments, panels)),)))

    monkeypatch.setattr(ocr_module, "_engine", lambda _image: SimpleNamespace(
        boxes=[[(2, 2), (8, 2), (8, 8), (2, 8)]],
        txts=["t" * 140],
        scores=[0.8],
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


def test_pie_sensor_measures_supported_circle_without_cartesian_axes(monkeypatch) -> None:
    monkeypatch.setattr(pie_module, "recognize_text", lambda *_args: OCRObservation((), True))
    result = measure_pie_image(_pie_bytes())

    assert result["image_size"] == {"width": 300, "height": 260}
    assert result["status"] == "measured"
    assert result["plot_region"] is not None
    assert len(result["sectors"]) == 3
    assert all(item["ratio"] == pytest.approx(1 / 3, abs=0.01) for item in result["sectors"])
    assert all(item["color"].startswith("#") for item in result["sectors"])
    assert all(item["start_angle_deg"] < 360 for item in result["sectors"])
    assert "axes" not in result


def test_pie_sensor_reports_empty_and_unsupported_geometry(monkeypatch) -> None:
    monkeypatch.setattr(pie_module, "recognize_text", lambda *_args: OCRObservation((), True))
    blank = measure_pie_image(_image_bytes(Image.new("RGB", (300, 260), "white")))
    donut = measure_pie_image(_pie_bytes(donut=True))
    exploded = measure_pie_image(_pie_bytes(exploded=True))
    ellipse = measure_pie_image(_pie_bytes(ellipse=True))

    assert blank["status"] == "no_evidence"
    assert blank["plot_region"] is None
    assert blank["sectors"] == []
    assert donut["status"] == "unsupported"
    assert exploded["status"] == "unsupported"
    assert ellipse["status"] == "unsupported"


def test_pie_sensor_keeps_scoped_partial_sectors_and_associates_ocr(monkeypatch) -> None:
    scope = {"exclude": [[[434, 385], [466, 158], [575, 221], [631, 359]]]}
    monkeypatch.setattr(pie_module, "recognize_text", lambda *_args: OCRObservation((
        OCRSnippet("text_1", "Revenue", (142, 123, 10, 8), 0.92),
    ), True))

    result = measure_pie_image(_pie_bytes(), scope)

    assert result["status"] == "partial"
    assert result["sectors"]
    assert any(item["ratio"] is None for item in result["sectors"])
    red = next(item for item in result["sectors"] if item["color"] == "#e83838")
    assert red["label_text"] == "Revenue"
    assert red["label_confidence"] == 0.92


def test_measure_pie_adapter_authorizes_sources_and_rejects_invalid_scope(tmp_path, monkeypatch) -> None:
    (_store, coordinator, session, run, attachments, panels, state, attachment) = _setup(
        tmp_path, _pie_bytes()
    )
    other = coordinator.create_session()
    foreign = attachments.upload(other.session_id, "foreign.png", _pie_bytes())
    original_resolve = type(attachments).resolve
    reads: list[str] = []

    def track_resolve(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original_resolve(service, session_id, attachment_id)

    monkeypatch.setattr(type(attachments), "resolve", track_resolve)
    monkeypatch.setattr(pie_module, "recognize_text", lambda *_args: OCRObservation((), True))
    definition = measure_pie_definition(state.for_run, make_execution_image_reader(attachments, panels))
    runtime = ToolRuntime(ToolRegistry("pie-tool-tests", (definition,)))
    rejected = _invoke(runtime, "measure_pie", {
        "source_kind": "attachment", "source_id": foreign.attachment_id,
    }, run.run_id, session.session_id)
    assert rejected.outcome is ToolOutcome.FAILED
    assert rejected.error.code == "image_not_available"
    assert reads == []

    invalid_scope = _invoke(runtime, "measure_pie", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
        "observation_scope": {},
    }, run.run_id, session.session_id)
    assert invalid_scope.outcome is ToolOutcome.FAILED
    assert invalid_scope.error.code == "invalid_observation_scope"

    valid = _invoke(runtime, "measure_pie", {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
    }, run.run_id, session.session_id)
    assert valid.outcome is ToolOutcome.SUCCEEDED
    assert valid.result["status"] == "measured"
    assert valid.result["source_id"] == attachment.attachment_id
    assert valid.result["coordinate_system"] == "attachment_px"
    assert "image_bytes" not in valid.result
    assert reads == [attachment.attachment_id, attachment.attachment_id]


def test_v4_observation_registry_uses_one_scope_contract_without_legacy_aliases(tmp_path) -> None:
    (_store, _coordinator, _session, _run, attachments, panels, state, _attachment) = _setup(
        tmp_path, _pie_bytes()
    )
    definitions = (
        extract_text_definition(state.for_run, make_execution_image_reader(attachments, panels)),
        measure_bars_definition(state.for_run, make_execution_image_reader(attachments, panels)),
        measure_lines_definition(state.for_run, make_execution_image_reader(attachments, panels)),
        measure_scatter_definition(state.for_run, make_execution_image_reader(attachments, panels)),
        measure_pie_definition(state.for_run, make_execution_image_reader(attachments, panels)),
    )
    registry = ToolRegistry("figura-web-v4", definitions)

    assert registry.version == "figura-web-v4"
    assert {item.name for item in registry} == {
        "extract_text", "measure_bars", "measure_lines", "measure_scatter", "measure_pie",
    }
    assert all("observation_scope" in item.parameters_schema["properties"] for item in definitions)
    assert registry.get("extract_pie_slices") is None


@pytest.mark.parametrize("triangle", [False, True])
def test_extract_text_accepts_authorized_panel_images(tmp_path, monkeypatch, triangle) -> None:
    store, coordinator, session, run, attachments, panels, state, attachment = _setup(
        tmp_path, _image_bytes(Image.new("RGB", (100, 80), "white"))
    )
    panel_registry = ToolRegistry(
        "panel-test-tools",
        image_tool_definitions(state.for_run, make_execution_image_reader(attachments, panels), panels),
    )
    args = json.dumps({
        "attachment_id": attachment.attachment_id,
        "panels": [{"name": "主图", "points": (
            [{"x": 0, "y": 0}, {"x": 1000, "y": 0}, {"x": 0, "y": 1000}]
            if triangle else [
                {"x": 0, "y": 0}, {"x": 1000, "y": 0},
                {"x": 1000, "y": 1000}, {"x": 0, "y": 1000},
            ]
        )}],
    })
    call = ProviderToolCall("panel-call", "decompose_chart_image", args)
    current = coordinator.read_run_state(session.session_id, run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, current.checkpoint.revision)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "拆分图表。", (call,), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id,
        registry_version=panel_registry.version,
    )
    DurableToolExecutor(
        store,
        panel_registry,
        execution_lock=PerRunExecutionLock(store.data_root),
    ).execute_pending(session.session_id, run.run_id)
    panel_id = state.for_run(session.session_id, run.run_id).list("panel")[0].ref.id
    monkeypatch.setattr(ocr_module, "_engine", lambda _image: SimpleNamespace(
        boxes=[
            [(8, 9), (28, 9), (28, 21), (8, 21)],
            [(42, 30), (65, 30), (65, 50), (42, 50)],
            [(80, 65), (90, 65), (90, 75), (80, 75)],
        ],
        txts=["Panel label", "crosses transparent boundary", "transparent"],
        scores=[0.88, 0.9, 0.9],
    ))
    runtime = ToolRuntime(ToolRegistry(
        "panel-ocr-tests",
        (extract_text_definition(state.for_run, make_execution_image_reader(attachments, panels)),),
    ))

    result = _invoke(runtime, "extract_text", {"source_kind": "panel", "source_id": panel_id}, run.run_id, session.session_id)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["coordinate_system"] == "panel_px"
    assert result.result["snippets"][0]["bbox_px"] == (8, 9, 20, 12)
    assert len(result.result["snippets"]) == (1 if triangle else 3)


_OBSERVATION_FACTORIES = (
    extract_text_definition, measure_bars_definition, measure_lines_definition,
    measure_scatter_definition, measure_pie_definition,
)


@pytest.mark.parametrize("factory", _OBSERVATION_FACTORIES, ids=lambda factory: factory.__name__)
def test_all_observation_adapters_neutralize_panel_crop_before_detection(tmp_path, monkeypatch, factory):
    from figura.sources.imaging import crop_panel
    from figura.sources.models import PanelPoint
    from figura.tools.measurements.observation_scope import decode_scoped_image

    crop = crop_panel(_image_bytes(Image.new("RGB", (100, 80), (220, 30, 40))), (
        PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(0, 1000),
    ))
    _store, _coordinator, session, run, attachments, panels, state, attachment = _setup(tmp_path, crop)
    definition = factory(state.for_run, make_execution_image_reader(attachments, panels))
    observed = []

    def engine(rgb):
        observed.append(rgb.copy())
        return SimpleNamespace(boxes=[], txts=[], scores=[])

    monkeypatch.setattr(ocr_module, "_engine", engine)
    result = _invoke(ToolRuntime(ToolRegistry("alpha-tests", (definition,))), definition.name, {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
    }, run.run_id, session.session_id)
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["image_size"] == {"width": 100, "height": 80}
    expected, _mask = decode_scoped_image(crop)
    assert observed
    for rgb in observed:
        np.testing.assert_array_equal(rgb, expected)
        assert tuple(rgb[79, 99]) == (255, 255, 255)


@pytest.mark.parametrize("factory", _OBSERVATION_FACTORIES, ids=lambda factory: factory.__name__)
@pytest.mark.parametrize("scope", [None, {"include": [[[0, 0], [1000, 0], [0, 1000]]]}])
def test_all_observation_adapters_reject_invisible_input_before_detectors(tmp_path, monkeypatch, factory, scope):
    import importlib

    _store, _coordinator, session, run, attachments, panels, state, attachment = _setup(
        tmp_path, _image_bytes(Image.new("RGBA", (100, 80), (220, 30, 40, 0))),
    )
    definition = factory(state.for_run, make_execution_image_reader(attachments, panels))
    detected = []

    def detect(*_args, **_kwargs):
        detected.append(True)
        raise AssertionError("must not reach detector")

    # Geometric adapters decode before invoking their OCR/geometry stages.
    module = importlib.import_module("figura.tools.measurements." + {
        "extract_text": "ocr", "measure_bars": "bars", "measure_lines": "lines",
        "measure_scatter": "scatter", "measure_pie": "pie",
    }[definition.name])
    monkeypatch.setattr(module, "recognize_text", detect)
    monkeypatch.setattr(ocr_module, "_engine", detect)
    arguments = {"source_kind": "attachment", "source_id": attachment.attachment_id}
    if scope is not None:
        arguments["observation_scope"] = scope
    result = _invoke(ToolRuntime(ToolRegistry("invisible-tests", (definition,))), definition.name,
        arguments, run.run_id, session.session_id)
    assert result.error.code == ("image_unavailable" if scope is None else "invalid_observation_scope")
    assert detected == []


def test_pie_sector_ratio_gate_requires_full_coverage_and_boundary_support() -> None:
    from figura.tools.measurements.pie import _sector_runs

    labels = np.repeat(np.array([0, 1]), 360)
    weak_support = np.full(720, 0.4)
    strong_support = np.full(720, 0.9)
    palette = ((230, 40, 40), (40, 180, 50))

    weak = _sector_runs(labels, weak_support, palette)
    strong = _sector_runs(labels, strong_support, palette)

    assert all(item["ratio"] is None for item in weak)
    assert [item["ratio"] for item in strong] == [0.5, 0.5]
