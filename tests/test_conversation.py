"""Tests for the in-memory multi-turn conversation session.

Uses a fake LLM client so no real endpoint is touched. The fake records every
(messages, model) call and returns a fixed NormalizedResult.
"""

from __future__ import annotations

from typing import List, Optional

from chartagent import Conversation
from chartagent.client.models import NormalizedResult


class FakeClient:
    """Records calls and returns canned replies."""

    def __init__(self, replies: Optional[List[str]] = None) -> None:
        self.replies = replies or []
        self.seen_messages: List[List[dict]] = []
        self.seen_models: List[Optional[str]] = []
        self._idx = 0

    def chat(self, messages, *, model=None, **__):
        self.seen_messages.append(list(messages))
        self.seen_models.append(model)
        text = self.replies[self._idx] if self._idx < len(self.replies) else f"reply{self._idx}"
        self._idx += 1
        return NormalizedResult(
            content=text,
            reasoning="SECRET-REASONING",
            tool_calls=[],
            finish_reason="stop",
            usage=None,
            raw=None,
        )


def _talk(conv: Conversation, *texts: str) -> List[str]:
    return [conv.run(t) for t in texts]


def test_turns_accumulate_context():
    fake = FakeClient()
    conv = Conversation(fake)

    assert _talk(conv, "hello", "how are you") == ["reply0", "reply1"]

    assert len(fake.seen_messages) == 2
    # First call: only the first user message.
    assert fake.seen_messages[0] == [{"role": "user", "content": "hello"}]
    # Second call: carries the full prior context (turn 1 user + assistant).
    assert fake.seen_messages[1] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "reply0"},
        {"role": "user", "content": "how are you"},
    ]
    # Session history reflects all accumulated turns.
    assert len(conv.history) == 4


def test_reset_clears_history_back_to_system():
    fake = FakeClient(replies=["a", "b", "c"])
    conv = Conversation(fake, system="SYS")

    _talk(conv, "1", "2", "3")
    assert len(conv.history) == 7  # system + 3 pairs

    conv.reset()
    assert conv.history == [{"role": "system", "content": "SYS"}]

    # A fresh turn starts from just the system prompt.
    conv.run("again")
    assert fake.seen_messages[-1][0] == {"role": "system", "content": "SYS"}
    assert fake.seen_messages[-1][1] == {"role": "user", "content": "again"}


def test_assistant_history_excludes_reasoning():
    fake = FakeClient()
    conv = Conversation(fake)

    conv.run("tell me a secret")
    last = conv.history[-1]
    assert last == {"role": "assistant", "content": "reply0"}
    # Reasoning never leaks into history.
    assert "SECRET-REASONING" not in [m.get("content", "") for m in conv.history]

    # And a follow-up call does not carry any reasoning either.
    conv.run("continue")
    assistant_entries = [
        m for m in fake.seen_messages[-1] if m.get("role") == "assistant"
    ]
    assert assistant_entries == [{"role": "assistant", "content": "reply0"}]
    # The newest reply lands in history content-only, reasoning-free.
    assert conv.history[-1] == {"role": "assistant", "content": "reply1"}


def test_default_model_used_and_overridable():
    fake = FakeClient(replies=["x", "y", "z"])
    conv = Conversation(fake, model="default-model")

    conv.run("hi")                 # uses session default
    conv.run("hi again", model="override")  # per-turn override wins

    assert fake.seen_models[0] == "default-model"
    assert fake.seen_models[1] == "override"