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


def make_tool_runtime(registry, *, store=None, reader=None, inventory=None):
    """Tests wire the same explicit media boundary as bootstrap, with real storage."""
    from figura.tools import ToolRuntime
    from figura.agent.execution_state import RunExecutionStateService
    from figura.providers import ProviderFactory
    from figura.runtime.coordinator import RunCoordinator
    if store is not None:
        attachments = make_attachment_service(store)
        panels = make_panel_service(store, attachments)
        reader = make_execution_image_reader(attachments, panels, FiguraChartRenderService(store.data_root))
        inventory = RunExecutionStateService(RunCoordinator(store, ProviderFactory.from_env({})), panels).for_run
    if reader is None or inventory is None:
        return ToolRuntime(registry)
    return ToolRuntime(registry, media_committer=reader.media_committer(inventory))


def make_durable_tool_executor(store, registry, runtime=None, **kwargs):
    from figura.runtime.tool_execution import DurableToolExecutor
    return DurableToolExecutor(store, registry, runtime or make_tool_runtime(registry, store=store), **kwargs)


def open_legacy_schema_for_test(data_root):
    """Test only: isolate pre-media DDL tests from the new activation requirement.

    Production startup never calls this. Real deployments use the backed-up
    migration entry, which additionally requires terminal Runs and media conversion.
    """
    import sqlite3
    from pathlib import Path
    from unittest.mock import patch
    from figura.storage.schema import upgrade_pre_media_schema
    from figura.storage.database import SqliteDatabase
    database = Path(data_root) / 'figura.sqlite3'
    try:
        with sqlite3.connect(database) as connection:
            connection.row_factory = sqlite3.Row
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if 0 < version < 13:
                connection.execute('PRAGMA foreign_keys=OFF')
                connection.execute('BEGIN IMMEDIATE')
                upgrade_pre_media_schema(connection, version)
                connection.commit()
    except sqlite3.Error:
        from figura.runtime.errors import RunError, RunErrorCode
        raise RunError(RunErrorCode.STORAGE_ERROR) from None
    with patch.object(SqliteDatabase, '_initialize', lambda self: None):
        return FiguraRunStore(data_root)
