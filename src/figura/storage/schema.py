"""SQLite schema definitions and migrations for durable Figura Runs."""

from __future__ import annotations

import sqlite3

from figura.runtime.errors import RunError, RunErrorCode

_SCHEMA_VERSION = 9


def _run_stream_events_table(table_name: str) -> str:
    return f"""CREATE TABLE {table_name} (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
        event_kind TEXT NOT NULL CHECK (event_kind IN (
            'run_created', 'run_progress', 'run_completed', 'run_failed', 'run_interrupted'
        )),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 16384),
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, event_sequence)
    )"""


_RUN_STREAM_EVENT_TRIGGERS = (
    """CREATE TRIGGER immutable_run_event_update BEFORE UPDATE ON run_stream_events
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
    """CREATE TRIGGER immutable_run_event_delete BEFORE DELETE ON run_stream_events
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
)


_SESSION_DELETION_TRIGGERS = (
    """CREATE TRIGGER immutable_run_event_delete BEFORE DELETE ON run_stream_events
        WHEN NOT EXISTS (
            SELECT 1 FROM runs
            JOIN session_deletion_scopes USING (session_id)
            WHERE runs.run_id = OLD.run_id
        )
        BEGIN SELECT RAISE(ABORT, 'immutable stream event'); END""",
    """CREATE TRIGGER immutable_run_record_delete BEFORE DELETE ON run_execution_records
        WHEN NOT EXISTS (
            SELECT 1 FROM runs
            JOIN session_deletion_scopes USING (session_id)
            WHERE runs.run_id = OLD.run_id
        )
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    """CREATE TRIGGER immutable_run_tool_fact_delete BEFORE DELETE ON run_tool_execution_facts
        WHEN NOT EXISTS (
            SELECT 1 FROM runs
            JOIN session_deletion_scopes USING (session_id)
            WHERE runs.run_id = OLD.run_id
        )
        BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END""",
    """CREATE TRIGGER immutable_run_provider_continuation_delete
        BEFORE DELETE ON run_provider_continuations
        WHEN NOT EXISTS (
            SELECT 1 FROM runs
            JOIN session_deletion_scopes USING (session_id)
            WHERE runs.run_id = OLD.run_id
        )
        BEGIN SELECT RAISE(ABORT, 'immutable provider continuation'); END""",
    """CREATE TRIGGER immutable_run_provider_attempt_delete
        BEFORE DELETE ON run_provider_attempts
        WHEN NOT EXISTS (
            SELECT 1 FROM runs
            JOIN session_deletion_scopes USING (session_id)
            WHERE runs.run_id = OLD.run_id
        )
        BEGIN SELECT RAISE(ABORT, 'immutable provider attempt'); END""",
    """CREATE TRIGGER immutable_panel_delete BEFORE DELETE ON panels
        WHEN NOT EXISTS (
            SELECT 1 FROM session_deletion_scopes
            WHERE session_id = OLD.session_id
        )
        BEGIN SELECT RAISE(ABORT, 'immutable panel'); END""",
)

_CORE_SCHEMA = (
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
        last_committed_tool_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_committed_tool_sequence >= 0),
        next_action_json TEXT NULL CHECK (next_action_json IS NULL OR (json_valid(next_action_json) AND length(CAST(next_action_json AS BLOB)) <= 1024)),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        updated_at TEXT NOT NULL
    )""",
    _run_stream_events_table("run_stream_events"),
    """CREATE TRIGGER immutable_run_record_update BEFORE UPDATE ON run_execution_records
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    """CREATE TRIGGER immutable_run_record_delete BEFORE DELETE ON run_execution_records
        BEGIN SELECT RAISE(ABORT, 'immutable execution record'); END""",
    *_RUN_STREAM_EVENT_TRIGGERS,
)

_TOOL_SCHEMA = (
    """CREATE TABLE run_tool_execution_facts (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        tool_sequence INTEGER NOT NULL CHECK (tool_sequence > 0),
        fact_kind TEXT NOT NULL CHECK (fact_kind IN ('tool_call', 'tool_attempt_started', 'tool_result')),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND length(CAST(payload_json AS BLOB)) <= 524288),
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, tool_sequence)
    )""",
    """CREATE TRIGGER immutable_run_tool_fact_update BEFORE UPDATE ON run_tool_execution_facts
        BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END""",
    """CREATE TRIGGER immutable_run_tool_fact_delete BEFORE DELETE ON run_tool_execution_facts
        BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END""",
)

_CONTINUATION_SCHEMA = (
    """CREATE TABLE run_provider_continuations (
        continuation_id TEXT PRIMARY KEY CHECK (length(CAST(continuation_id AS BLOB)) BETWEEN 1 AND 128),
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        response_record_id TEXT NOT NULL,
        provider_id TEXT NOT NULL CHECK (provider_id IN ('qwen', 'deepseek', 'mimo')),
        format_version INTEGER NOT NULL CHECK (format_version > 0),
        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
        reasoning_content TEXT CHECK (
            (provider_id = 'deepseek' OR (reasoning_content IS NOT NULL AND length(reasoning_content) > 0))
            AND (reasoning_content IS NULL OR length(CAST(reasoning_content AS BLOB)) <= 524288)
        ),
        created_at TEXT NOT NULL,
        UNIQUE(run_id, response_record_id),
        FOREIGN KEY(response_record_id, run_id)
            REFERENCES run_execution_records(record_id, run_id) ON DELETE RESTRICT
    )""",
    """CREATE TRIGGER continuation_matches_model_response BEFORE INSERT ON run_provider_continuations
        WHEN NOT EXISTS (
            SELECT 1 FROM run_execution_records
            WHERE record_id = NEW.response_record_id
              AND run_id = NEW.run_id
              AND record_kind = 'model_response'
              AND schema_version = 2
              AND json_extract(payload_json, '$.continuation_ref') = NEW.continuation_id
              AND json_extract(payload_json, '$.provider_id') = NEW.provider_id
        )
        BEGIN SELECT RAISE(ABORT, 'continuation response mismatch'); END""",
    """CREATE TRIGGER immutable_run_provider_continuation_update BEFORE UPDATE ON run_provider_continuations
        BEGIN SELECT RAISE(ABORT, 'immutable provider continuation'); END""",
    """CREATE TRIGGER immutable_run_provider_continuation_delete BEFORE DELETE ON run_provider_continuations
        BEGIN SELECT RAISE(ABORT, 'immutable provider continuation'); END""",
)

_PROVIDER_ATTEMPT_SCHEMA = (
    """CREATE TABLE run_provider_attempts (
        attempt_id TEXT PRIMARY KEY CHECK (length(CAST(attempt_id AS BLOB)) BETWEEN 1 AND 128),
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        attempt_sequence INTEGER NOT NULL CHECK (attempt_sequence BETWEEN 1 AND 8),
        base_record_sequence INTEGER NOT NULL CHECK (base_record_sequence > 0),
        base_tool_sequence INTEGER NOT NULL CHECK (base_tool_sequence >= 0),
        status TEXT NOT NULL CHECK (status IN ('started', 'response_committed', 'known_failure', 'outcome_unknown')),
        response_record_id TEXT NULL,
        failure_code TEXT NULL CHECK (failure_code IS NULL OR failure_code IN (
            'configuration_missing', 'invalid_configuration', 'unsupported_provider', 'unsupported_model',
            'invalid_request', 'unsupported_capability', 'provider_rejected', 'provider_unavailable',
            'timeout', 'connection_error', 'incomplete_stream', 'invalid_provider_response', 'transport_error'
        )),
        started_at TEXT NOT NULL,
        finished_at TEXT NULL,
        UNIQUE(run_id, attempt_sequence),
        UNIQUE(run_id, base_record_sequence, base_tool_sequence),
        UNIQUE(run_id, response_record_id),
        FOREIGN KEY(response_record_id, run_id)
            REFERENCES run_execution_records(record_id, run_id) ON DELETE RESTRICT,
        CHECK (
            (status = 'started' AND response_record_id IS NULL AND failure_code IS NULL AND finished_at IS NULL)
            OR (status = 'response_committed' AND response_record_id IS NOT NULL AND failure_code IS NULL AND finished_at IS NOT NULL)
            OR (status = 'known_failure' AND response_record_id IS NULL AND failure_code IS NOT NULL AND finished_at IS NOT NULL)
            OR (status = 'outcome_unknown' AND response_record_id IS NULL AND finished_at IS NOT NULL)
        )
    )""",
    """CREATE TRIGGER provider_attempt_response_matches_model_response
        BEFORE UPDATE OF response_record_id ON run_provider_attempts
        WHEN NEW.response_record_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM run_execution_records
            WHERE record_id = NEW.response_record_id
              AND run_id = NEW.run_id
              AND record_kind = 'model_response'
        )
        BEGIN SELECT RAISE(ABORT, 'provider attempt response mismatch'); END""",
    """CREATE TRIGGER provider_attempt_has_one_terminal_transition
        BEFORE UPDATE ON run_provider_attempts
        WHEN OLD.status <> 'started'
          OR NEW.status = 'started'
          OR NEW.attempt_id <> OLD.attempt_id
          OR NEW.run_id <> OLD.run_id
          OR NEW.attempt_sequence <> OLD.attempt_sequence
          OR NEW.base_record_sequence <> OLD.base_record_sequence
          OR NEW.base_tool_sequence <> OLD.base_tool_sequence
          OR NEW.started_at <> OLD.started_at
        BEGIN SELECT RAISE(ABORT, 'invalid provider attempt transition'); END""",
    """CREATE TRIGGER immutable_run_provider_attempt_delete BEFORE DELETE ON run_provider_attempts
        BEGIN SELECT RAISE(ABORT, 'immutable provider attempt'); END""",
)

_ATTACHMENT_SCHEMA = (
    """CREATE TABLE attachments (
        attachment_id TEXT PRIMARY KEY CHECK (
            length(CAST(attachment_id AS BLOB)) = 32
            AND attachment_id NOT GLOB '*[^0-9a-f]*'
        ),
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
        filename TEXT NOT NULL CHECK (length(CAST(filename AS BLOB)) BETWEEN 1 AND 255),
        media_type TEXT NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png', 'image/gif', 'image/webp')),
        byte_count INTEGER NOT NULL CHECK (byte_count BETWEEN 1 AND 25165760),
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX attachments_by_session_created ON attachments(session_id, created_at, attachment_id)",
)

