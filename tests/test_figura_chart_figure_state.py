from __future__ import annotations

from tests.figura_sources_support import (
    make_attachment_service,
    make_execution_image_reader,
    make_panel_service,
)

import json
import hashlib

import pytest

from figura.agent.execution_resources import (
    ChartFigureContent,
    ChartFigureResult,
    ChartRenderContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.request import AgentRequestBuilder
from figura.charts.chartfigure.rendering import render_chart_figure_image
from figura.charts.chartfigure import parse_chart_figure
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ImageBlock,
    MessageRole,
    ProviderFactory,
    ProviderId,
    ProviderInputError,
    ProviderResponse,
    ProviderToolCall,
    TextBlock,
)
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunCreateRequest, ToolFactKind
from figura.runtime.records import ToolCallFact, ToolResultFact
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.sources.chart_renders import FiguraChartRenderService
from figura.tools import ToolContext, ToolInvocation, ToolOutcome, ToolRegistry, ToolRuntime
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
import figura.tools.implementations.render_chart_figure as render_module
from figura.tools.implementations.render_chart_figure import render_chart_figure_definition


def _figure(title: str, chart_id: str = "sales") -> dict[str, object]:
    return {
        "schema_version": 2,
        "title": title,
        "layout": {"columns": 1},
        "charts": [
            {
                "chart_id": chart_id,
                "chart_spec": {
                    "schema_version": 2,
                    "metadata": {"chart_type": "pie", "title": f"{title} chart"},
                    "coordinate_system": {"kind": "none"},
                    "dataset": {"slices": [{"id": "a", "label": "A", "value": 1}]},
                },
            }
        ],
    }


def _setup(tmp_path):
    store = FiguraRunStore(tmp_path)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: pytest.fail("the test must not send provider requests"),
    )
    coordinator = RunCoordinator(store, factory)
    attachments = make_attachment_service(store)
    panels = make_panel_service(store, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    renders = FiguraChartRenderService(store.data_root)
    registry = ToolRegistry(
        "figura-web-v10",
        (
            assemble_chart_figure_definition(execution_state.for_run),
            render_chart_figure_definition(execution_state.for_run, renders),
        ),
    )
    return store, coordinator, attachments, execution_state, registry


def _accepted_figures(state: RunExecutionState):
    return tuple(
        resource
        for resource in state.list("chart_figure")
        if isinstance(resource.content, ChartFigureContent)
        and resource.content.result is not None
    )


def _request_builder(store, attachments, execution_state):
    panels = make_panel_service(store, attachments)
    return AgentRequestBuilder(
        execution_state,
        make_execution_image_reader(
            attachments,
            panels,
            FiguraChartRenderService(store.data_root),
        ),
    )


def _prepare_provider_request(request) -> None:
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    factory.create(request.provider_id, request.model_id).prepare(request)


def _render_entries(state: RunExecutionState):
    return tuple(
        (resource.ref, resource.content)
        for resource in state.list("chart_render")
        if isinstance(resource.ref, ToolResourceRef)
        and isinstance(resource.content, ChartRenderContent)
    )


def _create_run(coordinator: RunCoordinator, session_id: str, key: str):
    return coordinator.create_run(
        RunCreateRequest(
            session_id=session_id,
            text="继续分析图表。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key=key,
        )
    )


def _commit_calls(coordinator, session_id, run_id, registry, values):
    state = coordinator.read_run_state(session_id, run_id)
    provider_attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    calls = tuple(
        ProviderToolCall(
            call_id,
            "assemble_chart_figure",
            json.dumps(figure, ensure_ascii=False, separators=(",", ":")),
        )
        for call_id, figure in values
    )
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "整理图表画布。",
            calls,
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=provider_attempt.attempt_id,
        registry_version=registry.version,
    )


def _commit_mixed_calls(coordinator, session_id, run_id, registry, figure):
    state = coordinator.read_run_state(session_id, run_id)
    provider_attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    assembly_call_id = f"assembly-{run_id}"
    render_call_id = f"render-{run_id}"
    calls = (
        ProviderToolCall(
            assembly_call_id,
            "assemble_chart_figure",
            json.dumps(figure, ensure_ascii=False, separators=(",", ":")),
        ),
        ProviderToolCall(
            render_call_id,
            "render_chart_figure",
            json.dumps(
                {"figure_ref": {"run_id": run_id, "call_id": assembly_call_id}},
                separators=(",", ":"),
            ),
        ),
    )
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "先组合，再绘制。",
            calls,
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=provider_attempt.attempt_id,
        registry_version=registry.version,
    )


