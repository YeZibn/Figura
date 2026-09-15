"""Durable, bounded execution history owned by the local Gateway."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..memory.sqlite import default_database_path
from ..trace import truncate_text
from .protocol import (
    GeneratedChartReference,
    MAX_ARTIFACT_CAPTION,
    MAX_ARTIFACT_CHART_TYPE,
    MAX_ARTIFACT_TITLE,
    MAX_EVENT_KIND,
    MAX_EVENT_PAYLOAD,
    RunEvent,
    RunStatus,
    utc_timestamp,
)

DEFAULT_MAX_HISTORY_EVENTS = 512
DEFAULT_MAX_HISTORY_RUNS = 256
DEFAULT_HISTORY_RETENTION_SECONDS = 30 * 24 * 60 * 60.0
DEFAULT_MAX_HISTORY_ARTIFACT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_HISTORY_ARTIFACTS = 32
_SUPPORTED_ARTIFACT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class HistoryStoreError(Exception):
    """A bounded persistence or artifact failure."""


class GatewayHistoryStore:
    """Persist Gateway-owned runs, events, and generated visual artifacts."""

    def __init__(
        self,
        database: str | Path | None,
        *,
        artifact_root: str | Path | None = None,
        max_events: int = DEFAULT_MAX_HISTORY_EVENTS,
        max_runs: int = DEFAULT_MAX_HISTORY_RUNS,
        retention_seconds: float = DEFAULT_HISTORY_RETENTION_SECONDS,
        max_artifact_bytes: int = DEFAULT_MAX_HISTORY_ARTIFACT_BYTES,
        max_artifacts: int = DEFAULT_MAX_HISTORY_ARTIFACTS,
    ) -> None:
        self.database = Path(database).expanduser() if database is not None else default_database_path()
        self.artifact_root = Path(artifact_root).expanduser() if artifact_root is not None else self._default_artifact_root()
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

    def _default_artifact_root(self) -> Path:
        configured = os.environ.get("CHARTAGENT_DATA_DIR")
        return (Path(configured).expanduser() if configured else Path.home() / ".chartagent") / "run-artifacts"

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
                  history_warning TEXT
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
                  review_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_runs_session
                  ON gateway_runs(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_gateway_events_run
                  ON gateway_run_events(run_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_gateway_artifacts_run
                  ON gateway_run_artifacts(run_id, observation_id);
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
                ("review_json", "TEXT"),
            ):
                table = "gateway_runs" if name in {"terminal_code", "terminal_message", "answer_source", "history_warning"} else "gateway_run_artifacts"
                table_columns = columns if table == "gateway_runs" else {
                    row["name"] for row in connection.execute("PRAGMA table_info(gateway_run_artifacts)")
                }
                if name not in table_columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

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

    def create_run(self, run_id: str, session_id: str) -> None:
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
                "INSERT INTO gateway_runs(run_id, session_id, status, created_at, updated_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, session_id, RunStatus.RUNNING.value, now, now, expires_at),
            )

    def append_event(self, event: RunEvent) -> None:
        payload = dict(event.payload)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_EVENT_PAYLOAD:
            payload = {"truncated": True, "preview": truncate_text(encoded, MAX_EVENT_PAYLOAD // 2)}
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute("SELECT 1 FROM gateway_runs WHERE run_id = ?", (event.run_id,)).fetchone()
            if row is None:
                raise HistoryStoreError("Gateway run is not registered")
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
    ) -> None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            connection.execute(
                """UPDATE gateway_runs
                   SET status = ?, updated_at = ?, expires_at = ?, terminal_code = ?, terminal_message = ?,
                       answer_source = ?, history_warning = ?
                 WHERE run_id = ?""",
                (
                    status.value,
                    utc_timestamp(),
                    time.time() + self.retention_seconds,
                    truncate_text(terminal_code, 128) if terminal_code else None,
                    truncate_text(terminal_message, 240) if terminal_message else None,
                    truncate_text(answer_source, 12000) if answer_source is not None else None,
                    truncate_text(history_warning, 240) if history_warning else None,
                    run_id,
                ),
            )

    def interrupt_running_runs(self) -> None:
        """Mark runs left active by a previous Gateway process as interrupted."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE gateway_runs
                   SET status = ?, updated_at = ?, terminal_code = ?, terminal_message = ?
                 WHERE status = ?""",
                (
                    RunStatus.INTERRUPTED.value,
                    utc_timestamp(),
                    "gateway_restarted",
                    "Gateway 重启，运行已中断",
                    RunStatus.RUNNING.value,
                ),
            )

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            rows = connection.execute(
                """SELECT run_id, session_id, status, created_at, updated_at,
                          expires_at,
                          terminal_code, terminal_message, answer_source, history_warning,
                          (SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count
                     FROM gateway_runs r WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
        return [self._run_summary(row) for row in rows]

    def get_run(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT run_id, session_id, status, created_at, updated_at, expires_at, terminal_code, terminal_message, answer_source, history_warning, (SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count FROM gateway_runs r WHERE run_id = ? AND session_id = ?",
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
                           publication_status = ?, review_json = ?, expires_at = ?
                           WHERE observation_id = ? AND artifact_kind = 'generated_candidate'""",
                        (
                            str(metadata.get("candidateStatus", "review_pending")),
                            "completed",
                            str(metadata.get("publicationStatus", "unpublished")),
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
            managed_path = str(path) if candidate_status not in {"review_failed", "timed_out", "retry_exhausted", "expired"} else ""
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
                       review_status, publication_status, review_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated_candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        candidate_id, run_id, session_id, managed_path, media_type,
                        truncate_text(caption, MAX_ARTIFACT_CAPTION), len(content),
                        hashlib.sha256(content).hexdigest(), created, expires_at,
                        chart_type, title, width, height, candidate_id, review_id,
                        digest, candidate_status,
                        str(metadata.get("reviewStatus", "pending")),
                        str(metadata.get("publicationStatus", "unpublished")),
                        json.dumps(metadata.get("review", {}), ensure_ascii=False)[:MAX_EVENT_PAYLOAD],
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
                    "INSERT INTO gateway_run_artifacts(observation_id, run_id, session_id, managed_path, media_type, caption, byte_count, sha256, created_at, expires_at, artifact_kind, chart_type, title, width, height) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (observation_id, run_id, session_id, str(path), media_type, reference["caption"], len(content), hashlib.sha256(content).hexdigest(), created, expires_at, artifact_kind, chart_type, title, width, height),
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
