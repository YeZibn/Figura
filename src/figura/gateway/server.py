"""Threaded loopback HTTP and replayable lifecycle-event transport."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit

from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.runtime.errors import RunError
from figura.runtime.models import RunStatus

from .application import FiguraGatewayApplication
from .web_projection import event_id, event_projection


_MAX_REQUEST_BYTES = MAX_IMAGE_BYTES
_EVENT_PATH = re.compile(r"^/api/v1/sessions/([0-9a-f]{32})/runs/([0-9a-f]{32})/events$")


class FiguraHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], application: FiguraGatewayApplication) -> None:
        self.application = application
        super().__init__(address, FiguraRequestHandler)


class FiguraRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FiguraGateway"
    sys_version = ""

    @property
    def application(self) -> FiguraGatewayApplication:
        return self.server.application  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        match = _EVENT_PATH.fullmatch(urlsplit(self.path).path)
        if match is not None:
            self._serve_event_stream(*match.groups())
            return
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        headers = {key.lower(): value for key, value in self.headers.items()}
        if not self.application.origin_allowed(self.command, headers):
            self.close_connection = True
            response = self.application.handle(self.command, self.path, headers, b"")
            self._write_response(response)
            return
        if "chunked" in headers.get("transfer-encoding", "").lower():
            self._write_response(
                self.application.handle(self.command, self.path, headers, b"")
            )
            return
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_REQUEST_BYTES:
            response = self.application._error(
                413,
                "request_too_large",
                "请求内容超过本地服务限制。",
                headers,
            )
            self._write_response(response)
            return
        body = self.rfile.read(length) if length else b""
        if len(body) != length:
            self._write_response(
                self.application._error(
                    400, "invalid_request", "请求内容无效。", headers
                )
            )
            return
        self._write_response(self.application.handle(self.command, self.path, headers, body))

    def _serve_event_stream(self, session_id: str, run_id: str) -> None:
        headers = {key.lower(): value for key, value in self.headers.items()}
        if not self.application.origin_allowed("GET", headers):
            self._write_response(
                self.application._error(403, "origin_not_allowed", "浏览器来源不受允许。", headers)
            )
            return
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            values = query.get("afterSequence", ["0"])
            if len(values) != 1:
                raise ValueError
            cursor = int(values[0])
            if cursor < 0 or str(cursor) != values[0]:
                raise ValueError
            state = self.application.coordinator.read_run_state(session_id, run_id)
        except ValueError:
            self._write_response(
                self.application._error(400, "invalid_request", "事件游标无效。", headers)
            )
            return
        except RunError as error:
            response = self.application.handle(
                "GET",
                f"/api/v1/sessions/{session_id}/runs/{run_id}/history",
                headers,
            )
            self._write_response(response)
            return

        response_headers = self.application._cors_headers(headers) | {
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "close",
            "X-Content-Type-Options": "nosniff",
        }
        self.close_connection = True
        self.send_response(200)
        for key, value in response_headers.items():
            self.send_header(key, value)
        self.end_headers()

        last_heartbeat = monotonic()
        try:
            while True:
                state = self.application.coordinator.read_run_state(session_id, run_id)
                new_events = [event for event in state.events if event.event_sequence > cursor]
                for event in new_events:
                    data = json.dumps(
                        event_projection(state, event),
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                    frame = (
                        f"id: {event_id(state, event)}\n"
                        f"event: {event.event_kind.value}\n"
                        f"data: {data}\n\n"
                    )
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
                    cursor = event.event_sequence
                if state.run.status is not RunStatus.RUNNING:
                    return
                now = monotonic()
                if now - last_heartbeat >= 15:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    last_heartbeat = now
                sleep(0.25)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError, RunError):
            return

    def _write_response(self, response) -> None:
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        if response.status == 204:
            self.send_header("Content-Length", "0")
        self.end_headers()
        if response.body:
            try:
                self.wfile.write(response.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, format: str, *args: object) -> None:
        return

    def log_error(self, format: str, *args: object) -> None:
        return

    def handle_error(self) -> None:
        return