def _commit_render_calls(coordinator, session_id, run_id, registry, values):
    state = coordinator.read_run_state(session_id, run_id)
    provider_attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    calls = tuple(
        ProviderToolCall(
            call_id,
            "render_chart_figure",
            json.dumps({"figure_ref": figure_ref}, separators=(",", ":")),
        )
        for call_id, figure_ref in values
    )
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "绘制 Figure。",
            calls,
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=provider_attempt.attempt_id,
        registry_version=registry.version,
    )


def _complete_run(coordinator, session_id, run_id, registry):
    state = coordinator.read_run_state(session_id, run_id)
    provider_attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "已完成。",
            (),
            FinishReason.STOP,
        ),
        provider_attempt_id=provider_attempt.attempt_id,
        registry_version=registry.version,
    )
    committed = coordinator.read_run_state(session_id, run_id)
    coordinator.complete_run(session_id, run_id, committed.checkpoint.revision)


def _facts(state, kind, payload_type):
    return [
        fact.payload
        for fact in state.tool_facts
        if fact.fact_kind is kind and isinstance(fact.payload, payload_type)
    ]


def test_successful_figure_is_retained_in_existing_tool_call_and_result_facts(tmp_path) -> None:
    store, coordinator, _attachments, execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "persist-figure")
    figure = _figure("Durable figure")
    arguments_json = json.dumps(figure, ensure_ascii=False, separators=(",", ":"))
    _commit_calls(
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        [("figure-call", figure)],
    )

    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)
    calls = _facts(state, ToolFactKind.TOOL_CALL, ToolCallFact)
    results = _facts(state, ToolFactKind.TOOL_RESULT, ToolResultFact)

    assert state.run.run_id == run.run_id
    assert calls[0].arguments_json == arguments_json
    assert results[0].outcome is ToolOutcome.SUCCEEDED
    assert results[0].result is not None
    assert set(results[0].result) == {"figure_ref", "figure_digest", "title", "charts"}
    assert results[0].result["figure_ref"] == {"run_id": run.run_id, "call_id": "figure-call"}
    assert results[0].result["title"] == "Durable figure"
    resource = _accepted_figures(execution_state.for_run(session.session_id, run.run_id))[0]
    assert resource.ref == ToolResourceRef("chart_figure", run.run_id, "figure-call")
    assert resource.content.result is not None
    assert resource.content.result.figure.title == "Durable figure"
    assert resource.content.result.figure == parse_chart_figure(figure)


