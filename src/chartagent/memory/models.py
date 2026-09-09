"""Provider-independent objects used by session memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

MAX_SESSION_NAME = 128
MAX_RECORD_KIND = 64


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bounded(value: str, limit: int, label: str) -> str:
    value = str(value)
    if not value or len(value) > limit:
        raise ValueError(f"{label} must contain 1-{limit} characters")
    return value


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class Session:
    id: str
    name: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        bounded(self.name, MAX_SESSION_NAME, "session name")


@dataclass
class Run:
    id: str
    session_id: str | None
    ordinal: int
    status: RunStatus = RunStatus.RUNNING
    terminal_kind: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    records: list["Record"] = field(default_factory=list)


@dataclass(frozen=True)
class Record:
    kind: str
    payload: dict[str, Any]
    sequence: int = 0
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        bounded(self.kind, MAX_RECORD_KIND, "record kind")


@dataclass(frozen=True)
class Attachment:
    id: str
    session_id: str | None
    run_id: str | None
    ordinal: int
    canonical_path: str
    filename: str
    media_type: str
    byte_count: int
    sha256: str
    created_at: str = field(default_factory=utc_now)

    def metadata(self) -> dict[str, Any]:
        return {"attachment_id": self.id, "filename": self.filename, "media_type": self.media_type, "byte_count": self.byte_count}
