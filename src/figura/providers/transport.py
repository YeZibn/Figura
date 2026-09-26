"""OpenAI SDK transport shared by the OpenAI-compatible providers."""

from __future__ import annotations

from typing import Any, Protocol

from openai import OpenAI

from .config import ProviderProfile


class CompletionTransport(Protocol):
    def create(self, **payload: Any) -> Any: ...


class OpenAISDKTransport:
    """A provider-scoped OpenAI SDK client with SDK retries disabled."""

    def __init__(self, profile: ProviderProfile) -> None:
        if not profile.api_key or not profile.base_url:
            raise ValueError("provider transport requires a configured profile")
        self._client = OpenAI(
            api_key=profile.api_key,
            base_url=profile.base_url,
            timeout=profile.timeout_seconds,
            max_retries=0,
        )

    def create(self, **payload: Any) -> Any:
        return self._client.chat.completions.create(**payload)

    def close(self) -> None:
        self._client.close()