def test_state_projection_orders_prior_and_current_figures_and_omits_failed_or_pending_calls(
    tmp_path,
) -> None:
    store, coordinator, attachments, execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    prior_run = _create_run(coordinator, session.session_id, "prior-figure-run")
    _commit_calls(
        coordinator,
        session.session_id,
        prior_run.run_id,
        registry,
        [("prior-figure", _figure("Prior figure"))],
    )
    DurableToolExecutor(store, registry).execute_pending(session.session_id, prior_run.run_id)
    _complete_run(coordinator, session.session_id, prior_run.run_id, registry)

    foreign_session = coordinator.create_session()
    foreign_run = _create_run(coordinator, foreign_session.session_id, "foreign-figure-run")
    _commit_calls(
        coordinator,
        foreign_session.session_id,
        foreign_run.run_id,
        registry,
        [("foreign-figure", _figure("Foreign figure"))],
    )
    DurableToolExecutor(store, registry).execute_pending(foreign_session.session_id, foreign_run.run_id)

    current_run = _create_run(coordinator, session.session_id, "current-figure-run")
    failed_figure = _figure("Failed figure")
    failed_figure["layout"] = {"columns": 2}
    pending_figure = _figure("Pending figure")
    _commit_calls(
        coordinator,
        session.session_id,
        current_run.run_id,
        registry,
        [
            ("current-figure", _figure("Current figure")),
            ("failed-figure", failed_figure),
            ("pending-figure", pending_figure),
        ],
    )

    partially_executed = DurableToolExecutor(store, registry).execute_pending(
        session.session_id, current_run.run_id, max_calls=2
    )
    partial_projection = execution_state.for_run(session.session_id, current_run.run_id)

    partial_figures = _accepted_figures(partial_projection)
    assert [item.content.result.figure.title for item in partial_figures] == [
        "Prior figure",
        "Current figure",
    ]
    assert all(item.ref.run_id != foreign_run.run_id for item in partial_figures)
    assert partially_executed.checkpoint.next_action is not None

    completed_tools = DurableToolExecutor(store, registry).execute_pending(
        session.session_id, current_run.run_id
    )
    projection = execution_state.for_run(session.session_id, current_run.run_id)

    accepted_figures = _accepted_figures(projection)
    assert [item.content.result.figure.title for item in accepted_figures] == [
        "Prior figure",
        "Current figure",
        "Pending figure",
    ]
    assert [item.ref.run_id for item in accepted_figures] == [
        prior_run.run_id,
        current_run.run_id,
        current_run.run_id,
    ]

    request = _request_builder(store, attachments, execution_state).build(
        completed_tools,
        registry,
        coordinator.read_prior_run_states(session.session_id, current_run.run_id),
    )
    inventory = json.loads(request.instructions[2].content.split("\n", 1)[1])
    figure_resources = [
        resource
        for resource in inventory["resources"]
        if resource["ref"]["kind"] == "chart_figure"
    ]
    titles = [resource["title"] for resource in figure_resources if "title" in resource]
    assert titles == ["Prior figure", "Current figure", "Pending figure"]
    assert any(
        resource["ref"]["call_id"] == "failed-figure"
        and resource["outcome"] == "failed"
        for resource in figure_resources
    )
    assert "Foreign figure" not in titles
    assert '"dataset"' not in json.dumps(figure_resources, ensure_ascii=False)
    full_chart_calls = [
        call
        for message in request.messages
        for call in message.tool_calls
        if call.name == "assemble_chart_figure"
    ]
    assert len(full_chart_calls) == 4
    assert all('"dataset"' in call.arguments for call in full_chart_calls)


