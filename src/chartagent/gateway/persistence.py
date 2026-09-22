"""Canonical durable persistence for the local Gateway."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..trace import sanitize_payload, truncate_text
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
    RecoveryStatus,
    RunEvent,
    RunStatus,
    _truncate_tool_result_payload,
    utc_timestamp,
)
from .operation_journal import OperationJournalMixin
from .persistence_connection import SQLiteGatewayDatabase
from .persistence_errors import HistoryStoreError
from .run_persistence import RunPersistenceMixin
from .recovery import (
    CheckpointError,
    RecoveryCheckpoint,
    deserialize_checkpoint,
    serialize_checkpoint,
)

DEFAULT_MAX_HISTORY_EVENTS = 512
DEFAULT_MAX_HISTORY_RUNS = 256
DEFAULT_HISTORY_RETENTION_SECONDS = 30 * 24 * 60 * 60.0
DEFAULT_MAX_HISTORY_ARTIFACT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_HISTORY_ARTIFACTS = 32
DEFAULT_RECOVERY_RETENTION_SECONDS = DEFAULT_HISTORY_RETENTION_SECONDS
MAX_EVENT_DETAIL_BYTES = 4 * 1024 * 1024
_SUPPORTED_ARTIFACT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class GatewayHistoryStore(RunPersistenceMixin, OperationJournalMixin):
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
        self._database = SQLiteGatewayDatabase(
            data_dir=data_dir,
            database=database,
            artifact_root=artifact_root,
        )
        self.database = self._database.database
        self.artifact_root = self._database.artifact_root
        self.max_events = max_events
        self.max_runs = max_runs
        self.retention_seconds = retention_seconds
        self.max_artifact_bytes = max_artifact_bytes
        self.max_artifacts = max_artifacts
        self._lock = RLock()
        self._initialize()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._restrict_permissions(self.artifact_root, 0o700)

    def _connect(self):
        """Compatibility hook for query methods; setup lives in the DB port."""

        return self._database.connect()

    def _initialize(self) -> None:
        with self._database.transaction() as connection:
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
                  recovery_updated_at TEXT,
                  execution_gate_json TEXT
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
                ("execution_gate_json", "TEXT"),
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
                    "execution_gate_json",
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



    def append_event(self, event: RunEvent) -> None:
        payload = dict(event.payload)
        detail_reference = self._persist_evaluation_event_detail(event)
        if detail_reference is not None:
            payload["detail_resource"] = detail_reference
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

    def _persist_evaluation_event_detail(self, event: RunEvent) -> dict[str, Any] | None:
        """Persist a safe large-event sidecar for managed evaluation bundles."""
        if not (self.artifact_root.parent / "evaluation.json").is_file():
            return None
        detail_payload = event.detail_payload
        if not isinstance(detail_payload, Mapping):
            return None
        encoded_payload = json.dumps(detail_payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded_payload.encode("utf-8")) <= MAX_EVENT_PAYLOAD:
            return None
        envelope = {
            "schemaVersion": 1,
            "runId": event.run_id,
            "sequence": event.sequence,
            "kind": event.kind,
            "payload": detail_payload,
        }
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        encoded_bytes = encoded.encode("utf-8")
        if len(encoded_bytes) > MAX_EVENT_DETAIL_BYTES:
            return None
        safe_run = re.sub(r"[^A-Za-z0-9_.-]", "_", event.run_id)[:128] or "run"
        relative = Path("history-details") / safe_run / f"{event.sequence}.json"
        destination = self.artifact_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(encoded_bytes)
            temporary.replace(destination)
            self._restrict_permissions(destination, 0o600)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return {
            "kind": "history_detail",
            "token": relative.relative_to("history-details").as_posix(),
            "mediaType": "application/json",
            "byteCount": len(encoded_bytes),
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
        generation_context = figure_metadata.get("generation_context")
        if not isinstance(generation_context, Mapping):
            generation_context = None
        coverage = figure_metadata.get("coverage")
        if not isinstance(coverage, Mapping) and generation_context is not None:
            context_coverage = generation_context.get("coverage")
            coverage = context_coverage if isinstance(context_coverage, Mapping) else None
        review_repair_kind = review.get("repairKind") if isinstance(review, Mapping) else None
        repair_kind = figure_metadata.get("repair_kind") or review_repair_kind
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
            coverage=coverage,
            chart_types=tuple(item for item in figure_metadata.get("chart_types", []) if isinstance(item, str)),
            generation_context=generation_context,
            generation_context_digest=figure_metadata.get("generation_context_digest"),
            context_status=figure_metadata.get("context_status"),
            candidate_attempt=figure_metadata.get("candidate_attempt"),
            review_attempts=figure_metadata.get("review_attempts"),
            lineage_attempt=figure_metadata.get("lineage_attempt"),
            parent_candidate_id=figure_metadata.get("parent_candidate_id"),
            parent_attempt=figure_metadata.get("parent_attempt"),
            panel_ids=tuple(item for item in figure_metadata.get("panel_ids", []) if isinstance(item, str)),
            source_attachment_ids=tuple(item for item in figure_metadata.get("source_attachment_ids", []) if isinstance(item, str)),
            repair_kind=repair_kind if isinstance(repair_kind, str) else None,
        )
        return reference.to_dict()

    @staticmethod
    def _chart_figure_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        """Project bounded candidate context into the durable artifact row."""
        raw_context = metadata.get("generationContext") or metadata.get("generation_context")
        generation_context = sanitize_payload(raw_context) if isinstance(raw_context, Mapping) else None
        raw_review = metadata.get("review")
        repair_kind = metadata.get("repairKind") or metadata.get("repair_kind")
        if not repair_kind and isinstance(raw_review, Mapping):
            repair_kind = raw_review.get("repairKind") or raw_review.get("repair_kind")
        figure_metadata: dict[str, Any] = {
            "figure_id": metadata.get("figureId") or metadata.get("figure_id"),
            "collection_id": metadata.get("collectionId") or metadata.get("collection_id"),
            "child_chart_ids": metadata.get("childChartIds") or metadata.get("child_chart_ids") or [],
            "source": metadata.get("source") if isinstance(metadata.get("source"), Mapping) else None,
            "layout": metadata.get("layout") if isinstance(metadata.get("layout"), Mapping) else None,
            "coverage": metadata.get("coverage") if isinstance(metadata.get("coverage"), Mapping) else None,
            "chart_types": metadata.get("chartTypes") or metadata.get("chart_types") or [],
            "generation_context": generation_context,
            "generation_context_digest": metadata.get("generationContextDigest") or metadata.get("context_digest"),
            "context_status": metadata.get("contextStatus") or metadata.get("context_status"),
            "candidate_attempt": metadata.get("candidateAttempt") or metadata.get("candidate_attempt"),
            "review_attempts": metadata.get("attempts") or metadata.get("review_attempts"),
            "lineage_attempt": metadata.get("lineageAttempt") or metadata.get("lineage_attempt"),
            "parent_candidate_id": metadata.get("parentCandidateId") or metadata.get("parent_candidate_id"),
            "parent_attempt": metadata.get("parentAttempt") or metadata.get("parent_attempt"),
            "panel_ids": metadata.get("panelIds") or metadata.get("panel_ids") or [],
            "source_attachment_ids": metadata.get("sourceAttachmentIds") or metadata.get("source_attachment_ids") or [],
            "repair_kind": repair_kind,
        }
        return {
            key: value
            for key, value in figure_metadata.items()
            if value not in (None, "", [], {})
        }

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
        figure_metadata = self._chart_figure_metadata(metadata)
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
        figure_metadata = self._chart_figure_metadata(metadata)
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
                coverage=figure_metadata.get("coverage") or (
                    figure_metadata.get("generation_context", {}).get("coverage")
                    if isinstance(figure_metadata.get("generation_context"), Mapping)
                    else None
                ),
                chart_types=tuple(item for item in figure_metadata.get("chart_types", []) if isinstance(item, str)),
                generation_context=figure_metadata.get("generation_context"),
                generation_context_digest=figure_metadata.get("generation_context_digest"),
                context_status=figure_metadata.get("context_status"),
                candidate_attempt=figure_metadata.get("candidate_attempt"),
                review_attempts=figure_metadata.get("review_attempts"),
                lineage_attempt=figure_metadata.get("lineage_attempt"),
                parent_candidate_id=figure_metadata.get("parent_candidate_id"),
                parent_attempt=figure_metadata.get("parent_attempt"),
                panel_ids=tuple(item for item in figure_metadata.get("panel_ids", []) if isinstance(item, str)),
                source_attachment_ids=tuple(item for item in figure_metadata.get("source_attachment_ids", []) if isinstance(item, str)),
                repair_kind=figure_metadata.get("repair_kind"),
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
