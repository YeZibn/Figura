"""SQLite persistence for attachment and Panel metadata."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.storage.database import SqliteDatabase

from .models import AttachmentMetadata, PanelPoint, PanelRecord


class SourcesRepository:
    """Persist Sources metadata using the shared Figura SQLite database."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def assert_session(self, session_id: str) -> None:
        _validate_id(session_id)
        with self._database.read() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if exists is None:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)

    def register_attachment(
        self,
        metadata: AttachmentMetadata,
        install_file: Callable[[], None],
    ) -> None:
        _validate_attachment(metadata)
        if not callable(install_file):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        with self._database.write() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (metadata.session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            install_file()
            connection.execute(
                "INSERT INTO attachments(attachment_id, session_id, filename, media_type, byte_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    metadata.attachment_id,
                    metadata.session_id,
                    metadata.filename,
                    metadata.media_type,
                    metadata.byte_count,
                    metadata.created_at,
                ),
            )

    def list_attachments(self, session_id: str) -> tuple[AttachmentMetadata, ...]:
        _validate_id(session_id)
        with self._database.read() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            rows = connection.execute(
                "SELECT * FROM attachments WHERE session_id = ? "
                "ORDER BY created_at, attachment_id",
                (session_id,),
            ).fetchall()
        return tuple(attachment_from_row(row) for row in rows)

    def get_attachment_metadata(
        self,
        session_id: str,
        attachment_id: str,
    ) -> AttachmentMetadata:
        _validate_id(session_id)
        _validate_id(attachment_id)
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM attachments WHERE session_id = ? AND attachment_id = ?",
                (session_id, attachment_id),
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return attachment_from_row(row)

    @contextmanager
    def delete_attachment_transaction(
        self,
        session_id: str,
        attachment_id: str,
    ) -> Iterator[AttachmentMetadata]:
        _validate_id(session_id)
        _validate_id(attachment_id)
        with self._database.write() as connection:
            row = connection.execute(
                "SELECT * FROM attachments WHERE session_id = ? AND attachment_id = ?",
                (session_id, attachment_id),
            ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if _attachment_is_referenced(connection, session_id, attachment_id):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            metadata = attachment_from_row(row)
            yield metadata
            cursor = connection.execute(
                "DELETE FROM attachments WHERE session_id = ? AND attachment_id = ?",
                (session_id, attachment_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

    def reconcile_attachment_files(
        self,
        reconcile: Callable[[frozenset[str]], None],
    ) -> None:
        if not callable(reconcile):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        with self._database.write() as connection:
            rows = connection.execute("SELECT attachment_id FROM attachments").fetchall()
            reconcile(frozenset(row["attachment_id"] for row in rows))

    def list_panels(self, session_id: str) -> tuple[PanelRecord, ...]:
        _validate_id(session_id)
        with self._database.read() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            rows = connection.execute(
                "SELECT * FROM panels WHERE session_id = ? ORDER BY rowid", (session_id,)
            ).fetchall()
        return tuple(_panel_from_row(row) for row in rows)

    def list_all_panels(self) -> tuple[PanelRecord, ...]:
        with self._database.read() as connection:
            rows = connection.execute("SELECT * FROM panels ORDER BY rowid").fetchall()
        return tuple(_panel_from_row(row) for row in rows)

    def session_deletion_resources(
        self, connection: sqlite3.Connection, session_id: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        _validate_id(session_id)
        attachment_rows = connection.execute(
            "SELECT attachment_id FROM attachments WHERE session_id = ? "
            "ORDER BY attachment_id",
            (session_id,),
        ).fetchall()
        panel_rows = connection.execute(
            "SELECT panel_id FROM panels WHERE session_id = ? ORDER BY panel_id",
            (session_id,),
        ).fetchall()
        return (
            tuple(row["attachment_id"] for row in attachment_rows),
            tuple(row["panel_id"] for row in panel_rows),
        )

    def delete_session_rows(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        _validate_id(session_id)
        connection.execute("DELETE FROM panels WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM attachments WHERE session_id = ?", (session_id,))

    def get_panel(self, session_id: str, panel_id: str) -> PanelRecord:
        _validate_id(session_id)
        _validate_id(panel_id)
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM panels WHERE session_id = ? AND panel_id = ?",
                (session_id, panel_id),
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return _panel_from_row(row)

    def register_panels(
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
                existing.append(_panel_from_row(row) if row is not None else None)
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

    def reconcile_panel_files(self, reconcile: Callable[[frozenset[str]], None]) -> None:
        if not callable(reconcile):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        with self._database.write() as connection:
            rows = connection.execute("SELECT panel_id FROM panels").fetchall()
            reconcile(frozenset(row["panel_id"] for row in rows))


def attachment_from_row(row: sqlite3.Row) -> AttachmentMetadata:
    try:
        return AttachmentMetadata(
            attachment_id=row["attachment_id"],
            session_id=row["session_id"],
            filename=row["filename"],
            media_type=row["media_type"],
            byte_count=row["byte_count"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _panel_from_row(row: sqlite3.Row) -> PanelRecord:
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


def _attachment_is_referenced(
    connection: sqlite3.Connection,
    session_id: str,
    attachment_id: str,
) -> bool:
    row = connection.execute(
        "SELECT 1 FROM run_execution_records AS record "
        "JOIN runs AS run ON run.run_id = record.run_id "
        "JOIN json_each(record.payload_json, '$.attachment_ids') AS referenced "
        "WHERE run.session_id = ? AND record.record_kind = 'input' "
        "AND referenced.value = ? LIMIT 1",
        (session_id, attachment_id),
    ).fetchone()
    return row is not None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value or _byte_length(value) > 128:
        raise RunError(RunErrorCode.INVALID_REQUEST)


def _validate_attachment(metadata: object) -> None:
    if not isinstance(metadata, AttachmentMetadata):
        raise RunError(RunErrorCode.INVALID_REQUEST)
    try:
        parsed_id = uuid.UUID(metadata.attachment_id)
    except (AttributeError, TypeError, ValueError):
        raise RunError(RunErrorCode.INVALID_REQUEST) from None
    if parsed_id.hex != metadata.attachment_id:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    _validate_id(metadata.session_id)
    if (
        not isinstance(metadata.filename, str)
        or not metadata.filename
        or _byte_length(metadata.filename) > 255
        or "/" in metadata.filename
        or "\\" in metadata.filename
    ):
        raise RunError(RunErrorCode.INVALID_REQUEST)
    if not isinstance(metadata.media_type, str) or metadata.media_type not in {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    if type(metadata.byte_count) is not int or not 1 <= metadata.byte_count <= MAX_IMAGE_BYTES:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    if not isinstance(metadata.created_at, str) or not metadata.created_at:
        raise RunError(RunErrorCode.INVALID_REQUEST)


def _byte_length(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return 2**63 - 1
