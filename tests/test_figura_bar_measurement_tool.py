from __future__ import annotations

import json
from io import BytesIO

from PIL import Image

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import MeasurementContent
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.request import AgentRequestBuilder
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import RunCreateRequest
from figura.runtime.run_lock import PerRunExecutionLock
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.tools import ReplayEffect, ToolContext, ToolDefinition, ToolInvocation, ToolOutcome, ToolRegistry, ToolRuntime
from figura.tools.implementations.measure_chart import MEASURE_CHART_PARAMETERS_SCHEMA, measure_chart_definition
from figura.tools.measurements.family_adapters import current_chart_family_adapters
from tests.figura_sources_support import make_execution_image_reader


def _chart_bytes() -> bytes:
    image = Image.new("RGB", (300, 200), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.line((25, 175, 275, 175), fill="black", width=2)
    draw.rectangle((55, 100, 90, 174), fill="#3366cc")
    draw.rectangle((130, 60, 165, 174), fill="#3366cc")
    draw.rectangle((205, 115, 240, 174), fill="#3366cc")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pie_chart_bytes() -> bytes:
    image = Image.new("RGB", (300, 200), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    for start, end, color in ((0, 120, "#e53935"), (120, 240, "#43a047"), (240, 360, "#1e88e5")):
        draw.pieslice((70, 30, 170, 130), start, end, fill=color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _blank_bytes() -> bytes:
    output = BytesIO()
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
    attachment = attachments.upload(session.session_id, "chart.png", image_bytes or _chart_bytes())
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请观察图表。",
            attachment_ids=(attachment.attachment_id,),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="measure-tool-run",
        )
    )
    panels = FiguraPanelService(repository, store.data_root, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    reader = make_execution_image_reader(attachments, panels)
    definition = measure_chart_definition(
        execution_state.for_run,
        reader,
        current_chart_family_adapters(),
    )
    registry = ToolRegistry("figura-web-v9", (definition,))
    return store, coordinator, session, run, attachments, panels, execution_state, registry, ToolRuntime(registry), attachment


def _request_builder(store, attachments, panels, execution_state) -> AgentRequestBuilder:
    return AgentRequestBuilder(
        execution_state,
        make_execution_image_reader(
            attachments,
            panels,
            FiguraChartRenderService(store.data_root),
        ),
    )


def _commit_measurements(store, coordinator, session_id, run_id, registry, calls) -> None:
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "观察图表。", tuple(calls), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )
    DurableToolExecutor(
        store,
        registry,
        execution_lock=PerRunExecutionLock(store.data_root),
    ).execute_pending(session_id, run_id)


def test_registry_exposes_one_explicit_family_measurement_contract(tmp_path) -> None:
    *_, registry, _runtime, _attachment = _setup(tmp_path)
    definition = registry["measure_chart"]

    assert definition.replay_effect is ReplayEffect.REPLAY_SAFE
    assert set(definition.parameters_schema["properties"]) == {
        "source_kind", "source_id", "chart_type", "observation_scope"
    }
    assert tuple(definition.parameters_schema["properties"]["chart_type"]["enum"]) == (
        "bar", "line", "scatter", "pie", "area", "histogram", "box_plot", "radar", "heatmap", "treemap"
    )
    assert registry.get("measure_bars") is None
    assert registry.get("measure_lines") is None
    assert registry.get("measure_scatter") is None
    assert registry.get("measure_pie") is None
    assert "chart_type" in MEASURE_CHART_PARAMETERS_SCHEMA["required"]


def test_measure_chart_commits_v2_measurement_and_typed_resource(tmp_path) -> None:
    store, coordinator, session, run, _attachments, _panels, execution_state, registry, _runtime, attachment = _setup(tmp_path)
    args = json.dumps({
        "source_kind": "attachment", "source_id": attachment.attachment_id, "chart_type": "bar",
    })
    _commit_measurements(store, coordinator, session.session_id, run.run_id, registry, (
        ProviderToolCall("measurement", "measure_chart", args),
    ))

    state = execution_state.for_run(session.session_id, run.run_id)
    measurements = state.list("measurement")
    assert len(measurements) == 1
    content = measurements[0].content
    assert isinstance(content, MeasurementContent)
    assert content.tool_name == "measure_chart"
    assert content.outcome is ToolOutcome.SUCCEEDED
    assert content.result["schema_version"] == 2
    assert content.result["chart_type"] == "bar"
    assert content.result["source_id"] == attachment.attachment_id
    assert content.result["coordinate_system"] == "attachment_px"
    assert content.result["observations"]["bars"]


def test_measure_chart_rejects_foreign_sources_before_reading_pixels(tmp_path, monkeypatch) -> None:
    (_store, coordinator, session, run, attachments, _panels, _state, _registry, runtime, _attachment) = _setup(tmp_path)
    other = coordinator.create_session()
    foreign = attachments.upload(other.session_id, "foreign.png", _chart_bytes())
    reads: list[str] = []
    original = type(attachments).resolve

    def track(service, session_id, attachment_id):
        reads.append(attachment_id)
        return original(service, session_id, attachment_id)

    monkeypatch.setattr(type(attachments), "resolve", track)
    call_id = "foreign-measurement"
    result = runtime.invoke(
        ToolInvocation(call_id, "measure_chart", json.dumps({
            "source_kind": "attachment", "source_id": foreign.attachment_id, "chart_type": "bar",
        })),
        ToolContext(run.run_id, session.session_id, call_id),
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.error.code == "image_not_available"
    assert reads == []


def test_measure_chart_preserves_family_choice_and_returns_partial_observation(tmp_path) -> None:
    (_store, _coordinator, session, run, _attachments, _panels, _state, _registry, runtime, attachment) = _setup(
        tmp_path, _pie_chart_bytes()
    )
    call_id = "pie-measurement"
    result = runtime.invoke(
        ToolInvocation(call_id, "measure_chart", json.dumps({
            "source_kind": "attachment", "source_id": attachment.attachment_id, "chart_type": "pie",
        })),
        ToolContext(run.run_id, session.session_id, call_id),
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.result["chart_type"] == "pie"
    assert result.result["observations"]["sectors"]
    assert all("value" not in sector for sector in result.result["observations"]["sectors"])


def test_successful_measurement_can_be_read_as_a_v2_annotation(tmp_path) -> None:
    store, coordinator, session, run, _attachments, _panels, execution_state, registry, _runtime, attachment = _setup(tmp_path)
    _commit_measurements(store, coordinator, session.session_id, run.run_id, registry, (
        ProviderToolCall("measurement", "measure_chart", json.dumps({
            "source_kind": "attachment", "source_id": attachment.attachment_id, "chart_type": "bar",
        })),
    ))
    reader = RunExecutionImageReader(
        _attachments,
        _panels,
        FiguraChartRenderService(store.data_root),
    )

    annotated, width, height = reader.read(
        session.session_id,
        execution_state.for_run(session.session_id, run.run_id),
        execution_state.for_run(session.session_id, run.run_id).list("measurement")[0].ref,
    )
    with Image.open(BytesIO(annotated)) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (width, height) == (300, 200)


def test_old_measurement_facts_remain_raw_and_are_not_projected_as_v2(tmp_path) -> None:
    store, coordinator, session, run, _attachments, _panels, execution_state, _registry, _runtime, _attachment = _setup(tmp_path)
    legacy = ToolDefinition(
        name="measure_bars",
        description="historical test fact",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        result_schema={"type": "object", "properties": {}, "additionalProperties": False},
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=lambda _context, _arguments: {"bars": []},
    )
    old_registry = ToolRegistry("figura-web-v8", (legacy,))
    call = ProviderToolCall("legacy-call", "measure_bars", "{}")
    _commit_measurements(store, coordinator, session.session_id, run.run_id, old_registry, (call,))

    raw_state = coordinator.read_run_state(session.session_id, run.run_id)
    assert any(getattr(fact.payload, "tool_name", None) == "measure_bars" for fact in raw_state.tool_facts)
    assert execution_state.for_run(session.session_id, run.run_id).list("measurement") == ()
