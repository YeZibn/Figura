"""Small SQL helpers shared by atomic execution transactions."""

from __future__ import annotations

import sqlite3

from ..codecs.tools import encode_tool_fact
from ..models import ToolFactKind
from ..records import ToolAttemptStartedFact, ToolCallFact, ToolExecutionFact, ToolResultFact


def _insert_tool_fact(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    tool_sequence: int,
    kind: ToolFactKind,
    payload: ToolCallFact | ToolAttemptStartedFact | ToolResultFact,
    created_at: str,
) -> ToolExecutionFact:
    raw_payload = encode_tool_fact(kind, payload)
    connection.execute(
        "INSERT INTO run_tool_execution_facts(run_id, tool_sequence, fact_kind, schema_version, payload_json, created_at) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (run_id, tool_sequence, kind.value, raw_payload, created_at),
    )
    return ToolExecutionFact(
        run_id=run_id,
        tool_sequence=tool_sequence,
        fact_kind=kind,
        schema_version=1,
        payload=payload,
        created_at=created_at,
    )


def _next_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM run_stream_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])
