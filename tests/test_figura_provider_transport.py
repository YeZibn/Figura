from __future__ import annotations

import json
import time

import httpx
from openai import OpenAI

from figura.providers.config import ProviderSettings
from figura.providers.models import ProviderId
from figura.providers.transport import OpenAISDKTransport, TransportNotice, _bound_response, _strict_lines


def _environment() -> dict[str, str]:
    return {
        "FIGURA_QWEN_API_KEY": "test-key",
        "FIGURA_QWEN_BASE_URL": "https://provider.test/v1",
        "FIGURA_DEEPSEEK_API_KEY": "test-key",
        "FIGURA_DEEPSEEK_BASE_URL": "https://provider.test/v1",
        "FIGURA_MIMO_API_KEY": "test-key",
        "FIGURA_MIMO_BASE_URL": "https://provider.test/v1",
    }


class _Chunks(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], *, delay_before: int | None = None) -> None:
        self.chunks = chunks
        self.delay_before = delay_before
        self.closed = False

    def __iter__(self):
        for index, chunk in enumerate(self.chunks):
            if index == self.delay_before:
                time.sleep(0.06)
            yield chunk

    def close(self) -> None:
        self.closed = True


def test_strict_sse_line_reader_handles_fragmented_utf8_and_boundaries():
    text = 'data: {"content":"图表"}\n\n'
    encoded = text.encode("utf-8")
    split = encoded.index("图".encode("utf-8")) + 1
    response = httpx.Response(200, stream=_Chunks([encoded[:split], encoded[split:]]))

    assert list(_strict_lines(response)) == ['data: {"content":"图表"}', ""]


def test_stream_waits_past_write_timeout_and_yields_heartbeat_then_fragmented_chunks():
    profile = ProviderSettings.from_env({
        **_environment(),
        "FIGURA_QWEN_WRITE_TIMEOUT_SECONDS": "0.01",
    }).profiles[ProviderId.QWEN]
    transport = OpenAISDKTransport(profile)
    chunks = [
        b": provider-heartbeat\n\n",
        ("data: " + json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "qwen3.8-flash",
            "choices": [{"index": 0, "delta": {"content": "图表"}, "finish_reason": None}],
        }, ensure_ascii=False, separators=(",", ":")) + "\n\n").encode("utf-8"),
        ("data: " + json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "qwen3.8-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }, separators=(",", ":")) + "\n\n").encode("utf-8"),
        b"data: [DONE]\n\n",
    ]
    full_frame = chunks[1]
    split = full_frame.index("图".encode("utf-8")) + 1
    chunks[1:2] = [full_frame[:split], full_frame[split:]]
    byte_stream = _Chunks(chunks, delay_before=1)
    transport._client.close()
    transport._client = OpenAI(
        api_key="test-key",
        base_url="https://provider.test/v1",
        timeout=httpx.Timeout(None, connect=0.2, write=0.01, read=None, pool=0.2),
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=byte_stream)),
            event_hooks={"response": [_bound_response]},
        ),
    )
    try:
        assert transport._client.timeout.read is None
        events = list(transport.create(
            model="qwen3.8-flash",
            messages=[{"role": "user", "content": "test"}],
            stream=True,
        ))
        assert isinstance(events[0], TransportNotice) and events[0].kind == "response_opened"
        assert any(isinstance(event, TransportNotice) and event.kind == "heartbeat" for event in events)
        chunks_out = [event for event in events if not isinstance(event, TransportNotice)]
        assert chunks_out[0]["choices"][0]["delta"]["content"] == "图表"
        assert chunks_out[-1]["choices"][0]["finish_reason"] == "stop"
        assert byte_stream.closed
    finally:
        transport.close()


def test_interrupt_closes_an_open_stream_response():
    profile = ProviderSettings.from_env(_environment()).profiles[ProviderId.QWEN]
    transport = OpenAISDKTransport(profile)
    byte_stream = _Chunks([b": wait\n\n"])
    transport._client.close()
    transport._client = OpenAI(
        api_key="test-key",
        base_url="https://provider.test/v1",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=byte_stream)),
            event_hooks={"response": [_bound_response]},
        ),
    )
    events = iter(transport.create(
        model="qwen3.8-flash",
        messages=[{"role": "user", "content": "test"}],
        stream=True,
    ))
    try:
        opened = next(events)
        assert isinstance(opened, TransportNotice) and opened.kind == "response_opened"
        transport.interrupt()
        assert byte_stream.closed
    finally:
        events.close()
        transport.close()
