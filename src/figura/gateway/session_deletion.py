"""Coordinate permanent Session deletion across Figura persistence owners."""

from __future__ import annotations

import shutil
from pathlib import Path

from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.store import FiguraRunStore
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.sources.storage import ensure_private_directory


class FiguraSessionDeletion:
    """Stage owned images and delete one terminal Session in a SQLite transaction."""

    def __init__(
        self,
        store: FiguraRunStore,
        sources: SourcesRepository,
        attachments: FiguraAttachmentService,
        panels: FiguraPanelService,
        chart_renders: FiguraChartRenderService,
    ) -> None:
        self._store = store
        self._sources = sources
        self._attachments = attachments
        self._panels = panels
        self._chart_renders = chart_renders
        self._trash_root = store.data_root / "session-trash"
        try:
            ensure_private_directory(self._trash_root, "Session deletion staging")
            self._reconcile_staged_files()
            self._chart_renders.reconcile_files(store.list_chart_render_calls())
            self._panels.validate_files()
        except RunError:
            raise
        except OSError:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def delete(self, session_id: str) -> None:
        if not _is_session_id(session_id):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        session_trash = self._trash_root / session_id
        staging_started = False
        try:
            with self._store.database.write() as connection:
                if session_trash.exists() or session_trash.is_symlink():
                    if self._store.session_exists(session_id):
                        self._restore(session_trash)
                    else:
                        self._discard(session_trash)

                render_calls = self._store.session_deletion_resources(connection, session_id)
                attachment_ids, panel_ids = self._sources.session_deletion_resources(
                    connection, session_id
                )
                ensure_private_directory(session_trash, "Session deletion staging")
                staging_started = True
                self._attachments.stage_session_deletion(session_trash, attachment_ids)
                self._panels.stage_session_deletion(session_trash, panel_ids)
                self._chart_renders.stage_session_deletion(session_trash, render_calls)
                self._store.begin_session_deletion(connection, session_id)
                self._store.delete_session_run_facts(connection, session_id)
                self._sources.delete_session_rows(connection, session_id)
                self._store.delete_session_runs(connection, session_id)
                self._store.complete_session_deletion(connection, session_id)
        except Exception as error:
            if staging_started:
                try:
                    self._restore(session_trash)
                except OSError:
                    raise RunError(RunErrorCode.STORAGE_ERROR) from None
            if isinstance(error, RunError):
                raise
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

        try:
            self._discard(session_trash)
        except OSError:
            # The Session is already gone. Startup reconciliation will remove this private tree.
            pass

    def _reconcile_staged_files(self) -> None:
        for session_trash in self._trash_root.iterdir():
            if session_trash.is_symlink() or not session_trash.is_dir():
                raise OSError("invalid Session deletion staging entry")
            session_id = session_trash.name
            if not _is_session_id(session_id):
                raise OSError("invalid Session deletion identity")
            if self._store.session_exists(session_id):
                self._restore(session_trash)
            else:
                self._discard(session_trash)

    def _restore(self, session_trash: Path) -> None:
        self._attachments.restore_session_deletion(session_trash)
        self._panels.restore_session_deletion(session_trash)
        self._chart_renders.restore_session_deletion(session_trash)
        session_trash.rmdir()

    def _discard(self, session_trash: Path) -> None:
        if session_trash.is_symlink():
            raise OSError("invalid Session deletion staging path")
        if not session_trash.exists():
            return
        self._attachments.discard_session_deletion(session_trash)
        self._panels.discard_session_deletion(session_trash)
        self._chart_renders.discard_session_deletion(session_trash)
        shutil.rmtree(session_trash)


def _is_session_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )
