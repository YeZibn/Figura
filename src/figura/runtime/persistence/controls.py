"""Durable, idempotent stop controls independent of execution revisions."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta

from figura.storage.database import SqliteDatabase, _utc_now
from ..errors import RunError, RunErrorCode
from ..models import EventKind, RunStatus, RunStopRequest
from ..codecs.events import encode_event_payload
from .runs import RunRepository
from .transaction_helpers import _next_event_sequence


class RunStopRequested(RunError):
    def __init__(self) -> None:
        super().__init__(RunErrorCode.INVALID_TRANSITION)


def read_stop_request(connection: sqlite3.Connection, run_id: str) -> RunStopRequest | None:
    row = connection.execute("SELECT * FROM run_stop_requests WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    try:
        timestamp = datetime.fromisoformat(row["requested_at"].replace("Z", "+00:00"))
        valid = (
            row["reason"] == "user_requested"
            and isinstance(row["request_id"], str)
            and 0 < len(row["request_id"].encode("utf-8")) <= 128
            and timestamp.utcoffset() == timedelta(0)
        )
    except (AttributeError, TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return RunStopRequest(row["run_id"], row["request_id"], row["requested_at"], row["reason"])


def assert_not_stopped(connection: sqlite3.Connection, run_id: str) -> None:
    if read_stop_request(connection, run_id) is not None:
        raise RunStopRequested()


class RunControlRepository:
    def __init__(self, database: SqliteDatabase, runs: RunRepository) -> None:
        self._database = database
        self._runs = runs

    def request_stop(self, session_id: str, run_id: str) -> RunStopRequest | None:
        with self._database.write() as connection:
            run = self._runs._scoped_run(connection, session_id, run_id)
            existing = read_stop_request(connection, run_id)
            if run.status is not RunStatus.RUNNING or existing is not None:
                return existing
            request = RunStopRequest(run_id, uuid.uuid4().hex, _utc_now(), "user_requested")
            connection.execute(
                "INSERT INTO run_stop_requests VALUES (?, ?, ?, ?)",
                (request.run_id, request.request_id, request.requested_at, request.reason),
            )
            checkpoint = self._runs._checkpoint_for_write(connection, run_id)
            payload = encode_event_payload(EventKind.RUN_PROGRESS, {"checkpoint_revision": checkpoint.revision})
            connection.execute(
                "INSERT INTO run_stream_events VALUES (?, ?, 'run_progress', ?, ?)",
                (run_id, _next_event_sequence(connection, run_id), payload, request.requested_at),
            )
            return request
