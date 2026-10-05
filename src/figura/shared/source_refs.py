"""Stable references into canonical Run records and tool-result facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class MessageSourceRef:
    run_id: str
    record_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.run_id, "run_id")
        _validate_identifier(self.record_id, "record_id")

    def to_dict(self) -> dict[str, str]:
        return {"kind": "message", "run_id": self.run_id, "record_id": self.record_id}


@dataclass(frozen=True)
class ToolResultSourceRef:
    run_id: str
    call_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.run_id, "run_id")
        _validate_identifier(self.call_id, "call_id")

    def to_dict(self) -> dict[str, str]:
        return {"kind": "tool_result", "run_id": self.run_id, "call_id": self.call_id}


HistorySourceRef: TypeAlias = MessageSourceRef | ToolResultSourceRef


def source_ref_from_dict(value: object) -> HistorySourceRef:
    if not isinstance(value, dict):
        raise ValueError("source reference must be an object")
    kind = value.get("kind")
    if kind == "message" and set(value) == {"kind", "run_id", "record_id"}:
        return MessageSourceRef(value["run_id"], value["record_id"])
    if kind == "tool_result" and set(value) == {"kind", "run_id", "call_id"}:
        return ToolResultSourceRef(value["run_id"], value["call_id"])
    raise ValueError("source reference has an unknown kind or fields")


def _validate_identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty opaque identifier")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} must be valid UTF-8") from None
