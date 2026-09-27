"""Immutable, transient message projections derived from persisted Run facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias


@dataclass(frozen=True)
class MemoryToolCall:
    call_id: str
    tool_name: str
    arguments_json: str = field(repr=False)
    position: int
    registry_version: str


@dataclass(frozen=True)
class UserMessage:
    run_id: str
    run_ordinal: int
    source_record_id: str
    text: str = field(repr=False)
    attachment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssistantMessage:
    run_id: str
    run_ordinal: int
    source_record_id: str
    content: str = field(repr=False)
    tool_calls: tuple[MemoryToolCall, ...] = ()


@dataclass(frozen=True)
class ToolMessage:
    run_id: str
    run_ordinal: int
    source_tool_sequence: int
    tool_call_id: str
    content: str = field(repr=False)


MemoryMessage: TypeAlias = UserMessage | AssistantMessage | ToolMessage


@dataclass(frozen=True)
class SessionHistory:
    session_id: str
    target_run_id: str
    target_run_ordinal: int
    messages: tuple[MemoryMessage, ...] = field(default=(), repr=False)
