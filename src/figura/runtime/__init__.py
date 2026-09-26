"""Figura Run persistence and coordination boundary."""

from .coordinator import RunCoordinator
from .errors import RunError, RunErrorCode
from .models import (
    ActionKind,
    EventKind,
    ExecutionCheckpoint,
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    NextAction,
    RecordKind,
    Run,
    RunCreateRequest,
    RunInput,
    RunState,
    RunStatus,
    RunStreamEvent,
    Session,
    TerminalCode,
)
from .store import FiguraRunStore

__all__ = [
    "ActionKind",
    "EventKind",
    "ExecutionCheckpoint",
    "ExecutionRecord",
    "FiguraRunStore",
    "FinalAnswerFact",
    "ModelResponseFact",
    "NextAction",
    "RecordKind",
    "Run",
    "RunCoordinator",
    "RunCreateRequest",
    "RunError",
    "RunErrorCode",
    "RunInput",
    "RunState",
    "RunStatus",
    "RunStreamEvent",
    "Session",
    "TerminalCode",
]
