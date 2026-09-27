"""SQLite row and checkpoint-payload mapping for Figura runtime values."""

from __future__ import annotations

import json
import sqlite3

from .._codec import (
    decode_event_payload,
    decode_payload,
    decode_tool_fact,
    validate_provider_continuation_fact,
)
from ..domain.models import (
    ActionKind,
    AttachmentMetadata,
    EventKind,
    ExecutionCheckpoint,
    ExecutionRecord,
    NextAction,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderContinuationFact,
    RecordKind,
    Run,
    RunStatus,
    RunStreamEvent,
    ToolExecutionFact,
    ToolFactKind,
)
from ..errors import RunError, RunErrorCode

def _attachment_from_row(row: sqlite3.Row) -> AttachmentMetadata:
    try:
        return AttachmentMetadata(
            attachment_id=row["attachment_id"],
            session_id=row["session_id"],
            filename=row["filename"],
            media_type=row["media_type"],
            byte_count=row["byte_count"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _run_from_row(row: sqlite3.Row) -> Run:
    try:
        status = RunStatus(row["status"])
    except ValueError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    return Run(
        run_id=row["run_id"],
        session_id=row["session_id"],
        ordinal=row["ordinal"],
        input_record_id=row["input_record_id"],
        status=status,
        provider=row["provider"],
        model=row["model"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        terminal_code=row["terminal_code"],
        terminal_message=row["terminal_message"],
        final_record_id=row["final_record_id"],
    )


def _record_from_row(row: sqlite3.Row) -> ExecutionRecord:
    try:
        kind = RecordKind(row["record_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    schema_version = row["schema_version"]
    if type(schema_version) is not int:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    supported_versions = {1, 2} if kind is RecordKind.MODEL_RESPONSE else {1}
    if schema_version not in supported_versions:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    payload = decode_payload(
        kind,
        row["payload_json"],
        expected_schema_version=schema_version,
    )
    return ExecutionRecord(
        record_id=row["record_id"],
        run_id=row["run_id"],
        record_sequence=row["record_sequence"],
        record_kind=kind,
        payload=payload,
        created_at=row["created_at"],
    )


def _continuation_fact_from_row(row: sqlite3.Row) -> ProviderContinuationFact:
    fact = ProviderContinuationFact(
        continuation_id=row["continuation_id"],
        run_id=row["run_id"],
        response_record_id=row["response_record_id"],
        provider_id=row["provider_id"],
        format_version=row["format_version"],
        schema_version=row["schema_version"],
        reasoning_content=row["reasoning_content"],
        created_at=row["created_at"],
    )
    return validate_provider_continuation_fact(fact, persisted=True)


def _provider_attempt_from_row(row: sqlite3.Row) -> ProviderAttempt:
    try:
        status = ProviderAttemptStatus(row["status"])
    except ValueError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    return ProviderAttempt(
        attempt_id=row["attempt_id"],
        run_id=row["run_id"],
        attempt_sequence=row["attempt_sequence"],
        base_record_sequence=row["base_record_sequence"],
        base_tool_sequence=row["base_tool_sequence"],
        status=status,
        response_record_id=row["response_record_id"],
        failure_code=row["failure_code"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _checkpoint_from_row(row: sqlite3.Row) -> ExecutionCheckpoint:
    if row["schema_version"] != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    return ExecutionCheckpoint(
        run_id=row["run_id"],
        revision=row["revision"],
        last_committed_record_sequence=row["last_committed_record_sequence"],
        last_committed_tool_sequence=(
            row["last_committed_tool_sequence"]
            if "last_committed_tool_sequence" in row.keys()
            else 0
        ),
        next_action=_decode_action(row["next_action_json"]),
        schema_version=row["schema_version"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: sqlite3.Row) -> RunStreamEvent:
    try:
        kind = EventKind(row["event_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return RunStreamEvent(
        run_id=row["run_id"],
        event_sequence=row["event_sequence"],
        event_kind=kind,
        payload=decode_event_payload(kind, row["payload_json"]),
        created_at=row["created_at"],
    )


def _tool_fact_from_row(row: sqlite3.Row) -> ToolExecutionFact:
    try:
        kind = ToolFactKind(row["fact_kind"])
    except ValueError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    payload = decode_tool_fact(kind, row["schema_version"], row["payload_json"])
    return ToolExecutionFact(
        run_id=row["run_id"],
        tool_sequence=row["tool_sequence"],
        fact_kind=kind,
        schema_version=row["schema_version"],
        payload=payload,
        created_at=row["created_at"],
    )


def _encode_action(action: NextAction | None) -> str | None:
    if action is None:
        return None
    if (
        action.action_kind is ActionKind.MODEL
        and action.response_record_id is None
        and action.tool_call_sequence is None
        and action.attempt_id is None
    ):
        value = {"action_kind": "model"}
    elif (
        action.action_kind is ActionKind.PROVIDER_ATTEMPT
        and action.response_record_id is None
        and action.tool_call_sequence is None
        and isinstance(action.attempt_id, str)
        and action.attempt_id
        and len(action.attempt_id.encode("utf-8")) <= 128
    ):
        value = {"action_kind": "provider_attempt", "attempt_id": action.attempt_id}
    elif (
        action.action_kind is ActionKind.FINAL
        and action.response_record_id
        and action.tool_call_sequence is None
        and action.attempt_id is None
    ):
        value = {"action_kind": "final", "response_record_id": action.response_record_id}
    elif (
        action.action_kind is ActionKind.TOOL_EXECUTION
        and action.response_record_id is None
        and type(action.tool_call_sequence) is int
        and action.tool_call_sequence > 0
        and action.attempt_id is None
    ):
        value = {"action_kind": "tool_execution", "tool_call_sequence": action.tool_call_sequence}
    elif (
        action.action_kind is ActionKind.TOOL_ATTEMPT
        and action.response_record_id is None
        and type(action.tool_call_sequence) is int
        and action.tool_call_sequence > 0
        and isinstance(action.attempt_id, str)
        and action.attempt_id
        and len(action.attempt_id.encode("utf-8")) <= 128
    ):
        value = {
            "action_kind": "tool_attempt",
            "tool_call_sequence": action.tool_call_sequence,
            "attempt_id": action.attempt_id,
        }
    else:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _decode_action(raw: str | None) -> NextAction | None:
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > 1024:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        value = json.loads(raw)
        if value == {"action_kind": "model"}:
            return NextAction(ActionKind.MODEL)
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "attempt_id"}
            and value["action_kind"] == "provider_attempt"
            and isinstance(value["attempt_id"], str)
            and value["attempt_id"]
            and len(value["attempt_id"].encode("utf-8")) <= 128
        ):
            return NextAction(ActionKind.PROVIDER_ATTEMPT, attempt_id=value["attempt_id"])
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "response_record_id"}
            and value["action_kind"] == "final"
            and isinstance(value["response_record_id"], str)
            and value["response_record_id"]
            and len(value["response_record_id"].encode("utf-8")) <= 128
        ):
            return NextAction(ActionKind.FINAL, value["response_record_id"])
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "tool_call_sequence"}
            and value["action_kind"] == "tool_execution"
            and type(value["tool_call_sequence"]) is int
            and value["tool_call_sequence"] > 0
        ):
            return NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=value["tool_call_sequence"])
        if (
            isinstance(value, dict)
            and set(value) == {"action_kind", "tool_call_sequence", "attempt_id"}
            and value["action_kind"] == "tool_attempt"
            and type(value["tool_call_sequence"]) is int
            and value["tool_call_sequence"] > 0
            and isinstance(value["attempt_id"], str)
            and value["attempt_id"]
            and len(value["attempt_id"].encode("utf-8")) <= 128
        ):
            return NextAction(
                ActionKind.TOOL_ATTEMPT,
                tool_call_sequence=value["tool_call_sequence"],
                attempt_id=value["attempt_id"],
            )
    except (TypeError, ValueError):
        pass
    raise RunError(RunErrorCode.INTEGRITY_ERROR)
