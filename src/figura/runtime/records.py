"""Persisted execution facts and Runtime snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

from figura.providers.models import ProviderUsage
from figura.sources.models import AttachmentMetadata
from figura.tools.contracts import ReplayEffect, ToolExecutionError, ToolOutcome

from .models import (
    EventKind,
    ExecutionCheckpoint,
    RecordKind,
    Run,
    Session,
    ToolFactKind,
)


@dataclass(frozen=True)
class SessionSnapshot:
    session: Session
    run_states: tuple[RunState, ...]
    attachments: tuple[AttachmentMetadata, ...]


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
    continuation_ref: str | None = field(default=None, repr=False)
    schema_version: int = 2


@dataclass(frozen=True)
class ProviderContinuationFact:
    """Private continuation payload attached to its originating model response."""

    continuation_id: str = field(repr=False)
    run_id: str
    response_record_id: str
    provider_id: str
    format_version: int
    schema_version: int
    reasoning_content: str | None = field(repr=False)
    created_at: str


@dataclass(frozen=True)
class ProviderAttempt:
    attempt_id: str
    run_id: str
    attempt_sequence: int
    base_record_sequence: int
    base_tool_sequence: int
    status: ProviderAttemptStatus
    response_record_id: str | None
    failure_code: str | None
    started_at: str
    finished_at: str | None


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
    provider_continuations: tuple[ProviderContinuationFact, ...] = field(default=(), repr=False)
    provider_attempts: tuple[ProviderAttempt, ...] = field(default=(), repr=False)

