"""Session creation and listing persistence."""

from __future__ import annotations

import sqlite3
import uuid

from ..record_validation import _utf8_length
from ..validation import _validate_id
from ..models import (
    Session,
    SessionListEntry,
)
from ..errors import RunError, RunErrorCode
from figura.storage.database import SqliteDatabase, _utc_now

from .mappers import _session_from_row


class SessionRepository:
    """Persist Session values and their list projections."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

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

    def list_sessions(self) -> tuple[Session, ...]:
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, session_id"
            ).fetchall()
        return tuple(_session_from_row(row) for row in rows)

    def list_session_entries(self) -> tuple[SessionListEntry, ...]:
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT session.*, "
                "(SELECT COUNT(*) FROM runs WHERE runs.session_id = session.session_id) AS run_count, "
                "MAX(session.updated_at, "
                "COALESCE((SELECT MAX(COALESCE(finished_at, created_at)) FROM runs "
                "WHERE runs.session_id = session.session_id), session.updated_at), "
                "COALESCE((SELECT MAX(created_at) FROM attachments "
                "WHERE attachments.session_id = session.session_id), session.updated_at)"
                ") AS latest_activity "
                "FROM sessions AS session ORDER BY latest_activity DESC, session.session_id"
            ).fetchall()
        return tuple(
            SessionListEntry(
                session=_session_from_row(row),
                run_count=int(row["run_count"]),
                latest_activity=row["latest_activity"],
            )
            for row in rows
        )

    def get_session(self, session_id: str) -> Session:
        _validate_id(session_id)
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)
        return _session_from_row(row)

    def session_exists(self, session_id: str) -> bool:
        _validate_id(session_id)
        with self._database.read() as connection:
            return connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is not None

    def assert_deletable(self, connection: sqlite3.Connection, session_id: str) -> None:
        _validate_id(session_id)
        if connection.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone() is None:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)
        if connection.execute(
            "SELECT 1 FROM runs WHERE session_id = ? AND status = 'running' LIMIT 1",
            (session_id,),
        ).fetchone() is not None:
            raise RunError(RunErrorCode.SESSION_HAS_RUNNING_RUN)

    def begin_deletion(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            "INSERT INTO session_deletion_scopes(session_id, created_at) VALUES (?, ?)",
            (session_id, _utc_now()),
        )

    def complete_deletion(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            "DELETE FROM session_deletion_scopes WHERE session_id = ?", (session_id,)
        )
        cursor = connection.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        if cursor.rowcount != 1:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)
