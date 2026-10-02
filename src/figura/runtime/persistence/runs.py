"""Run creation, idempotency, and aggregate-state reads."""

from __future__ import annotations

import sqlite3
import uuid

from figura.storage.database import SqliteDatabase, _utc_now

from ..codecs.events import (
    encode_event_payload,
)
from ..codecs.records import (
    encode_payload,
)
from ..errors import RunError, RunErrorCode
from ..models import (
    ActionKind,
    EventKind,
    ExecutionCheckpoint,
    NextAction,
    RecordKind,
    Run,
    RunStatus,
)
from ..records import (
    RunInput,
    RunState,
)
from ..validation import _validate_id, _validate_state
from .mappers import (
    _checkpoint_from_row,
    _continuation_fact_from_row,
    _encode_action,
    _event_from_row,
    _provider_attempt_from_row,
    _record_from_row,
    _run_from_row,
    _tool_fact_from_row,
)


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


def _read_run_state_from_connection(
    connection: sqlite3.Connection,
    session_id: str,
    run_id: str,
) -> RunState:
    _validate_id(session_id)
    _validate_id(run_id)
    run_row = connection.execute(
        "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
        (run_id, session_id),
    ).fetchone()
    if run_row is None:
        raise RunError(RunErrorCode.RUN_NOT_FOUND)
    checkpoint_row = connection.execute(
        "SELECT * FROM run_execution_checkpoints WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if checkpoint_row is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    record_rows = connection.execute(
        "SELECT * FROM run_execution_records WHERE run_id = ? ORDER BY record_sequence",
        (run_id,),
    ).fetchall()
    event_rows = connection.execute(
        "SELECT * FROM run_stream_events WHERE run_id = ? ORDER BY event_sequence",
        (run_id,),
    ).fetchall()
    tool_fact_rows = connection.execute(
        "SELECT * FROM run_tool_execution_facts WHERE run_id = ? ORDER BY tool_sequence",
        (run_id,),
    ).fetchall()
    continuation_rows = connection.execute(
        "SELECT continuation.* FROM run_provider_continuations AS continuation "
        "WHERE continuation.run_id = ? "
        "ORDER BY (SELECT record_sequence FROM run_execution_records "
        "WHERE record_id = continuation.response_record_id AND run_id = continuation.run_id)",
        (run_id,),
    ).fetchall()
    provider_attempt_rows = connection.execute(
        "SELECT * FROM run_provider_attempts WHERE run_id = ? ORDER BY attempt_sequence",
        (run_id,),
    ).fetchall()
    from .controls import read_stop_request

    state = RunState(
        stop_request=read_stop_request(connection, run_id),
        run=_run_from_row(run_row),
        records=tuple(_record_from_row(row) for row in record_rows),
        checkpoint=_checkpoint_from_row(checkpoint_row),
        events=tuple(_event_from_row(row) for row in event_rows),
        tool_facts=tuple(_tool_fact_from_row(row) for row in tool_fact_rows),
        provider_continuations=tuple(
            _continuation_fact_from_row(row) for row in continuation_rows
        ),
        provider_attempts=tuple(
            _provider_attempt_from_row(row) for row in provider_attempt_rows
        ),
    )
    _validate_state(state)
    return state


class RunRepository:
    """Persist Run creation and hydrate validated RunState aggregates."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def _read_run_state_from_connection(
        self, connection: sqlite3.Connection, session_id: str, run_id: str
    ) -> RunState:
        return _read_run_state_from_connection(connection, session_id, run_id)

    def find_idempotent_run(
        self, session_id: str, key_digest: str, request_fingerprint: str
    ) -> Run | None:
        _validate_id(session_id)
        with self._database.read() as connection:
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
        with self._database.write() as connection:
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

            active_run = connection.execute(
                "SELECT 1 FROM runs WHERE session_id = ? AND status = 'running' LIMIT 1",
                (session_id,),
            ).fetchone()
            if active_run is not None:
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            _require_attachment_ownership(
                connection,
                session_id,
                input_payload.attachment_ids,
            )

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
                "INSERT INTO run_execution_checkpoints(run_id, revision, last_committed_record_sequence, last_committed_tool_sequence, next_action_json, schema_version, updated_at) "
                "VALUES (?, 1, 1, 0, ?, 1, ?)",
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
        with self._database.read() as connection:
            state = self._read_run_state_from_connection(connection, session_id, run_id)
            input_payload = state.records[0].payload
            if not isinstance(input_payload, RunInput):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            _require_attachment_ownership(
                connection,
                session_id,
                input_payload.attachment_ids,
                integrity=True,
            )
            return state

    def list_running_runs(self) -> tuple[Run, ...]:
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE status = ? ORDER BY session_id, ordinal",
                (RunStatus.RUNNING.value,),
            ).fetchall()
        return tuple(_run_from_row(row) for row in rows)

    def session_render_calls(
        self, connection: sqlite3.Connection, session_id: str
    ) -> tuple[tuple[str, str], ...]:
        return self._chart_render_calls(connection, session_id)

    def all_chart_render_calls(
        self, connection: sqlite3.Connection
    ) -> tuple[tuple[str, str], ...]:
        return self._chart_render_calls(connection)

    @staticmethod
    def _chart_render_calls(
        connection: sqlite3.Connection, session_id: str | None = None
    ) -> tuple[tuple[str, str], ...]:
        session_filter = "WHERE facts.fact_kind = 'tool_call' "
        parameters: tuple[object, ...] = ()
        if session_id is not None:
            session_filter += "AND runs.session_id = ? "
            parameters = (session_id,)
        rows = connection.execute(
            "SELECT facts.run_id, json_extract(facts.payload_json, '$.call_id') AS call_id "
            "FROM run_tool_execution_facts AS facts "
            "JOIN runs ON runs.run_id = facts.run_id "
            f"{session_filter}"
            "AND json_extract(facts.payload_json, '$.tool_name') = 'render_chart_figure' "
            "ORDER BY facts.run_id, facts.tool_sequence",
            parameters,
        ).fetchall()
        return tuple((row["run_id"], row["call_id"]) for row in rows)

    def delete_session_facts(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        connection.execute(
            "DELETE FROM run_idempotency WHERE session_id = ?", (session_id,)
        )
        for table in (
            "run_stop_requests",
            "run_provider_continuations",
            "run_provider_attempts",
            "run_execution_checkpoints",
            "run_stream_events",
            "run_tool_execution_facts",
            "run_execution_records",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE run_id IN "
                "(SELECT run_id FROM runs WHERE session_id = ?)",
                (session_id,),
            )

    def delete_session_rows(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        connection.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))

    def _scoped_run(self, connection: sqlite3.Connection, session_id: str, run_id: str) -> Run:
        _validate_id(session_id)
        _validate_id(run_id)
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
        ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.RUN_NOT_FOUND)
        return _run_from_row(row)

    def _checkpoint_for_write(self, connection: sqlite3.Connection, run_id: str) -> ExecutionCheckpoint:
        row = connection.execute(
            "SELECT * FROM run_execution_checkpoints WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return _checkpoint_from_row(row)
