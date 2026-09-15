"""Shared test fixtures: a fake transport layered under the client.

The client only touches the ``openai`` SDK through ``_openai_factory``, so
tests inject a fake with no network. This fake records connection kwargs and
each request so behavior (knots, retries, normalization) can be asserted.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Optional, Sequence

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chartagent import client as client_mod  # noqa: E402
from chartagent.client import client as _client_module  # noqa: E402


class FakeSDK:
    """Mimics the ``openai`` client surface enough for tests."""

    def __init__(self, backend: "FakeBackend", **conn_kwargs: Any) -> None:
        self.conn_kwargs = conn_kwargs
        self.backend = backend

    @property
    def chat(self) -> "SimpleNamespace":
        completions = FakeCompletions(self.backend)
        return SimpleNamespace(completions=completions)


class FakeCompletions:
    def __init__(self, backend: "FakeBackend") -> None:
        self.backend = backend
        self.last_request: Optional[dict] = None

    def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        return self.backend.dispatch(**kwargs)


class FakeBackend:
    """Returns pre-built responses per call, and records usage."""

    def __init__(self, responses: Sequence[Callable[[dict], Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.conn_kwargs: dict[str, Any] = {}

    def __call__(self, **conn: Any) -> FakeSDK:
        self.conn_kwargs = dict(conn)
        return FakeSDK(self, **conn)

    def dispatch(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1](kwargs)
        raise AssertionError("backend exhausted responses")

    @property
    def retry_attempts(self) -> int:
        return len(self.calls)


# --- response builders ------------------------------------------------------ #
def msg(content: Any = "", reasoning: str = "", tool_calls: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls,
    )


def tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def non_streaming(content: str = "hi", reasoning: str = "", tool_calls: Any = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg(content, reasoning, tool_calls), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _stream_chunk(
    delta: Optional[SimpleNamespace] = None,
    finish_reason: str = None,
    usage: Any = None,
) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta or SimpleNamespace(), finish_reason=finish_reason)],
        usage=usage,
    )


def streaming(content_parts: Sequence[str], reasoning_parts: Sequence[str] = ()) -> Any:
    chunks = []
    for r in reasoning_parts:
        chunks.append(_stream_chunk(SimpleNamespace(reasoning_content=r, content=None, tool_calls=None)))
    for c in content_parts:
        chunks.append(_stream_chunk(SimpleNamespace(reasoning_content=None, content=c, tool_calls=None)))
    chunks.append(_stream_chunk(finish_reason="stop"))
    chunks.append(SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8)))
    return iter(chunks)


def streaming_with_tool_calls(tc_deltas: Sequence[SimpleNamespace]) -> Any:
    chunks = []
    for d in tc_deltas:
        chunks.append(_stream_chunk(SimpleNamespace(reasoning_content=None, content=None, tool_calls=d)))
    chunks.append(_stream_chunk(finish_reason="tool_calls"))
    chunks.append(SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
    return iter(chunks)


@pytest.fixture
def backend_factory():
    """Builds a client wired to a FakeBackend via ``_openai_factory``.

    Returns (make_client, backend). make_client accepts any kwargs passable to
    ``LLMClient`` and pins the fake transport.
    """

    def _make(*, backend: FakeBackend, **client_kwargs: Any):
        prev = _client_module._openai_factory
        _client_module._openai_factory = backend
        try:
            return client_mod.LLMClient(
                api_key=client_kwargs.pop("api_key", "test-key"),
                provider=client_kwargs.pop("provider", "openai"),
                **client_kwargs,
            )
        finally:
            _client_module._openai_factory = prev

    def build(
        responses: Sequence[Callable[[dict], Any]],
        **client_kwargs: Any,
    ) -> tuple[Any, FakeBackend]:
        backend = FakeBackend(responses)
        return _make(backend=backend, **client_kwargs), backend

    return build
