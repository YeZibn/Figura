"""Runtime-owned value objects."""

from __future__ import annotations

from dataclasses import dataclass

from ..attachments import AttachmentRegistry
from ..agent import Agent
from ..memory import SQLiteAgentMemory


@dataclass
class AgentRuntime:
    """Constructed Agent and resources owned by one named runtime."""

    agent: Agent
    memory: SQLiteAgentMemory | None
    attachments: AttachmentRegistry

    def close(self) -> None:
        if self.memory is not None:
            self.memory.close()


__all__ = ["AgentRuntime"]