_PANEL_SCHEMA = (
    """CREATE TABLE panels (
        panel_id TEXT PRIMARY KEY CHECK (
            length(CAST(panel_id AS BLOB)) = 64
            AND panel_id NOT GLOB '*[^0-9a-f]*'
        ),
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
        run_id TEXT NOT NULL,
        source_attachment_id TEXT NOT NULL REFERENCES attachments(attachment_id) ON DELETE RESTRICT,
        name TEXT NOT NULL CHECK (length(CAST(name AS BLOB)) BETWEEN 1 AND 256),
        points_json TEXT NOT NULL CHECK (json_valid(points_json) AND length(CAST(points_json AS BLOB)) <= 16384),
        FOREIGN KEY(run_id, session_id) REFERENCES runs(run_id, session_id) ON DELETE RESTRICT
    )""",
    "CREATE INDEX panels_by_session ON panels(session_id)",
    """CREATE TRIGGER immutable_panel_update BEFORE UPDATE ON panels
        BEGIN SELECT RAISE(ABORT, 'immutable panel'); END""",
    """CREATE TRIGGER immutable_panel_delete BEFORE DELETE ON panels
        BEGIN SELECT RAISE(ABORT, 'immutable panel'); END""",
)

_SCHEMA = (
    *_CORE_SCHEMA,
    *_TOOL_SCHEMA,
    *_CONTINUATION_SCHEMA,
    *_PROVIDER_ATTEMPT_SCHEMA,
    *_ATTACHMENT_SCHEMA,
    *_PANEL_SCHEMA,
)

