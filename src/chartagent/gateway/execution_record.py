"""Versioned private execution facts and their compact recovery cursor."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

EXECUTION_RECORD_VERSION = 1
MAX_EXECUTION_ENTRY_BYTES = 512 * 1024
MAX_EXECUTION_CURSOR_BYTES = 16 * 1024
MAX_EXECUTION_ENTRIES_PER_RUN = 4096

EntryKind = Literal[
    "input",
    "model_response",
    "tool_result",
    "verification_result",
    "promotion_result",
    "final_answer",
]
ActionKind = Literal["model", "tool", "verify", "promote", "final"]

_ENTRY_KINDS = frozenset({
    "input", "model_response", "tool_result", "verification_result", "promotion_result", "final_answer",
})
_ACTION_KINDS = frozenset({"model", "tool", "verify", "promote", "final"})
_CURSOR_REFERENCE_KEYS = frozenset({"parentRunId", "parentCursor"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_REFERENCE_PREFIXES = {
    "messageEntryId": "exe_",
    "stagedRef": "stg_",
    "verificationRef": "ver_",
    "answerEntryId": "exe_",
}


class ExecutionRecordError(ValueError):
    """An execution record is malformed, oversized, or unsupported."""


def execution_cursor_id(run_id: str, entry_cursor: int) -> str:
    """Return a bounded opaque public reference for one committed cursor."""
    digest = hashlib.sha256(f"{run_id}:{int(entry_cursor)}".encode("utf-8")).hexdigest()[:32]
    return f"cur_{digest}"


def _canonical_json(value: Any, *, limit: int, what: str) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ExecutionRecordError(f"{what} is not JSON-safe") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise ExecutionRecordError(f"{what} exceeds the size limit")
    return encoded


def _validate_json_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 24:
        raise ExecutionRecordError("execution payload is too deeply nested")
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        if len(value) > 4096:
            raise ExecutionRecordError("execution payload has too many list items")
        for item in value:
            _validate_json_tree(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 4096 or any(not isinstance(key, str) or len(key) > 256 for key in value):
            raise ExecutionRecordError("execution payload has invalid object keys")
        for item in value.values():
            _validate_json_tree(item, depth=depth + 1)
        return
    raise ExecutionRecordError("execution payload contains an unsupported value")


def _identifier(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ExecutionRecordError(f"{what} is invalid")
    return value


@dataclass(frozen=True)
class NextAction:
    """Typed description of the one action allowed after the committed prefix."""

    kind: ActionKind
    message_entry_id: str | None = None
    call_id: str | None = None
    staged_ref: str | None = None
    verification_ref: str | None = None
    answer_entry_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        kind = self.kind
        if kind not in _ACTION_KINDS:
            raise ExecutionRecordError("unsupported next action")
        result: dict[str, str] = {"kind": kind}
        if kind == "tool":
            result["messageEntryId"] = _identifier(self.message_entry_id, "message entry id")
            if not result["messageEntryId"].startswith("exe_"):
                raise ExecutionRecordError("message entry reference is invalid")
            result["callId"] = _identifier(self.call_id, "tool call id")
        elif kind == "verify":
            result["stagedRef"] = _identifier(self.staged_ref, "staged reference")
            if not result["stagedRef"].startswith("stg_"):
                raise ExecutionRecordError("staged reference is invalid")
        elif kind == "promote":
            result["stagedRef"] = _identifier(self.staged_ref, "staged reference")
            result["verificationRef"] = _identifier(self.verification_ref, "verification reference")
            if not result["stagedRef"].startswith("stg_") or not result["verificationRef"].startswith("ver_"):
                raise ExecutionRecordError("promotion reference is invalid")
        elif kind == "final":
            result["answerEntryId"] = _identifier(self.answer_entry_id, "answer entry id")
            if not result["answerEntryId"].startswith("exe_"):
                raise ExecutionRecordError("answer entry reference is invalid")
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "NextAction":
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise ExecutionRecordError("next action must be an object")
        kind = value["kind"]
        if kind not in _ACTION_KINDS:
            raise ExecutionRecordError("unsupported next action")
        required = {
            "model": {"kind"},
            "tool": {"kind", "messageEntryId", "callId"},
            "verify": {"kind", "stagedRef"},
            "promote": {"kind", "stagedRef", "verificationRef"},
            "final": {"kind", "answerEntryId"},
        }[kind]
        if set(value) != required:
            raise ExecutionRecordError("next action has unexpected or missing fields")
        for field, prefix in _REFERENCE_PREFIXES.items():
            if field in value and (
                not isinstance(value[field], str) or not value[field].startswith(prefix)
            ):
                raise ExecutionRecordError("next action reference is invalid")
        return cls(
            kind=kind,
            message_entry_id=value.get("messageEntryId"),
            call_id=value.get("callId"),
            staged_ref=value.get("stagedRef"),
            verification_ref=value.get("verificationRef"),
            answer_entry_id=value.get("answerEntryId"),
        )


@dataclass(frozen=True)
class ExecutionCursor:
    """Compact cursor pointing only at a committed execution prefix."""

    run_id: str
    entry_cursor: int
    turn: int
    next_action: NextAction
    references: dict[str, Any]
    version: int = EXECUTION_RECORD_VERSION

    def to_json(self) -> str:
        if self.version != EXECUTION_RECORD_VERSION:
            raise ExecutionRecordError("unsupported execution cursor version")
        if self.entry_cursor < 0 or self.turn < 0:
            raise ExecutionRecordError("execution cursor counters are invalid")
        _identifier(self.run_id, "run id")
        if not isinstance(self.references, dict):
            raise ExecutionRecordError("execution cursor references are invalid")
        if not set(self.references).issubset(_CURSOR_REFERENCE_KEYS):
            raise ExecutionRecordError("execution cursor contains non-reference state")
        if self.references:
            if set(self.references) != _CURSOR_REFERENCE_KEYS:
                raise ExecutionRecordError("execution parent reference is incomplete")
            parent_run_id = _identifier(self.references["parentRunId"], "parent run id")
            parent_cursor = self.references["parentCursor"]
            if parent_run_id == self.run_id or not isinstance(parent_cursor, int) or parent_cursor < 1:
                raise ExecutionRecordError("execution parent reference is invalid")
        _validate_json_tree(self.references)
        return _canonical_json({
            "version": self.version,
            "runId": self.run_id,
            "entryCursor": self.entry_cursor,
            "turn": self.turn,
            "nextAction": self.next_action.to_dict(),
            "references": self.references,
        }, limit=MAX_EXECUTION_CURSOR_BYTES, what="execution cursor")

    @classmethod
    def from_json(cls, payload: str) -> "ExecutionCursor":
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_EXECUTION_CURSOR_BYTES:
            raise ExecutionRecordError("execution cursor is unavailable")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ExecutionRecordError("execution cursor is invalid") from exc
        if not isinstance(value, dict) or value.get("version") != EXECUTION_RECORD_VERSION:
            raise ExecutionRecordError("unsupported execution cursor version")
        if set(value) != {"version", "runId", "entryCursor", "turn", "nextAction", "references"}:
            raise ExecutionRecordError("execution cursor has unexpected or missing fields")
        if not isinstance(value["entryCursor"], int) or not isinstance(value["turn"], int):
            raise ExecutionRecordError("execution cursor counters are invalid")
        result = cls(
            run_id=_identifier(value["runId"], "run id"),
            entry_cursor=value["entryCursor"],
            turn=value["turn"],
            next_action=NextAction.from_dict(value["nextAction"]),
            references=value["references"],
        )
        result.to_json()
        return result


@dataclass(frozen=True)
class ExecutionEntry:
    """One bounded private fact in a run's ordered execution history."""

    run_id: str
    sequence: int
    kind: EntryKind
    payload: dict[str, Any]
    entry_id: str | None = None
    work_key: str | None = None
    created_at: str | None = None

    def normalized(self) -> "ExecutionEntry":
        if self.kind not in _ENTRY_KINDS:
            raise ExecutionRecordError("unsupported execution entry type")
        if self.sequence < 1:
            raise ExecutionRecordError("execution entry sequence must be positive")
        _identifier(self.run_id, "run id")
        entry_id = _identifier(self.entry_id or f"exe_{uuid4().hex}", "entry id")
        if not entry_id.startswith("exe_"):
            raise ExecutionRecordError("execution entry id is invalid")
        if self.work_key is not None:
            _identifier(self.work_key, "work key")
        if not isinstance(self.payload, dict):
            raise ExecutionRecordError("execution payload must be an object")
        _validate_json_tree(self.payload)
        _canonical_json(self.payload, limit=MAX_EXECUTION_ENTRY_BYTES, what="execution payload")
        return ExecutionEntry(
            run_id=self.run_id,
            sequence=self.sequence,
            kind=self.kind,
            payload=self.payload,
            entry_id=entry_id,
            work_key=self.work_key,
            created_at=self.created_at or datetime.now(timezone.utc).isoformat(),
        )

    def payload_json(self) -> str:
        return _canonical_json(self.payload, limit=MAX_EXECUTION_ENTRY_BYTES, what="execution payload")


__all__ = [
    "ActionKind",
    "EntryKind",
    "EXECUTION_RECORD_VERSION",
    "ExecutionCursor",
    "ExecutionEntry",
    "ExecutionRecordError",
    "execution_cursor_id",
    "MAX_EXECUTION_CURSOR_BYTES",
    "MAX_EXECUTION_ENTRIES_PER_RUN",
    "MAX_EXECUTION_ENTRY_BYTES",
    "NextAction",
]
