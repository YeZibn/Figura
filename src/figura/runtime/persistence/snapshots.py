"""Consistent cross-table reads for Runtime Session history."""

from __future__ import annotations

from figura.sources.repository import attachment_from_row
from figura.storage.database import SqliteDatabase

from ..errors import RunError, RunErrorCode
from ..models import RunStatus
from ..records import RunInput, RunState, SessionSnapshot
from ..validation import _validate_id
from .mappers import _session_from_row
from .runs import RunRepository, _require_attachment_ownership


class SnapshotRepository:
    def __init__(self, database: SqliteDatabase, runs: RunRepository) -> None:
        self._database = database
        self._runs = runs

    def read_session_snapshot(self, session_id: str) -> SessionSnapshot:
        _validate_id(session_id)
        with self._database.read_snapshot() as connection:
            session_row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise RunError(RunErrorCode.SESSION_NOT_FOUND)
            run_rows = connection.execute(
                "SELECT run_id FROM runs WHERE session_id = ? ORDER BY ordinal",
                (session_id,),
            ).fetchall()
            states: list[RunState] = []
            for row in run_rows:
                state = self._runs._read_run_state_from_connection(
                    connection, session_id, row["run_id"]
                )
                input_payload = state.records[0].payload
                if not isinstance(input_payload, RunInput):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                _require_attachment_ownership(
                    connection,
                    session_id,
                    input_payload.attachment_ids,
                    integrity=True,
                )
                states.append(state)
            if [state.run.ordinal for state in states] != list(range(1, len(states) + 1)):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            attachment_rows = connection.execute(
                "SELECT * FROM attachments WHERE session_id = ? "
                "ORDER BY created_at, attachment_id",
                (session_id,),
            ).fetchall()
        return SessionSnapshot(
            session=_session_from_row(session_row),
            run_states=tuple(states),
            attachments=tuple(attachment_from_row(row) for row in attachment_rows),
        )

    def read_prior_run_states(self, session_id: str, run_id: str) -> tuple[RunState, ...]:
        """Load every earlier Run in one Session snapshot, in ordinal order."""
        _validate_id(session_id)
        _validate_id(run_id)
        with self._database.read_snapshot() as connection:
            target_row = connection.execute(
                "SELECT ordinal FROM runs WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
            if target_row is None:
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            target_ordinal = int(target_row["ordinal"])
            prior_rows = connection.execute(
                "SELECT run_id, ordinal, status FROM runs "
                "WHERE session_id = ? AND ordinal < ? ORDER BY ordinal",
                (session_id, target_ordinal),
            ).fetchall()
            if [int(row["ordinal"]) for row in prior_rows] != list(range(1, target_ordinal)):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if any(row["status"] == RunStatus.RUNNING.value for row in prior_rows):
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            states: list[RunState] = []
            for row in prior_rows:
                state = self._runs._read_run_state_from_connection(
                    connection, session_id, row["run_id"]
                )
                input_payload = state.records[0].payload
                if not isinstance(input_payload, RunInput):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                _require_attachment_ownership(
                    connection,
                    session_id,
                    input_payload.attachment_ids,
                    integrity=True,
                )
                states.append(state)
            return tuple(states)