def _validate_migration(connection: sqlite3.Connection) -> None:
    foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    quick_check = connection.execute("PRAGMA quick_check").fetchone()
    if foreign_key_violations or quick_check is None or quick_check[0] != "ok":
        raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _migrate_run_stream_events(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TRIGGER IF EXISTS immutable_run_event_update")
    connection.execute("DROP TRIGGER IF EXISTS immutable_run_event_delete")
    connection.execute(_run_stream_events_table("run_stream_events_v7"))
    connection.execute(
        "INSERT INTO run_stream_events_v7(run_id, event_sequence, event_kind, payload_json, created_at) "
        "SELECT run_id, event_sequence, event_kind, payload_json, created_at FROM run_stream_events"
    )
    connection.execute("DROP TABLE run_stream_events")
    connection.execute("ALTER TABLE run_stream_events_v7 RENAME TO run_stream_events")
    for statement in _RUN_STREAM_EVENT_TRIGGERS:
        connection.execute(statement)


def _migrate_session_deletion(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS session_deletion_scopes (
            session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL
        )"""
    )
    for trigger_name in (
        "immutable_run_event_delete",
        "immutable_run_record_delete",
        "immutable_run_tool_fact_delete",
        "immutable_run_provider_continuation_delete",
        "immutable_run_provider_attempt_delete",
        "immutable_panel_delete",
    ):
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    for statement in _SESSION_DELETION_TRIGGERS:
        connection.execute(statement)


def _migrate_continuations(connection: sqlite3.Connection) -> None:
    for name in (
        "continuation_matches_model_response",
        "immutable_run_provider_continuation_update",
        "immutable_run_provider_continuation_delete",
    ):
        connection.execute(f"DROP TRIGGER IF EXISTS {name}")
    connection.execute(_CONTINUATION_SCHEMA[0].replace(
        "CREATE TABLE run_provider_continuations", "CREATE TABLE run_provider_continuations_v9"
    ))
    connection.execute(
        "INSERT INTO run_provider_continuations_v9 SELECT * FROM run_provider_continuations"
    )
    connection.execute("DROP TABLE run_provider_continuations")
    connection.execute("ALTER TABLE run_provider_continuations_v9 RENAME TO run_provider_continuations")
    for statement in _CONTINUATION_SCHEMA[1:]:
        connection.execute(statement)


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Initialize or migrate the database while holding its writer lock."""
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("BEGIN IMMEDIATE")
    try:
        # Read the migration version after acquiring the writer lock so concurrent
        # first opens cannot race migrations.
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > _SCHEMA_VERSION:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        if version == _SCHEMA_VERSION:
            connection.commit()
            return
        if version == 0:
            for statement in _SCHEMA:
                connection.execute(statement)
        elif version == 1:
            connection.execute(
                "ALTER TABLE run_execution_checkpoints ADD COLUMN "
                "last_committed_tool_sequence INTEGER NOT NULL DEFAULT 0 "
                "CHECK (last_committed_tool_sequence >= 0)"
            )
            for statement in _TOOL_SCHEMA:
                connection.execute(statement)
            for statement in _CONTINUATION_SCHEMA:
                connection.execute(statement)
            for statement in _PROVIDER_ATTEMPT_SCHEMA:
                connection.execute(statement)
        elif version == 2:
            for statement in _CONTINUATION_SCHEMA:
                connection.execute(statement)
            for statement in _PROVIDER_ATTEMPT_SCHEMA:
                connection.execute(statement)
        elif version == 3:
            for statement in _PROVIDER_ATTEMPT_SCHEMA:
                connection.execute(statement)
        elif version in {4, 5, 6, 7, 8}:
            pass
        else:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        if 0 < version < 5:
            for statement in _ATTACHMENT_SCHEMA:
                connection.execute(statement)
            for statement in _PANEL_SCHEMA:
                connection.execute(statement)
        elif version == 5:
            for statement in _PANEL_SCHEMA:
                connection.execute(statement)
        if 0 < version < 8:
            _migrate_run_stream_events(connection)
        if 3 <= version < 9:
            _migrate_continuations(connection)
        _migrate_session_deletion(connection)
        _validate_migration(connection)
        connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
