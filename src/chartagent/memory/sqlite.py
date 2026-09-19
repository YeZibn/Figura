"""SQLite-backed named session memory."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .context import build_context, recovery_messages, sanitize_payload
from .models import Attachment, Record, Run, RunStatus, Session, SessionStats, bounded, utc_now
from ..panels import ActiveSourceContext, PanelHandoff, bbox_iou
from ..storage import resolve_storage_paths

SCHEMA_VERSION = 2


def default_database_path() -> Path:
    return resolve_storage_paths().database


class SQLiteAgentMemory:
    """Durable memory for one named session."""

    def __init__(self, name: str, *, database: str | Path | None = None, context_budget: int = 24000, create: bool = True) -> None:
        bounded(name, 128, "session name")
        self.database = resolve_storage_paths(database=database).database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.context_budget = context_budget
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._initialize()
        self.session = self._get_session(name)
        if self.session is None:
            if not create:
                raise KeyError(f"session not found: {name}")
            self.session = self.create_session(name)
        self._interrupt_running()

    def _initialize(self) -> None:
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        row = self.connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        if row and int(row[0]) > SCHEMA_VERSION:
            raise RuntimeError(f"unsupported session database version: {row[0]}")
        if not row:
            self.connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
        elif int(row[0]) < SCHEMA_VERSION:
            self.connection.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          ordinal INTEGER NOT NULL, status TEXT NOT NULL, terminal_kind TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          sequence INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(run_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS attachments (
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          run_id TEXT REFERENCES runs(id) ON DELETE SET NULL, ordinal INTEGER NOT NULL,
          canonical_path TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
          byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS session_state (
          session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
          active_attachment_ids_json TEXT NOT NULL DEFAULT '[]',
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS panel_handoffs (
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          panel_id TEXT NOT NULL,
          revision INTEGER NOT NULL,
          attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
          attachment_sha256 TEXT NOT NULL,
          status TEXT NOT NULL,
          record_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(session_id, panel_id, revision)
        );
        CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_records_run ON records(run_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_attachments_session ON attachments(session_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_panel_handoffs_attachment ON panel_handoffs(session_id, attachment_id, status);
        """)
        self.connection.commit()
        try:
            self.database.chmod(0o600)
        except OSError:
            pass

    def _get_session(self, name: str) -> Session | None:
        row = self.connection.execute("SELECT * FROM sessions WHERE name = ?", (name,)).fetchone()
        return Session(row["id"], row["name"], row["created_at"], row["updated_at"]) if row else None

    def create_session(self, name: str) -> Session:
        bounded(name, 128, "session name")
        now = utc_now()
        session = Session(str(uuid.uuid4()), name, now, now)
        try:
            with self.connection:
                self.connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (session.id, session.name, now, now))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"session already exists: {name}") from exc
        return session

    @classmethod
    def list_sessions(cls, *, database: str | Path | None = None) -> list[Session]:
        path = Path(database) if database else default_database_path()
        if not path.exists():
            return []
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
            return [Session(row[0], row[1], row[2], row[3]) for row in rows]
        finally:
            conn.close()

    @classmethod
    def list_session_stats(cls, *, database: str | Path | None = None) -> list[SessionStats]:
        """Return bounded session metadata without exposing SQLite rows."""
        path = Path(database) if database else default_database_path()
        if not path.exists():
            return []
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute(
                """
                SELECT s.id, s.name, s.created_at, s.updated_at,
                       COALESCE(SUM(CASE WHEN r.status = ? THEN 1 ELSE 0 END), 0)
                  FROM sessions AS s
             LEFT JOIN runs AS r ON r.session_id = s.id
              GROUP BY s.id, s.name, s.created_at, s.updated_at
              ORDER BY s.updated_at DESC
                """,
                (RunStatus.COMPLETED.value,),
            ).fetchall()
            return [
                SessionStats(
                    Session(row[0], row[1], row[2], row[3]),
                    int(row[4]),
                )
                for row in rows
            ]
        finally:
            conn.close()

    @classmethod
    def get_session_by_id(
        cls,
        session_id: str,
        *,
        database: str | Path | None = None,
    ) -> Session | None:
        """Resolve an opaque session ID to safe session metadata."""
        path = Path(database) if database else default_database_path()
        if not path.exists():
            return None
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT id, name, created_at, updated_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return Session(row[0], row[1], row[2], row[3]) if row else None
        finally:
            conn.close()

    @classmethod
    def get_session_by_name(
        cls,
        name: str,
        *,
        database: str | Path | None = None,
    ) -> Session | None:
        """Resolve a display name without creating or opening a session."""
        path = Path(database) if database else default_database_path()
        if not path.exists():
            return None
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT id, name, created_at, updated_at FROM sessions WHERE name = ?",
                (name,),
            ).fetchone()
            return Session(row[0], row[1], row[2], row[3]) if row else None
        finally:
            conn.close()

    @classmethod
    def delete_session_by_id(
        cls,
        session_id: str,
        *,
        database: str | Path | None = None,
    ) -> list[Attachment] | None:
        """Delete a session by opaque ID and return its attachment rows.

        ``None`` means that no session existed; an empty list is a valid
        deleted session with no attachments.
        """
        path = Path(database) if database else default_database_path()
        if not path.exists():
            return None
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            rows = conn.execute(
                "SELECT id, session_id, run_id, ordinal, canonical_path, filename, media_type, byte_count, sha256, created_at FROM attachments WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            attachments = [
                Attachment(
                    item["id"], item["session_id"], item["run_id"], item["ordinal"],
                    item["canonical_path"], item["filename"], item["media_type"],
                    item["byte_count"], item["sha256"], item["created_at"],
                )
                for item in rows
            ]
            with conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return attachments
        finally:
            conn.close()

    @classmethod
    def delete_attachment_by_id(
        cls,
        session_id: str,
        attachment_id: str,
        *,
        database: str | Path | None = None,
    ) -> Attachment | None:
        """Delete and return one attachment owned by a session."""
        path = Path(database) if database else default_database_path()
        if not path.exists():
            return None
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            row = conn.execute(
                "SELECT id, session_id, run_id, ordinal, canonical_path, filename, media_type, byte_count, sha256, created_at FROM attachments WHERE id = ? AND session_id = ?",
                (attachment_id, session_id),
            ).fetchone()
            if row is None:
                return None
            item = Attachment(
                row["id"], row["session_id"], row["run_id"], row["ordinal"],
                row["canonical_path"], row["filename"], row["media_type"],
                row["byte_count"], row["sha256"], row["created_at"],
            )
            with conn:
                conn.execute(
                    "DELETE FROM attachments WHERE id = ? AND session_id = ?",
                    (attachment_id, session_id),
                )
            return item
        finally:
            conn.close()

    @classmethod
    def delete_session(cls, name: str, *, database: str | Path | None = None) -> bool:
        session = cls.get_session_by_name(name, database=database)
        if session is None:
            return False
        return cls.delete_session_by_id(session.id, database=database) is not None

    def _interrupt_running(self) -> None:
        with self.connection:
            self.connection.execute("UPDATE runs SET status = ?, updated_at = ? WHERE session_id = ? AND status = ?", (RunStatus.INTERRUPTED.value, utc_now(), self.session.id, RunStatus.RUNNING.value))

    def begin_run(self, run_id: str | None = None) -> Run:
        if run_id is None:
            run_id = str(uuid.uuid4())
        elif not isinstance(run_id, str):
            raise ValueError("run id must be text")
        run_id = bounded(run_id, 128, "run id")
        existing = self.connection.execute(
            "SELECT session_id FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if existing is not None:
            if existing["session_id"] != self.session.id:
                raise ValueError("run id belongs to another session")
            raise ValueError("run id already exists")
        ordinal = self.connection.execute("SELECT COALESCE(MAX(ordinal), 0) + 1 FROM runs WHERE session_id = ?", (self.session.id,)).fetchone()[0]
        run = Run(run_id, self.session.id, int(ordinal))
        now = utc_now()
        with self.connection:
            self.connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)", (run.id, run.session_id, run.ordinal, run.status.value, None, now, now))
        return run

    def append(self, run: Run, kind: str, payload: dict[str, Any]) -> None:
        clean = sanitize_payload(payload)
        record = Record(kind, clean, len(run.records))
        with self.connection:
            self.connection.execute("INSERT INTO records(run_id, sequence, kind, payload_json, created_at) VALUES (?, ?, ?, ?, ?)", (run.id, record.sequence, record.kind, json.dumps(clean, ensure_ascii=False), record.created_at))
            self.connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (utc_now(), self.session.id))
        run.records.append(record)

    def finish(self, run: Run, status: RunStatus, terminal_kind: str | None = None) -> None:
        status = RunStatus(status)
        now = utc_now()
        with self.connection:
            self.connection.execute("UPDATE runs SET status = ?, terminal_kind = ?, updated_at = ? WHERE id = ?", (status.value, terminal_kind, now, run.id))
            self.connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, self.session.id))
        run.status, run.terminal_kind, run.updated_at = status, terminal_kind, now

    def _load_runs(self) -> list[Run]:
        rows = self.connection.execute("SELECT * FROM runs WHERE session_id = ? ORDER BY ordinal", (self.session.id,)).fetchall()
        runs: list[Run] = []
        for row in rows:
            run = Run(row["id"], row["session_id"], row["ordinal"], RunStatus(row["status"]), row["terminal_kind"], row["created_at"], row["updated_at"])
            records = self.connection.execute("SELECT * FROM records WHERE run_id = ? ORDER BY sequence", (run.id,)).fetchall()
            run.records = [Record(item["kind"], json.loads(item["payload_json"]), item["sequence"], item["created_at"]) for item in records]
            runs.append(run)
        return runs

    def completed_runs(self) -> list[Run]:
        """Return only completed runs for this session."""
        return [run for run in self._load_runs() if run.status == RunStatus.COMPLETED]

    def context(self, run: Run, system: dict[str, Any] | None = None, budget: int = 24000, current_messages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        all_runs = [item for item in self._load_runs() if item.id != run.id]
        return build_context(system, all_runs, run.records, current_messages=current_messages, budget=budget or self.context_budget)

    def recovery_context(self, checkpoint_state: dict[str, Any] | None, *, budget: int | None = None) -> list[dict[str, Any]]:
        """Load explicitly authorized checkpoint messages, never ordinary history."""
        return recovery_messages(checkpoint_state, budget=budget or self.context_budget)

    def begin_continuation(self, run_id: str, checkpoint_state: dict[str, Any]) -> tuple[Run, list[dict[str, Any]]]:
        """Start a child memory run and return its isolated recovery messages."""
        run = self.begin_run(run_id)
        self.append(run, "recovery_context", {
            "parentRunId": checkpoint_state.get("parentRunId"),
            "checkpointId": checkpoint_state.get("checkpointId"),
            "phase": checkpoint_state.get("phase"),
        })
        return run, self.recovery_context(checkpoint_state)

    def save_attachment(self, attachment: Attachment) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO attachments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (attachment.id, self.session.id, attachment.run_id, attachment.ordinal,
                 attachment.canonical_path, attachment.filename, attachment.media_type,
                 attachment.byte_count, attachment.sha256, attachment.created_at),
            )

    def set_active_source(self, attachment_ids: list[str] | tuple[str, ...]) -> ActiveSourceContext:
        """Persist the session's explicit active source references."""
        normalized = tuple(item for item in attachment_ids[:16] if isinstance(item, str) and item)
        now = utc_now()
        with self.connection:
            self.connection.execute(
                """INSERT INTO session_state(session_id, active_attachment_ids_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     active_attachment_ids_json = excluded.active_attachment_ids_json,
                     updated_at = excluded.updated_at""",
                (self.session.id, json.dumps(list(normalized), ensure_ascii=False), now),
            )
            self.connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, self.session.id))
        return ActiveSourceContext(self.session.id, normalized, "explicit", now)

    def get_active_source(self) -> ActiveSourceContext:
        row = self.connection.execute(
            "SELECT active_attachment_ids_json, updated_at FROM session_state WHERE session_id = ?",
            (self.session.id,),
        ).fetchone()
        if row is None:
            return ActiveSourceContext(self.session.id)
        try:
            values = json.loads(row["active_attachment_ids_json"])
        except (TypeError, json.JSONDecodeError):
            values = []
        ids = tuple(item for item in values if isinstance(item, str)) if isinstance(values, list) else ()
        return ActiveSourceContext(self.session.id, ids[:16], "session", row["updated_at"])

    def save_panel_handoff(self, handoff: PanelHandoff) -> PanelHandoff:
        if handoff.session_id != self.session.id:
            raise ValueError("panel handoff belongs to another session")
        now = utc_now()
        payload = handoff.to_dict()
        payload["updatedAt"] = now
        stored = PanelHandoff.from_dict(payload)
        with self.connection:
            self.connection.execute(
                """INSERT INTO panel_handoffs(
                   session_id, panel_id, revision, attachment_id, attachment_sha256,
                   status, record_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, panel_id, revision) DO UPDATE SET
                     attachment_id = excluded.attachment_id,
                     attachment_sha256 = excluded.attachment_sha256,
                     status = excluded.status,
                     record_json = excluded.record_json,
                     updated_at = excluded.updated_at""",
                (
                    stored.session_id,
                    stored.panel_id,
                    stored.revision,
                    stored.attachment_id,
                    stored.attachment_sha256,
                    stored.status,
                    json.dumps(stored.to_dict(), ensure_ascii=False),
                    stored.updated_at or now,
                    stored.updated_at or now,
                ),
            )
        return stored

    def save_panel_handoffs(self, handoffs: list[PanelHandoff] | tuple[PanelHandoff, ...]) -> list[PanelHandoff]:
        return [self.save_panel_handoff(item) for item in handoffs]

    def list_panel_handoffs(self, attachment_id: str | None = None, *, include_stale: bool = False) -> list[PanelHandoff]:
        query = "SELECT record_json FROM panel_handoffs WHERE session_id = ?"
        params: list[Any] = [self.session.id]
        if attachment_id:
            query += " AND attachment_id = ?"
            params.append(attachment_id)
        if not include_stale:
            query += " AND status = 'active'"
        query += " ORDER BY attachment_id, panel_id, revision"
        rows = self.connection.execute(query, params).fetchall()
        result: list[PanelHandoff] = []
        for row in rows:
            try:
                result.append(PanelHandoff.from_dict(json.loads(row["record_json"])))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    def get_panel_handoff(self, panel_id: str, *, attachment_id: str | None = None, revision: int | None = None) -> PanelHandoff | None:
        query = "SELECT record_json FROM panel_handoffs WHERE session_id = ? AND panel_id = ?"
        params: list[Any] = [self.session.id, panel_id]
        if attachment_id:
            query += " AND attachment_id = ?"
            params.append(attachment_id)
        if revision is not None:
            query += " AND revision = ?"
            params.append(int(revision))
        query += " ORDER BY revision DESC LIMIT 1"
        row = self.connection.execute(query, params).fetchone()
        if row is None:
            return None
        try:
            handoff = PanelHandoff.from_dict(json.loads(row["record_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return handoff if handoff.status == "active" else None

    def match_panel_handoff(
        self,
        attachment_id: str,
        attachment_sha256: str,
        *,
        name: str | None = None,
        chart_type: str | None = None,
        source_bbox: list[int] | tuple[int, ...] | None = None,
        minimum_iou: float = 0.55,
    ) -> PanelHandoff | None:
        candidates = [item for item in self.list_panel_handoffs(attachment_id) if item.attachment_sha256 == attachment_sha256]
        if not candidates:
            return None
        normalized_name = (name or "").strip().casefold()
        normalized_type = (chart_type or "").strip().casefold()
        scored: list[tuple[float, PanelHandoff]] = []
        for item in candidates:
            score = bbox_iou(item.source_bbox, source_bbox)
            if normalized_name and normalized_name == item.name.casefold():
                score = max(score, 1.0 if source_bbox is None else score + 0.35)
            elif normalized_name and normalized_name in item.name.casefold():
                score += 0.15
            if normalized_type and normalized_type == item.chart_type.casefold():
                score += 0.1
            scored.append((score, item))
        if not scored:
            return None
        score, item = max(scored, key=lambda value: value[0])
        return item if score >= minimum_iou else None

    def invalidate_panel_handoff(self, panel_id: str, *, reason: str = "stale") -> bool:
        now = utc_now()
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE panel_handoffs SET status = 'stale', updated_at = ?
                   WHERE session_id = ? AND panel_id = ? AND status = 'active'""",
                (now, self.session.id, panel_id),
            )
        return cursor.rowcount > 0

    def update_attachment_run(self, attachment_id: str, run_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE attachments SET run_id = ? WHERE id = ? AND session_id = ?",
                (run_id, attachment_id, self.session.id),
            )

    def update_attachment_path(self, attachment_id: str, canonical_path: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE attachments SET canonical_path = ? WHERE id = ? AND session_id = ?",
                (canonical_path, attachment_id, self.session.id),
            )

    def get_attachment(self, attachment_id: str) -> Attachment | None:
        row = self.connection.execute(
            "SELECT * FROM attachments WHERE id = ? AND session_id = ?",
            (attachment_id, self.session.id),
        ).fetchone()
        if not row:
            return None
        return Attachment(row["id"], row["session_id"], row["run_id"], row["ordinal"],
                          row["canonical_path"], row["filename"], row["media_type"],
                          row["byte_count"], row["sha256"], row["created_at"])

    def list_attachments(self) -> list[Attachment]:
        """Return all attachment references owned by this session."""
        rows = self.connection.execute(
            "SELECT * FROM attachments WHERE session_id = ? ORDER BY ordinal, created_at",
            (self.session.id,),
        ).fetchall()
        return [
            Attachment(
                row["id"],
                row["session_id"],
                row["run_id"],
                row["ordinal"],
                row["canonical_path"],
                row["filename"],
                row["media_type"],
                row["byte_count"],
                row["sha256"],
                row["created_at"],
            )
            for row in rows
        ]

    def close(self) -> None:
        self.connection.close()
