"""Durable, source-validated Session context summary checkpoints."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
import uuid

from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.records import ContextCompactionOperation, SessionContextCheckpoint
from figura.runtime.validation import _validate_id
from figura.shared.payloads import PayloadError, decode_json, encode_json, payload_read_scope
from figura.shared.source_refs import (
    HistorySourceRef,
    MessageSourceRef,
    ToolResultSourceRef,
    source_ref_from_dict,
)
from figura.storage.database import SqliteDatabase, _utc_now


_SUMMARY_MAX_BYTES = 524288
_SOURCE_REFS_MAX_BYTES = 262144


def _validated_source_refs(
    value: object,
) -> tuple[HistorySourceRef, ...]:
    if not isinstance(value, tuple) or not value:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    refs: list[HistorySourceRef] = []
    identities: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, (MessageSourceRef, ToolResultSourceRef)):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        kind = "message" if isinstance(item, MessageSourceRef) else "tool_result"
        identity = (kind, item.run_id, item.record_id if isinstance(item, MessageSourceRef) else item.call_id)
        if identity in identities:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        identities.add(identity)
        refs.append(item)
    return tuple(refs)


def _encode_checkpoint(checkpoint: SessionContextCheckpoint) -> tuple[str, str]:
    try:
        if not isinstance(checkpoint, SessionContextCheckpoint):
            raise ValueError
        _validate_id(checkpoint.session_id)
        if (
            type(checkpoint.revision) is not int
            or checkpoint.revision < 1
            or not isinstance(checkpoint.covered_run_id, str)
            or not checkpoint.covered_run_id
            or len(checkpoint.covered_run_id.encode("utf-8")) > 128
            or type(checkpoint.covered_run_ordinal) is not int
            or checkpoint.covered_run_ordinal < 1
            or type(checkpoint.covered_record_sequence) is not int
            or checkpoint.covered_record_sequence < 1
            or type(checkpoint.covered_tool_sequence) is not int
            or checkpoint.covered_tool_sequence < 0
            or type(checkpoint.summary_contract_version) is not int
            or checkpoint.summary_contract_version < 1
            or not isinstance(checkpoint.summary, Mapping)
            or (checkpoint.compaction_operation_id is not None and (
                not isinstance(checkpoint.compaction_operation_id, str)
                or not checkpoint.compaction_operation_id
                or len(checkpoint.compaction_operation_id.encode("utf-8")) > 128
            ))
        ):
            raise ValueError
        refs = _validated_source_refs(checkpoint.source_refs)
        summary_json = encode_json(checkpoint.summary, maximum=_SUMMARY_MAX_BYTES)
        source_refs_json = encode_json(
            [ref.to_dict() for ref in refs], maximum=_SOURCE_REFS_MAX_BYTES
        )
        if not isinstance(json.loads(summary_json), dict):
            raise ValueError
        return summary_json, source_refs_json
    except (PayloadError, TypeError, ValueError, AttributeError, OverflowError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None


def _deep_freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _checkpoint_from_row(row: sqlite3.Row) -> SessionContextCheckpoint:
    try:
        summary = decode_json(row["summary_json"], maximum=_SUMMARY_MAX_BYTES)
        refs_value = decode_json(row["source_refs_json"], maximum=_SOURCE_REFS_MAX_BYTES)
        if not isinstance(summary, dict) or not isinstance(refs_value, list):
            raise ValueError
        refs = tuple(source_ref_from_dict(value) for value in refs_value)
        checkpoint = SessionContextCheckpoint(
            session_id=row["session_id"],
            revision=row["revision"],
            covered_run_id=row["covered_run_id"],
            covered_run_ordinal=row["covered_run_ordinal"],
            covered_record_sequence=row["covered_record_sequence"],
            covered_tool_sequence=row["covered_tool_sequence"],
            summary_contract_version=row["summary_contract_version"],
            summary=_deep_freeze(summary),
            source_refs=refs,
            updated_at=row["updated_at"],
            compaction_operation_id=row["compaction_operation_id"],
        )
        _encode_checkpoint(checkpoint)
        return checkpoint
    except (PayloadError, TypeError, ValueError, KeyError, RunError, OverflowError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _validate_ownership(
    connection: sqlite3.Connection,
    checkpoint: SessionContextCheckpoint,
) -> None:
    covered = connection.execute(
        "SELECT r.ordinal, r.status, c.last_committed_record_sequence, "
        "c.last_committed_tool_sequence FROM runs r "
        "JOIN run_execution_checkpoints c USING (run_id) "
        "WHERE r.session_id = ? AND r.run_id = ?",
        (checkpoint.session_id, checkpoint.covered_run_id),
    ).fetchone()
    if (
        covered is None
        or covered["ordinal"] != checkpoint.covered_run_ordinal
        or covered["status"] == "running"
        or checkpoint.covered_record_sequence > covered["last_committed_record_sequence"]
        or checkpoint.covered_tool_sequence > covered["last_committed_tool_sequence"]
    ):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    _validate_coverage_boundary(
        connection,
        checkpoint.session_id,
        checkpoint.covered_run_id,
        checkpoint.covered_record_sequence,
        checkpoint.covered_tool_sequence,
    )

    for source_ref in checkpoint.source_refs:
        if isinstance(source_ref, MessageSourceRef):
            row = connection.execute(
                "SELECT r.ordinal, e.record_sequence FROM runs r "
                "JOIN run_execution_records e USING (run_id) "
                "WHERE r.session_id = ? AND r.run_id = ? AND e.record_id = ? "
                "AND e.record_kind IN ('input', 'model_response')",
                (checkpoint.session_id, source_ref.run_id, source_ref.record_id),
            ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if row["ordinal"] > checkpoint.covered_run_ordinal or (
                row["ordinal"] == checkpoint.covered_run_ordinal
                and row["record_sequence"] > checkpoint.covered_record_sequence
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        elif isinstance(source_ref, ToolResultSourceRef):
            row = connection.execute(
                "SELECT r.ordinal, MAX(f.tool_sequence) AS tool_sequence FROM runs r "
                "JOIN run_tool_execution_facts f USING (run_id) "
                "WHERE r.session_id = ? AND r.run_id = ? AND f.fact_kind = 'tool_result' "
                "AND json_extract(f.payload_json, '$.call_id') = ? GROUP BY r.ordinal",
                (checkpoint.session_id, source_ref.run_id, source_ref.call_id),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT r.ordinal, f.tool_sequence FROM runs r "
                    "JOIN run_tool_execution_facts f USING (run_id) "
                    "WHERE r.session_id = ? AND r.run_id = ? AND f.fact_kind = 'tool_call' "
                    "AND json_extract(f.payload_json, '$.call_id') = ? "
                    "ORDER BY f.tool_sequence LIMIT 1",
                    (checkpoint.session_id, source_ref.run_id, source_ref.call_id),
                ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if row["ordinal"] > checkpoint.covered_run_ordinal or (
                row["ordinal"] == checkpoint.covered_run_ordinal
                and row["tool_sequence"] > checkpoint.covered_tool_sequence
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _validate_coverage_boundary(
    connection: sqlite3.Connection,
    session_id: str,
    run_id: str,
    record_sequence: int,
    tool_sequence: int,
) -> None:
    """Require a coverage cursor to end after a complete, committed interaction."""
    boundary = connection.execute(
        "SELECT e.record_kind, e.record_id, e.payload_json FROM run_execution_records e "
        "JOIN runs r USING (run_id) WHERE r.session_id = ? AND r.run_id = ? "
        "AND e.record_sequence = ?",
        (session_id, run_id, record_sequence),
    ).fetchone()
    if boundary is None or boundary["record_kind"] not in {"model_response", "final_answer"}:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

    response_record_id = boundary["record_id"]
    if boundary["record_kind"] == "final_answer":
        try:
            payload = json.loads(boundary["payload_json"])
            response_record_id = payload["response_record_id"]
        except (TypeError, ValueError, KeyError):
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        response = connection.execute(
            "SELECT record_sequence FROM run_execution_records WHERE run_id = ? "
            "AND record_id = ? AND record_kind = 'model_response'",
            (run_id, response_record_id),
        ).fetchone()
        if response is None or response["record_sequence"] >= record_sequence:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

    if boundary["record_kind"] == "model_response":
        try:
            payload = json.loads(boundary["payload_json"])
            finish_reason = payload["finish_reason"]
        except (TypeError, ValueError, KeyError):
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        calls = connection.execute(
            "SELECT tool_sequence, json_extract(payload_json, '$.call_id') AS call_id "
            "FROM run_tool_execution_facts WHERE run_id = ? AND fact_kind = 'tool_call' "
            "AND json_extract(payload_json, '$.response_record_id') = ?",
            (run_id, boundary["record_id"]),
        ).fetchall()
        if (finish_reason == "tool_calls") != bool(calls):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        for call in calls:
            result = connection.execute(
                "SELECT MAX(tool_sequence) AS tool_sequence FROM run_tool_execution_facts "
                "WHERE run_id = ? AND fact_kind = 'tool_result' "
                "AND json_extract(payload_json, '$.tool_call_sequence') = ?",
                (run_id, call["tool_sequence"]),
            ).fetchone()
            if result is None or result["tool_sequence"] is None or result["tool_sequence"] > tool_sequence:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

    expected_tool_sequence = connection.execute(
        "WITH covered_calls AS ("
        " SELECT f.tool_sequence AS call_sequence FROM run_tool_execution_facts f "
        " JOIN run_execution_records e ON e.run_id = f.run_id "
        " AND e.record_id = json_extract(f.payload_json, '$.response_record_id') "
        " WHERE f.run_id = ? AND f.fact_kind = 'tool_call' AND e.record_sequence <= ?"
        "), covered_facts AS ("
        " SELECT f.tool_sequence FROM run_tool_execution_facts f "
        " WHERE f.run_id = ? AND ("
        "   (f.fact_kind = 'tool_call' AND f.tool_sequence IN (SELECT call_sequence FROM covered_calls))"
        "   OR (f.fact_kind IN ('tool_attempt_started', 'tool_result') AND "
        "       CAST(json_extract(f.payload_json, '$.tool_call_sequence') AS INTEGER) "
        "       IN (SELECT call_sequence FROM covered_calls))"
        " )"
        ") SELECT MAX(tool_sequence) FROM covered_facts",
        (run_id, record_sequence, run_id),
    ).fetchone()[0]
    if (expected_tool_sequence or 0) != tool_sequence:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


class SessionContextCheckpointRepository:
    """Store one replaceable summary projection for each owning Session."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def read(self, session_id: str) -> SessionContextCheckpoint | None:
        _validate_id(session_id)
        with self._database.read_snapshot() as connection:
            row = connection.execute(
                "SELECT * FROM session_context_checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                if connection.execute(
                    "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone() is None:
                    raise RunError(RunErrorCode.SESSION_NOT_FOUND)
                return None
            checkpoint = _checkpoint_from_row(row)
            _validate_ownership(connection, checkpoint)
            return checkpoint

    def replace(
        self,
        checkpoint: SessionContextCheckpoint,
        *,
        expected_revision: int,
    ) -> SessionContextCheckpoint:
        if type(expected_revision) is not int or expected_revision < 0:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        summary_json, source_refs_json = _encode_checkpoint(checkpoint)
        if checkpoint.revision != expected_revision + 1:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        updated = replace(checkpoint, updated_at=_utc_now())
        with self._database.write() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (checkpoint.session_id,)
            ).fetchone() is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            _validate_ownership(connection, updated)
            current = connection.execute(
                "SELECT revision FROM session_context_checkpoints WHERE session_id = ?",
                (checkpoint.session_id,),
            ).fetchone()
            current_revision = 0 if current is None else current["revision"]
            if current_revision != expected_revision:
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if current is None:
                connection.execute(
                    "INSERT INTO session_context_checkpoints(" 
                    "session_id, revision, covered_run_id, covered_run_ordinal, "
                    "covered_record_sequence, covered_tool_sequence, summary_contract_version, "
                    "summary_json, source_refs_json, compaction_operation_id, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        updated.session_id,
                        updated.revision,
                        updated.covered_run_id,
                        updated.covered_run_ordinal,
                        updated.covered_record_sequence,
                        updated.covered_tool_sequence,
                        updated.summary_contract_version,
                        summary_json,
                        source_refs_json,
                        updated.compaction_operation_id,
                        updated.updated_at,
                    ),
                )
            else:
                cursor = connection.execute(
                    "UPDATE session_context_checkpoints SET revision = ?, covered_run_id = ?, "
                    "covered_run_ordinal = ?, covered_record_sequence = ?, covered_tool_sequence = ?, "
                    "summary_contract_version = ?, summary_json = ?, source_refs_json = ?, "
                    "compaction_operation_id = ?, updated_at = ? "
                    "WHERE session_id = ? AND revision = ?",
                    (
                        updated.revision,
                        updated.covered_run_id,
                        updated.covered_run_ordinal,
                        updated.covered_record_sequence,
                        updated.covered_tool_sequence,
                        updated.summary_contract_version,
                        summary_json,
                        source_refs_json,
                        updated.compaction_operation_id,
                        updated.updated_at,
                        updated.session_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RunError(RunErrorCode.STALE_CHECKPOINT)
            if updated.compaction_operation_id is not None:
                operation = connection.execute(
                    "SELECT session_id, status FROM session_context_compaction_operations "
                    "WHERE operation_id = ?",
                    (updated.compaction_operation_id,),
                ).fetchone()
                if (
                    operation is None
                    or operation["session_id"] != updated.session_id
                    or operation["status"] != "preparing"
                ):
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                connection.execute(
                    "UPDATE session_context_compaction_operations SET status = 'completed', "
                    "result_checkpoint_revision = ?, updated_at = ? WHERE operation_id = ?",
                    (updated.revision, updated.updated_at, updated.compaction_operation_id),
                )
        return updated


class ContextCompactionOperationRepository:
    """Persist stable request identity and retry state for compaction calls."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def get_or_create(
        self,
        *,
        session_id: str,
        target_run_id: str,
        base_record_sequence: int,
        base_tool_sequence: int,
        input_checkpoint_revision: int,
        covered_run_id: str,
        covered_run_ordinal: int,
        covered_record_sequence: int,
        covered_tool_sequence: int,
        selection_binding: Mapping[str, object] | None = None,
    ) -> ContextCompactionOperation:
        for identity in (session_id, target_run_id, covered_run_id):
            _validate_id(identity)
        integer_values = (
            base_record_sequence,
            base_tool_sequence,
            input_checkpoint_revision,
            covered_run_ordinal,
            covered_record_sequence,
            covered_tool_sequence,
        )
        if any(type(value) is not int for value in integer_values) or (
            base_record_sequence < 1
            or base_tool_sequence < 0
            or input_checkpoint_revision < 0
            or covered_run_ordinal < 1
            or covered_record_sequence < 1
            or covered_tool_sequence < 0
        ):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        selection_json = None
        if selection_binding is not None:
            if not isinstance(selection_binding, Mapping):
                raise RunError(RunErrorCode.INVALID_REQUEST)
            try:
                selection_json = encode_json({
                    "plan": dict(selection_binding),
                    "summary_contract_version": 2,
                }, maximum=262144)
            except (PayloadError, TypeError, ValueError):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        with self._database.write() as connection:
            target = connection.execute(
                "SELECT r.ordinal, r.status, c.last_committed_record_sequence, "
                "c.last_committed_tool_sequence FROM runs r "
                "JOIN run_execution_checkpoints c USING (run_id) "
                "WHERE r.session_id = ? AND r.run_id = ?",
                (session_id, target_run_id),
            ).fetchone()
            checkpoint = connection.execute(
                "SELECT revision FROM session_context_checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            checkpoint_revision = 0 if checkpoint is None else checkpoint["revision"]
            if target is None or target["status"] != "running":
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            if (
                target["last_committed_record_sequence"] != base_record_sequence
                or target["last_committed_tool_sequence"] != base_tool_sequence
                or checkpoint_revision != input_checkpoint_revision
            ):
                raise RunError(RunErrorCode.STALE_CHECKPOINT)

            row = connection.execute(
                "SELECT * FROM session_context_compaction_operations WHERE target_run_id = ? "
                "AND base_record_sequence = ? AND base_tool_sequence = ?",
                (target_run_id, base_record_sequence, base_tool_sequence),
            ).fetchone()
            if row is not None:
                operation = _operation_from_row(row)
                if (
                    operation.session_id != session_id
                    or operation.input_checkpoint_revision != input_checkpoint_revision
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                stored_covered = connection.execute(
                    "SELECT r.ordinal, r.status, c.last_committed_record_sequence, "
                    "c.last_committed_tool_sequence FROM runs r "
                    "JOIN run_execution_checkpoints c USING (run_id) "
                    "WHERE r.session_id = ? AND r.run_id = ?",
                    (session_id, operation.covered_run_id),
                ).fetchone()
                if (
                    stored_covered is None
                    or stored_covered["status"] == "running"
                    or stored_covered["ordinal"] != operation.covered_run_ordinal
                    or operation.covered_run_ordinal >= target["ordinal"]
                    or operation.covered_record_sequence > stored_covered["last_committed_record_sequence"]
                    or operation.covered_tool_sequence > stored_covered["last_committed_tool_sequence"]
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                _validate_coverage_boundary(
                    connection, session_id, operation.covered_run_id,
                    operation.covered_record_sequence, operation.covered_tool_sequence,
                )
                return operation

            covered = connection.execute(
                "SELECT r.ordinal, r.status, c.last_committed_record_sequence, "
                "c.last_committed_tool_sequence FROM runs r "
                "JOIN run_execution_checkpoints c USING (run_id) "
                "WHERE r.session_id = ? AND r.run_id = ?",
                (session_id, covered_run_id),
            ).fetchone()
            if covered is None or covered["status"] == "running":
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if (
                covered["ordinal"] != covered_run_ordinal
                or covered_run_ordinal >= target["ordinal"]
                or covered_record_sequence > covered["last_committed_record_sequence"]
                or covered_tool_sequence > covered["last_committed_tool_sequence"]
            ):
                raise RunError(RunErrorCode.STALE_CHECKPOINT)
            _validate_coverage_boundary(
                connection, session_id, covered_run_id,
                covered_record_sequence, covered_tool_sequence,
            )

            now = _utc_now()
            operation_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO session_context_compaction_operations(" 
                "operation_id, session_id, target_run_id, base_record_sequence, base_tool_sequence, "
                "input_checkpoint_revision, covered_run_id, covered_run_ordinal, "
                "covered_record_sequence, covered_tool_sequence, status, request_binding_json, "
                "attempt_count, result_checkpoint_revision, failure_code, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'preparing', ?, 0, NULL, NULL, ?, ?)",
                (
                    operation_id,
                    session_id,
                    target_run_id,
                    base_record_sequence,
                    base_tool_sequence,
                    input_checkpoint_revision,
                    covered_run_id,
                    covered_run_ordinal,
                    covered_record_sequence,
                    covered_tool_sequence,
                    selection_json,
                    now,
                    now,
                ),
            )
            created = connection.execute(
                "SELECT * FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            return _operation_from_row(created)

    def bind_request(
        self, operation_id: str, binding: Mapping[str, object]
    ) -> ContextCompactionOperation:
        _validate_id(operation_id)
        try:
            binding_json = encode_json(binding, maximum=262144)
        except (PayloadError, TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        with self._database.write() as connection:
            row = connection.execute(
                "SELECT * FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            operation = _operation_from_row(row)
            if operation.status != "preparing":
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            if row["request_binding_json"] is not None:
                if row["request_binding_json"] != binding_json:
                    current = dict(operation.request_binding or {})
                    incoming = dict(binding)
                    if (
                        current.get("descriptor") is None
                        and incoming.get("descriptor") is not None
                        and current.get("plan") == incoming.get("plan")
                        and current.get("summary_contract_version") == incoming.get("summary_contract_version")
                        and set(incoming) == {"plan", "summary_contract_version", "descriptor"}
                    ):
                        connection.execute(
                            "UPDATE session_context_compaction_operations SET request_binding_json = ?, "
                            "updated_at = ? WHERE operation_id = ? AND status = 'preparing' "
                            "AND request_binding_json = ?",
                            (binding_json, _utc_now(), operation_id, row["request_binding_json"]),
                        )
                        updated = connection.execute(
                            "SELECT * FROM session_context_compaction_operations WHERE operation_id = ?",
                            (operation_id,),
                        ).fetchone()
                        return _operation_from_row(updated)
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                return operation
            connection.execute(
                "UPDATE session_context_compaction_operations SET request_binding_json = ?, updated_at = ? "
                "WHERE operation_id = ? AND status = 'preparing' AND request_binding_json IS NULL",
                (binding_json, _utc_now(), operation_id),
            )
            updated = connection.execute(
                "SELECT * FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            return _operation_from_row(updated)

    @payload_read_scope
    def find_for_target(
        self,
        session_id: str,
        target_run_id: str,
        base_record_sequence: int,
        base_tool_sequence: int,
    ) -> ContextCompactionOperation | None:
        _validate_id(session_id)
        _validate_id(target_run_id)
        if (
            type(base_record_sequence) is not int
            or base_record_sequence < 1
            or type(base_tool_sequence) is not int
            or base_tool_sequence < 0
        ):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM session_context_compaction_operations "
                "WHERE session_id = ? AND target_run_id = ? AND base_record_sequence = ? "
                "AND base_tool_sequence = ?",
                (session_id, target_run_id, base_record_sequence, base_tool_sequence),
            ).fetchone()
        return None if row is None else _operation_from_row(row)

    @payload_read_scope
    def read(self, operation_id: str) -> ContextCompactionOperation:
        _validate_id(operation_id)
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise RunError(RunErrorCode.RUN_NOT_FOUND)
        return _operation_from_row(row)

    def begin_attempt(self, operation_id: str) -> int:
        _validate_id(operation_id)
        with self._database.write() as connection:
            row = connection.execute(
                "SELECT status, request_binding_json, attempt_count "
                "FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            if row["status"] != "preparing" or row["request_binding_json"] is None:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            attempt_count = int(row["attempt_count"]) + 1
            connection.execute(
                "UPDATE session_context_compaction_operations SET attempt_count = ?, updated_at = ? "
                "WHERE operation_id = ? AND status = 'preparing'",
                (attempt_count, _utc_now(), operation_id),
            )
            return attempt_count

    def mark_fallback(
        self, operation_id: str, failure_code: str | None
    ) -> ContextCompactionOperation:
        _validate_id(operation_id)
        if failure_code is not None and (
            not isinstance(failure_code, str) or len(failure_code.encode("utf-8")) > 64
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        with self._database.write() as connection:
            row = connection.execute(
                "SELECT status FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            if row["status"] == "completed":
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            connection.execute(
                "UPDATE session_context_compaction_operations SET status = 'fallback', "
                "failure_code = ?, updated_at = ? WHERE operation_id = ?",
                (failure_code, _utc_now(), operation_id),
            )
            updated = connection.execute(
                "SELECT * FROM session_context_compaction_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            return _operation_from_row(updated)


def _operation_from_row(row: sqlite3.Row) -> ContextCompactionOperation:
    try:
        raw_binding = row["request_binding_json"]
        binding = None if raw_binding is None else decode_json(raw_binding, maximum=262144)
        if binding is not None and not isinstance(binding, dict):
            raise ValueError
        return ContextCompactionOperation(
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            target_run_id=row["target_run_id"],
            base_record_sequence=row["base_record_sequence"],
            base_tool_sequence=row["base_tool_sequence"],
            input_checkpoint_revision=row["input_checkpoint_revision"],
            covered_run_id=row["covered_run_id"],
            covered_run_ordinal=row["covered_run_ordinal"],
            covered_record_sequence=row["covered_record_sequence"],
            covered_tool_sequence=row["covered_tool_sequence"],
            status=row["status"],
            request_binding=None if binding is None else MappingProxyType(binding),
            attempt_count=row["attempt_count"],
            result_checkpoint_revision=row["result_checkpoint_revision"],
            failure_code=row["failure_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (PayloadError, KeyError, TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
