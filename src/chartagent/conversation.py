"""Stateful multi-turn conversation session.

Owns its message history in memory and drives each turn through an
``LLMClient``. The assistant side of history is built with
``append_to_history`` (content-only), so reasoning from deep-thinking providers
never enters history.
"""

from __future__ import annotations

from typing import List, Optional

from openai.types.chat import ChatCompletionMessageParam

from .client import LLMClient, append_to_history


class Conversation:
    """An in-memory, multi-turn chat session backed by an :class:`LLMClient`.

    The caller drives the turn loop: submit a user message via :meth:`run`,
    get back the assistant's content. History accumulates in memory across
    calls; the session itself has no state beyond its ``messages``.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        system: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._client = client
        self._model = model
        self._system = system
        self._messages: List[ChatCompletionMessageParam] = []
        self._reset_messages()

    def _reset_messages(self) -> None:
        self._messages = (
            [{"role": "system", "content": self._system}] if self._system else []
        )

    # -- public API --------------------------------------------------------- #
    @property
    def history(self) -> List[ChatCompletionMessageParam]:
        """Read-only view of the in-memory conversation history."""
        return list(self._messages)

    def reset(self) -> None:
        """Clear the conversation back to its initial system prompt (if any)."""
        self._reset_messages()

    def run(self, text: str, *, model: Optional[str] = None) -> str:
        """Submit one user turn and return the assistant's reply content.

        ``text`` is appended as a user message, sent to the client with the
        full history, and the assistant reply (content only) is appended back.
        A per-turn ``model`` overrides the session default; if neither is set,
        the client uses its own configured model.
        """
        use_model = model or self._model
        self._messages.append({"role": "user", "content": text})
        result = self._client.chat(self._messages, model=use_model)
        append_to_history(self._messages, result)
        return result.content