def test_render_observations_include_prior_and_current_runs_and_structured_failure(
    tmp_path, monkeypatch
) -> None:
    store, coordinator, _attachments, execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    prior_run = _create_run(coordinator, session.session_id, "prior-render-run")
    _commit_mixed_calls(coordinator, session.session_id, prior_run.run_id, registry, _figure("Prior"))
    DurableToolExecutor(store, registry).execute_pending(session.session_id, prior_run.run_id)
    _complete_run(coordinator, session.session_id, prior_run.run_id, registry)

    current_run = _create_run(coordinator, session.session_id, "current-render-run")
    _commit_mixed_calls(
        coordinator, session.session_id, current_run.run_id, registry, _figure("Current")
    )
    DurableToolExecutor(store, registry).execute_pending(session.session_id, current_run.run_id)
    _complete_run(coordinator, session.session_id, current_run.run_id, registry)

    original_renderer = render_chart_figure_image
    should_fail = True

    def fail_once(value):
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise ValueError("controlled render failure")
        return original_renderer(value)

    monkeypatch.setattr(render_module, "render_chart_figure_image", fail_once)
    later_run = _create_run(coordinator, session.session_id, "later-render-run")
    prior_ref = {
        "run_id": prior_run.run_id,
        "call_id": f"assembly-{prior_run.run_id}",
    }
    current_ref = {
        "run_id": current_run.run_id,
        "call_id": f"assembly-{current_run.run_id}",
    }
    _commit_render_calls(
        coordinator,
        session.session_id,
        later_run.run_id,
        registry,
        [
            ("failed-render", current_ref),
            ("successful-render", prior_ref),
            ("successful-current-render", current_ref),
            ("unknown-render", {"run_id": "unknown-run", "call_id": "unknown-call"}),
        ],
    )
    executor = DurableToolExecutor(store, registry)
    partial = executor.execute_pending(session.session_id, later_run.run_id, max_calls=3)
    observations = _render_entries(execution_state.for_run(session.session_id, later_run.run_id))

    assert [ref.call_id for ref, _content in observations] == [
        f"render-{prior_run.run_id}",
        f"render-{current_run.run_id}",
        "failed-render",
        "successful-render",
        "successful-current-render",
    ]
    assert observations[-3][1].outcome is ToolOutcome.FAILED
    assert observations[-3][1].result is None
    assert observations[-3][1].error is not None
    assert observations[-2][1].outcome is ToolOutcome.SUCCEEDED
    assert observations[-1][1].outcome is ToolOutcome.SUCCEEDED
    assert observations[-1][1].error is None
    assert "figure_ref" not in observations[-1][1].result
    assert observations[-1][1].result["media_type"] == "image/png"
    assert partial.checkpoint.next_action is not None
    assert all(ref.call_id != "unknown-render" for ref, _content in observations)

    completed = executor.execute_pending(session.session_id, later_run.run_id)
    finished_projection = execution_state.for_run(session.session_id, later_run.run_id)
    unknown_render = next(
        content
        for ref, content in _render_entries(finished_projection)
        if ref.call_id == "unknown-render"
    )
    assert unknown_render.outcome is ToolOutcome.FAILED
    assert unknown_render.error is not None
    assert unknown_render.error.code == "figure_reference_not_found"
    request = _request_builder(store, _attachments, execution_state).build(
        completed,
        registry,
        coordinator.read_prior_run_states(session.session_id, later_run.run_id),
    )
    render_images = [
        block
        for message in request.messages
        for block in (message.content if isinstance(message.content, tuple) else ())
        if isinstance(block, ImageBlock)
    ]
    assert len(render_images) == 2
    current_render_texts = [
        block.text
        for message in request.messages
        for block in (message.content if isinstance(message.content, tuple) else ())
        if isinstance(block, TextBlock) and "Figure 图像回看" in block.text
    ]
    assert [text.rsplit("调用 ID：", 1)[-1].rstrip("。") for text in current_render_texts] == [
        "successful-render",
        "successful-current-render",
    ]


def test_render_tool_returns_bounded_metadata_and_replays_the_same_artifact(tmp_path) -> None:
    store, coordinator, _attachments, _execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "render-tool-run")
    _commit_calls(coordinator, session.session_id, run.run_id, registry, [("figure-call", _figure("Sales"))])
    DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)

    definition = registry["render_chart_figure"]
    runtime = ToolRuntime(ToolRegistry(registry.version, (definition,)))
    context = ToolContext(
        run_id=run.run_id,
        session_id=session.session_id,
        call_id="render-call",
        idempotency_key="e" * 64,
    )
    invocation = ToolInvocation(
        "render-call",
        "render_chart_figure",
        json.dumps({"figure_ref": {"run_id": run.run_id, "call_id": "figure-call"}}),
    )

    result = runtime.invoke(invocation, context)
    replay = runtime.invoke(invocation, context)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert replay.outcome is ToolOutcome.SUCCEEDED
    assert dict(result.result) == dict(replay.result)
    assert set(result.result) == {
        "figure_ref",
        "figure_digest",
        "image_sha256",
        "media_type",
        "byte_count",
        "width",
        "height",
    }
    assert result.result["figure_ref"] == {"run_id": run.run_id, "call_id": "figure-call"}
    assert result.result["media_type"] == "image/png"
    assert 0 < result.result["byte_count"] <= MAX_IMAGE_BYTES
    assert (result.result["width"], result.result["height"]) == (640, 522)
    content, width, height = FiguraChartRenderService(store.data_root).resolve(run.run_id, "render-call")
    assert hashlib.sha256(content).hexdigest() == result.result["image_sha256"]
    assert (width, height) == (result.result["width"], result.result["height"])


