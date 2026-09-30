"""Construction helpers for tests that share a Figura SQLite database."""

from figura.sources.attachments import FiguraAttachmentService
from figura.agent.execution_images import RunExecutionImageReader
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.runtime.store import FiguraRunStore


def make_attachment_service(store: FiguraRunStore) -> FiguraAttachmentService:
    repository = SourcesRepository(store.database)
    return FiguraAttachmentService(repository, store.data_root)


def make_panel_service(
    store: FiguraRunStore,
    attachments: FiguraAttachmentService,
) -> FiguraPanelService:
    repository = SourcesRepository(store.database)
    return FiguraPanelService(repository, store.data_root, attachments)


def make_execution_image_reader(
    attachments: FiguraAttachmentService,
    panels: FiguraPanelService,
    chart_renders: FiguraChartRenderService | None = None,
) -> RunExecutionImageReader:
    return RunExecutionImageReader(attachments, panels, chart_renders)
