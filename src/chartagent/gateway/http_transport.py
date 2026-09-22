"""HTTP request/response and SSE transport adapter for the Gateway."""

from __future__ import annotations

import json
import socket
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..attachments import DEFAULT_MAX_ATTACHMENT_BYTES
from .protocol import GatewayFault

MAX_REQUEST_BYTES = 1024 * 1024
MAX_BINARY_REQUEST_BYTES = DEFAULT_MAX_ATTACHMENT_BYTES


class GatewayHTTPTransportMixin:
    """Keep wire-format handling out of the route dispatcher."""

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            raise GatewayFault("unsupported_media_type", 415, "JSON content is required")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "-1")
        except ValueError as exc:
            raise GatewayFault("invalid_request", 400, "Content length is invalid") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise GatewayFault("request_too_large", 413, "Request body is too large")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise GatewayFault("invalid_request", 400, "Request body is incomplete")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayFault("invalid_json", 400, "Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise GatewayFault("invalid_request", 400, "Request body must be a JSON object")
        return value

    def _read_binary(self) -> bytes:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/octet-stream"):
            raise GatewayFault("unsupported_media_type", 415, "Binary attachment content is required")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "-1")
        except ValueError as exc:
            raise GatewayFault("invalid_request", 400, "Content length is invalid") from exc
        if length < 0 or length > MAX_BINARY_REQUEST_BYTES:
            raise GatewayFault("request_too_large", 413, "Attachment body is too large")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise GatewayFault("invalid_request", 400, "Attachment body is incomplete")
        return raw

    def _method_not_allowed(self) -> None:
        self._send_fault(GatewayFault("method_not_allowed", 405, "HTTP method is not supported"))

    def _send_fault(self, fault: GatewayFault) -> None:
        self._send_json(fault.status, fault.to_dict())

    def _send_events(self, run, after_sequence: int) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._send_cors_headers()
        self.end_headers()
        try:
            for event in run.iter_events(after_sequence):
                if event is None:
                    self.wfile.write(b": heartbeat\n\n")
                else:
                    frame = (
                        f"id: {event.sequence}\n"
                        f"event: {event.kind}\n"
                        f"data: {event.to_json()}\n\n"
                    ).encode("utf-8")
                    self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        finally:
            self.close_connection = True
            try:
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def _last_event_id(self) -> int:
        raw = self.headers.get("Last-Event-ID", "0")
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _query_sequence(self) -> int:
        raw = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("after", ["0"])[0]
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _query_record_sequence(self) -> int:
        raw = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("after_record", ["0"])[0]
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _stream_cursor(self) -> int:
        return max(self._last_event_id(), self._query_sequence())

    def _send_binary(self, status: int | HTTPStatus, content: bytes, media_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", "inline")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Expose-Headers", "Content-Type, Content-Length")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        allowed = getattr(self.server, "allowed_origins", frozenset())
        if origin and origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-ChartAgent-Media-Type, Last-Event-ID, Idempotency-Key",
            )
            self.send_header("Vary", "Origin")

    def _send_json(self, status: int | HTTPStatus, payload: dict[str, Any] | None) -> None:
        encoded = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors_headers()
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)


__all__ = [
    "GatewayHTTPTransportMixin",
    "MAX_REQUEST_BYTES",
    "MAX_BINARY_REQUEST_BYTES",
]
