"""Memory interfaces and the default ephemeral implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from .context import build_context, sanitize_payload
from .models import Run, RunStatus, Session, bounded, utc_now


class AgentMemory(ABC):
    session: Session | None

    @abstractmethod
    def begin_run(self, run_id: str | None = None) -> Run: ...
    @abstractmethod
    def append(self, run: Run, kind: str, payload: dict[str, Any]) -> None: ...
    @abstractmethod
    def finish(self, run: Run, status: RunStatus, terminal_kind: str | None = None) -> None: ...
    @abstractmethod
    def context(self, run: Run, system: dict[str, Any] | None = None, budget: int = 24000, current_messages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]: ...


class InMemoryAgentMemory(AgentMemory):
    def __init__(self, session: Session | None = None, *, context_budget: int = 24000) -> None:
        self.session = session
        self.context_budget = context_budget
        self.runs: list[Run] = []

    def begin_run(self, run_id: str | None = None) -> Run:
        if run_id is None:
            run_id = str(uuid.uuid4())
        elif not isinstance(run_id, str):
            raise ValueError("run id must be text")
        run_id = bounded(run_id, 128, "run id")
        if any(item.id == run_id for item in self.runs):
            raise ValueError(f"run id already exists: {run_id}")
        run = Run(run_id, self.session.id if self.session else None, len(self.runs) + 1)
        self.runs.append(run)
        return run

    def append(self, run: Run, kind: str, payload: dict[str, Any]) -> None:
        from .models import Record
        run.records.append(Record(kind, sanitize_payload(payload), len(run.records)))
        run.updated_at = utc_now()

    def finish(self, run: Run, status: RunStatus, terminal_kind: str | None = None) -> None:
        run.status = RunStatus(status)
        run.terminal_kind = terminal_kind
        run.updated_at = utc_now()

    def context(self, run: Run, system: dict[str, Any] | None = None, budget: int = 24000, current_messages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return build_context(system, [item for item in self.runs if item.id != run.id], run.records, current_messages=current_messages, budget=budget or self.context_budget)

    def reset(self) -> None:
        self.runs.clear()
