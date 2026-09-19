"""Durable, bounded execution history owned by the local Gateway."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..storage import resolve_storage_paths
from ..trace import truncate_text
from .protocol import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointPhase,
    ContinuationKind,
    GeneratedChartReference,
    MAX_ARTIFACT_CAPTION,
    MAX_ARTIFACT_CHART_TYPE,
    MAX_ARTIFACT_TITLE,
    MAX_EVENT_KIND,
    MAX_EVENT_PAYLOAD,
    MAX_IDEMPOTENCY_KEY,
    MAX_RUN_ID,
    MAX_TERMINAL_CODE,
    OperationState,
    RecoveryStatus,
    RunEvent,
    RunStatus,
    _truncate_tool_result_payload,
    utc_timestamp,
)
from .recovery import (
    CheckpointError,
    RecoveryCheckpoint,
    bounded_operation_result,
    deserialize_checkpoint,
    serialize_checkpoint,
)

DEFAULT_MAX_HISTORY_EVENTS = 512
DEFAULT_MAX_HISTORY_RUNS = 256
DEFAULT_HISTORY_RETENTION_SECONDS = 30 * 24 * 60 * 60.0
DEFAULT_MAX_HISTORY_ARTIFACT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_HISTORY_ARTIFACTS = 32
DEFAULT_RECOVERY_RETENTION_SECONDS = DEFAULT_HISTORY_RETENTION_SECONDS
_SUPPORTED_ARTIFACT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class HistoryStoreError(Exception):
    """A bounded persistence or artifact failure."""


class GatewayHistoryStore:
    """Persist Gateway-owned runs, events, and generated visual artifacts."""

    def __init__(
        self,
        database: str | Path | None,
        *,
        data_dir: str | Path | None = None,
        artifact_root: str | Path | None = None,
        max_events: int = DEFAULT_MAX_HISTORY_EVENTS,
        max_runs: int = DEFAULT_MAX_HISTORY_RUNS,
        retention_seconds: float = DEFAULT_HISTORY_RETENTION_SECONDS,
        max_artifact_bytes: int = DEFAULT_MAX_HISTORY_ARTIFACT_BYTES,
        max_artifacts: int = DEFAULT_MAX_HISTORY_ARTIFACTS,
    ) -> None:
        paths = resolve_storage_paths(
            data_dir=data_dir,
            database=database,
            artifact_root=artifact_root,
        )
        self.database = paths.database
        self.artifact_root = paths.run_artifacts
        self.max_events = max_events
        self.max_runs = max_runs
        self.retention_seconds = retention_seconds
        self.max_artifact_bytes = max_artifact_bytes
        self.max_artifacts = max_artifacts
        self._lock = RLock()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._restrict_permissions(self.artifact_root, 0o700)

    def _connect(self):
        import sqlite3

        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                -- The Gateway may initialize before the memory layer opens its
                -- first session. Keep the shared parent table compatible with
                -- SQLiteAgentMemory so foreign-keyed Gateway tables are usable.
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gateway_runs (
                  run_id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  terminal_code TEXT,
                  terminal_message TEXT,
                  answer_source TEXT,
                  history_warning TEXT,
                  provider TEXT,
                  model TEXT,
                  cancel_requested INTEGER NOT NULL DEFAULT 0,
                  retry_of TEXT,
                  parent_run_id TEXT REFERENCES gateway_runs(run_id) ON DELETE SET NULL,
                  root_run_id TEXT,
                  continuation_kind TEXT,
                  recovery_status TEXT NOT NULL DEFAULT 'unavailable',
                  checkpoint_id TEXT,
                  recovery_phase TEXT,
                  recovery_next_action TEXT,
                  recovery_reason TEXT,
                  recovery_version INTEGER,
                  recovery_updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS gateway_run_idempotency (
                  idempotency_key TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  request_fingerprint TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gateway_run_checkpoints (
                  checkpoint_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  version INTEGER NOT NULL,
                  phase TEXT NOT NULL,
                  next_action TEXT NOT NULL,
                  state_json TEXT NOT NULL,
                  digest TEXT NOT NULL,
                  recovery_status TEXT NOT NULL,
                  blocked_reason TEXT,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  sequence INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS gateway_run_operations (
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  operation_id TEXT NOT NULL,
                  operation_kind TEXT NOT NULL,
                  state TEXT NOT NULL,
                  request_fingerprint TEXT,
                  result_json TEXT,
                  reference_json TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  PRIMARY KEY(run_id, operation_id)
                );
                CREATE TABLE IF NOT EXISTS gateway_run_events (
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  sequence INTEGER NOT NULL,
                  kind TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS gateway_run_artifacts (
                  observation_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  managed_path TEXT NOT NULL,
                  media_type TEXT NOT NULL,
                  caption TEXT NOT NULL,
                  byte_count INTEGER NOT NULL,
                  sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  artifact_kind TEXT NOT NULL DEFAULT 'visual_observation',
                  chart_type TEXT,
                  title TEXT,
                  width INTEGER,
                  height INTEGER,
                  candidate_id TEXT,
                  review_id TEXT,
                  chart_spec_digest TEXT,
                  candidate_status TEXT,
                  review_status TEXT,
                  publication_status TEXT,
                  review_mode TEXT,
                  review_json TEXT,
                  figure_metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_runs_session
                  ON gateway_runs(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_gateway_events_run
                  ON gateway_run_events(run_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_gateway_artifacts_run
                  ON gateway_run_artifacts(run_id, observation_id);
                CREATE INDEX IF NOT EXISTS idx_gateway_idempotency_run
                  ON gateway_run_idempotency(run_id);
                CREATE INDEX IF NOT EXISTS idx_gateway_checkpoints_run
                  ON gateway_run_checkpoints(run_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_gateway_checkpoints_expiry
                  ON gateway_run_checkpoints(expires_at);
                CREATE INDEX IF NOT EXISTS idx_gateway_operations_run
                  ON gateway_run_operations(run_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_gateway_operations_expiry
                  ON gateway_run_operations(expires_at);
                """
            )
            # Older development databases may contain partially-created
            # Gateway tables. Add nullable columns without changing memory
            # records so those databases remain readable.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(gateway_runs)")}
            for name, declaration in (
                ("terminal_code", "TEXT"),
                ("terminal_message", "TEXT"),
                ("answer_source", "TEXT"),
                ("history_warning", "TEXT"),
                ("provider", "TEXT"),
                ("model", "TEXT"),
                ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
                ("retry_of", "TEXT"),
                ("parent_run_id", "TEXT"),
                ("root_run_id", "TEXT"),
                ("continuation_kind", "TEXT"),
                ("recovery_status", "TEXT NOT NULL DEFAULT 'unavailable'"),
                ("checkpoint_id", "TEXT"),
                ("recovery_phase", "TEXT"),
                ("recovery_next_action", "TEXT"),
                ("recovery_reason", "TEXT"),
                ("recovery_version", "INTEGER"),
                ("recovery_updated_at", "TEXT"),
                ("artifact_kind", "TEXT NOT NULL DEFAULT 'visual_observation'"),
                ("chart_type", "TEXT"),
                ("title", "TEXT"),
                ("width", "INTEGER"),
                ("height", "INTEGER"),
                ("candidate_id", "TEXT"),
                ("review_id", "TEXT"),
                ("chart_spec_digest", "TEXT"),
                ("candidate_status", "TEXT"),
                ("review_status", "TEXT"),
                ("publication_status", "TEXT"),
                ("review_mode", "TEXT"),
                ("review_json", "TEXT"),
                ("figure_metadata_json", "TEXT"),
            ):
                table = "gateway_runs" if name in {
                    "terminal_code",
                    "terminal_message",
                    "answer_source",
                    "history_warning",
                    "provider",
                    "model",
                    "cancel_requested",
                    "retry_of",
                    "parent_run_id",
                    "root_run_id",
                    "continuation_kind",
                    "recovery_status",
                    "checkpoint_id",
                    "recovery_phase",
                    "recovery_next_action",
                    "recovery_reason",
                    "recovery_version",
                    "recovery_updated_at",
                } else "gateway_run_artifacts"
                table_columns = columns if table == "gateway_runs" else {
                    row["name"] for row in connection.execute("PRAGMA table_info(gateway_run_artifacts)")
                }
                if name not in table_columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            idem_columns = {row["name"] for row in connection.execute("PRAGMA table_info(gateway_run_idempotency)")}
            for name, declaration in (
                ("operation_kind", "TEXT"),
                ("parent_run_id", "TEXT"),
                ("checkpoint_id", "TEXT"),
            ):
                if name not in idem_columns:
                    connection.execute(f"ALTER TABLE gateway_run_idempotency ADD COLUMN {name} {declaration}")

    @staticmethod
    def _restrict_permissions(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except OSError:
            pass

    def _cleanup_connection(self, connection) -> list[Path]:
        """Remove expired rows using the caller's transaction connection."""
        now = time.time()
        artifact_paths: list[Path] = []
        connection.execute(
            "DELETE FROM gateway_run_idempotency WHERE expires_at <= ?",
            (now,),
        )
        connection.execute(
            """UPDATE gateway_runs SET recovery_status = 'unavailable',
                      recovery_reason = 'checkpoint_expired', recovery_updated_at = ?
                WHERE checkpoint_id IN (SELECT checkpoint_id FROM gateway_run_checkpoints WHERE expires_at <= ?)""",
            (utc_timestamp(), now),
        )
        connection.execute(
            "DELETE FROM gateway_run_checkpoints WHERE expires_at <= ?",
            (now,),
        )
        connection.execute(
            "DELETE FROM gateway_run_operations WHERE expires_at <= ?",
            (now,),
        )
        expired_artifacts = connection.execute(
            "SELECT managed_path FROM gateway_run_artifacts WHERE expires_at <= ?", (now,)
        ).fetchall()
        artifact_paths.extend(Path(row["managed_path"]) for row in expired_artifacts if row["managed_path"])
        connection.execute(
            """UPDATE gateway_run_artifacts SET managed_path = '', candidate_status = 'expired',
               review_status = 'timed_out', publication_status = 'rejected', expires_at = ?
               WHERE expires_at <= ? AND artifact_kind = 'generated_candidate' AND managed_path != ''""",
            (now + self.retention_seconds, now),
        )
        connection.execute(
            """DELETE FROM gateway_run_artifacts
               WHERE expires_at <= ? AND (artifact_kind != 'generated_candidate' OR managed_path = '')""",
            (now,),
        )
        expired_runs = connection.execute(
            "SELECT run_id FROM gateway_runs WHERE expires_at <= ? AND status != ?",
            (now, RunStatus.RUNNING.value),
        ).fetchall()
        for run in expired_runs:
            paths = connection.execute(
                "SELECT managed_path FROM gateway_run_artifacts WHERE run_id = ?", (run["run_id"],)
            ).fetchall()
            artifact_paths.extend(Path(row["managed_path"]) for row in paths if row["managed_path"])
        connection.executemany(
            "DELETE FROM gateway_runs WHERE run_id = ?",
            [(row["run_id"],) for row in expired_runs],
        )
        return artifact_paths

    def _safe_artifact_path(self, raw_path: str, session_id: str) -> Path | None:
        try:
            root = self.artifact_root.resolve()
            path = Path(raw_path).resolve()
            session_root = (root / session_id).resolve()
            path.relative_to(session_root)
            return path
        except (OSError, ValueError):
            return None

    def create_run(
        self,
        run_id: str,
        session_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
        retry_of: str | None = None,
        parent_run_id: str | None = None,
        root_run_id: str | None = None,
        continuation_kind: ContinuationKind | str | None = None,
        idempotency_operation_kind: str | None = None,
        idempotency_parent_run_id: str | None = None,
        idempotency_checkpoint_id: str | None = None,
    ) -> None:
        now = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            count = connection.execute(
                "SELECT COUNT(*) FROM gateway_runs WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            if int(count) >= self.max_runs:
                raise HistoryStoreError("Gateway run history limit exceeded")
            connection.execute(
                """INSERT INTO gateway_runs(
                   run_id, session_id, status, created_at, updated_at, expires_at,
                   provider, model, retry_of, parent_run_id, root_run_id, continuation_kind
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    session_id,
                    RunStatus.RUNNING.value,
                    now,
                    now,
                    expires_at,
                    provider,
                    model,
                    retry_of,
                    parent_run_id,
                    root_run_id or run_id,
                    ContinuationKind(continuation_kind).value if continuation_kind is not None else None,
                ),
            )
            if idempotency_key is not None:
                if request_fingerprint is None:
                    raise HistoryStoreError("Idempotency fingerprint is required")
                connection.execute(
                    """INSERT INTO gateway_run_idempotency(
                       idempotency_key, session_id, run_id, request_fingerprint,
                       created_at, expires_at, operation_kind, parent_run_id, checkpoint_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        idempotency_key[:MAX_IDEMPOTENCY_KEY],
                        session_id,
                        run_id,
                        request_fingerprint[:128],
                        now,
                        expires_at,
                        idempotency_operation_kind,
                        idempotency_parent_run_id,
                        idempotency_checkpoint_id,
                    ),
                )

    def get_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return the durable run binding for one non-expired request key."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT idempotency_key, session_id, run_id, request_fingerprint,
                          created_at, expires_at
                     FROM gateway_run_idempotency
                    WHERE idempotency_key = ?""",
                (idempotency_key[:MAX_IDEMPOTENCY_KEY],),
            ).fetchone()
        if row is None:
            return None
        return {
            "idempotencyKey": row["idempotency_key"],
            "sessionId": row["session_id"],
            "runId": row["run_id"],
            "requestFingerprint": row["request_fingerprint"],
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
        }

    def create_checkpoint(
        self,
        session_id: str,
        run_id: str,
        state: Mapping[str, Any],
        *,
        phase: CheckpointPhase | str,
        next_action: str,
        status: RecoveryStatus | str = RecoveryStatus.AVAILABLE,
        blocked_reason: str | None = None,
        sequence: int = 0,
        version: int = CHECKPOINT_SCHEMA_VERSION,
    ) -> RecoveryCheckpoint:
        """Commit a versioned checkpoint and its public run projection atomically."""
        try:
            normalized_status = RecoveryStatus(status)
            encoded, digest = serialize_checkpoint(
                state,
                phase=phase,
                next_action=next_action,
                version=version,
            )
            normalized_phase = CheckpointPhase(phase).value
        except (CheckpointError, TypeError, ValueError) as exc:
            raise HistoryStoreError(str(exc)) from exc
        checkpoint_id = f"chk_{uuid4().hex}"
        now = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        reason = truncate_text(blocked_reason, 240) if blocked_reason else None
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            run = connection.execute(
                "SELECT 1 FROM gateway_runs WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
            if run is None:
                raise HistoryStoreError("Gateway run is not registered")
            connection.execute(
                """INSERT INTO gateway_run_checkpoints(
                   checkpoint_id, run_id, version, phase, next_action, state_json,
                   digest, recovery_status, blocked_reason, created_at, expires_at, sequence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint_id, run_id, int(version), normalized_phase,
                    truncate_text(next_action, 120), encoded, digest,
                    normalized_status.value, reason, now, expires_at, max(0, int(sequence)),
                ),
            )
            connection.execute(
                """UPDATE gateway_runs SET checkpoint_id = ?, recovery_status = ?,
                   recovery_phase = ?, recovery_next_action = ?, recovery_reason = ?,
                   recovery_version = ?, recovery_updated_at = ?, updated_at = ?
                   WHERE run_id = ? AND session_id = ?""",
                (
                    checkpoint_id, normalized_status.value, normalized_phase,
                    truncate_text(next_action, 120), reason, int(version), now, now,
                    run_id, session_id,
                ),
            )
        return RecoveryCheckpoint(
            checkpoint_id, run_id, int(version), normalized_phase,
            truncate_text(next_action, 120), json.loads(encoded)["state"], digest,
            normalized_status, reason, now, expires_at, max(0, int(sequence)),
        )

    def get_checkpoint(
        self,
        session_id: str,
        run_id: str,
        checkpoint_id: str | None = None,
        *,
        validate: bool = True,
    ) -> RecoveryCheckpoint | None:
        """Load the latest authorized checkpoint, optionally validating its digest/version."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            query = """SELECT c.* FROM gateway_run_checkpoints c
                       JOIN gateway_runs r ON r.run_id = c.run_id
                       WHERE c.run_id = ? AND r.session_id = ?"""
            params: list[Any] = [run_id, session_id]
            if checkpoint_id:
                query += " AND c.checkpoint_id = ?"
                params.append(checkpoint_id)
            query += " ORDER BY c.created_at DESC LIMIT 1"
            row = connection.execute(query, params).fetchone()
        if row is None or float(row["expires_at"]) <= time.time():
            return None
        try:
            parsed = deserialize_checkpoint(row["state_json"], row["digest"], version=CHECKPOINT_SCHEMA_VERSION) if validate else json.loads(row["state_json"])
            if validate and int(row["version"]) != CHECKPOINT_SCHEMA_VERSION:
                raise CheckpointError("unsupported checkpoint version")
            state = parsed.get("state", {})
        except (CheckpointError, TypeError, ValueError, json.JSONDecodeError):
            if validate:
                self.mark_recovery(
                    session_id, run_id, RecoveryStatus.BLOCKED,
                    reason="unsupported_or_invalid_checkpoint",
                )
                return None
            state = {}
        return RecoveryCheckpoint(
            row["checkpoint_id"], row["run_id"], int(row["version"]), row["phase"],
            row["next_action"], state, row["digest"], RecoveryStatus(row["recovery_status"]),
            row["blocked_reason"], row["created_at"], float(row["expires_at"]), int(row["sequence"]),
        )

    def mark_recovery(
        self,
        session_id: str,
        run_id: str,
        status: RecoveryStatus | str,
        *,
        reason: str | None = None,
    ) -> bool:
        normalized = RecoveryStatus(status)
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            now = utc_timestamp()
            cursor = connection.execute(
                """UPDATE gateway_runs SET recovery_status = ?, recovery_reason = ?,
                   recovery_updated_at = ?, updated_at = ?
                   WHERE run_id = ? AND session_id = ?""",
                (normalized.value, truncate_text(reason, 240) if reason else None, now, now, run_id, session_id),
            )
            if cursor.rowcount:
                connection.execute(
                    """UPDATE gateway_run_checkpoints SET recovery_status = ?, blocked_reason = ?
                       WHERE checkpoint_id = (SELECT checkpoint_id FROM gateway_runs WHERE run_id = ?)""",
                    (normalized.value, truncate_text(reason, 240) if reason else None, run_id),
                )
            return cursor.rowcount > 0

    def get_recovery(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        """Return a safe recovery projection for an authorized run."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT recovery_status, checkpoint_id, recovery_version, recovery_phase,
                          recovery_next_action, recovery_reason, recovery_updated_at,
                          (SELECT expires_at FROM gateway_run_checkpoints c
                            WHERE c.checkpoint_id = r.checkpoint_id) AS checkpoint_expires_at
                     FROM gateway_runs r WHERE run_id = ? AND session_id = ?""",
                (run_id, session_id),
            ).fetchone()
        if row is None:
            return None
        status = row["recovery_status"] or RecoveryStatus.UNAVAILABLE.value
        if status == RecoveryStatus.AVAILABLE.value and row["checkpoint_id"] is None:
            status = RecoveryStatus.UNAVAILABLE.value
        result: dict[str, Any] = {"status": status}
        if row["checkpoint_id"]:
            result["checkpointId"] = row["checkpoint_id"]
        if row["recovery_version"] is not None:
            result["checkpointVersion"] = int(row["recovery_version"])
        if row["recovery_phase"]:
            result["phase"] = row["recovery_phase"]
        if row["recovery_next_action"]:
            result["nextAction"] = row["recovery_next_action"]
        if row["recovery_reason"]:
            result["blockedReason"] = row["recovery_reason"]
        if row["recovery_updated_at"]:
            result["updatedAt"] = row["recovery_updated_at"]
        if row["checkpoint_expires_at"] is not None:
            result["expiresAt"] = float(row["checkpoint_expires_at"])
        return result

    def begin_operation(
        self,
        run_id: str,
        operation_id: str,
        operation_kind: str,
        *,
        request_fingerprint: str | None = None,
        state: OperationState | str = OperationState.IN_FLIGHT,
    ) -> dict[str, Any]:
        """Create or return a durable operation boundary."""
        now = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        normalized_state = OperationState(state)
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            existing = connection.execute(
                "SELECT * FROM gateway_run_operations WHERE run_id = ? AND operation_id = ?",
                (run_id, operation_id[:160]),
            ).fetchone()
            if existing is not None:
                return self._operation_summary(existing)
            connection.execute(
                """INSERT INTO gateway_run_operations(
                   run_id, operation_id, operation_kind, state, request_fingerprint,
                   created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, operation_id[:160], truncate_text(operation_kind, 64),
                    normalized_state.value,
                    truncate_text(request_fingerprint, 128) if request_fingerprint else None,
                    now, now, expires_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM gateway_run_operations WHERE run_id = ? AND operation_id = ?",
                (run_id, operation_id[:160]),
            ).fetchone()
        return self._operation_summary(row)

    def complete_operation(
        self,
        run_id: str,
        operation_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        references: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._set_operation_state(run_id, operation_id, OperationState.COMPLETED, result=result, references=references)

    def uncertain_operation(self, run_id: str, operation_id: str, *, reason: str | None = None) -> dict[str, Any] | None:
        return self._set_operation_state(
            run_id, operation_id, OperationState.UNCERTAIN,
            result={"reason": truncate_text(reason, 240) if reason else "operation_outcome_uncertain"},
        )

    def _set_operation_state(
        self,
        run_id: str,
        operation_id: str,
        state: OperationState,
        *,
        result: Mapping[str, Any] | None = None,
        references: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_timestamp()
        result_json = bounded_operation_result(result)
        reference_json = bounded_operation_result(references)
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            connection.execute(
                """UPDATE gateway_run_operations SET state = ?, result_json = COALESCE(?, result_json),
                   reference_json = COALESCE(?, reference_json), updated_at = ?
                   WHERE run_id = ? AND operation_id = ?""",
                (state.value, result_json, reference_json, now, run_id, operation_id[:160]),
            )
            row = connection.execute(
                "SELECT * FROM gateway_run_operations WHERE run_id = ? AND operation_id = ?",
                (run_id, operation_id[:160]),
            ).fetchone()
        return self._operation_summary(row) if row is not None else None

    def get_operation(self, run_id: str, operation_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT * FROM gateway_run_operations WHERE run_id = ? AND operation_id = ?",
                (run_id, operation_id[:160]),
            ).fetchone()
        return self._operation_summary(row) if row is not None else None

    def list_operations(self, run_id: str) -> list[dict[str, Any]]:
        """Return bounded operation projections for recovery validation."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            rows = connection.execute(
                "SELECT * FROM gateway_run_operations WHERE run_id = ? ORDER BY created_at, operation_id LIMIT 128",
                (run_id,),
            ).fetchall()
        return [self._operation_summary(row) for row in rows]

    @staticmethod
    def _operation_summary(row) -> dict[str, Any]:
        result: dict[str, Any] = {
            "runId": row["run_id"],
            "operationId": row["operation_id"],
            "operationKind": row["operation_kind"],
            "state": row["state"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "expiresAt": row["expires_at"],
        }
        if row["request_fingerprint"]:
            result["requestFingerprint"] = row["request_fingerprint"]
        for key, column in (("result", "result_json"), ("references", "reference_json")):
            if row[column]:
                try:
                    result[key] = json.loads(row[column])
                except json.JSONDecodeError:
                    result[key] = {"truncated": True}
        return result

    def bind_resume_idempotency(
        self,
        idempotency_key: str,
        session_id: str,
        parent_run_id: str,
        checkpoint_id: str,
        request_fingerprint: str,
        child_run_id: str,
    ) -> dict[str, Any]:
        """Atomically bind a resume intent before worker submission."""
        now = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        key = idempotency_key[:MAX_IDEMPOTENCY_KEY]
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            existing = connection.execute(
                "SELECT * FROM gateway_run_idempotency WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                return {
                    "idempotencyKey": key,
                    "sessionId": existing["session_id"],
                    "runId": existing["run_id"],
                    "requestFingerprint": existing["request_fingerprint"],
                    "parentRunId": existing["parent_run_id"] if "parent_run_id" in existing.keys() else None,
                    "checkpointId": existing["checkpoint_id"] if "checkpoint_id" in existing.keys() else None,
                    "existing": True,
                }
            connection.execute(
                """INSERT INTO gateway_run_idempotency(
                   idempotency_key, session_id, run_id, request_fingerprint,
                   created_at, expires_at, operation_kind, parent_run_id, checkpoint_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'resume', ?, ?)""",
                (key, session_id, child_run_id, request_fingerprint[:128], now, expires_at, parent_run_id, checkpoint_id),
            )
        return {
            "idempotencyKey": key,
            "sessionId": session_id,
            "runId": child_run_id,
            "requestFingerprint": request_fingerprint[:128],
            "parentRunId": parent_run_id,
            "checkpointId": checkpoint_id,
            "existing": False,
        }

    def append_event(self, event: RunEvent) -> None:
        payload = dict(event.payload)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_EVENT_PAYLOAD:
            if event.kind == "tool_result":
                payload = _truncate_tool_result_payload(payload)
                encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) > MAX_EVENT_PAYLOAD:
                payload = {"truncated": True, "preview": truncate_text(encoded, MAX_EVENT_PAYLOAD // 2)}
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT status FROM gateway_runs WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
            if row is None:
                raise HistoryStoreError("Gateway run is not registered")
            if row["status"] != RunStatus.RUNNING.value and event.kind != "run_interrupted":
                return
            existing = connection.execute(
                "SELECT 1 FROM gateway_run_events WHERE run_id = ? AND sequence = ?",
                (event.run_id, event.sequence),
            ).fetchone()
            if existing is not None:
                return
            count = connection.execute(
                "SELECT COUNT(*) FROM gateway_run_events WHERE run_id = ?", (event.run_id,)
            ).fetchone()[0]
            if int(count) >= self.max_events:
                oldest = connection.execute(
                    "SELECT sequence FROM gateway_run_events WHERE run_id = ? ORDER BY sequence LIMIT ?",
                    (event.run_id, max(1, int(count) - self.max_events + 1)),
                ).fetchall()
                connection.executemany(
                    "DELETE FROM gateway_run_events WHERE run_id = ? AND sequence = ?",
                    [(event.run_id, row["sequence"]) for row in oldest],
                )
            connection.execute(
                "INSERT OR IGNORE INTO gateway_run_events(run_id, sequence, kind, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event.run_id, event.sequence, truncate_text(event.kind, MAX_EVENT_KIND), encoded, event.timestamp),
            )
            connection.execute(
                "UPDATE gateway_runs SET updated_at = ? WHERE run_id = ?",
                (event.timestamp, event.run_id),
            )

    def update_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        terminal_code: str | None = None,
        terminal_message: str | None = None,
        answer_source: str | None = None,
        history_warning: str | None = None,
        cancel_requested: bool | None = None,
        retry_of: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            assignments = [
                "status = ?",
                "updated_at = ?",
                "expires_at = ?",
                "terminal_code = ?",
                "terminal_message = ?",
                "answer_source = ?",
                "history_warning = ?",
            ]
            values: list[Any] = [
                status.value,
                utc_timestamp(),
                time.time() + self.retention_seconds,
                truncate_text(terminal_code, MAX_TERMINAL_CODE) if terminal_code else None,
                truncate_text(terminal_message, 240) if terminal_message else None,
                truncate_text(answer_source, 12000) if answer_source is not None else None,
                truncate_text(history_warning, 240) if history_warning else None,
            ]
            if cancel_requested is not None:
                assignments.append("cancel_requested = ?")
                values.append(1 if cancel_requested else 0)
            if retry_of is not None:
                assignments.append("retry_of = ?")
                values.append(truncate_text(retry_of, MAX_RUN_ID))
            values.append(run_id)
            connection.execute(
                f"""UPDATE gateway_runs SET {', '.join(assignments)}
                 WHERE run_id = ?""",
                values,
            )

    def request_interrupt(self, run_id: str) -> bool:
        """Record a cooperative cancellation request for an active run."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            cursor = connection.execute(
                """UPDATE gateway_runs SET cancel_requested = 1, updated_at = ?
                    WHERE run_id = ? AND status = ? AND cancel_requested = 0""",
                (utc_timestamp(), run_id, RunStatus.RUNNING.value),
            )
            return cursor.rowcount > 0

    def interrupt_running_runs(self) -> None:
        """Mark runs left active by a previous Gateway process as interrupted."""
        with self._lock, self._connect() as connection:
            now = utc_timestamp()
            rows = connection.execute(
                "SELECT run_id FROM gateway_runs WHERE status = ?",
                (RunStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                run_id = row["run_id"]
                sequence = int(connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM gateway_run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0])
                payload = json.dumps(
                    {
                        "status": RunStatus.INTERRUPTED.value,
                        "code": "gateway_restarted",
                        "reason": "gateway_restarted",
                        "message": "Gateway 重启，运行已中断",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO gateway_run_events(
                       run_id, sequence, kind, payload_json, created_at
                       ) VALUES (?, ?, 'run_interrupted', ?, ?)""",
                    (run_id, sequence, payload, now),
                )
                connection.execute(
                    """UPDATE gateway_runs
                       SET status = ?, updated_at = ?, terminal_code = ?, terminal_message = ?,
                           cancel_requested = 1
                     WHERE run_id = ? AND status = ?""",
                    (
                        RunStatus.INTERRUPTED.value,
                        now,
                        "gateway_restarted",
                        "Gateway 重启，运行已中断",
                        run_id,
                        RunStatus.RUNNING.value,
                    ),
                )

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            rows = connection.execute(
                """SELECT run_id, session_id, status, created_at, updated_at,
                          expires_at,
                          terminal_code, terminal_message, answer_source, history_warning, provider, model,
                          cancel_requested, retry_of, parent_run_id, root_run_id, continuation_kind,
                          recovery_status, checkpoint_id, recovery_phase, recovery_next_action,
                          recovery_reason, recovery_version, recovery_updated_at,
                          (SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count
                     FROM gateway_runs r WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
        return [self._run_summary(row) for row in rows]

    def get_run(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT run_id, session_id, status, created_at, updated_at, expires_at, terminal_code, terminal_message, answer_source, history_warning, provider, model, cancel_requested, retry_of, parent_run_id, root_run_id, continuation_kind, recovery_status, checkpoint_id, recovery_phase, recovery_next_action, recovery_reason, recovery_version, recovery_updated_at, (SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count FROM gateway_runs r WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
        return self._run_summary(row) if row else None

    @staticmethod
    def _run_summary(row) -> dict[str, Any]:
        return {
            "runId": row["run_id"],
            "sessionId": row["session_id"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "expiresAt": row["expires_at"],
            "eventCount": int(row["event_count"]),
            "terminalCode": row["terminal_code"],
            "terminalMessage": row["terminal_message"],
            "answer": row["answer_source"],
            "historyWarning": row["history_warning"],
            "provider": row["provider"],
            "model": row["model"],
            "cancelRequested": bool(row["cancel_requested"]),
            "retryOf": row["retry_of"],
            "parentRunId": row["parent_run_id"],
            "rootRunId": row["root_run_id"] or row["run_id"],
            "continuationKind": row["continuation_kind"] or (ContinuationKind.RETRY.value if row["retry_of"] else None),
            "recovery": {
                "status": row["recovery_status"] or RecoveryStatus.UNAVAILABLE.value,
                **({"checkpointId": row["checkpoint_id"]} if row["checkpoint_id"] else {}),
                **({"checkpointVersion": int(row["recovery_version"])} if row["recovery_version"] is not None else {}),
                **({"phase": row["recovery_phase"]} if row["recovery_phase"] else {}),
                **({"nextAction": row["recovery_next_action"]} if row["recovery_next_action"] else {}),
                **({"blockedReason": row["recovery_reason"]} if row["recovery_reason"] else {}),
                **({"updatedAt": row["recovery_updated_at"]} if row["recovery_updated_at"] else {}),
            },
        }

    def list_events(self, session_id: str, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            run = connection.execute(
                "SELECT 1 FROM gateway_runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
            ).fetchone()
            if run is None:
                return []
            rows = connection.execute(
                "SELECT run_id, sequence, kind, payload_json, created_at FROM gateway_run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, max(0, int(after_sequence))),
            ).fetchall()
        return [
            RunEvent(row["run_id"], int(row["sequence"]), row["kind"], json.loads(row["payload_json"]), row["created_at"])
            for row in rows
        ]

    def history(self, session_id: str, run_id: str, after_sequence: int = 0) -> dict[str, Any] | None:
        summary = self.get_run(session_id, run_id)
        if summary is None:
            return None
        events = self.list_events(session_id, run_id, after_sequence)
        with self._lock, self._connect() as connection:
            first = connection.execute(
                "SELECT MIN(sequence) FROM gateway_run_events WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
        first_sequence = int(first) if first is not None else None
        history_gap = first_sequence is not None and int(after_sequence) < first_sequence - 1
        return {
            "run": summary,
            "events": [event.to_dict() for event in events],
            "historyGap": history_gap,
            "historyGapCode": "history_gap" if history_gap else None,
            "firstSequence": first_sequence,
        }

    @staticmethod
    def _candidate_reference(row, *, artifact_id: str | None = None) -> dict[str, Any]:
        publication = row["publication_status"] or "unpublished"
        candidate_status = row["candidate_status"] or "candidate"
        visible_status = "available" if publication == "published" else (
            "warning" if publication == "published_with_warning" else (
                "failed" if candidate_status in {"review_failed", "timed_out", "retry_exhausted", "expired"} else "pending"
            )
        )
        review: Mapping[str, Any] | None = None
        try:
            parsed_review = json.loads(row["review_json"] or "{}")
            if isinstance(parsed_review, Mapping):
                review = parsed_review
        except (TypeError, json.JSONDecodeError):
            review = None
        review_mode = row["review_mode"] or (review or {}).get("reviewMode")
        figure_metadata: Mapping[str, Any] = {}
        if "figure_metadata_json" in row.keys():
            try:
                parsed_figure = json.loads(row["figure_metadata_json"] or "{}")
                if isinstance(parsed_figure, Mapping):
                    figure_metadata = parsed_figure
            except (TypeError, json.JSONDecodeError):
                figure_metadata = {}
        reference = GeneratedChartReference(
            artifact_id=artifact_id,
            media_type=row["media_type"],
            caption=row["caption"],
            byte_count=int(row["byte_count"]),
            chart_type=row["chart_type"] or "",
            title=row["title"] or row["caption"],
            width=int(row["width"] or 0),
            height=int(row["height"] or 0),
            status=visible_status,
            reason=("图表仍在审核中" if visible_status == "pending" else "审核未通过" if visible_status == "failed" else None),
            candidate_id=row["candidate_id"],
            review_id=row["review_id"],
            chart_spec_digest=row["chart_spec_digest"],
            candidate_status=row["candidate_status"],
            review_status=row["review_status"],
            publication_status=publication,
            review_mode=review_mode,
            review=review,
            figure_id=figure_metadata.get("figure_id"),
            collection_id=figure_metadata.get("collection_id"),
            child_chart_ids=tuple(item for item in figure_metadata.get("child_chart_ids", []) if isinstance(item, str)),
            source=figure_metadata.get("source") if isinstance(figure_metadata.get("source"), Mapping) else None,
            layout=figure_metadata.get("layout") if isinstance(figure_metadata.get("layout"), Mapping) else None,
            coverage=figure_metadata.get("coverage") if isinstance(figure_metadata.get("coverage"), Mapping) else None,
            chart_types=tuple(item for item in figure_metadata.get("chart_types", []) if isinstance(item, str)),
        )
        return reference.to_dict()

    def add_candidate(self, run_id: str, session_id: str, image: Any) -> dict[str, Any] | None:
        """Persist a generated candidate without exposing it as a final artifact."""
        content = getattr(image, "content", None)
        media_type = str(getattr(image, "media_type", "")).lower()
        caption = getattr(image, "caption", "")
        metadata = getattr(image, "metadata", {})
        if not isinstance(metadata, Mapping):
            return None
        candidate_id = metadata.get("candidateId")
        review_id = metadata.get("reviewId")
        digest = metadata.get("chartSpecDigest")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id.startswith("cand_")
            or "/" in candidate_id
            or not isinstance(review_id, str)
            or not review_id.startswith("review_")
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(content, bytes)
            or not content
            or len(content) > self.max_artifact_bytes
            or media_type not in _SUPPORTED_ARTIFACT_TYPES
            or not isinstance(caption, str)
            or not caption.strip()
        ):
            return None
        chart_type = str(metadata.get("chartType") or metadata.get("chart_type") or "")[:MAX_ARTIFACT_CHART_TYPE]
        title = str(metadata.get("title") or caption)[:MAX_ARTIFACT_TITLE]
        try:
            width = int(metadata.get("width", 0))
            height = int(metadata.get("height", 0))
        except (TypeError, ValueError):
            return None
        if not chart_type or not title or width <= 0 or height <= 0:
            return None
        figure_metadata = {
            "figure_id": metadata.get("figureId") or metadata.get("figure_id"),
            "collection_id": metadata.get("collectionId") or metadata.get("collection_id"),
            "child_chart_ids": metadata.get("childChartIds") or metadata.get("child_chart_ids") or [],
            "source": metadata.get("source") if isinstance(metadata.get("source"), Mapping) else None,
            "layout": metadata.get("layout") if isinstance(metadata.get("layout"), Mapping) else None,
            "coverage": metadata.get("coverage") if isinstance(metadata.get("coverage"), Mapping) else None,
            "chart_types": metadata.get("chartTypes") or metadata.get("chart_types") or [],
        }
        figure_metadata = {
            key: value
            for key, value in figure_metadata.items()
            if value not in (None, "", [])
        }
        candidate_root = self.artifact_root / session_id
        candidate_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._restrict_permissions(candidate_root, 0o700)
        path = candidate_root / f"{candidate_id}.bin"
        created = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            existing = connection.execute(
                """SELECT * FROM gateway_run_artifacts
                   WHERE run_id = ? AND session_id = ?
                     AND (observation_id = ? OR candidate_id = ?)
                   ORDER BY CASE WHEN artifact_kind = 'generated_chart' THEN 0 ELSE 1 END
                   LIMIT 1""",
                (run_id, session_id, candidate_id, candidate_id),
            ).fetchone()
            if existing is not None:
                if existing["artifact_kind"] == "generated_chart":
                    return self._candidate_reference(existing, artifact_id=existing["observation_id"])
                if existing["candidate_status"] in {"expired", "timed_out", "retry_exhausted", "review_failed"}:
                    return self._candidate_reference(existing)
                if (
                    existing["review_id"] == review_id
                    and existing["chart_spec_digest"] == digest
                    and str(metadata.get("reviewStatus", "pending")) == "completed"
                ):
                    connection.execute(
                        """UPDATE gateway_run_artifacts SET candidate_status = ?, review_status = ?,
                           publication_status = ?, review_mode = ?, review_json = ?, expires_at = ?
                           WHERE observation_id = ? AND artifact_kind = 'generated_candidate'""",
                        (
                            str(metadata.get("candidateStatus", "review_pending")),
                            "completed",
                            str(metadata.get("publicationStatus", "unpublished")),
                            str(metadata.get("reviewMode", "safety")),
                            json.dumps(metadata.get("review", {}), ensure_ascii=False)[:MAX_EVENT_PAYLOAD],
                            time.time() + self.retention_seconds,
                            candidate_id,
                        ),
                    )
                    existing = connection.execute(
                        "SELECT * FROM gateway_run_artifacts WHERE observation_id = ?", (candidate_id,)
                    ).fetchone()
                return self._candidate_reference(existing)
            run = connection.execute(
                "SELECT 1 FROM gateway_runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
            ).fetchone()
            if run is None:
                return None
            count = connection.execute(
                "SELECT COUNT(*) FROM gateway_run_artifacts WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            if int(count) >= self.max_artifacts:
                return None
            candidate_status = str(metadata.get("candidateStatus", "review_pending"))
            # Failed candidates remain previewable for diagnosis and repair. They
            # are still never promoted unless the publication gate later sees a
            # verified/warning candidate with a matching review context.
            managed_path = str(path) if candidate_status != "expired" else ""
            try:
                if managed_path:
                    path.write_bytes(content)
                    self._restrict_permissions(path, 0o600)
                connection.execute(
                    """INSERT INTO gateway_run_artifacts(
                       observation_id, run_id, session_id, managed_path, media_type,
                       caption, byte_count, sha256, created_at, expires_at,
                       artifact_kind, chart_type, title, width, height,
                       candidate_id, review_id, chart_spec_digest, candidate_status,
                       review_status, publication_status, review_mode, review_json, figure_metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated_candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        candidate_id, run_id, session_id, managed_path, media_type,
                        truncate_text(caption, MAX_ARTIFACT_CAPTION), len(content),
                        hashlib.sha256(content).hexdigest(), created, expires_at,
                        chart_type, title, width, height, candidate_id, review_id,
                        digest, candidate_status,
                        str(metadata.get("reviewStatus", "pending")),
                        str(metadata.get("publicationStatus", "unpublished")),
                        str(metadata.get("reviewMode", "safety")),
                        json.dumps(metadata.get("review", {}), ensure_ascii=False)[:MAX_EVENT_PAYLOAD],
                        json.dumps(figure_metadata, ensure_ascii=False)[:MAX_EVENT_PAYLOAD],
                    ),
                )
            except Exception:
                path.unlink(missing_ok=True)
                raise
            row = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE observation_id = ?", (candidate_id,)
            ).fetchone()
        return self._candidate_reference(row) if row is not None else None

    def promote_candidate(
        self,
        run_id: str,
        session_id: str,
        candidate_id: str,
        review_id: str,
        chart_spec_digest: str,
        *,
        candidate_status: str,
        review_status: str,
        publication_status: str,
        review: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically convert one matching reviewed candidate into an artifact."""
        if publication_status not in {"published", "published_with_warning"} or review_status != "completed":
            return None
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE observation_id = ? AND run_id = ? AND session_id = ?",
                (candidate_id, run_id, session_id),
            ).fetchone()
            if row is None:
                # Idempotent replay after the observation ID was promoted.
                row = connection.execute(
                    "SELECT * FROM gateway_run_artifacts WHERE candidate_id = ? AND run_id = ? AND session_id = ? AND artifact_kind = 'generated_chart'",
                    (candidate_id, run_id, session_id),
                ).fetchone()
                if row is None:
                    return None
                return self._candidate_reference(row, artifact_id=row["observation_id"])
            if row["artifact_kind"] != "generated_candidate":
                return None
            if row["review_id"] != review_id or row["chart_spec_digest"] != chart_spec_digest:
                return None
            if row["candidate_status"] not in {"verified", "warning"}:
                return None
            artifact_id = f"artifact_{uuid4().hex}"
            reason = "审核通过并发布" if publication_status == "published" else "审核通过，但包含明确警告"
            connection.execute(
                """UPDATE gateway_run_artifacts SET observation_id = ?, artifact_kind = 'generated_chart',
                   candidate_status = ?, review_status = ?, publication_status = ?, review_json = ?
                   WHERE observation_id = ? AND artifact_kind = 'generated_candidate'""",
                (
                    artifact_id, candidate_status, review_status, publication_status,
                    json.dumps(review or {}, ensure_ascii=False)[:MAX_EVENT_PAYLOAD], candidate_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE observation_id = ?", (artifact_id,)
            ).fetchone()
        if updated is None:
            return None
        result = self._candidate_reference(updated, artifact_id=artifact_id)
        result["reason"] = reason
        result["status"] = "warning" if publication_status == "published_with_warning" else "available"
        return result

    def get_candidate(self, session_id: str, run_id: str, candidate_id: str) -> tuple[bytes, str] | None:
        return self.get_artifact(session_id, run_id, candidate_id, artifact_kind="generated_candidate")

    def get_chart_preview(self, session_id: str, run_id: str, reference_id: str) -> tuple[bytes, str] | None:
        """Read the current bytes for an artifact or candidate reference.

        A candidate reference remains stable for the client-facing preview
        route even after promotion, when its row becomes a generated artifact.
        """
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT observation_id, artifact_kind FROM gateway_run_artifacts
                   WHERE run_id = ? AND session_id = ?
                     AND (observation_id = ? OR candidate_id = ?)
                     AND artifact_kind IN ('generated_chart', 'generated_candidate')
                   ORDER BY CASE WHEN artifact_kind = 'generated_chart' THEN 0 ELSE 1 END
                   LIMIT 1""",
                (run_id, session_id, reference_id, reference_id),
            ).fetchone()
        if row is None:
            return None
        return self.get_artifact(
            session_id,
            run_id,
            row["observation_id"],
            artifact_kind=row["artifact_kind"],
        )

    def add_artifact(self, run_id: str, session_id: str, image: Any) -> dict[str, Any] | None:
        content = getattr(image, "content", None)
        media_type = str(getattr(image, "media_type", "")).lower()
        caption = getattr(image, "caption", "")
        if not isinstance(content, bytes) or not content or len(content) > self.max_artifact_bytes:
            return None
        if media_type not in _SUPPORTED_ARTIFACT_TYPES or not isinstance(caption, str) or not caption.strip():
            return None
        metadata = getattr(image, "metadata", {})
        generated = isinstance(metadata, Mapping) and metadata.get("kind") == "generated_chart"
        artifact_kind = "generated_chart" if generated else "visual_observation"
        observation_id = f"artifact_{uuid4().hex}" if generated else f"obs_{uuid4().hex}"
        chart_type = str(metadata.get("chart_type", ""))[:MAX_ARTIFACT_CHART_TYPE] if generated else None
        title = str(metadata.get("title", caption))[:MAX_ARTIFACT_TITLE] if generated else None
        try:
            width = int(metadata.get("width", 0)) if generated else None
            height = int(metadata.get("height", 0)) if generated else None
        except (TypeError, ValueError):
            return None
        if generated and (not chart_type or not title or not width or not height):
            return None
        figure_metadata = {
            "figure_id": metadata.get("figureId") or metadata.get("figure_id"),
            "collection_id": metadata.get("collectionId") or metadata.get("collection_id"),
            "child_chart_ids": metadata.get("childChartIds") or metadata.get("child_chart_ids") or [],
            "source": metadata.get("source") if isinstance(metadata.get("source"), Mapping) else None,
            "layout": metadata.get("layout") if isinstance(metadata.get("layout"), Mapping) else None,
            "coverage": metadata.get("coverage") if isinstance(metadata.get("coverage"), Mapping) else None,
            "chart_types": metadata.get("chartTypes") or metadata.get("chart_types") or [],
        }
        figure_metadata = {key: value for key, value in figure_metadata.items() if value not in (None, "", [])}
        session_root = self.artifact_root / session_id
        session_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._restrict_permissions(session_root, 0o700)
        path = session_root / f"{observation_id}.bin"
        try:
            path.write_bytes(content)
            self._restrict_permissions(path, 0o600)
        except OSError:
            path.unlink(missing_ok=True)
            return None
        created = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        if generated:
            reference = GeneratedChartReference(
                artifact_id=observation_id,
                media_type=media_type,
                caption=caption,
                byte_count=len(content),
                chart_type=chart_type,
                title=title,
                width=width,
                height=height,
                figure_id=figure_metadata.get("figure_id"),
                collection_id=figure_metadata.get("collection_id"),
                child_chart_ids=tuple(item for item in figure_metadata.get("child_chart_ids", []) if isinstance(item, str)),
                source=figure_metadata.get("source"),
                layout=figure_metadata.get("layout"),
                coverage=figure_metadata.get("coverage"),
                chart_types=tuple(item for item in figure_metadata.get("chart_types", []) if isinstance(item, str)),
            ).to_dict()
        else:
            reference = {
                "observationId": observation_id,
                "mediaType": media_type,
                "caption": truncate_text(caption, MAX_ARTIFACT_CAPTION),
                "byteCount": len(content),
            }
        try:
            with self._lock, self._connect() as connection:
                self._cleanup_connection(connection)
                run = connection.execute(
                    "SELECT 1 FROM gateway_runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
                ).fetchone()
                if run is None:
                    path.unlink(missing_ok=True)
                    return None
                count = connection.execute(
                    "SELECT COUNT(*) FROM gateway_run_artifacts WHERE run_id = ?", (run_id,)
                ).fetchone()[0]
                if int(count) >= self.max_artifacts:
                    path.unlink(missing_ok=True)
                    return None
                connection.execute(
                    "INSERT INTO gateway_run_artifacts(observation_id, run_id, session_id, managed_path, media_type, caption, byte_count, sha256, created_at, expires_at, artifact_kind, chart_type, title, width, height, figure_metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (observation_id, run_id, session_id, str(path), media_type, reference["caption"], len(content), hashlib.sha256(content).hexdigest(), created, expires_at, artifact_kind, chart_type, title, width, height, json.dumps(figure_metadata, ensure_ascii=False)[:MAX_EVENT_PAYLOAD]),
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return reference

    def get_artifact(
        self,
        session_id: str,
        run_id: str,
        observation_id: str,
        *,
        artifact_kind: str | None = None,
    ) -> tuple[bytes, str] | None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            query = "SELECT managed_path, media_type, expires_at FROM gateway_run_artifacts WHERE observation_id = ? AND run_id = ? AND session_id = ?"
            params: list[Any] = [observation_id, run_id, session_id]
            if artifact_kind is not None:
                query += " AND artifact_kind = ?"
                params.append(artifact_kind)
            row = connection.execute(query, params).fetchone()
            if row is None or float(row["expires_at"]) <= time.time():
                return None
            path = self._safe_artifact_path(row["managed_path"], session_id)
            if path is None or not path.is_file():
                return None
            try:
                content = path.read_bytes()
            except OSError:
                return None
            if len(content) > self.max_artifact_bytes:
                return None
            stored = connection.execute(
                "SELECT byte_count, sha256 FROM gateway_run_artifacts WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
            if stored is None or int(stored["byte_count"]) != len(content) or hashlib.sha256(content).hexdigest() != stored["sha256"]:
                return None
            return content, row["media_type"]

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT managed_path FROM gateway_run_artifacts WHERE session_id = ?", (session_id,)
            ).fetchall()
            connection.execute("DELETE FROM gateway_runs WHERE session_id = ?", (session_id,))
        for row in rows:
            path = self._safe_artifact_path(row["managed_path"], session_id)
            if path is not None:
                path.unlink(missing_ok=True)
        shutil.rmtree(self.artifact_root / session_id, ignore_errors=True)

    def cleanup(self) -> None:
        with self._lock, self._connect() as connection:
            paths = self._cleanup_connection(connection)
        for path in paths:
            safe = self._safe_artifact_path(str(path), path.parent.name)
            if safe is not None:
                safe.unlink(missing_ok=True)

    def close(self) -> None:
        with self._lock:
            self.cleanup()


__all__ = ["GatewayHistoryStore", "HistoryStoreError"]
