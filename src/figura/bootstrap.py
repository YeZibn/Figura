"""Construct Figura services and connect them to the local Gateway."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from figura.shared.payloads import ExecutionPayloadLimits

from figura.agent import AgentExecutor, AgentRequestBuilder
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.gateway.application import FiguraGatewayApplication
from figura.gateway.dispatcher import RunDispatcher
from figura.gateway.session_deletion import FiguraSessionDeletion
from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_state import RunExecutionStateService
from figura.memory.retrieval import SessionHistorySearch
from figura.providers import ProviderFactory
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.runtime.run_lock import PerRunExecutionLock
from figura.runtime.models import RunStatus
from figura.runtime.records import ToolAttemptStartedFact, ToolCallFact
from figura.tools import ToolRegistry, ToolRuntime
from figura.tools.implementations.image import image_tool_definitions
from figura.tools.implementations.extract_text import extract_text_definition
from figura.tools.implementations.measure_chart import measure_chart_definition
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
from figura.tools.implementations.render_chart_figure import render_chart_figure_definition
from figura.tools.implementations.history import history_tool_definitions, historical_image_tool_definition
from figura.tools.measurements.family_adapters import current_chart_family_adapters


def create_application(
    project_root: str | Path,
    *,
    data_dir: str | Path | None = None,
    provider_factory: ProviderFactory | None = None,
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:1421",),
    max_workers: int = 3,
    max_queued: int = 8,
) -> FiguraGatewayApplication:
    root = Path(project_root).expanduser().resolve()
    selected_data_dir = Path(data_dir).expanduser() if data_dir is not None else root / ".figura"
    if not selected_data_dir.is_absolute():
        selected_data_dir = root / selected_data_dir
    limits = ExecutionPayloadLimits.from_env()
    store = FiguraRunStore(selected_data_dir, payload_limits=limits)
    sources = SourcesRepository(store.database)
    attachment_service = FiguraAttachmentService(sources, store.data_root)
    factory = provider_factory or ProviderFactory(payload_limits=limits)
    factory.payload_limits = limits
    coordinator = RunCoordinator(store, factory)
    panel_service = FiguraPanelService(sources, store.data_root, attachment_service)
    chart_renders = FiguraChartRenderService(store.data_root)
    session_deletion = FiguraSessionDeletion(
        store,
        sources,
        attachment_service,
        panel_service,
        chart_renders,
    )
    execution_state = RunExecutionStateService(coordinator, panel_service)
    execution_images = RunExecutionImageReader(attachment_service, panel_service, chart_renders)
    history = SessionHistorySearch(coordinator, execution_state)
    registry = ToolRegistry(
        "figura-web-v9",
        (
            *image_tool_definitions(execution_state.for_run, execution_images, panel_service),
            *history_tool_definitions(history),
            historical_image_tool_definition(history, execution_images),
            extract_text_definition(execution_state.for_run, execution_images),
            measure_chart_definition(
                execution_state.for_run,
                execution_images,
                current_chart_family_adapters(),
            ),
            assemble_chart_figure_definition(execution_state.for_run),
            render_chart_figure_definition(execution_state.for_run, chart_renders),
        ),
        payload_limits=limits,
    )
    _ensure_registry_cutover_ready(coordinator, registry.version)
    runtime = ToolRuntime(registry)
    lock = PerRunExecutionLock(store.data_root)
    tools = DurableToolExecutor(store, registry, runtime, execution_lock=lock)
    agent = AgentExecutor(
        coordinator,
        factory,
        tools,
        lock,
        AgentRequestBuilder(execution_state, execution_images),
    )
    dispatcher = RunDispatcher(agent, max_workers=max_workers, max_queued=max_queued)
    return FiguraGatewayApplication(
        coordinator,
        attachment_service,
        panel_service,
        execution_state,
        execution_images,
        factory,
        dispatcher,
        session_deletion,
        allowed_origins=allowed_origins,
    )


def recover_running_runs(application: FiguraGatewayApplication) -> int:
    """Schedule persisted Runs through the ordinary safe executor path."""
    return application.dispatcher.scan_ready(application.coordinator)


def _ensure_registry_cutover_ready(coordinator: RunCoordinator, registry_version: str) -> None:
    """Do not start v9 while any Run bound to v8 could still resume."""
    if registry_version != "figura-web-v9":
        return
    for run in coordinator.list_running_runs():
        state = coordinator.read_run_state(run.session_id, run.run_id)
        bound_versions = {
            fact.payload.registry_version
            for fact in state.tool_facts
            if isinstance(fact.payload, (ToolCallFact, ToolAttemptStartedFact))
        }
        bound_versions.update(
            manifest.get("registry_version")
            for binding in state.provider_request_bindings
            if isinstance((manifest := binding.asset_manifest), Mapping)
            and isinstance(manifest.get("registry_version"), str)
        )
        if state.run.status is RunStatus.RUNNING and "figura-web-v8" in bound_versions:
            raise RuntimeError(
                "Cannot activate Figura Registry v9 while a Run bound to v8 is still active; "
                "finish or interrupt all v8 Runs, then restart Figura."
            )
