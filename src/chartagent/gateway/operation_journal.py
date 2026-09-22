"""Durable operation journal primitives used by Gateway persistence."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from ..trace import truncate_text
from .protocol import OperationState, utc_timestamp
from .recovery import bounded_operation_result


class OperationJournalMixin:
    """Persistence-independent operation journal behavior.

    The mixin owns only operation-row semantics.  The concrete persistence
    class supplies the database connection, lock, cleanup policy, and
    retention configuration.
    """

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


__all__ = ["OperationJournalMixin"]
