"""SQLite-backed, Figura-owned persistence for Sessions and Runs."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from figura.providers.models import FinishReason

from ._codec import decode_event_payload, decode_payload, encode_event_payload, encode_payload
from .errors import RunError, RunErrorCode
from .models import (
    ActionKind,
    EventKind,
    ExecutionCheckpoint,
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    NextAction,
    RecordKind,
    Run,
    RunInput,
    RunState,
    RunStatus,
    RunStreamEvent,
    Session,
    TerminalCode,
    TERMINAL_MESSAGES,
)

_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 5000
_DB_FILENAME = "figura.sqlite3"


class FiguraRunStore:
    """Own one Figura SQLite database under an explicitly injected data root."""

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self.data_root = Path(data_root).expanduser()
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database_path = self.data_root / _DB_FILENAME
        existed = self.database_path.exists()
        self._initialize()
        if not existed:
            try:
                self.database_path.chmod(0o600)
            except OSError:
                raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def create_session(self, name: str | None = None) -> Session:
        if name is not None and (not isinstance(name, str) or _utf8_length(name) > 256):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        now = _utc_now()
        session = Session(uuid.uuid4().hex, name, now, now)
        with self._write() as connection:
            connection.execute(
                "INSERT INTO sessions(session_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session.session_id, session.name, session.created_at, session.updated_at),
            )
        return session

    def assert_session(self, session_id: str) -> None:
        _validate_id(session_id)
        with self._read() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.SESSION_NOT_FOUND)

    def find_idempotent_run(
        self, session_id: str, key_digest: str, request_fingerprint: str
    ) -> Run | None:
        _validate_id(session_id)
        with self._read() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            row = connection.execute(
                "SELECT request_fingerprint, run_id FROM run_idempotency "
                "WHERE session_id = ? AND idempotency_key_digest = ?",
                (session_id, key_digest),
            ).fetchone()
            if row is None:
                return None
            if row["request_fingerprint"] != request_fingerprint:
                raise RunError(RunErrorCode.IDEMPOTENCY_CONFLICT)
            run_row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
                (row["run_id"], session_id),
            ).fetchone()
            if run_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return _run_from_row(run_row)

    def create_initial_run(
        self,
        *,
        session_id: str,
        provider_id: str,
        model_id: str,
        input_payload: RunInput,
        key_digest: str,
        request_fingerprint: str,
    ) -> Run:
        now = _utc_now()
        run_id = uuid.uuid4().hex
        input_record_id = uuid.uuid4().hex
        input_json = encode_payload(RecordKind.INPUT, input_payload)
        action_json = _encode_action(NextAction(ActionKind.MODEL))
        created_event_json = encode_event_payload(
            EventKind.RUN_CREATED, {"session_id": session_id, "ordinal": 1}
        )
        with self._write() as connection:
            session_row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)

            existing = connection.execute(
                "SELECT request_fingerprint, run_id FROM run_idempotency "
                "WHERE session_id = ? AND idempotency_key_digest = ?",
                (session_id, key_digest),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise RunError(RunErrorCode.IDEMPOTENCY_CONFLICT)
                run_row = connection.execute(
                    "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
                    (existing["run_id"], session_id),
                ).fetchone()
                if run_row is None:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                return _run_from_row(run_row)

            ordinal_row = connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM runs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            ordinal = int(ordinal_row[0])
            created_event_json = encode_event_payload(
                EventKind.RUN_CREATED, {"session_id": session_id, "ordinal": ordinal}
            )
            # The input-record foreign key is deferred, so the whole bundle is
            # checked only when this transaction commits.
            connection.execute(
                "INSERT INTO runs(run_id, session_id, ordinal, input_record_id, status, provider, model, "
                "created_at, started_at, finished_at, terminal_code, terminal_message, final_record_id) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
                (run_id, session_id, ordinal, input_record_id, provider_id, model_id, now, now),
            )
            connection.execute(
                "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
                "VALUES (?, ?, 1, 'input', 1, ?, ?)",
                (input_record_id, run_id, input_json, now),
            )
            connection.execute(
                "INSERT INTO run_execution_checkpoints(run_id, revision, last_committed_record_sequence, next_action_json, schema_version, updated_at) "
                "VALUES (?, 1, 1, ?, 1, ?)",
                (run_id, action_json, now),
            )
            connection.execute(
                "INSERT INTO run_idempotency(session_id, idempotency_key_digest, request_fingerprint, run_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, key_digest, request_fingerprint, run_id, now),
            )
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, 1, 'run_created', ?, ?)",
                (run_id, created_event_json, now),
            )
        return Run(
            run_id=run_id,
            session_id=session_id,
            ordinal=ordinal,
            input_record_id=input_record_id,
            status=RunStatus.RUNNING,
            provider=provider_id,
            model=model_id,
            created_at=now,
            started_at=now,
        )

    def read_run_state(self, session_id: str, run_id: str) -> RunState:
        _validate_id(session_id)
        _validate_id(run_id)
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            run = _run_from_row(row)
            checkpoint_row = connection.execute(
                "SELECT * FROM run_execution_checkpoints WHERE run_id = ?", (run_id,)
            ).fetchone()
            if checkpoint_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            checkpoint = _checkpoint_from_row(checkpoint_row)
            record_rows = connection.execute(
                "SELECT * FROM run_execution_records WHERE run_id = ? ORDER BY record_sequence",
                (run_id,),
            ).fetchall()
            event_rows = connection.execute(
                "SELECT * FROM run_stream_events WHERE run_id = ? ORDER BY event_sequence",
                (run_id,),
            ).fetchall()

        records = tuple(_record_from_row(record_row) for record_row in record_rows)
        events = tuple(_event_from_row(event_row) for event_row in event_rows)
        state = RunState(run=run, records=records, checkpoint=checkpoint, events=events)
        _validate_state(state)
        return state

    def commit_model_response(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        payload: ModelResponseFact,
    ) -> ExecutionRecord:
        raw_payload = encode_payload(RecordKind.MODEL_RESPONSE, payload)
        now = _utc_now()
        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if checkpoint.next_action != NextAction(ActionKind.MODEL):
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if payload.provider_id != run.provider or payload.model_id != run.model:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            sequence = checkpoint.last_committed_record_sequence + 1
            record_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
                "VALUES (?, ?, ?, 'model_response', 1, ?, ?)",
                (record_id, run_id, sequence, raw_payload, now),
            )
            next_action = _encode_action(NextAction(ActionKind.FINAL, record_id))
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, last_committed_record_sequence = ?, "
                "next_action_json = ?, updated_at = ? WHERE run_id = ? AND revision = ?",
                (sequence, next_action, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
        return ExecutionRecord(record_id, run_id, sequence, RecordKind.MODEL_RESPONSE, payload, now)

    def complete_run(
        self, *, session_id: str, run_id: str, expected_revision: int
    ) -> ExecutionRecord:
        now = _utc_now()
        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            action = checkpoint.next_action
            if action is None or action.action_kind is not ActionKind.FINAL or not action.response_record_id:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            response_row = connection.execute(
                "SELECT * FROM run_execution_records WHERE record_id = ? AND run_id = ?",
                (action.response_record_id, run_id),
            ).fetchone()
            if response_row is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response_record = _record_from_row(response_row)
            if response_record.record_kind is not RecordKind.MODEL_RESPONSE:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response = response_record.payload
            if not isinstance(response, ModelResponseFact) or response.finish_reason != FinishReason.STOP.value:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if not response.assistant_content.strip():
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            final_record_id = uuid.uuid4().hex
            sequence = checkpoint.last_committed_record_sequence + 1
            payload = FinalAnswerFact(response_record_id=response_record.record_id)
            raw_payload = encode_payload(RecordKind.FINAL_ANSWER, payload)
            connection.execute(
                "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
                "VALUES (?, ?, ?, 'final_answer', 1, ?, ?)",
                (final_record_id, run_id, sequence, raw_payload, now),
            )
            cursor = connection.execute(
                "UPDATE runs SET status = 'completed', finished_at = ?, final_record_id = ? "
                "WHERE run_id = ? AND session_id = ? AND status = 'running'",
                (now, final_record_id, run_id, session_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, last_committed_record_sequence = ?, "
                "next_action_json = NULL, updated_at = ? WHERE run_id = ? AND revision = ?",
                (sequence, now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            event_sequence = _next_event_sequence(connection, run_id)
            event_json = encode_event_payload(EventKind.RUN_COMPLETED, {"final_artifact_refs": ()})
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, ?, 'run_completed', ?, ?)",
                (run_id, event_sequence, event_json, now),
            )
        return ExecutionRecord(final_record_id, run_id, sequence, RecordKind.FINAL_ANSWER, payload, now)

    def terminal_run(
        self,
        *,
        session_id: str,
        run_id: str,
        expected_revision: int,
        status: RunStatus,
        terminal_code: TerminalCode,
    ) -> Run:
        if status not in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        if (status is RunStatus.INTERRUPTED) != (terminal_code is TerminalCode.INTERRUPTED):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        now = _utc_now()
        event_kind = EventKind.RUN_INTERRUPTED if status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
        message = TERMINAL_MESSAGES[terminal_code]
        with self._write() as connection:
            run = self._scoped_run(connection, session_id, run_id)
            checkpoint = self._checkpoint_for_write(connection, run_id)
            if run.status is not RunStatus.RUNNING:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if checkpoint.revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            cursor = connection.execute(
                "UPDATE runs SET status = ?, finished_at = ?, terminal_code = ?, terminal_message = ? "
                "WHERE run_id = ? AND session_id = ? AND status = 'running'",
                (status.value, now, terminal_code.value, message, run_id, session_id),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            cursor = connection.execute(
                "UPDATE run_execution_checkpoints SET revision = revision + 1, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (now, run_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            event_sequence = _next_event_sequence(connection, run_id)
            event_json = encode_event_payload(event_kind, {"terminal_code": terminal_code.value})
            connection.execute(
                "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, event_sequence, event_kind.value, event_json, now),
            )
        return Run(
            run_id=run.run_id,
            session_id=run.session_id,
            ordinal=run.ordinal,
            input_record_id=run.input_record_id,
            status=status,
            provider=run.provider,
            model=run.model,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=now,
            terminal_code=terminal_code.value,
            terminal_message=message,
        )

    def _initialize(self) -> None:
        try:
            with self._connection() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    # Read the migration version after acquiring the writer
                    # lock so concurrent first opens cannot both create v1.
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version > _SCHEMA_VERSION:
                        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
                    if version == _SCHEMA_VERSION:
                        connection.commit()
                        return
                    for statement in _SCHEMA:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                yield connection
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except RunError:
            raise
        except sqlite3.IntegrityError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @staticmethod
    def _scoped_run(connection: sqlite3.Connection, session_id: str, run_id: str) -> Run:
        _validate_id(session_id)
        _validate_id(run_id)
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
        ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.RUN_NOT_FOUND)
        return _run_from_row(row)

    @staticmethod
    def _checkpoint_for_write(connection: sqlite3.Connection, run_id: str) -> ExecutionCheckpoint:
        row = connection.execute(
            "SELECT * FROM run_execution_checkpoints WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return _checkpoint_from_row(row)


_SCHEMA = (
    """CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY,
        name TEXT NULL CHECK (name IS NULL OR length(CAST(name AS BLOB)) <= 256),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK (ordinal > 0),
        input_record_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'interrupted')),
        provider TEXT NOT NULL CHECK (length(CAST(provider AS BLOB)) <= 64),
        model TEXT NOT NULL CHECK (length(CAST(model AS BLOB)) <= 128),
        created_at TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NULL,
        terminal_code TEXT NULL,
        terminal_message TEXT NULL CHECK (terminal_message IS NULL OR length(CAST(terminal_message AS BLOB)) <= 256),
        final_record_id TEXT NULL,
        UNIQUE(session_id, ordinal),
        UNIQUE(run_id, session_id),
        FOREIGN KEY(input_record_id, run_id) REFERENCES run_execution_records(record_id, run_id) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(final_record_id, run_id) REFERENCES run_execution_records(record_id, run_id) DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE run_execution_records (
        record_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        record_sequence INTEGER NOT NULL CHECK (record_sequence > 0),
        record_kind TEXT NOT NULL CHECK (record_kind IN ('input', 'model_response', 'final_answer')),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 262144),
        created_at TEXT NOT NULL,
        UNIQUE(run_id, record_sequence),
        UNIQUE(record_id, run_id)
    )""",
    """CREATE TABLE run_idempotency (
        session_id TEXT NOT NULL,
        idempotency_key_digest TEXT NOT NULL CHECK (length(idempotency_key_digest) = 64),
        request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
        run_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(session_id, idempotency_key_digest),
        FOREIGN KEY(run_id, session_id) REFERENCES runs(run_id, session_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE run_execution_checkpoints (
        run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK (revision > 0),
        last_committed_record_sequence INTEGER NOT NULL CHECK (last_committed_record_sequence > 0),
        next_action_json TEXT NULL CHECK (next_action_json IS NULL OR (json_valid(next_action_json) AND length(CAST(next_action_json AS BLOB)) <= 1024)),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE run_stream_events (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
        event_kind TEXT NOT NULL CHECK (event_kind IN ('run_created', 'run_completed', 'run_failed', 'run_interrupted')),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 16384),
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, event_sequence)
    )""",
    """CREATE TRIGGER immutable_run_record_update BEFORE UPDATE ON run_execution_records
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    """CREATE TRIGGER immutable_run_record_delete BEFORE DELETE ON run_execution_records
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    """CREATE TRIGGER immutable_run_event_update BEFORE UPDATE ON run_stream_events
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
    """CREATE TRIGGER immutable_run_event_delete BEFORE DELETE ON run_stream_events
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value or _utf8_length(value) > 128:
        raise RunError(RunErrorCode.INVALID_REQUEST)


def _utf8_length(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return 2**63 - 1


def _run_from_row(row: sqlite3.Row) -> Run:
    try:
        status = RunStatus(row["status"])
    except ValueError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    return Run(
        run_id=row["run_id"],
        session_id=row["session_id"],
        ordinal=row["ordinal"],
        input_record_id=row["input_record_id"],
        status=status,
        provider=row["provider"],
        model=row["model"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        terminal_code=row["terminal_code"],
        terminal_message=row["terminal_message"],
        final_record_id=row["final_record_id"],
    )


def _record_from_row(row: sqlite3.Row) -> ExecutionRecord:
    try:
        kind = RecordKind(row["record_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    if row["schema_version"] != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    payload = decode_payload(kind, row["payload_json"])
    return ExecutionRecord(
        record_id=row["record_id"],
        run_id=row["run_id"],
        record_sequence=row["record_sequence"],
        record_kind=kind,
        payload=payload,
        created_at=row["created_at"],
    )


def _checkpoint_from_row(row: sqlite3.Row) -> ExecutionCheckpoint:
    if row["schema_version"] != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    return ExecutionCheckpoint(
        run_id=row["run_id"],
        revision=row["revision"],
        last_committed_record_sequence=row["last_committed_record_sequence"],
        next_action=_decode_action(row["next_action_json"]),
        schema_version=row["schema_version"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: sqlite3.Row) -> RunStreamEvent:
    try:
        kind = EventKind(row["event_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return RunStreamEvent(
        run_id=row["run_id"],
        event_sequence=row["event_sequence"],
        event_kind=kind,
        payload=decode_event_payload(kind, row["payload_json"]),
        created_at=row["created_at"],
    )


def _encode_action(action: NextAction | None) -> str | None:
    if action is None:
        return None
    if action.action_kind is ActionKind.MODEL and action.response_record_id is None:
        value = {"action_kind": "model"}
    elif action.action_kind is ActionKind.FINAL and action.response_record_id:
        value = {"action_kind": "final", "response_record_id": action.response_record_id}
    else:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _decode_action(raw: str | None) -> NextAction | None:
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > 1024:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        value = json.loads(raw)
        if value == {"action_kind": "model"}:
            return NextAction(ActionKind.MODEL)
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "response_record_id"}
            and value["action_kind"] == "final"
            and isinstance(value["response_record_id"], str)
            and value["response_record_id"]
            and len(value["response_record_id"].encode("utf-8")) <= 128
        ):
            return NextAction(ActionKind.FINAL, value["response_record_id"])
    except (TypeError, ValueError):
        pass
    raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _next_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM run_stream_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def _validate_state(state: RunState) -> None:
    run, checkpoint = state.run, state.checkpoint
    records, events = state.records, state.events
    if checkpoint.run_id != run.run_id or checkpoint.schema_version != 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if not records or len(records) != checkpoint.last_committed_record_sequence:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if [record.record_sequence for record in records] != list(range(1, len(records) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    first = records[0]
    if first.record_kind is not RecordKind.INPUT or first.record_id != run.input_record_id:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    input_fact = first.payload
    if not isinstance(input_fact, RunInput) or input_fact.attachment_ids:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if (input_fact.requested_provider, input_fact.requested_model) != (run.provider, run.model):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    response_records = [record for record in records if record.record_kind is RecordKind.MODEL_RESPONSE]
    final_records = [record for record in records if record.record_kind is RecordKind.FINAL_ANSWER]
    if len(response_records) > 1 or len(final_records) > 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if any(record.record_kind is RecordKind.INPUT for record in records[1:]):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if response_records:
        response = response_records[0]
        if response.record_sequence != 2:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        fact = response.payload
        if not isinstance(fact, ModelResponseFact) or (fact.provider_id, fact.model_id) != (run.provider, run.model):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if final_records:
        final = final_records[0]
        if not response_records or final.record_sequence != 3 or not isinstance(final.payload, FinalAnswerFact):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if final.payload.response_record_id != response_records[0].record_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if run.status is RunStatus.RUNNING:
        if run.finished_at is not None or run.terminal_code is not None or run.final_record_id is not None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        expected_action = (
            NextAction(ActionKind.FINAL, response_records[0].record_id)
            if response_records
            else NextAction(ActionKind.MODEL)
        )
        if checkpoint.next_action != expected_action or final_records:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    elif run.status is RunStatus.COMPLETED:
        if run.finished_at is None or run.terminal_code is not None or run.terminal_message is not None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if checkpoint.next_action is not None or not final_records or run.final_record_id != final_records[0].record_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        response = response_records[0].payload
        if not isinstance(response, ModelResponseFact) or response.finish_reason != FinishReason.STOP.value or not response.assistant_content.strip():
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    else:
        if run.finished_at is None or checkpoint.next_action not in {NextAction(ActionKind.MODEL), NextAction(ActionKind.FINAL, response_records[0].record_id) if response_records else None}:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if run.final_record_id is not None or final_records or run.terminal_code not in {code.value for code in TerminalCode}:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        try:
            code = TerminalCode(run.terminal_code)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        if run.terminal_message != TERMINAL_MESSAGES[code]:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if (run.status is RunStatus.INTERRUPTED) != (code is TerminalCode.INTERRUPTED):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if not events or [event.event_sequence for event in events] != list(range(1, len(events) + 1)):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if events[0].event_kind is not EventKind.RUN_CREATED:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    created_payload = events[0].payload
    if created_payload != {"session_id": run.session_id, "ordinal": run.ordinal}:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if run.status is RunStatus.RUNNING:
        if len(events) != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    elif len(events) != 2:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    else:
        terminal_event = events[1]
        if run.status is RunStatus.COMPLETED:
            if terminal_event.event_kind is not EventKind.RUN_COMPLETED or terminal_event.payload != {"final_artifact_refs": ()}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            expected_kind = EventKind.RUN_INTERRUPTED if run.status is RunStatus.INTERRUPTED else EventKind.RUN_FAILED
            if terminal_event.event_kind is not expected_kind or terminal_event.payload != {"terminal_code": run.terminal_code}:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
