"""Single-send SDK transport with bounded bytes before JSON/SSE parsing."""
from __future__ import annotations

from typing import Any, Protocol

import httpx
import codecs
from openai import OpenAI, APIConnectionError
from contextlib import contextmanager

from figura.shared.payloads import PayloadError, current_payload_limits, decode_json
from .config import ProviderProfile
from .errors import ProviderProtocolError


class CompletionTransport(Protocol):
    def create(self, **payload: Any) -> Any: ...


class _BoundedStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream, maximum: int) -> None:
        self.stream, self.maximum = stream, maximum

    def __iter__(self):
        total = 0
        for chunk in self.stream:
            total += len(chunk)
            if total > self.maximum:
                self.stream.close()
                raise ProviderProtocolError()
            yield chunk

    def close(self):
        self.stream.close()


def _bound_response(response: httpx.Response) -> None:
    maximum = current_payload_limits().max_json_bytes
    if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
        response.close()
        raise ProviderProtocolError()
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > maximum:
        response.close()
        raise ProviderProtocolError()
    response.stream = _BoundedStream(response.stream, maximum)
    if response.status_code >= 400:
        # SDK error parsing also receives a bounded, strictly checked JSON body.
        response.read()
        try:
            decode_json(response.content.decode("utf-8"))
        except (PayloadError, UnicodeError):
            raise ProviderProtocolError() from None


class OpenAISDKTransport:
    def __init__(self, profile: ProviderProfile) -> None:
        if not profile.api_key or not profile.base_url:
            raise ValueError("provider transport requires a configured profile")
        self._client = OpenAI(api_key=profile.api_key, base_url=profile.base_url,
            timeout=profile.timeout_seconds, max_retries=0, default_headers={"Accept-Encoding": "identity"},
            http_client=httpx.Client(transport=httpx.HTTPTransport(retries=0),
                event_hooks={"response": [_bound_response]}))

    def create(self, **payload: Any) -> Any:
        if payload.get("stream"):
            return self._events(payload)
        with self._response(payload) as response:
            try:
                return decode_json(response.read().decode("utf-8"))
            except (PayloadError, UnicodeError):
                raise ProviderProtocolError() from None

    def _events(self, payload: dict[str, Any]):
        with self._response(payload) as response:
            data = []
            for line in _strict_lines(response):
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    raw = "\n".join(data)
                    data.clear()
                    if raw == "[DONE]":
                        return
                    try:
                        yield decode_json(raw)
                    except PayloadError:
                        raise ProviderProtocolError() from None

    @contextmanager
    def _response(self, payload):
        try:
            with self._client.chat.completions.with_streaming_response.create(**payload) as response:
                yield response
        except APIConnectionError as error:
            if isinstance(error.__cause__, ProviderProtocolError):
                raise ProviderProtocolError() from None
            raise

    def close(self) -> None:
        self._client.close()


def _strict_lines(response):
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    pending = ""
    try:
        for chunk in response.iter_bytes():
            pending += decoder.decode(chunk)
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                yield line.rstrip("\r")
        pending += decoder.decode(b"", final=True)
        if pending:
            yield pending.rstrip("\r")
    except UnicodeError:
        raise ProviderProtocolError() from None
