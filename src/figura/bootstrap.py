"""Construct Figura services and connect them to the local Gateway."""

from __future__ import annotations

from pathlib import Path

from figura.agent import AgentExecutor, AgentRequestBuilder
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.gateway.application import FiguraGatewayApplication
from figura.gateway.dispatcher import RunDispatcher
from figura.agent.execution_state import RunExecutionStateService
from figura.providers import ProviderFactory
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.runtime.run_lock import PerRunExecutionLock
from figura.tools import ToolRegistry, ToolRuntime
from figura.tools.implementations.image import image_tool_definitions
from figura.tools.implementations.extract_text import extract_text_definition
from figura.tools.implementations.measure_bars import measure_bars_definition
from figura.tools.implementations.measure_lines import measure_lines_definition
from figura.tools.implementations.measure_pie import measure_pie_definition
from figura.tools.implementations.measure_scatter import measure_scatter_definition
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
from figura.tools.implementations.render_chart_figure import render_chart_figure_definition


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
    store = FiguraRunStore(selected_data_dir)
    sources = SourcesRepository(store.database)
    attachment_service = FiguraAttachmentService(sources, store.data_root)
    factory = provider_factory or ProviderFactory.from_env()
    coordinator = RunCoordinator(store, factory)
    panel_service = FiguraPanelService(sources, store.data_root, attachment_service)
    chart_renders = FiguraChartRenderService(store.data_root)
    execution_state = RunExecutionStateService(coordinator, panel_service)
    registry = ToolRegistry(
        "figura-web-v6",
        (
            *image_tool_definitions(execution_state.for_run, attachment_service, panel_service),
            extract_text_definition(execution_state.for_run, attachment_service, panel_service),
            measure_bars_definition(execution_state.for_run, attachment_service, panel_service),
            measure_lines_definition(execution_state.for_run, attachment_service, panel_service),
            measure_scatter_definition(execution_state.for_run, attachment_service, panel_service),
            measure_pie_definition(execution_state.for_run, attachment_service, panel_service),
            assemble_chart_figure_definition(execution_state.for_run),
            render_chart_figure_definition(execution_state.for_run, coordinator, chart_renders),
        ),
    )
    runtime = ToolRuntime(registry)
    lock = PerRunExecutionLock(store.data_root)
    tools = DurableToolExecutor(store, registry, runtime, execution_lock=lock)
    agent = AgentExecutor(
        coordinator,
        factory,
        tools,
        lock,
        AgentRequestBuilder(attachment_service, execution_state, chart_renders),
    )
    dispatcher = RunDispatcher(agent, max_workers=max_workers, max_queued=max_queued)
    return FiguraGatewayApplication(
        coordinator,
        attachment_service,
        panel_service,
        execution_state,
        chart_renders,
        factory,
        dispatcher,
        allowed_origins=allowed_origins,
    )


def recover_running_runs(application: FiguraGatewayApplication) -> int:
    """Schedule persisted Runs through the ordinary safe executor path."""
    scheduled = 0
    for run in application.coordinator.list_running_runs():
        if application.dispatcher.ensure_scheduled(run, wait_for_capacity=True):
            scheduled += 1
    return scheduled
