"""SQLite persistence for immutable Session-owned Panel metadata."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence

from figura.runtime import RunError, RunErrorCode
from figura.runtime.persistence.database import SqliteDatabase

from .models import PanelPoint, PanelRecord


class PanelRepository:
    def __init__(self, data_root: str) -> None:
        self._database = SqliteDatabase(data_root)

    def list(self, session_id: str) -> tuple[PanelRecord, ...]:
        with self._database.read() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            rows = connection.execute(
                "SELECT * FROM panels WHERE session_id = ? ORDER BY rowid", (session_id,)
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def list_all(self) -> tuple[PanelRecord, ...]:
        with self._database.read() as connection:
            rows = connection.execute("SELECT * FROM panels ORDER BY rowid").fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def get(self, session_id: str, panel_id: str) -> PanelRecord:
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM panels WHERE session_id = ? AND panel_id = ?",
                (session_id, panel_id),
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return _record_from_row(row)

    def register(
        self,
        records: Sequence[PanelRecord],
        install_files: Callable[[], None],
    ) -> None:
        if not records or not callable(install_files):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        with self._database.write() as connection:
            existing = []
            for record in records:
                row = connection.execute(
                    "SELECT * FROM panels WHERE panel_id = ?", (record.panel_id,)
                ).fetchone()
                existing.append(_record_from_row(row) if row is not None else None)
            if any(item is not None for item in existing):
                if tuple(existing) != tuple(records):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                return
            install_files()
            connection.executemany(
                "INSERT INTO panels(panel_id, session_id, run_id, source_attachment_id, name, points_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (
                        record.panel_id,
                        record.session_id,
                        record.run_id,
                        record.source_attachment_id,
                        record.name,
                        json.dumps(
                            [{"x": point.x, "y": point.y} for point in record.points],
                            separators=(",", ":"),
                        ),
                    )
                    for record in records
                ),
            )
    def reconcile_files(self, reconcile: Callable[[frozenset[str]], None]) -> None:
        with self._database.write() as connection:
            rows = connection.execute("SELECT panel_id FROM panels").fetchall()
            reconcile(frozenset(row["panel_id"] for row in rows))


def _record_from_row(row: sqlite3.Row) -> PanelRecord:
    try:
        points_raw = json.loads(row["points_json"])
        if not isinstance(points_raw, list):
            raise ValueError
        points = tuple(PanelPoint(point["x"], point["y"]) for point in points_raw)
        return PanelRecord(
            panel_id=row["panel_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            source_attachment_id=row["source_attachment_id"],
            name=row["name"],
            points=points,
        )
    except (KeyError, TypeError, ValueError, RunError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
