"""Run and history query primitives for Gateway persistence."""

from __future__ import annotations

import json
import time
from typing import Any

from ..trace import truncate_text
from .persistence_errors import HistoryStoreError
from .protocol import (
    ContinuationKind,
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


class RunPersistenceMixin:
    """Own durable run, idempotency, event and history projections."""

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
        idempotency_continuation_kind: str | None = None,
        idempotency_parent_run_id: str | None = None,
        idempotency_cursor_id: str | None = None,
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
                       created_at, expires_at, continuation_kind, parent_run_id, cursor_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        idempotency_key[:MAX_IDEMPOTENCY_KEY],
                        session_id,
                        run_id,
                        request_fingerprint[:128],
                        now,
                        expires_at,
                        idempotency_continuation_kind,
                        idempotency_parent_run_id,
                        idempotency_cursor_id,
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

    def bind_resume_idempotency(
        self,
        idempotency_key: str,
        session_id: str,
        parent_run_id: str,
        cursor_id: str,
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
                    "cursorId": existing["cursor_id"] if "cursor_id" in existing.keys() else None,
                    "existing": True,
                }
            connection.execute(
                """INSERT INTO gateway_run_idempotency(
                   idempotency_key, session_id, run_id, request_fingerprint,
                   created_at, expires_at, continuation_kind, parent_run_id, cursor_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'resume', ?, ?)""",
                (key, session_id, child_run_id, request_fingerprint[:128], now, expires_at, parent_run_id, cursor_id),
            )
        return {
            "idempotencyKey": key,
            "sessionId": session_id,
            "runId": child_run_id,
            "requestFingerprint": request_fingerprint[:128],
            "parentRunId": parent_run_id,
            "cursorId": cursor_id,
            "existing": False,
        }

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
                          (SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count
                     FROM gateway_runs r WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
        return [self._summary_with_recovery(row) for row in rows]

    def get_run(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            self._cleanup_connection(connection)
            row = connection.execute(
                "SELECT run_id, session_id, status, created_at, updated_at, expires_at, terminal_code, terminal_message, answer_source, history_warning, provider, model, cancel_requested, retry_of, parent_run_id, root_run_id, continuation_kind, (SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count FROM gateway_runs r WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
        return self._summary_with_recovery(row) if row else None

    def _summary_with_recovery(self, row) -> dict[str, Any]:
        summary = self._run_summary(row)
        derived = self.get_recovery(row["session_id"], row["run_id"])
        if derived is not None:
            summary["recovery"] = derived
        return summary

    @staticmethod
    def _run_summary(row) -> dict[str, Any]:
        result = {
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
        }
        return result

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


__all__ = ["RunPersistenceMixin"]
