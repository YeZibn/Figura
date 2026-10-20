"""Single-send SDK transport with bounded bytes before JSON/SSE parsing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import codecs
from openai import OpenAI, APIConnectionError
from contextlib import contextmanager
from threading import Lock

from figura.shared.payloads import PayloadError, current_payload_limits, decode_json
from .config import ProviderProfile
from .errors import ProviderProtocolError


class CompletionTransport(Protocol):
    def create(self, **payload: Any) -> Any: ...


@dataclass(frozen=True)
class TransportNotice:
    kind: str
    http_status: int | None = None
    provider_request_id: str | None = None


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
        self._active_lock = Lock()
        self._active_response = None
        self._client = OpenAI(api_key=profile.api_key, base_url=profile.base_url,
            timeout=httpx.Timeout(
                None,
                connect=profile.connect_timeout_seconds,
                write=profile.write_timeout_seconds,
                read=None,
                pool=profile.connect_timeout_seconds,
            ), max_retries=0, default_headers={"Accept-Encoding": "identity"},
            http_client=httpx.Client(transport=httpx.HTTPTransport(retries=0),
                event_hooks={"response": [_bound_response]}))

    def create(self, **payload: Any) -> Any:
        if payload.get("stream") is not True:
            raise ProviderProtocolError()
        return self._events(payload)

    def _events(self, payload: dict[str, Any]):
        with self._response(payload) as response:
            yield TransportNotice(
                "response_opened",
                response.http_response.status_code,
                response.headers.get("x-request-id"),
            )
            data = []
            for line in _strict_lines(response):
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif line.startswith(":") or (not line and not data):
                    yield TransportNotice("heartbeat")
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
                with self._active_lock:
                    self._active_response = response
                try:
                    yield response
                finally:
                    with self._active_lock:
                        if self._active_response is response:
                            self._active_response = None
        except APIConnectionError as error:
            if isinstance(error.__cause__, ProviderProtocolError):
                raise ProviderProtocolError() from None
            raise

    def interrupt(self) -> None:
        """Abort a blocked request or close its active response stream."""
        with self._active_lock:
            response = self._active_response
        if response is not None:
            response.close()
        else:
            # The SDK may still be waiting for response headers, before the
            # streaming response context manager has published its handle.
            # Closing the client also tears down that in-flight connection.
            self._client.close()

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
