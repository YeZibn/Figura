"""Durable Run domain values owned by Figura."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TypeAlias

from figura.providers.models import ProviderUsage
from figura.tools.contracts import ReplayEffect, ToolExecutionError, ToolOutcome


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RecordKind(str, Enum):
    INPUT = "input"
    MODEL_RESPONSE = "model_response"
    FINAL_ANSWER = "final_answer"


class ActionKind(str, Enum):
    MODEL = "model"
    TOOL_EXECUTION = "tool_execution"
    TOOL_ATTEMPT = "tool_attempt"
    FINAL = "final"


class ToolFactKind(str, Enum):
    TOOL_CALL = "tool_call"
    TOOL_ATTEMPT_STARTED = "tool_attempt_started"
    TOOL_RESULT = "tool_result"


class EventKind(str, Enum):
    RUN_CREATED = "run_created"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_INTERRUPTED = "run_interrupted"


class TerminalCode(str, Enum):
    EXECUTION_FAILED = "execution_failed"
    INVALID_RESPONSE = "invalid_response"
    STORAGE_ERROR = "storage_error"
    INTERRUPTED = "interrupted"


TERMINAL_MESSAGES: Mapping[TerminalCode, str] = MappingProxyType(
    {
        TerminalCode.EXECUTION_FAILED: "Run 执行未能完成。",
        TerminalCode.INVALID_RESPONSE: "Run 收到无法接受的模型结果。",
        TerminalCode.STORAGE_ERROR: "Run 执行结果未能保存。",
        TerminalCode.INTERRUPTED: "Run 已中断。",
    }
)


@dataclass(frozen=True)
class Session:
    session_id: str
    name: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Run:
    run_id: str
    session_id: str
    ordinal: int
    input_record_id: str
    status: RunStatus
    provider: str
    model: str
    created_at: str
    started_at: str
    finished_at: str | None = None
    terminal_code: str | None = None
    terminal_message: str | None = None
    final_record_id: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return the bounded Run summary without input or execution payloads."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "ordinal": self.ordinal,
            "status": self.status.value,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "terminal_code": self.terminal_code,
            "terminal_message": self.terminal_message,
            "final_record_id": self.final_record_id,
        }


@dataclass(frozen=True)
class RunInput:
    text: str = field(repr=False)
    attachment_ids: tuple[str, ...]
    requested_provider: str
    requested_model: str
    schema_version: int = 1


@dataclass(frozen=True)
class ModelResponseFact:
    provider_id: str
    model_id: str
    assistant_content: str = field(repr=False)
    finish_reason: str
    usage: ProviderUsage | None = None
    provider_response_id: str | None = None
    schema_version: int = 1


@dataclass(frozen=True)
class FinalAnswerFact:
    response_record_id: str
    artifact_refs: tuple[str, ...] = ()
    guard_version: str = "text-only-v1"
    schema_version: int = 1


RecordPayload: TypeAlias = RunInput | ModelResponseFact | FinalAnswerFact


@dataclass(frozen=True)
class ToolCallFact:
    response_record_id: str
    call_id: str
    tool_name: str
    arguments_json: str = field(repr=False)
    position: int = 0
    registry_version: str = ""
    schema_version: int = 1


@dataclass(frozen=True)
class ToolAttemptStartedFact:
    tool_call_sequence: int
    call_id: str
    attempt_id: str
    attempt_number: int
    replay_effect: ReplayEffect
    registry_version: str
    schema_version: int = 1


@dataclass(frozen=True)
class ToolResultFact:
    tool_call_sequence: int
    attempt_id: str
    call_id: str
    tool_name: str
    outcome: ToolOutcome
    result: Mapping[str, object] | None = field(default=None, repr=False)
    error: ToolExecutionError | None = None
    schema_version: int = 1


ToolFactPayload: TypeAlias = ToolCallFact | ToolAttemptStartedFact | ToolResultFact


@dataclass(frozen=True)
class ToolExecutionFact:
    run_id: str
    tool_sequence: int
    fact_kind: ToolFactKind
    schema_version: int
    payload: ToolFactPayload = field(repr=False)
    created_at: str


@dataclass(frozen=True)
class ExecutionRecord:
    record_id: str
    run_id: str
    record_sequence: int
    record_kind: RecordKind
    payload: RecordPayload = field(repr=False)
    created_at: str


@dataclass(frozen=True)
class NextAction:
    action_kind: ActionKind
    response_record_id: str | None = None
    tool_call_sequence: int | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class ExecutionCheckpoint:
    run_id: str
    revision: int
    last_committed_record_sequence: int
    last_committed_tool_sequence: int
    next_action: NextAction | None
    schema_version: int
    updated_at: str


EventValue: TypeAlias = str | int | tuple[str, ...]


@dataclass(frozen=True)
class RunStreamEvent:
    run_id: str
    event_sequence: int
    event_kind: EventKind
    payload: Mapping[str, EventValue]
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "event_sequence": self.event_sequence,
            "event_kind": self.event_kind.value,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class RunState:
    run: Run
    records: tuple[ExecutionRecord, ...] = field(repr=False)
    checkpoint: ExecutionCheckpoint
    events: tuple[RunStreamEvent, ...]
    tool_facts: tuple[ToolExecutionFact, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class RunCreateRequest:
    session_id: str
    text: str = field(repr=False)
    provider_id: str
    model_id: str
    idempotency_key: str = field(repr=False)
    attachment_ids: tuple[str, ...] = ()