def test_render_tool_rejects_foreign_figure_and_typed_resource_rejects_digest_mismatch(tmp_path) -> None:
    store, coordinator, _attachments, execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "target-render-run")
    _commit_calls(coordinator, session.session_id, run.run_id, registry, [("figure-call", _figure("Local"))])
    DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)

    foreign_session = coordinator.create_session()
    foreign_run = _create_run(coordinator, foreign_session.session_id, "foreign-render-run")
    _commit_calls(
        coordinator,
        foreign_session.session_id,
        foreign_run.run_id,
        registry,
        [("foreign-figure", _figure("Foreign"))],
    )
    DurableToolExecutor(store, registry).execute_pending(foreign_session.session_id, foreign_run.run_id)

    definition = registry["render_chart_figure"]
    runtime = ToolRuntime(ToolRegistry(registry.version, (definition,)))
    foreign_invocation = ToolInvocation(
        "foreign-render",
        "render_chart_figure",
        json.dumps(
            {"figure_ref": {"run_id": foreign_run.run_id, "call_id": "foreign-figure"}}
        ),
    )
    foreign_result = runtime.invoke(
        foreign_invocation,
        ToolContext(run.run_id, session.session_id, "foreign-render", idempotency_key="f" * 64),
    )
    assert foreign_result.outcome is ToolOutcome.FAILED
    assert foreign_result.error.code == "figure_reference_not_found"

    accepted = _accepted_figures(execution_state.for_run(session.session_id, run.run_id))[0]
    assert isinstance(accepted.content, ChartFigureContent)
    assert accepted.content.result is not None
    with pytest.raises(ValueError, match="invalid ChartFigure resource result"):
        ChartFigureResult(accepted.content.result.figure, "0" * 64)


def test_completed_v8_tool_call_stays_inert_under_v9_registry(tmp_path) -> None:
    store, coordinator, _attachments, execution_state, current_registry = _setup(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "old-registry-run")
    prior_registry = ToolRegistry(
        "figura-web-v8",
        (assemble_chart_figure_definition(execution_state.for_run),),
    )
    _commit_calls(
        coordinator,
        session.session_id,
        run.run_id,
        prior_registry,
        [("old-figure", _figure("Earlier registry"))],
    )
    completed = DurableToolExecutor(store, prior_registry).execute_pending(
        session.session_id, run.run_id
    )

    replayed = DurableToolExecutor(store, current_registry).execute_pending(
        session.session_id, run.run_id
    )

    assert current_registry.version == "figura-web-v10"
    assert replayed.checkpoint.revision == completed.checkpoint.revision
    assert replayed.tool_facts == completed.tool_facts


def test_render_feedback_fails_on_corrupt_png_before_provider_attempt(tmp_path) -> None:
    store, coordinator, attachments, execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "corrupt-render-run")
    _commit_mixed_calls(coordinator, session.session_id, run.run_id, registry, _figure("Broken"))
    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)
    path = next((store.data_root / "chart-renders").glob("*.png"))
    path.write_bytes(b"corrupted png")
    prior_attempts = coordinator.read_run_state(session.session_id, run.run_id).provider_attempts

    builder = _request_builder(store, attachments, execution_state)
    with pytest.raises(RunError) as error:
        builder.build(state, registry)

    assert error.value.code is RunErrorCode.INTEGRITY_ERROR
    assert coordinator.read_run_state(session.session_id, run.run_id).provider_attempts == prior_attempts


@pytest.mark.parametrize(
    ("limit_name", "limit_value"),
    (("MAX_IMAGE_BYTES", 1), ("MAX_TOTAL_IMAGE_BYTES", 1)),
)
def test_render_feedback_provider_image_limit_fails_before_provider_attempt(
    tmp_path, monkeypatch, limit_name: str, limit_value: int
) -> None:
    import figura.providers.validation as provider_validation

    store, coordinator, attachments, execution_state, registry = _setup(tmp_path)
    session = coordinator.create_session()
    run = _create_run(coordinator, session.session_id, "render-limit-run")
    _commit_mixed_calls(coordinator, session.session_id, run.run_id, registry, _figure("Limit"))
    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id)
    prior_attempts = coordinator.read_run_state(session.session_id, run.run_id).provider_attempts
    monkeypatch.setattr(provider_validation, limit_name, limit_value)

    builder = _request_builder(store, attachments, execution_state)
    request = builder.build(state, registry)
    with pytest.raises(ProviderInputError):
        _prepare_provider_request(request)
    assert coordinator.read_run_state(session.session_id, run.run_id).provider_attempts == prior_attempts
