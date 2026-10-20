"""SQLite schema definitions and migrations for durable Figura Runs."""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone

from figura.runtime.errors import RunError, RunErrorCode

_SCHEMA_VERSION = 13


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
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
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
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
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
              AND schema_version IN (2, 3)
              AND json_extract(payload_json, '$.continuation_ref') = NEW.continuation_id
              AND json_extract(payload_json, '$.provider_id') = NEW.provider_id
        )
        BEGIN SELECT RAISE(ABORT, 'continuation response mismatch'); END""",
    """CREATE TRIGGER immutable_run_provider_continuation_update BEFORE UPDATE ON run_provider_continuations
        BEGIN SELECT RAISE(ABORT, 'immutable provider continuation'); END""",
    """CREATE TRIGGER immutable_run_provider_continuation_delete BEFORE DELETE ON run_provider_continuations
        BEGIN SELECT RAISE(ABORT, 'immutable provider continuation'); END""",
)

_PROVIDER_REQUEST_SCHEMA = (
    """CREATE TABLE run_provider_requests (
        request_id TEXT PRIMARY KEY CHECK (length(CAST(request_id AS BLOB)) BETWEEN 1 AND 128),
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        purpose TEXT NOT NULL CHECK (purpose IN ('agent_turn', 'context_compaction', 'historical_import')),
        compaction_operation_id TEXT NULL,
        base_record_sequence INTEGER NOT NULL CHECK (base_record_sequence > 0),
        base_tool_sequence INTEGER NOT NULL CHECK (base_tool_sequence >= 0),
        provider_id TEXT NOT NULL CHECK (provider_id IN ('qwen', 'deepseek', 'mimo')),
        model_id TEXT NOT NULL CHECK (length(CAST(model_id AS BLOB)) BETWEEN 1 AND 128),
        endpoint_identity TEXT NOT NULL CHECK (length(endpoint_identity) = 64),
        request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
        request_contract_version INTEGER NOT NULL CHECK (request_contract_version > 0),
        stream_contract_version INTEGER NOT NULL CHECK (stream_contract_version > 0),
        timeout_policy_version INTEGER NOT NULL CHECK (timeout_policy_version > 0),
        retry_policy_version INTEGER NOT NULL CHECK (retry_policy_version > 0),
        max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 4),
        generation_only INTEGER NOT NULL CHECK (generation_only IN (0, 1)),
        options_json TEXT NOT NULL CHECK (json_valid(options_json) AND length(CAST(options_json AS BLOB)) <= 4096),
        asset_manifest_json TEXT NOT NULL CHECK (json_valid(asset_manifest_json) AND length(CAST(asset_manifest_json AS BLOB)) <= 262144),
        prompt_digest TEXT NOT NULL CHECK (length(prompt_digest) = 64),
        tool_registry_digest TEXT NOT NULL CHECK (length(tool_registry_digest) = 64),
        context_estimate_json TEXT NULL CHECK (context_estimate_json IS NULL OR (json_valid(context_estimate_json) AND length(CAST(context_estimate_json AS BLOB)) <= 1024)),
        context_projection TEXT NOT NULL CHECK (context_projection IN ('full', 'checkpoint', 'fallback')),
        context_checkpoint_revision INTEGER NULL CHECK (context_checkpoint_revision IS NULL OR context_checkpoint_revision > 0),
        context_checkpoint_operation_id TEXT NULL CHECK (context_checkpoint_operation_id IS NULL OR length(CAST(context_checkpoint_operation_id AS BLOB)) BETWEEN 1 AND 128),
        created_at TEXT NOT NULL,
        request_json TEXT NOT NULL CHECK (json_valid(request_json) AND length(CAST(request_json AS BLOB)) <= 262144),
        CHECK ((purpose = 'context_compaction' AND compaction_operation_id IS NOT NULL)
            OR (purpose <> 'context_compaction' AND compaction_operation_id IS NULL)),
        UNIQUE(run_id, request_id)
    )""",
    "CREATE INDEX provider_requests_by_run ON run_provider_requests(run_id, created_at, request_id)",
)

_PROVIDER_ATTEMPT_SCHEMA = (
    """CREATE TABLE run_provider_attempts (
        attempt_id TEXT PRIMARY KEY CHECK (length(CAST(attempt_id AS BLOB)) BETWEEN 1 AND 128),
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        request_id TEXT NOT NULL REFERENCES run_provider_requests(request_id) ON DELETE RESTRICT,
        attempt_sequence INTEGER NOT NULL CHECK (attempt_sequence > 0),
        run_attempt_sequence INTEGER NOT NULL CHECK (run_attempt_sequence > 0),
        phase TEXT NOT NULL CHECK (phase IN ('connecting', 'sending', 'awaiting_response', 'streaming')),
        base_record_sequence INTEGER NOT NULL CHECK (base_record_sequence > 0),
        base_tool_sequence INTEGER NOT NULL CHECK (base_tool_sequence >= 0),
        status TEXT NOT NULL CHECK (status IN ('started', 'response_committed', 'known_failure', 'outcome_unknown', 'cancelled')),
        response_record_id TEXT NULL,
        failure_code TEXT NULL CHECK (failure_code IS NULL OR failure_code IN (
            'configuration_missing', 'invalid_configuration', 'unsupported_provider', 'unsupported_model',
            'invalid_request', 'unsupported_capability', 'provider_rejected', 'provider_unavailable',
            'timeout', 'connection_error', 'incomplete_stream', 'invalid_provider_response', 'transport_error'
        )),
        started_at TEXT NOT NULL,
        finished_at TEXT NULL,
        connected_at TEXT NULL,
        request_sent_at TEXT NULL,
        response_headers_at TEXT NULL,
        first_event_at TEXT NULL,
        last_activity_at TEXT NULL,
        failure_phase TEXT NULL CHECK (failure_phase IN ('connecting', 'sending', 'awaiting_response', 'streaming')),
        provider_request_id TEXT NULL CHECK (provider_request_id IS NULL OR length(CAST(provider_request_id AS BLOB)) <= 256),
        request_bytes INTEGER NULL CHECK (request_bytes IS NULL OR request_bytes >= 0),
        response_bytes INTEGER NULL CHECK (response_bytes IS NULL OR response_bytes >= 0),
        usage_json TEXT NULL CHECK (usage_json IS NULL OR (json_valid(usage_json) AND length(CAST(usage_json AS BLOB)) <= 1024)),
        retry_of_attempt_id TEXT NULL REFERENCES run_provider_attempts(attempt_id),
        failure_category TEXT NULL CHECK (failure_category IN ('temporary_unsent', 'temporary_rejected', 'temporary_unknown', 'permanent', 'invalid_response', 'internal_error')),
        http_status INTEGER NULL CHECK (http_status BETWEEN 100 AND 599),
        next_eligible_at TEXT NULL,
        UNIQUE(run_id, run_attempt_sequence),
        UNIQUE(request_id, attempt_sequence),
        UNIQUE(run_id, response_record_id),
        FOREIGN KEY(response_record_id, run_id)
            REFERENCES run_execution_records(record_id, run_id) ON DELETE RESTRICT,
        CHECK (
            (status = 'started' AND response_record_id IS NULL AND failure_code IS NULL AND finished_at IS NULL)
            OR (status = 'response_committed' AND failure_code IS NULL AND finished_at IS NOT NULL)
            OR (status = 'known_failure' AND response_record_id IS NULL AND failure_code IS NOT NULL AND finished_at IS NOT NULL)
            OR (status = 'outcome_unknown' AND response_record_id IS NULL AND finished_at IS NOT NULL)
            OR (status = 'cancelled' AND response_record_id IS NULL AND finished_at IS NOT NULL)
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
          OR NEW.attempt_id <> OLD.attempt_id
          OR NEW.run_id <> OLD.run_id
          OR NEW.request_id <> OLD.request_id
          OR NEW.attempt_sequence <> OLD.attempt_sequence
          OR NEW.run_attempt_sequence <> OLD.run_attempt_sequence
          OR NEW.base_record_sequence <> OLD.base_record_sequence
          OR NEW.base_tool_sequence <> OLD.base_tool_sequence
          OR NEW.retry_of_attempt_id IS NOT OLD.retry_of_attempt_id
          OR NEW.started_at <> OLD.started_at
        BEGIN SELECT RAISE(ABORT, 'invalid provider attempt transition'); END""",
    """CREATE TRIGGER immutable_run_provider_attempt_delete BEFORE DELETE ON run_provider_attempts
        BEGIN SELECT RAISE(ABORT, 'immutable provider attempt'); END""",
    "CREATE INDEX provider_attempts_by_request ON run_provider_attempts(request_id, attempt_sequence)",
    "CREATE UNIQUE INDEX provider_one_active_attempt ON run_provider_attempts(request_id) WHERE status = 'started'",
)

_LEGACY_PROVIDER_ATTEMPT_CREATE = """CREATE TABLE run_provider_attempts (
        attempt_id TEXT PRIMARY KEY CHECK (length(CAST(attempt_id AS BLOB)) BETWEEN 1 AND 128),
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        attempt_sequence INTEGER NOT NULL CHECK (attempt_sequence BETWEEN 1 AND 8),
        base_record_sequence INTEGER NOT NULL CHECK (base_record_sequence > 0),
        base_tool_sequence INTEGER NOT NULL CHECK (base_tool_sequence >= 0),
        status TEXT NOT NULL CHECK (status IN ('started', 'response_committed', 'known_failure', 'outcome_unknown')),
        response_record_id TEXT NULL,
        failure_code TEXT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NULL,
        UNIQUE(run_id, attempt_sequence),
        UNIQUE(run_id, response_record_id),
        FOREIGN KEY(response_record_id, run_id)
            REFERENCES run_execution_records(record_id, run_id) ON DELETE RESTRICT
    )"""

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

_SESSION_CONTEXT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS session_context_checkpoints (
        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
        revision INTEGER NOT NULL CHECK (revision > 0),
        covered_run_id TEXT NOT NULL CHECK (length(CAST(covered_run_id AS BLOB)) BETWEEN 1 AND 128),
        covered_run_ordinal INTEGER NOT NULL CHECK (covered_run_ordinal > 0),
        covered_record_sequence INTEGER NOT NULL CHECK (covered_record_sequence > 0),
        covered_tool_sequence INTEGER NOT NULL CHECK (covered_tool_sequence >= 0),
        summary_contract_version INTEGER NOT NULL CHECK (summary_contract_version > 0),
        summary_json TEXT NOT NULL CHECK (json_valid(summary_json) AND length(CAST(summary_json AS BLOB)) <= 524288),
        source_refs_json TEXT NOT NULL CHECK (json_valid(source_refs_json) AND length(CAST(source_refs_json AS BLOB)) <= 262144),
        compaction_operation_id TEXT NULL CHECK (compaction_operation_id IS NULL OR length(CAST(compaction_operation_id AS BLOB)) BETWEEN 1 AND 128),
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS session_context_compaction_operations (
        operation_id TEXT PRIMARY KEY CHECK (length(CAST(operation_id AS BLOB)) BETWEEN 1 AND 128),
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
        target_run_id TEXT NOT NULL,
        base_record_sequence INTEGER NOT NULL CHECK (base_record_sequence > 0),
        base_tool_sequence INTEGER NOT NULL CHECK (base_tool_sequence >= 0),
        input_checkpoint_revision INTEGER NOT NULL CHECK (input_checkpoint_revision >= 0),
        covered_run_id TEXT NOT NULL CHECK (length(CAST(covered_run_id AS BLOB)) BETWEEN 1 AND 128),
        covered_run_ordinal INTEGER NOT NULL CHECK (covered_run_ordinal > 0),
        covered_record_sequence INTEGER NOT NULL CHECK (covered_record_sequence > 0),
        covered_tool_sequence INTEGER NOT NULL CHECK (covered_tool_sequence >= 0),
        status TEXT NOT NULL CHECK (status IN ('preparing', 'completed', 'fallback')),
        selection_plan_json TEXT NOT NULL CHECK (json_valid(selection_plan_json) AND length(CAST(selection_plan_json AS BLOB)) <= 4096),
        provider_request_id TEXT NULL REFERENCES run_provider_requests(request_id) ON DELETE RESTRICT,
        result_checkpoint_revision INTEGER NULL CHECK (result_checkpoint_revision IS NULL OR result_checkpoint_revision > 0),
        failure_code TEXT NULL CHECK (failure_code IS NULL OR length(CAST(failure_code AS BLOB)) <= 64),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(target_run_id, session_id) REFERENCES runs(run_id, session_id) ON DELETE RESTRICT,
        UNIQUE(target_run_id, base_record_sequence, base_tool_sequence),
        CHECK (
            (status = 'preparing' AND result_checkpoint_revision IS NULL)
            OR (status = 'completed' AND result_checkpoint_revision IS NOT NULL AND failure_code IS NULL)
            OR (status = 'fallback' AND result_checkpoint_revision IS NULL)
        )
    )""",
)

_SCHEMA = (
    *_CORE_SCHEMA,
    *_TOOL_SCHEMA,
    *_CONTINUATION_SCHEMA,
    *_PROVIDER_REQUEST_SCHEMA,
    *_PROVIDER_ATTEMPT_SCHEMA,
    *_ATTACHMENT_SCHEMA,
    *_PANEL_SCHEMA,
)

def _validate_migration(connection: sqlite3.Connection) -> None:
    foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    quick_check = connection.execute("PRAGMA quick_check").fetchone()
    if foreign_key_violations or quick_check is None or quick_check[0] != "ok":
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    from figura.runtime.persistence.runs import _read_run_state_from_connection
    from figura.shared.payloads import ExecutionPayloadLimits, use_payload_read_limits

    ceiling = connection.execute("SELECT read_ceiling FROM execution_payload_metadata WHERE singleton = 1").fetchone()[0]
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        with use_payload_read_limits(ExecutionPayloadLimits(ceiling)):
            for row in connection.execute("SELECT session_id, run_id FROM runs").fetchall():
                _read_run_state_from_connection(connection, row["session_id"], row["run_id"])
    finally:
        connection.row_factory = previous_factory


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


def _migrate_execution_policy(connection: sqlite3.Connection) -> None:
    """Rebuild bounded v10 tables atomically without changing existing facts."""
    triggers = connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()
    for row in triggers:
        connection.execute(f'DROP TRIGGER "{row[0]}"')
    tables = {
        "run_execution_records": _CORE_SCHEMA[2].replace(" AND length(CAST(payload_json AS BLOB)) <= 262144", ""),
        "run_tool_execution_facts": _TOOL_SCHEMA[0].replace(" AND length(CAST(payload_json AS BLOB)) <= 524288", ""),
        "run_provider_continuations": _CONTINUATION_SCHEMA[0].replace(
            "AND (reasoning_content IS NULL OR length(CAST(reasoning_content AS BLOB)) <= 524288)", ""),
        "run_provider_attempts": _LEGACY_PROVIDER_ATTEMPT_CREATE.replace(
            "attempt_sequence BETWEEN 1 AND 8", "attempt_sequence > 0"
        ).replace("        UNIQUE(run_id, base_record_sequence, base_tool_sequence),", "").replace(
            "        started_at TEXT NOT NULL,",
            """        operation_id TEXT NULL REFERENCES run_provider_request_bindings(operation_id),
        operation_attempt_number INTEGER NULL CHECK (operation_attempt_number BETWEEN 1 AND 4),
        retry_of_attempt_id TEXT NULL REFERENCES run_provider_attempts(attempt_id),
        failure_category TEXT NULL CHECK (failure_category IN ('temporary_unsent', 'temporary_rejected', 'temporary_unknown', 'permanent', 'invalid_response', 'internal_error')),
        http_status INTEGER NULL CHECK (http_status BETWEEN 100 AND 599),
        next_eligible_at TEXT NULL,
        started_at TEXT NOT NULL,"""),
    }
    connection.execute("""CREATE TABLE IF NOT EXISTS run_provider_request_bindings (
        operation_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        base_record_sequence INTEGER NOT NULL,
        base_tool_sequence INTEGER NOT NULL,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        UNIQUE(run_id, base_record_sequence, base_tool_sequence)
    )""")
    for name, sql in tables.items():
        connection.execute(sql.replace(f"CREATE TABLE {name}", f"CREATE TABLE {name}_v11"))
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({name})")]
        projection = ', '.join(columns)
        connection.execute(f"INSERT INTO {name}_v11 ({projection}) SELECT {projection} FROM {name}")
        connection.execute(f"DROP TABLE {name}")
        connection.execute(f"ALTER TABLE {name}_v11 RENAME TO {name}")
    for name, sql in triggers:
        if name == "provider_attempt_has_one_terminal_transition":
            sql = sql.replace("OR NEW.started_at <> OLD.started_at", """OR NEW.started_at <> OLD.started_at
          OR NEW.operation_id IS NOT OLD.operation_id
          OR NEW.operation_attempt_number IS NOT OLD.operation_attempt_number
          OR NEW.retry_of_attempt_id IS NOT OLD.retry_of_attempt_id""")
        connection.execute(sql.replace("AND schema_version = 2", "AND schema_version IN (2, 3)"))
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_operation_attempt_number ON run_provider_attempts(operation_id, operation_attempt_number) WHERE operation_id IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_provider_operation ON run_provider_attempts(operation_id) WHERE operation_id IS NOT NULL AND status = 'started'")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_accepted_provider_operation ON run_provider_attempts(operation_id) WHERE operation_id IS NOT NULL AND status = 'response_committed'")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS immutable_provider_binding_update BEFORE UPDATE ON run_provider_request_bindings
        BEGIN SELECT RAISE(ABORT, 'immutable provider binding'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS immutable_provider_binding_delete BEFORE DELETE ON run_provider_request_bindings
        WHEN NOT EXISTS (SELECT 1 FROM runs JOIN session_deletion_scopes USING(session_id) WHERE runs.run_id = OLD.run_id)
        BEGIN SELECT RAISE(ABORT, 'immutable provider binding'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS provider_attempt_matches_binding
        BEFORE INSERT ON run_provider_attempts
        WHEN NEW.operation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM run_provider_request_bindings b WHERE b.operation_id = NEW.operation_id
              AND b.run_id = NEW.run_id AND b.base_record_sequence = NEW.base_record_sequence
              AND b.base_tool_sequence = NEW.base_tool_sequence
        ) BEGIN SELECT RAISE(ABORT, 'provider binding prefix mismatch'); END""")
    connection.execute("CREATE TABLE IF NOT EXISTS execution_payload_metadata (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), read_ceiling INTEGER NOT NULL CHECK(read_ceiling > 0))")
    connection.execute("INSERT OR IGNORE INTO execution_payload_metadata VALUES (1, 33554432)")


def _migrate_provider_stream_contract(connection: sqlite3.Connection) -> None:
    """Replace old frozen bindings and attempt rows with the stream-only ledger."""
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_provider_requests'"
    ).fetchone():
        return

    # Schema 12's continuation guard only recognized response schema 2. The
    # streaming contract writes schema 3 responses, so widen the guard as part
    # of the same atomic migration.
    connection.execute("DROP TRIGGER IF EXISTS continuation_matches_model_response")
    connection.execute(_CONTINUATION_SCHEMA[1])

    now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    connection.execute("DROP TRIGGER IF EXISTS provider_attempt_response_matches_model_response")
    connection.execute("DROP TRIGGER IF EXISTS provider_attempt_has_one_terminal_transition")
    connection.execute("DROP TRIGGER IF EXISTS immutable_run_provider_attempt_delete")
    connection.execute("DROP TRIGGER IF EXISTS immutable_provider_binding_update")
    connection.execute("DROP TRIGGER IF EXISTS immutable_provider_binding_delete")
    connection.execute("DROP TRIGGER IF EXISTS provider_attempt_matches_binding")
    connection.execute("DROP INDEX IF EXISTS one_operation_attempt_number")
    connection.execute("DROP INDEX IF EXISTS one_active_provider_operation")
    connection.execute("DROP INDEX IF EXISTS one_accepted_provider_operation")

    has_bindings = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_provider_request_bindings'"
    ).fetchone() is not None
    binding_rows = connection.execute(
        "SELECT * FROM run_provider_request_bindings ORDER BY run_id, base_record_sequence"
    ).fetchall() if has_bindings else ()
    attempt_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(run_provider_attempts)")
    }
    legacy_attempt_rows = connection.execute(
        "SELECT * FROM run_provider_attempts ORDER BY run_id, attempt_sequence"
    ).fetchall() if attempt_columns else ()

    connection.execute(_PROVIDER_REQUEST_SCHEMA[0])
    connection.execute(_PROVIDER_REQUEST_SCHEMA[1])
    request_by_operation: dict[str, dict[str, object]] = {}

    def add_historical_request(
        request_id: str,
        run_id: str,
        provider_id: str,
        model_id: str,
        base_record_sequence: int,
        base_tool_sequence: int,
        created_at: str,
        context_estimate_json: str | None = None,
    ) -> None:
        estimate = json.loads(context_estimate_json) if context_estimate_json is not None else None
        historical_json = json.dumps({
            "request_id": request_id,
            "run_id": run_id,
            "purpose": "historical_import",
            "compaction_operation_id": None,
            "base_record_sequence": base_record_sequence,
            "base_tool_sequence": base_tool_sequence,
            "provider_id": provider_id,
            "model_id": model_id,
            "request_fingerprint": "0" * 64,
            "endpoint_identity": "0" * 64,
            "prompt_digest": "0" * 64,
            "tool_registry_digest": "0" * 64,
            "options": {},
            "asset_manifest": {},
            "created_at": created_at,
            "request_contract_version": 2,
            "stream_contract_version": 1,
            "timeout_policy_version": 1,
            "schema_version": 2,
            "generation_only": False,
        "max_attempts": 4,
            "retry_policy_version": 1,
            "context_estimate": estimate,
            "context_projection": "full",
            "context_checkpoint_revision": None,
            "context_checkpoint_operation_id": None,
        }, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            "INSERT INTO run_provider_requests(request_id, run_id, purpose, compaction_operation_id, base_record_sequence, base_tool_sequence, provider_id, model_id, endpoint_identity, request_fingerprint, request_contract_version, stream_contract_version, timeout_policy_version, retry_policy_version, max_attempts, generation_only, options_json, asset_manifest_json, prompt_digest, tool_registry_digest, context_estimate_json, context_projection, context_checkpoint_revision, context_checkpoint_operation_id, created_at, request_json) VALUES (?, ?, 'historical_import', NULL, ?, ?, ?, ?, ?, ?, 2, 1, 1, 1, 4, 0, '{}', '{}', ?, ?, ?, 'full', NULL, NULL, ?, ?)",
            (
                request_id, run_id, base_record_sequence, base_tool_sequence,
                provider_id, model_id, "0" * 64, "0" * 64,
                "0" * 64, "0" * 64, context_estimate_json, created_at, historical_json,
            ),
        )

    if has_bindings:
        for row in binding_rows:
            try:
                old = json.loads(row["payload_json"])
                estimate = old.get("context_estimate")
                estimate_json = json.dumps(estimate, ensure_ascii=False, separators=(",", ":")) if estimate is not None else None
                request_id = f"history-{row['operation_id']}"
                if len(request_id.encode("utf-8")) > 128:
                    import hashlib
                    request_id = "history-" + hashlib.sha256(row["operation_id"].encode()).hexdigest()
                add_historical_request(
                    request_id, row["run_id"], old["provider_id"], old["model_id"],
                    old["base_record_sequence"], old["base_tool_sequence"],
                    old["created_at"], estimate_json,
                )
                request_by_operation[row["operation_id"]] = {
                    "request_id": request_id,
                    "run_id": row["run_id"],
                    "base_record_sequence": old["base_record_sequence"],
                    "base_tool_sequence": old["base_tool_sequence"],
                }
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None

    # Preserve historical attempt outcomes even when an older attempt predates
    # immutable request bindings. These imports are explicitly non-dispatchable.
    seen_ids: set[str] = {item["request_id"] for item in request_by_operation.values()}
    for row in legacy_attempt_rows:
        operation_id = row["operation_id"] if "operation_id" in attempt_columns else None
        if operation_id and operation_id in request_by_operation:
            continue
        request_id = "history-attempt-" + row["attempt_id"]
        if len(request_id.encode("utf-8")) > 128:
            import hashlib
            request_id = "history-attempt-" + hashlib.sha256(row["attempt_id"].encode()).hexdigest()
        if request_id not in seen_ids:
            run = connection.execute(
                "SELECT provider, model FROM runs WHERE run_id = ?", (row["run_id"],)
            ).fetchone()
            if run is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            add_historical_request(
                request_id, row["run_id"], run["provider"], run["model"],
                row["base_record_sequence"], row["base_tool_sequence"], row["started_at"],
            )
            seen_ids.add(request_id)
        if operation_id:
            request_by_operation[operation_id] = {
                "request_id": request_id,
                "run_id": row["run_id"],
                "base_record_sequence": row["base_record_sequence"],
                "base_tool_sequence": row["base_tool_sequence"],
            }

    if attempt_columns:
        connection.execute("ALTER TABLE run_provider_attempts RENAME TO run_provider_attempts_pre_stream")
    connection.execute(_PROVIDER_ATTEMPT_SCHEMA[0])
    retry_prior: dict[str, str] = {}
    request_attempt_counts: dict[str, int] = {}
    active_runs: set[str] = set()
    latest_attempt_by_operation: dict[str, tuple[int, str]] = {}
    for row in legacy_attempt_rows:
        operation_id = row["operation_id"] if "operation_id" in attempt_columns else None
        if not operation_id:
            continue
        operation_attempt = (
            row["operation_attempt_number"]
            if "operation_attempt_number" in attempt_columns
            else row["attempt_sequence"]
        )
        previous = latest_attempt_by_operation.get(operation_id)
        if previous is None or operation_attempt >= previous[0]:
            latest_attempt_by_operation[operation_id] = (operation_attempt, row["attempt_id"])
    for row in legacy_attempt_rows:
        operation_id = row["operation_id"] if "operation_id" in attempt_columns else None
        mapped = request_by_operation.get(operation_id) if operation_id else None
        request_id = mapped["request_id"] if mapped else "history-attempt-" + row["attempt_id"]
        if len(request_id.encode("utf-8")) > 128:
            import hashlib
            request_id = "history-attempt-" + hashlib.sha256(row["attempt_id"].encode()).hexdigest()
        attempt_sequence = request_attempt_counts.get(request_id, 0) + 1
        request_attempt_counts[request_id] = attempt_sequence
        status = row["status"]
        finished_at = row["finished_at"]
        failure_code = row["failure_code"]
        if status == "started":
            status = "outcome_unknown"
            finished_at = now
            latest = latest_attempt_by_operation.get(operation_id) if operation_id else None
            if latest is None or latest[1] == row["attempt_id"]:
                active_runs.add(row["run_id"])
        failure_category = row["failure_category"] if "failure_category" in attempt_columns else None
        if status == "known_failure" and failure_category is None:
            failure_category = "permanent"
        if status == "outcome_unknown" and failure_category is None:
            failure_category = "permanent"
        retry_of = row["retry_of_attempt_id"] if "retry_of_attempt_id" in attempt_columns else None
        if retry_of is None and operation_id:
            retry_of = retry_prior.get(operation_id)
        if operation_id:
            retry_prior[operation_id] = row["attempt_id"]
        next_eligible_at = row["next_eligible_at"] if "next_eligible_at" in attempt_columns else None
        if next_eligible_at is not None:
            latest = latest_attempt_by_operation.get(operation_id) if operation_id else None
            if latest is None or latest[1] == row["attempt_id"]:
                active_runs.add(row["run_id"])
                next_eligible_at = None
        connection.execute(
            "INSERT INTO run_provider_attempts(attempt_id, run_id, request_id, attempt_sequence, run_attempt_sequence, phase, base_record_sequence, base_tool_sequence, status, response_record_id, failure_code, started_at, finished_at, connected_at, request_sent_at, response_headers_at, first_event_at, last_activity_at, failure_phase, provider_request_id, request_bytes, response_bytes, usage_json, retry_of_attempt_id, failure_category, http_status, next_eligible_at) "
            "VALUES (?, ?, ?, ?, ?, 'sending', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?)",
            (
                row["attempt_id"], row["run_id"], request_id, attempt_sequence,
                row["attempt_sequence"], row["base_record_sequence"], row["base_tool_sequence"],
                status, row["response_record_id"], failure_code, row["started_at"], finished_at,
                "sending" if status in {"known_failure", "outcome_unknown"} else None,
                retry_of, failure_category,
                row["http_status"] if "http_status" in attempt_columns else None,
                next_eligible_at,
            ),
        )

    if attempt_columns:
        connection.execute("DROP TABLE run_provider_attempts_pre_stream")
    if has_bindings:
        connection.execute("DROP TABLE run_provider_request_bindings")

    # Install the canonical attempt indexes and transition guards after all rows
    # have been copied from the legacy table.
    for statement in _PROVIDER_ATTEMPT_SCHEMA[1:]:
        connection.execute(statement)

    # Split the old compaction JSON into frozen coverage and one canonical request
    # reference. Old summary attempts cannot be replayed under the new contract.
    operation_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_context_compaction_operations'"
    ).fetchone() is not None
    if operation_exists:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(session_context_compaction_operations)")}
        if "request_binding_json" in columns:
            old_operations = connection.execute(
                "SELECT * FROM session_context_compaction_operations"
            ).fetchall()
            connection.execute("DROP TABLE session_context_compaction_operations")
            connection.execute(_SESSION_CONTEXT_SCHEMA[1].replace(
                "CREATE TABLE IF NOT EXISTS session_context_compaction_operations",
                "CREATE TABLE session_context_compaction_operations",
            ))
            for row in old_operations:
                try:
                    old_binding = json.loads(row["request_binding_json"]) if row["request_binding_json"] else {}
                    plan = old_binding.get("plan", old_binding)
                    plan_json = json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
                status = row["status"]
                failure_code = row["failure_code"]
                has_frozen_descriptor = bool(old_binding.get("descriptor"))
                if status == "preparing" and (row["attempt_count"] > 0 or has_frozen_descriptor):
                    status = "fallback"
                    failure_code = "stream_contract_migration"
                    active_runs.add(row["target_run_id"])
                connection.execute(
                    "INSERT INTO session_context_compaction_operations("
                    "operation_id, session_id, target_run_id, base_record_sequence, base_tool_sequence, "
                    "input_checkpoint_revision, covered_run_id, covered_run_ordinal, covered_record_sequence, "
                    "covered_tool_sequence, status, selection_plan_json, provider_request_id, "
                    "result_checkpoint_revision, failure_code, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                    (
                        row["operation_id"], row["session_id"], row["target_run_id"],
                        row["base_record_sequence"], row["base_tool_sequence"],
                        row["input_checkpoint_revision"], row["covered_run_id"],
                        row["covered_run_ordinal"], row["covered_record_sequence"],
                        row["covered_tool_sequence"], status, plan_json,
                        row["result_checkpoint_revision"] if status == row["status"] else None,
                        failure_code, row["created_at"], now if status != row["status"] else row["updated_at"],
                    ),
                )

    # Old-contract in-flight work is never replayed. Close the Run and append one
    # durable terminal marker while retaining every committed record/checkpoint.
    for run_id in active_runs:
        row = connection.execute(
            "SELECT session_id, status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None or row["status"] != "running":
            continue
        connection.execute(
            "UPDATE runs SET status='interrupted', finished_at=?, terminal_code='interrupted', terminal_message='Run 已中断。' WHERE run_id=?",
            (now, run_id),
        )
        connection.execute(
            "UPDATE run_execution_checkpoints SET revision=revision+1, next_action_json=NULL, updated_at=? WHERE run_id=?",
            (now, run_id),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM run_stream_events WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        payload = json.dumps({"terminal_code": "interrupted"}, separators=(",", ":"))
        connection.execute(
            "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) VALUES (?, ?, 'run_interrupted', ?, ?)",
            (run_id, sequence, payload, now),
        )

    connection.execute("DROP TRIGGER IF EXISTS immutable_provider_request_update")
    connection.execute("DROP TRIGGER IF EXISTS immutable_provider_request_delete")
    connection.execute("CREATE TRIGGER immutable_provider_request_update BEFORE UPDATE ON run_provider_requests BEGIN SELECT RAISE(ABORT, 'immutable provider request'); END")
    connection.execute("CREATE TRIGGER immutable_provider_request_delete BEFORE DELETE ON run_provider_requests WHEN NOT EXISTS (SELECT 1 FROM runs JOIN session_deletion_scopes USING(session_id) WHERE runs.run_id=OLD.run_id) BEGIN SELECT RAISE(ABORT, 'immutable provider request'); END")


def _migrate_dynamic_payload_bounds(connection: sqlite3.Connection) -> None:
    """Use the shared codec limit instead of stale fixed SQLite payload caps."""
    definitions = (
        (
            "run_execution_records",
            _CORE_SCHEMA[2],
            " AND length(CAST(payload_json AS BLOB)) <= 262144",
        ),
        (
            "run_tool_execution_facts",
            _TOOL_SCHEMA[0],
            " AND length(CAST(payload_json AS BLOB)) <= 524288",
        ),
        (
            "run_provider_continuations",
            _CONTINUATION_SCHEMA[0],
            "AND (reasoning_content IS NULL OR length(CAST(reasoning_content AS BLOB)) <= 524288)",
        ),
    )
    for table_name, canonical_sql, fixed_limit in definitions:
        current = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if current is None or fixed_limit not in (current[0] or ""):
            continue
        triggers = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=? AND sql IS NOT NULL",
            (table_name,),
        ).fetchall()
        for name, _sql in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        replacement = canonical_sql.replace(
            f"CREATE TABLE {table_name}", f"CREATE TABLE {table_name}_v13"
        ).replace(fixed_limit, "")
        connection.execute(replacement)
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")]
        projection = ", ".join(columns)
        connection.execute(
            f"INSERT INTO {table_name}_v13 ({projection}) SELECT {projection} FROM {table_name}"
        )
        connection.execute(f"DROP TABLE {table_name}")
        connection.execute(f"ALTER TABLE {table_name}_v13 RENAME TO {table_name}")
        for _name, sql in triggers:
            connection.execute(sql)


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Initialize or migrate the database while holding its writer lock."""
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = OFF")
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
            connection.execute(_LEGACY_PROVIDER_ATTEMPT_CREATE)
        elif version == 2:
            for statement in _CONTINUATION_SCHEMA:
                connection.execute(statement)
            connection.execute(_LEGACY_PROVIDER_ATTEMPT_CREATE)
        elif version == 3:
            connection.execute(_LEGACY_PROVIDER_ATTEMPT_CREATE)
        elif version in {4, 5, 6, 7, 8, 9, 10, 11, 12}:
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
            # Older fixtures/deployments have no deletion scope yet; make all
            # existing scoped triggers valid before SQLite rewrites table names.
            connection.execute("CREATE TABLE IF NOT EXISTS session_deletion_scopes (session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE RESTRICT, created_at TEXT NOT NULL)")
            _migrate_run_stream_events(connection)
        if 3 <= version < 9:
            _migrate_continuations(connection)
        _migrate_session_deletion(connection)
        connection.execute("""CREATE TABLE IF NOT EXISTS run_stop_requests (
            run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
            request_id TEXT NOT NULL UNIQUE,
            requested_at TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (reason = 'user_requested')
        )""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS immutable_run_stop_request_update
            BEFORE UPDATE ON run_stop_requests
            BEGIN SELECT RAISE(ABORT, 'immutable stop request'); END""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS immutable_run_stop_request_delete
            BEFORE DELETE ON run_stop_requests
            WHEN NOT EXISTS (SELECT 1 FROM session_deletion_scopes g JOIN runs r
                ON r.session_id = g.session_id WHERE r.run_id = OLD.run_id)
            BEGIN SELECT RAISE(ABORT, 'immutable stop request'); END""")
        has_stream_provider_requests = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_provider_requests'"
        ).fetchone() is not None
        if 0 < version < 11 and not has_stream_provider_requests:
            _migrate_execution_policy(connection)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS execution_payload_metadata "
            "(singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
            "read_ceiling INTEGER NOT NULL CHECK(read_ceiling > 0))"
        )
        connection.execute(
            "INSERT OR IGNORE INTO execution_payload_metadata VALUES (1, 33554432)"
        )
        for statement in _SESSION_CONTEXT_SCHEMA:
            connection.execute(statement)
        if 0 < version < _SCHEMA_VERSION:
            _migrate_provider_stream_contract(connection)
            _migrate_dynamic_payload_bounds(connection)
        connection.execute("DROP TRIGGER IF EXISTS immutable_provider_request_update")
        connection.execute("DROP TRIGGER IF EXISTS immutable_provider_request_delete")
        connection.execute("CREATE TRIGGER immutable_provider_request_update BEFORE UPDATE ON run_provider_requests BEGIN SELECT RAISE(ABORT, 'immutable provider request'); END")
        connection.execute("CREATE TRIGGER immutable_provider_request_delete BEFORE DELETE ON run_provider_requests WHEN NOT EXISTS (SELECT 1 FROM runs JOIN session_deletion_scopes USING(session_id) WHERE runs.run_id=OLD.run_id) BEGIN SELECT RAISE(ABORT, 'immutable provider request'); END")
        _validate_migration(connection)
        connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    finally:
        connection.execute("PRAGMA foreign_keys = ON")
