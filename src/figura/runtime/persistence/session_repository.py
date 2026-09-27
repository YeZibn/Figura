"""Session and attachment metadata persistence."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator

from ..domain.invariants import _utf8_length, _validate_attachment_metadata, _validate_id
from ..domain.models import AttachmentMetadata, Session
from ..errors import RunError, RunErrorCode
from .database import SqliteDatabase, _utc_now
from .mappers import _attachment_from_row


def _require_attachment_ownership(
    connection: sqlite3.Connection,
    session_id: str,
    attachment_ids: tuple[str, ...],
    *,
    integrity: bool = False,
) -> None:
    if not attachment_ids:
        return
    placeholders = ", ".join("?" for _ in attachment_ids)
    rows = connection.execute(
        f"SELECT attachment_id FROM attachments WHERE session_id = ? "
        f"AND attachment_id IN ({placeholders})",
        (session_id, *attachment_ids),
    ).fetchall()
    if {row["attachment_id"] for row in rows} != set(attachment_ids):
        code = RunErrorCode.INTEGRITY_ERROR if integrity else RunErrorCode.UNSUPPORTED_PAYLOAD
        raise RunError(code)


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


class SessionRepository:
    """Persist Session and attachment metadata operations."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def _require_attachment_ownership(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        attachment_ids: tuple[str, ...],
        *,
        integrity: bool = False,
    ) -> None:
        _require_attachment_ownership(
            connection,
            session_id,
            attachment_ids,
            integrity=integrity,
        )

    def create_session(self, name: str | None = None) -> Session:
        if name is not None and (not isinstance(name, str) or _utf8_length(name) > 256):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        now = _utc_now()
        session = Session(uuid.uuid4().hex, name, now, now)
        with self._database.write() as connection:
            connection.execute(
                "INSERT INTO sessions(session_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session.session_id, session.name, session.created_at, session.updated_at),
            )
        return session

    def assert_session(self, session_id: str) -> None:
        _validate_id(session_id)
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)

    def register_attachment(
        self,
        metadata: AttachmentMetadata,
        install_file: Callable[[], None],
    ) -> None:
        _validate_attachment_metadata(metadata)
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
        return tuple(_attachment_from_row(row) for row in rows)

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
        return _attachment_from_row(row)

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
            metadata = _attachment_from_row(row)
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
