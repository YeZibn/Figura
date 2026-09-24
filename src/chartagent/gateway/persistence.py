"""Canonical durable persistence for the local Gateway."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..trace import sanitize_payload, truncate_text
from ..decision_timeline import validate_timeline_event
from .protocol import (
    ContinuationKind,
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
from .execution_persistence import ExecutionPersistenceMixin
from .execution_record import ExecutionCursor, ExecutionRecordError, execution_cursor_id
from .persistence_connection import SQLiteGatewayDatabase
from .persistence_errors import HistoryStoreError
from .run_persistence import RunPersistenceMixin
from ..verification.models import (
    ChartManifest,
    PublishedChart,
    VerificationError,
    VerificationResult,
    canonical_json,
    content_digest,
)

DEFAULT_MAX_HISTORY_EVENTS = 512
DEFAULT_MAX_HISTORY_RUNS = 256
DEFAULT_HISTORY_RETENTION_SECONDS = 30 * 24 * 60 * 60.0
DEFAULT_MAX_HISTORY_ARTIFACT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_HISTORY_ARTIFACTS = 32
DEFAULT_RECOVERY_RETENTION_SECONDS = DEFAULT_HISTORY_RETENTION_SECONDS
MAX_EVENT_DETAIL_BYTES = 4 * 1024 * 1024
_SUPPORTED_ARTIFACT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_PRIVATE_CHART_SPEC_BYTES = 2 * 1024 * 1024


class GatewayHistoryStore(RunPersistenceMixin, ExecutionPersistenceMixin):
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
        self._restrict_permissions(self.database, 0o600)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._restrict_permissions(self.artifact_root, 0o700)
        self.cleanup()

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
                  continuation_kind TEXT
                );
                CREATE TABLE IF NOT EXISTS gateway_run_idempotency (
                  idempotency_key TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  request_fingerprint TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  continuation_kind TEXT,
                  parent_run_id TEXT,
                  cursor_id TEXT
                );
                CREATE TABLE IF NOT EXISTS gateway_run_events (
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  sequence INTEGER NOT NULL,
                  kind TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS gateway_run_execution_entries (
                  run_id TEXT NOT NULL REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  sequence INTEGER NOT NULL CHECK(sequence > 0),
                  entry_id TEXT NOT NULL UNIQUE,
                  entry_kind TEXT NOT NULL CHECK(entry_kind IN (
                    'input', 'model_response', 'tool_result', 'verification_result',
                    'promotion_result', 'final_answer'
                  )),
                  work_key TEXT,
                  payload_json TEXT NOT NULL,
                  payload_sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (run_id, sequence),
                  UNIQUE (run_id, work_key)
                );
                CREATE TABLE IF NOT EXISTS gateway_run_execution_cursors (
                  run_id TEXT PRIMARY KEY REFERENCES gateway_runs(run_id) ON DELETE CASCADE,
                  version INTEGER NOT NULL,
                  entry_cursor INTEGER NOT NULL CHECK(entry_cursor >= 0),
                  turn INTEGER NOT NULL CHECK(turn >= 0),
                  next_action_json TEXT NOT NULL,
                  references_json TEXT NOT NULL,
                  cursor_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
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
                  figure_metadata_json TEXT,
                  chart_spec_json TEXT,
                  staged_ref TEXT,
                  work_key TEXT,
                  manifest_json TEXT,
                  verification_ref TEXT,
                  verification_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_runs_session
                  ON gateway_runs(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_gateway_events_run
                  ON gateway_run_events(run_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_gateway_artifacts_run
                  ON gateway_run_artifacts(run_id, observation_id);
                CREATE INDEX IF NOT EXISTS idx_gateway_idempotency_run
                  ON gateway_run_idempotency(run_id);
                CREATE INDEX IF NOT EXISTS idx_gateway_execution_entries_run
                  ON gateway_run_execution_entries(run_id, sequence);
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
                ("artifact_kind", "TEXT NOT NULL DEFAULT 'visual_observation'"),
                ("chart_type", "TEXT"),
                ("title", "TEXT"),
                ("width", "INTEGER"),
                ("height", "INTEGER"),
                ("figure_metadata_json", "TEXT"),
                ("chart_spec_json", "TEXT"),
                ("staged_ref", "TEXT"),
                ("work_key", "TEXT"),
                ("manifest_json", "TEXT"),
                ("verification_ref", "TEXT"),
                ("verification_json", "TEXT"),
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
                } else "gateway_run_artifacts"
                table_columns = columns if table == "gateway_runs" else {
                    row["name"] for row in connection.execute("PRAGMA table_info(gateway_run_artifacts)")
                }
                if name not in table_columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            idem_columns = {row["name"] for row in connection.execute("PRAGMA table_info(gateway_run_idempotency)")}
            for name, declaration in (
                ("continuation_kind", "TEXT"),
                ("parent_run_id", "TEXT"),
                ("cursor_id", "TEXT"),
            ):
                if name not in idem_columns:
                    connection.execute(f"ALTER TABLE gateway_run_idempotency ADD COLUMN {name} {declaration}")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_gateway_staged_work_key "
                "ON gateway_run_artifacts(run_id, work_key) WHERE work_key IS NOT NULL"
            )

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
        expired_artifacts = connection.execute(
            "SELECT managed_path FROM gateway_run_artifacts WHERE expires_at <= ?", (now,)
        ).fetchall()
        artifact_paths.extend(Path(row["managed_path"]) for row in expired_artifacts if row["managed_path"])
        connection.execute(
            """DELETE FROM gateway_run_artifacts
               WHERE expires_at <= ?""",
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


    def get_recovery(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        """Derive resumability from a validated cursor and committed action."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT r.status AS run_status, c.cursor_json, c.entry_cursor, c.updated_at
                     FROM gateway_runs r LEFT JOIN gateway_run_execution_cursors c ON c.run_id = r.run_id
                    WHERE r.run_id = ? AND r.session_id = ?""",
                (run_id, session_id),
            ).fetchone()
        if row is None:
            return None
        if row["cursor_json"] is None:
            return {"status": RecoveryStatus.UNAVAILABLE.value}
        try:
            cursor = ExecutionCursor.from_json(row["cursor_json"])
            entries = self._execution_prefix(run_id, cursor.entry_cursor)
        except (ExecutionRecordError, HistoryStoreError, TypeError, ValueError):
            return {"status": RecoveryStatus.UNAVAILABLE.value, "blockedReason": "execution_record_unavailable"}

        resumable = row["run_status"] in {RunStatus.FAILED.value, RunStatus.INTERRUPTED.value} or (
            row["run_status"] == RunStatus.COMPLETED.value
            and not any(entry.kind == "final_answer" for entry in entries)
        )
        if not resumable:
            return {"status": RecoveryStatus.UNAVAILABLE.value}

        blocked_reason = None
        action_model_entry_id: str | None = None
        action_call_id: str | None = None
        if cursor.next_action.kind == "tool":
            action_model_entry_id = cursor.next_action.message_entry_id
            action_call_id = cursor.next_action.call_id
        elif cursor.next_action.kind == "verify":
            staged_entry = next(
                (
                    entry for entry in reversed(entries)
                    if entry.kind == "tool_result"
                    and entry.payload.get("stagingCheckpoint") is True
                    and entry.payload.get("stagedRef") == cursor.next_action.staged_ref
                ),
                None,
            )
            if staged_entry is None or self.get_staged_chart_by_reference(session_id, cursor.next_action.staged_ref) is None:
                blocked_reason = "required_staged_chart_unavailable"
            else:
                action_model_entry_id = staged_entry.payload.get("modelEntryId")
                action_call_id = staged_entry.payload.get("callId")
        elif cursor.next_action.kind == "promote":
            verification_entry = next(
                (
                    entry for entry in reversed(entries)
                    if entry.kind == "verification_result"
                    and isinstance(entry.payload.get("verification"), dict)
                    and entry.payload["verification"].get("stagedRef") == cursor.next_action.staged_ref
                    and entry.payload["verification"].get("verificationRef") == cursor.next_action.verification_ref
                    and entry.payload["verification"].get("status") in {"pass", "pass_with_warning"}
                ),
                None,
            )
            if verification_entry is None or self.get_staged_chart_by_reference(session_id, cursor.next_action.staged_ref) is None:
                blocked_reason = "verification_result_unavailable"
            else:
                action_model_entry_id = verification_entry.payload.get("modelEntryId")
                action_call_id = verification_entry.payload.get("toolCallId")
        if action_model_entry_id is not None and action_call_id is not None:
            response = next((entry for entry in entries if entry.entry_id == action_model_entry_id), None)
            calls = response.payload.get("toolCalls") if response is not None else None
            call = next(
                (item for item in calls if isinstance(item, dict) and item.get("id") == action_call_id),
                None,
            ) if isinstance(calls, list) else None
            if call is None or call.get("replayEffect") not in {"replay_safe", "idempotent_local_write"}:
                blocked_reason = "tool_effect_requires_reconciliation"
        elif cursor.next_action.kind in {"tool", "verify", "promote"} and blocked_reason is None:
            blocked_reason = "execution_record_unavailable"
        return {
            "status": RecoveryStatus.BLOCKED.value if blocked_reason else RecoveryStatus.AVAILABLE.value,
            "cursorId": execution_cursor_id(run_id, cursor.entry_cursor),
            "nextAction": cursor.next_action.kind,
            "updatedAt": row["updated_at"] or utc_timestamp(),
            **({"blockedReason": blocked_reason} if blocked_reason else {}),
        }

    def _execution_prefix(self, run_id: str, through: int, seen: set[str] | None = None) -> list[ExecutionEntry]:
        lineage = set() if seen is None else seen
        if run_id in lineage or len(lineage) >= 16:
            raise ExecutionRecordError("execution prefix lineage is invalid")
        lineage.add(run_id)
        cursor = self.get_execution_cursor(run_id)
        if cursor is None or cursor.run_id != run_id or through > cursor.entry_cursor:
            raise ExecutionRecordError("execution prefix is unavailable")
        parent_run_id = cursor.references.get("parentRunId")
        parent_cursor = cursor.references.get("parentCursor")
        prefix: list[ExecutionEntry] = []
        if parent_run_id is not None or parent_cursor is not None:
            if not isinstance(parent_run_id, str) or not isinstance(parent_cursor, int) or parent_cursor < 1:
                raise ExecutionRecordError("execution parent reference is invalid")
            prefix = self._execution_prefix(parent_run_id, parent_cursor, lineage)
        own = self.list_execution_entries(run_id, through=through)
        if len(own) != through:
            raise ExecutionRecordError("execution entries are incomplete")
        return prefix + own



    def append_event(self, event: RunEvent) -> None:
        payload = dict(event.payload)
        validate_timeline_event(event.kind, payload)
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
    def _chart_figure_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        """Project bounded, non-lifecycle chart attribution metadata."""
        raw_context = metadata.get("generationContext") or metadata.get("generation_context")
        generation_context = sanitize_payload(raw_context) if isinstance(raw_context, Mapping) else None
        values = {
            "figure_id": metadata.get("figureId") or metadata.get("figure_id"),
            "collection_id": metadata.get("collectionId") or metadata.get("collection_id"),
            "child_chart_ids": metadata.get("childChartIds") or metadata.get("child_chart_ids") or [],
            "source": metadata.get("source") if isinstance(metadata.get("source"), Mapping) else None,
            "layout": metadata.get("layout") if isinstance(metadata.get("layout"), Mapping) else None,
            "coverage": metadata.get("coverage") if isinstance(metadata.get("coverage"), Mapping) else None,
            "generation_context": generation_context,
            "generation_context_digest": metadata.get("generationContextDigest") or metadata.get("generation_context_digest"),
            "panel_ids": metadata.get("panelIds") or metadata.get("panel_ids") or [],
            "source_attachment_ids": metadata.get("sourceAttachmentIds") or metadata.get("source_attachment_ids") or [],
        }
        return {key: value for key, value in values.items() if value not in (None, "", [], {})}

    @staticmethod
    def _staged_chart_reference(row: Mapping[str, Any]) -> dict[str, Any]:
        """Return the bounded staged or published chart facts from one row."""
        try:
            figure = json.loads(row["figure_metadata_json"] or "{}")
            verification = json.loads(row["verification_json"]) if row["verification_json"] else None
            manifest = ChartManifest.from_dict(json.loads(row["manifest_json"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, VerificationError):
            figure, verification, manifest = {}, None, None
        result: dict[str, Any] = {
            "artifactKind": "generated_chart",
            "mediaType": str(row["media_type"]),
            "caption": truncate_text(row["caption"], MAX_ARTIFACT_CAPTION),
            "byteCount": max(0, int(row["byte_count"])),
            "chartType": truncate_text(row["chart_type"] or "", MAX_ARTIFACT_CHART_TYPE),
            "title": truncate_text(row["title"] or "", MAX_ARTIFACT_TITLE),
            "width": max(0, int(row["width"] or 0)),
            "height": max(0, int(row["height"] or 0)),
            "status": (
                verification.get("status")
                if isinstance(verification, Mapping) and verification.get("status") in {"pass", "pass_with_warning", "fail", "unavailable"}
                else "staged"
            ),
        }
        if row["artifact_kind"] == "generated_chart":
            result["artifactId"] = str(row["observation_id"])
        if isinstance(row["staged_ref"], str) and row["staged_ref"]:
            result["stagedRef"] = row["staged_ref"]
        if isinstance(row["verification_ref"], str) and row["verification_ref"]:
            result["verificationRef"] = row["verification_ref"]
        if isinstance(verification, Mapping):
            result["verification"] = sanitize_payload(verification)
        if isinstance(figure, Mapping):
            aliases = {
                "figure_id": "figureId",
                "collection_id": "collectionId",
                "child_chart_ids": "childChartIds",
                "panel_ids": "panelIds",
                "source_attachment_ids": "sourceAttachmentIds",
                "generation_context": "generationContext",
                "generation_context_digest": "generationContextDigest",
            }
            for source, target in aliases.items():
                value = figure.get(source)
                if value not in (None, "", [], {}):
                    result[target] = sanitize_payload(value)
            for key in ("source", "layout", "coverage"):
                if isinstance(figure.get(key), Mapping):
                    result[key] = sanitize_payload(figure[key])
        if isinstance(manifest, ChartManifest):
            result["chartSpecDigest"] = manifest.chart_spec_digest
        return result

    def stage_chart(
        self,
        run_id: str,
        session_id: str,
        image: Any,
        manifest: ChartManifest,
    ) -> dict[str, Any] | None:
        """Atomically persist bounded render bytes and their immutable manifest."""
        content = getattr(image, "content", None)
        caption = getattr(image, "caption", "")
        metadata = getattr(image, "metadata", {})
        try:
            manifest_value = manifest.to_dict()
            manifest_json = canonical_json(manifest_value, limit=64 * 1024, name="chart manifest")
        except VerificationError:
            return None
        if (
            not isinstance(content, bytes)
            or not content
            or len(content) > self.max_artifact_bytes
            or content_digest(content) != manifest.image_sha256
            or len(content) != manifest.byte_count
            or getattr(image, "media_type", "") != manifest.media_type
            or not isinstance(caption, str)
            or not caption.strip()
            or not isinstance(metadata, Mapping)
            or not isinstance(metadata.get("width"), int)
            or not isinstance(metadata.get("height"), int)
            or (int(metadata["width"]), int(metadata["height"])) != (manifest.width, manifest.height)
        ):
            return None
        try:
            chart_spec_json = canonical_json(manifest.chart_spec, limit=MAX_PRIVATE_CHART_SPEC_BYTES, name="chart spec")
        except VerificationError:
            return None
        target = self.artifact_root / session_id / f"{manifest.staged_ref}.bin"
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._restrict_permissions(target.parent, 0o700)
        created = utc_timestamp()
        expires_at = time.time() + self.retention_seconds
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            prior = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE run_id = ? AND work_key = ?",
                (run_id, manifest.work_key),
            ).fetchone()
            if prior is not None:
                try:
                    prior_manifest = json.loads(prior["manifest_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    return None
                requested = dict(manifest_value)
                requested["stagedRef"] = prior_manifest.get("stagedRef")
                if (
                    prior["session_id"] != session_id
                    or prior["sha256"] != manifest.image_sha256
                    or prior["chart_spec_json"] != chart_spec_json
                    or prior["manifest_json"] != canonical_json(requested, limit=64 * 1024, name="chart manifest")
                ):
                    return None
                path = self._safe_artifact_path(prior["managed_path"], session_id)
                if path is None or not path.is_file():
                    return None
                try:
                    prior_bytes = path.read_bytes()
                except OSError:
                    return None
                if len(prior_bytes) != manifest.byte_count or content_digest(prior_bytes) != manifest.image_sha256:
                    return None
                return self._staged_chart_reference(prior)
            run = connection.execute(
                "SELECT 1 FROM gateway_runs WHERE run_id = ? AND session_id = ?", (run_id, session_id)
            ).fetchone()
            count = connection.execute(
                "SELECT COUNT(*) FROM gateway_run_artifacts WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            if run is None or int(count) >= self.max_artifacts:
                return None
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._restrict_permissions(temporary, 0o600)
                temporary.replace(target)
                self._restrict_permissions(target, 0o600)
                connection.execute(
                    """INSERT INTO gateway_run_artifacts(
                       observation_id, run_id, session_id, managed_path, media_type, caption,
                       byte_count, sha256, created_at, expires_at, artifact_kind, chart_type,
                       title, width, height, figure_metadata_json, chart_spec_json, staged_ref,
                       work_key, manifest_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged_chart', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        manifest.staged_ref, run_id, session_id, str(target), manifest.media_type,
                        truncate_text(caption, MAX_ARTIFACT_CAPTION), manifest.byte_count,
                        manifest.image_sha256, created, expires_at, manifest.chart_type,
                        manifest.title, manifest.width, manifest.height,
                        json.dumps(self._chart_figure_metadata(metadata), ensure_ascii=False),
                        chart_spec_json, manifest.staged_ref, manifest.work_key, manifest_json,
                    ),
                )
            except Exception:
                temporary.unlink(missing_ok=True)
                target.unlink(missing_ok=True)
                raise
            row = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE observation_id = ?", (manifest.staged_ref,)
            ).fetchone()
        return self._staged_chart_reference(row) if row is not None else None

    def record_verification(self, result: VerificationResult) -> dict[str, Any] | None:
        """Commit one immutable bounded result for its staged bytes."""
        try:
            result_value = result.to_dict()
            result_json = canonical_json(result_value, limit=16 * 1024, name="verification result")
        except VerificationError:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE observation_id = ? AND staged_ref = ?",
                (result.staged_ref, result.staged_ref),
            ).fetchone()
            if row is None or row["artifact_kind"] not in {"staged_chart", "generated_chart"}:
                return None
            manifest_text = row["manifest_json"]
            if not isinstance(manifest_text, str) or content_digest(manifest_text.encode("utf-8")) != result.manifest_digest:
                return None
            if row["verification_json"]:
                if row["verification_ref"] != result.verification_ref or row["verification_json"] != result_json:
                    return None
            else:
                connection.execute(
                    "UPDATE gateway_run_artifacts SET verification_ref = ?, verification_json = ? WHERE staged_ref = ?",
                    (result.verification_ref, result_json, result.staged_ref),
                )
                row = connection.execute(
                    "SELECT * FROM gateway_run_artifacts WHERE staged_ref = ?", (result.staged_ref,)
                ).fetchone()
        return self._staged_chart_reference(row) if row is not None else None

    def promote_staged_chart(
        self,
        run_id: str,
        session_id: str,
        staged_ref: str,
        verification_ref: str,
    ) -> dict[str, Any] | None:
        """Publish only the exact staged bytes with their committed allowed result."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE run_id = ? AND session_id = ? AND staged_ref = ?",
                (run_id, session_id, staged_ref),
            ).fetchone()
            if row is None:
                return None
            if row["artifact_kind"] == "generated_chart":
                if row["verification_ref"] != verification_ref:
                    return None
                return self._staged_chart_reference(row)
            if row["artifact_kind"] != "staged_chart" or row["verification_ref"] != verification_ref or not row["verification_json"]:
                return None
            try:
                result = json.loads(row["verification_json"])
                manifest = ChartManifest.from_dict(json.loads(row["manifest_json"]))
            except (TypeError, ValueError, json.JSONDecodeError, VerificationError):
                return None
            if (
                result.get("stagedRef") != staged_ref
                or result.get("manifestDigest") != content_digest(row["manifest_json"].encode("utf-8"))
                or result.get("status") not in ({"pass", "pass_with_warning"} if manifest.allow_warnings else {"pass"})
            ):
                return None
            path = self._safe_artifact_path(row["managed_path"], session_id)
            if path is None or not path.is_file():
                return None
            try:
                content = path.read_bytes()
            except OSError:
                return None
            if len(content) != manifest.byte_count or content_digest(content) != manifest.image_sha256:
                return None
            artifact_id = f"artifact_{uuid4().hex}"
            connection.execute(
                """UPDATE gateway_run_artifacts SET observation_id = ?, artifact_kind = 'generated_chart'
                   WHERE observation_id = ? AND artifact_kind = 'staged_chart'""",
                (artifact_id, staged_ref),
            )
            updated = connection.execute(
                "SELECT * FROM gateway_run_artifacts WHERE observation_id = ?", (artifact_id,)
            ).fetchone()
        return self._staged_chart_reference(updated) if updated is not None else None

    def get_staged_chart(self, session_id: str, run_id: str, staged_ref: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT * FROM gateway_run_artifacts WHERE run_id = ? AND session_id = ? AND staged_ref = ?
                   AND artifact_kind IN ('staged_chart', 'generated_chart')""",
                (run_id, session_id, staged_ref),
            ).fetchone()
        if row is None:
            return None
        return self._read_staged_chart(row, session_id)

    def get_staged_chart_by_reference(self, session_id: str, staged_ref: str) -> dict[str, Any] | None:
        """Resolve staged bytes by opaque reference within the owning session."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT * FROM gateway_run_artifacts
                   WHERE session_id = ? AND staged_ref = ?
                     AND artifact_kind IN ('staged_chart', 'generated_chart')
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, staged_ref),
            ).fetchone()
        if row is None:
            return None
        return self._read_staged_chart(row, session_id)

    def get_staged_chart_by_work_key(self, session_id: str, work_key: str) -> dict[str, Any] | None:
        """Resolve an idempotent staged render attempt across resumed child Runs."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT * FROM gateway_run_artifacts
                   WHERE session_id = ? AND work_key = ?
                     AND artifact_kind IN ('staged_chart', 'generated_chart')
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, work_key),
            ).fetchone()
        if row is None:
            return None
        return self._read_staged_chart(row, session_id)

    def _read_staged_chart(self, row: Any, session_id: str) -> dict[str, Any] | None:
        path = self._safe_artifact_path(row["managed_path"], session_id)
        if path is None or not path.is_file():
            return None
        try:
            content = path.read_bytes()
            manifest = ChartManifest.from_dict(json.loads(row["manifest_json"]))
        except (OSError, TypeError, ValueError, json.JSONDecodeError, VerificationError):
            return None
        if len(content) != manifest.byte_count or content_digest(content) != manifest.image_sha256:
            return None
        return {
            "content": content,
            "mediaType": manifest.media_type,
            "manifest": manifest,
            "reference": self._staged_chart_reference(row),
        }

    def get_chart_preview(self, session_id: str, run_id: str, reference_id: str) -> tuple[bytes, str] | None:
        """Read staged preview bytes or the corresponding published artifact."""
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                """SELECT observation_id, artifact_kind FROM gateway_run_artifacts
                   WHERE run_id = ? AND session_id = ?
                     AND (observation_id = ? OR staged_ref = ?)
                     AND artifact_kind IN ('generated_chart', 'staged_chart')
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
        if not isinstance(metadata, Mapping) or metadata.get("kind") == "generated_chart":
            return None
        observation_id = f"obs_{uuid4().hex}"
        artifact_kind = "visual_observation"
        chart_type = title = width = height = None
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

    def _cleanup_artifact_tree(self, referenced_paths: set[Path]) -> None:
        """Remove unreferenced Gateway files without entering evaluation details."""
        root = self.artifact_root
        if root.is_symlink() or not root.is_dir():
            return
        try:
            canonical_root = root.resolve(strict=True)
        except OSError:
            return

        def clean_directory(directory: Path) -> None:
            try:
                if directory.is_symlink():
                    directory.unlink(missing_ok=True)
                    return
                canonical_directory = directory.resolve(strict=True)
                canonical_directory.relative_to(canonical_root)
                entries = list(os.scandir(directory))
            except (OSError, ValueError):
                return
            for entry in entries:
                child = Path(entry.path)
                try:
                    if entry.is_symlink():
                        child.unlink(missing_ok=True)
                    elif entry.is_dir(follow_symlinks=False):
                        clean_directory(child)
                    elif entry.is_file(follow_symlinks=False):
                        resolved = child.resolve(strict=True)
                        resolved.relative_to(canonical_directory)
                        if resolved not in referenced_paths:
                            child.unlink(missing_ok=True)
                except (OSError, ValueError):
                    continue
            try:
                directory.rmdir()
            except OSError:
                pass

        try:
            entries = list(os.scandir(root))
        except OSError:
            return
        for entry in entries:
            child = Path(entry.path)
            if child.name == "history-details":
                continue
            try:
                if entry.is_symlink():
                    child.unlink(missing_ok=True)
                elif entry.is_dir(follow_symlinks=False):
                    clean_directory(child)
            except OSError:
                continue

    def cleanup(self) -> None:
        with self._lock:
            with self._connect() as connection:
                self._cleanup_connection(connection)
                rows = connection.execute(
                    "SELECT session_id, managed_path FROM gateway_run_artifacts"
                ).fetchall()
                referenced_paths = {
                    path
                    for row in rows
                    if (path := self._safe_artifact_path(row["managed_path"], row["session_id"])) is not None
                }
            self._cleanup_artifact_tree(referenced_paths)

    def close(self) -> None:
        with self._lock:
            self.cleanup()


__all__ = ["GatewayHistoryStore", "HistoryStoreError"]
