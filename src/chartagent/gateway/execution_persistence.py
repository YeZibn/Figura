"""Persistence methods for the private execution record and cursor."""

from __future__ import annotations

import hashlib
import json

from .execution_record import (
    MAX_EXECUTION_ENTRIES_PER_RUN,
    ExecutionCursor,
    ExecutionEntry,
    ExecutionRecordError,
)
from .persistence_errors import HistoryStoreError
from .protocol import MAX_EVENT_KIND, MAX_EVENT_PAYLOAD, RunEvent, RunStatus, _truncate_tool_result_payload
from ..trace import truncate_text


class ExecutionPersistenceMixin:
    """Read and atomically advance one run's private committed prefix."""

    def commit_execution_step(
        self,
        entry: ExecutionEntry,
        cursor: ExecutionCursor,
        *,
        event: RunEvent | None = None,
    ) -> ExecutionEntry:
        normalized = entry.normalized()
        cursor_json = cursor.to_json()
        if cursor.run_id != normalized.run_id or cursor.entry_cursor != normalized.sequence:
            raise ExecutionRecordError("execution cursor does not match the committed entry")
        if event is not None and event.run_id != normalized.run_id:
            raise ExecutionRecordError("execution event belongs to another run")
        payload_json = normalized.payload_json()
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS last_sequence, COUNT(*) AS entry_count "
                "FROM gateway_run_execution_entries WHERE run_id = ?",
                (normalized.run_id,),
            ).fetchone()
            if normalized.sequence != int(row["last_sequence"]) + 1:
                raise HistoryStoreError("execution entry sequence is not the next committed sequence")
            if int(row["entry_count"]) >= MAX_EXECUTION_ENTRIES_PER_RUN:
                raise HistoryStoreError("execution record entry limit reached")
            connection.execute(
                "INSERT INTO gateway_run_execution_entries "
                "(run_id, sequence, entry_id, entry_kind, work_key, payload_json, payload_sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.run_id,
                    normalized.sequence,
                    normalized.entry_id,
                    normalized.kind,
                    normalized.work_key,
                    payload_json,
                    digest,
                    normalized.created_at,
                ),
            )
            connection.execute(
                "INSERT INTO gateway_run_execution_cursors "
                "(run_id, version, entry_cursor, turn, next_action_json, references_json, cursor_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET version=excluded.version, "
                "entry_cursor=excluded.entry_cursor, turn=excluded.turn, "
                "next_action_json=excluded.next_action_json, references_json=excluded.references_json, "
                "cursor_json=excluded.cursor_json, updated_at=excluded.updated_at",
                (
                    cursor.run_id,
                    cursor.version,
                    cursor.entry_cursor,
                    cursor.turn,
                    json.dumps(cursor.next_action.to_dict(), ensure_ascii=False, sort_keys=True),
                    json.dumps(cursor.references, ensure_ascii=False, sort_keys=True),
                    cursor_json,
                    normalized.created_at,
                ),
            )
            if event is not None:
                event_payload = dict(event.payload)
                encoded_event = json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"))
                if len(encoded_event) > MAX_EVENT_PAYLOAD:
                    if event.kind == "tool_result":
                        event_payload = _truncate_tool_result_payload(event_payload)
                        encoded_event = json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"))
                    if len(encoded_event) > MAX_EVENT_PAYLOAD:
                        event_payload = {"truncated": True, "preview": truncate_text(encoded_event, MAX_EVENT_PAYLOAD // 2)}
                        encoded_event = json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"))
                run_row = connection.execute(
                    "SELECT status FROM gateway_runs WHERE run_id = ?",
                    (normalized.run_id,),
                ).fetchone()
                if run_row is None or run_row["status"] != RunStatus.RUNNING.value:
                    raise HistoryStoreError("execution event run is not active")
                existing = connection.execute(
                    "SELECT 1 FROM gateway_run_events WHERE run_id = ? AND sequence = ?",
                    (event.run_id, event.sequence),
                ).fetchone()
                if existing is not None:
                    raise HistoryStoreError("execution event sequence already exists")
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM gateway_run_events WHERE run_id = ?", (event.run_id,),
                ).fetchone()[0])
                if count >= self.max_events:
                    oldest = connection.execute(
                        "SELECT sequence FROM gateway_run_events WHERE run_id = ? ORDER BY sequence LIMIT ?",
                        (event.run_id, max(1, count - self.max_events + 1)),
                    ).fetchall()
                    connection.executemany(
                        "DELETE FROM gateway_run_events WHERE run_id = ? AND sequence = ?",
                        [(event.run_id, row["sequence"]) for row in oldest],
                    )
                connection.execute(
                    "INSERT INTO gateway_run_events(run_id, sequence, kind, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event.run_id, event.sequence, truncate_text(event.kind, MAX_EVENT_KIND), encoded_event, event.timestamp),
                )
                connection.execute(
                    "UPDATE gateway_runs SET updated_at = ? WHERE run_id = ?",
                    (event.timestamp, event.run_id),
                )
        return normalized

    def get_execution_cursor(self, run_id: str) -> ExecutionCursor | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor_json FROM gateway_run_execution_cursors WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return ExecutionCursor.from_json(row["cursor_json"])
        except ExecutionRecordError as exc:
            raise HistoryStoreError("execution cursor is invalid") from exc

    def list_execution_entries(self, run_id: str, *, through: int | None = None) -> list[ExecutionEntry]:
        query = (
            "SELECT run_id, sequence, entry_id, entry_kind, work_key, payload_json, payload_sha256, created_at "
            "FROM gateway_run_execution_entries WHERE run_id = ?"
        )
        parameters: tuple[object, ...] = (run_id,)
        if through is not None:
            query += " AND sequence <= ?"
            parameters += (through,)
        query += " ORDER BY sequence"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        result: list[ExecutionEntry] = []
        for row in rows:
            payload_json = row["payload_json"]
            if hashlib.sha256(payload_json.encode("utf-8")).hexdigest() != row["payload_sha256"]:
                raise HistoryStoreError("execution entry digest mismatch")
            try:
                payload = json.loads(payload_json)
                result.append(ExecutionEntry(
                    run_id=row["run_id"],
                    sequence=int(row["sequence"]),
                    kind=row["entry_kind"],
                    payload=payload,
                    entry_id=row["entry_id"],
                    work_key=row["work_key"],
                    created_at=row["created_at"],
                ).normalized())
            except (json.JSONDecodeError, ExecutionRecordError) as exc:
                raise HistoryStoreError("execution entry is invalid") from exc
        return result

    def get_execution_entry_by_work_key(self, run_id: str, work_key: str) -> ExecutionEntry | None:
        """Return a previously committed result for one stable execution identity."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sequence FROM gateway_run_execution_entries WHERE run_id = ? AND work_key = ?",
                (run_id, work_key),
            ).fetchone()
        if row is None:
            return None
        entries = self.list_execution_entries(run_id, through=int(row["sequence"]))
        return entries[-1] if entries and entries[-1].sequence == int(row["sequence"]) else None

    def get_execution_entry_by_work_key_in_lineage(self, run_id: str, work_key: str) -> ExecutionEntry | None:
        """Resolve a committed result from this run or its immutable parents."""
        seen: set[str] = set()
        current = run_id
        for _ in range(16):
            if current in seen:
                return None
            seen.add(current)
            entry = self.get_execution_entry_by_work_key(current, work_key)
            if entry is not None:
                return entry
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT parent_run_id FROM gateway_runs WHERE run_id = ?",
                    (current,),
                ).fetchone()
            parent = row["parent_run_id"] if row is not None else None
            if not isinstance(parent, str) or not parent:
                return None
            current = parent
        return None
