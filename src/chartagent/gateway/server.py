"""Loopback HTTP transport for :mod:`chartagent.gateway.service`."""

from __future__ import annotations

import argparse
import json
import os
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

from ..attachments import DEFAULT_MAX_ATTACHMENT_BYTES
from ..client import load_environment
from .protocol import GatewayFault, GATEWAY_VERSION, success
from .service import GatewayService

API_PREFIX = "/api/v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 1024 * 1024
MAX_BINARY_REQUEST_BYTES = DEFAULT_MAX_ATTACHMENT_BYTES
DEFAULT_ALLOWED_ORIGINS = frozenset({
    "http://127.0.0.1:1420",
    "http://localhost:1420",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
})


def configured_origins(value: str | None = None) -> frozenset[str]:
    raw = value if value is not None else os.environ.get("CHARTAGENT_GATEWAY_ORIGINS", "")
    extra = {item.strip() for item in raw.split(",") if item.strip()}
    return frozenset(DEFAULT_ALLOWED_ORIGINS | extra)


class GatewayHTTPServer(ThreadingHTTPServer):
    """Threaded server carrying an injected gateway service."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: GatewayService,
        *,
        allowed_origins: Iterable[str] = DEFAULT_ALLOWED_ORIGINS,
    ) -> None:
        super().__init__(server_address, GatewayRequestHandler)
        self.gateway_service = service
        self.allowed_origins = frozenset(allowed_origins)

    def server_close(self) -> None:
        try:
            self.gateway_service.close()
        finally:
            super().server_close()


class GatewayRequestHandler(BaseHTTPRequestHandler):
    """Small route dispatcher that never serializes internal exceptions."""

    server_version = "ChartAgentGateway/1"
    protocol_version = "HTTP/1.1"

    @property
    def gateway(self) -> GatewayService:
        return self.server.gateway_service  # type: ignore[attr-defined]

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self._send_json(HTTPStatus.NO_CONTENT, None)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            path = self._path()
            if path == f"{API_PREFIX}/health":
                payload = self.gateway.health()
            elif path == f"{API_PREFIX}/sessions":
                payload = self.gateway.list_sessions()
            elif path == f"{API_PREFIX}/evaluations":
                payload = self.gateway.list_evaluations()
            elif (evaluation_id := self._evaluation_detail_id(path)) is not None:
                payload = self.gateway.get_evaluation(evaluation_id)
            elif (parts := self._evaluation_case_history_details_parts(path)) is not None:
                evaluation_id, case_id = parts
                payload = self.gateway.get_evaluation_history_details(
                    evaluation_id,
                    case_id,
                    self._query_record_sequence(),
                )
            elif (parts := self._evaluation_case_history_parts(path)) is not None:
                evaluation_id, case_id = parts
                payload = self.gateway.get_evaluation_history(
                    evaluation_id,
                    case_id,
                    self._query_sequence(),
                )
            elif (parts := self._evaluation_case_parts(path)) is not None:
                evaluation_id, case_id = parts
                payload = self.gateway.get_evaluation_case(evaluation_id, case_id)
            elif (parts := self._evaluation_resource_parts(path)) is not None:
                evaluation_id, resource_id = parts
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                case_values = query.get("case_id", [])
                case_id = case_values[0] if len(case_values) == 1 and case_values[0] else None
                content, media_type = self.gateway.get_evaluation_resource(
                    evaluation_id,
                    resource_id,
                    case_id=unquote(case_id) if case_id is not None else None,
                )
                self._send_binary(HTTPStatus.OK, content, media_type)
                return
            elif (session_id := self._run_collection_session_id(path)) is not None:
                payload = self.gateway.list_runs(session_id)
            elif (parts := self._run_observation_parts(path)) is not None:
                session_id, run_id, observation_id = parts
                content, media_type = self.gateway.get_observation(
                    session_id,
                    run_id,
                    observation_id,
                )
                self._send_binary(HTTPStatus.OK, content, media_type)
                return
            elif (parts := self._run_artifact_parts(path)) is not None:
                session_id, run_id, artifact_id = parts
                content, media_type = self.gateway.get_generated_artifact(
                    session_id,
                    run_id,
                    artifact_id,
                )
                self._send_binary(HTTPStatus.OK, content, media_type)
                return
            elif (parts := self._run_candidate_parts(path)) is not None:
                session_id, run_id, candidate_id = parts
                content, media_type = self.gateway.get_generated_candidate(
                    session_id,
                    run_id,
                    candidate_id,
                )
                self._send_binary(HTTPStatus.OK, content, media_type)
                return
            elif (parts := self._run_chart_preview_parts(path)) is not None:
                session_id, run_id, reference_id = parts
                content, media_type = self.gateway.get_generated_chart_preview(
                    session_id,
                    run_id,
                    reference_id,
                )
                self._send_binary(HTTPStatus.OK, content, media_type)
                return
            elif (parts := self._attachment_content_parts(path)) is not None:
                session_id, attachment_id = parts
                content, media_type = self.gateway.get_attachment_content(
                    session_id,
                    attachment_id,
                )
                self._send_binary(HTTPStatus.OK, content, media_type)
                return
            elif (parts := self._run_events_parts(path)) is not None:
                session_id, run_id = parts
                run = self.gateway.get_run(session_id, run_id)
                self._send_events(run, self._stream_cursor())
                return
            elif (parts := self._run_detail_parts(path)) is not None:
                session_id, run_id = parts
                payload = self.gateway.get_run_history(session_id, run_id, self._query_sequence())
            elif (session_id := self._subresource_session_id(path, "attachments")) is not None:
                payload = self.gateway.list_attachments(session_id)
            else:
                session_id = self._session_id(path)
                session_prefix = f"{API_PREFIX}/sessions/"
                if session_id is None or not path.startswith(session_prefix) or "/" in path[len(session_prefix):]:
                    raise GatewayFault("not_found", 404, "Route was not found")
                payload = self.gateway.get_session(session_id)
            self._send_json(HTTPStatus.OK, payload)
        except GatewayFault as exc:
            self._send_fault(exc)
        except Exception:
            self._send_fault(GatewayFault("gateway_error", 500, "Gateway request failed"))

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            path = self._path()
            if path == f"{API_PREFIX}/sessions":
                body = self._read_json()
                payload = self.gateway.create_session(body.get("name"))
            elif (session_id := self._subresource_session_id(path, "attachments")) is not None:
                filename, media_type = self._attachment_headers()
                payload = self.gateway.upload_attachment(
                    session_id,
                    filename,
                    media_type,
                    self._read_binary(),
                )
            elif (session_id := self._run_collection_session_id(path)) is not None:
                body = self._read_json()
                payload = self.gateway.start_run(
                    session_id,
                    body.get("text"),
                    body.get("attachmentIds"),
                    body.get("provider"),
                    self.headers.get("Idempotency-Key"),
                    body.get("retryOf"),
                )
                self._send_json(HTTPStatus.ACCEPTED, payload)
                return
            elif (parts := self._run_resume_parts(path)) is not None:
                session_id, run_id = parts
                body = self._read_json()
                payload = self.gateway.resume_run(
                    session_id,
                    run_id,
                    self.headers.get("Idempotency-Key"),
                    body.get("checkpointId"),
                )
                self._send_json(HTTPStatus.ACCEPTED, payload)
                return
            elif (parts := self._run_interrupt_parts(path)) is not None:
                session_id, run_id = parts
                body = self._read_json()
                payload = self.gateway.interrupt_run(session_id, run_id, body.get("reason", "user_cancelled"))
                self._send_json(HTTPStatus.OK, payload)
                return
            else:
                session_id = self._session_id(path)
                if session_id is None or not path.endswith("/messages"):
                    raise GatewayFault("not_found", 404, "Route was not found")
                body = self._read_json()
                payload = self.gateway.submit_message(
                    session_id,
                    body.get("text"),
                    body.get("attachmentIds"),
                    body.get("provider"),
                )
            self._send_json(HTTPStatus.OK, payload)
        except GatewayFault as exc:
            self._send_fault(exc)
        except Exception:
            self._send_fault(GatewayFault("gateway_error", 500, "Gateway request failed"))

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            path = self._path()
            prefix = f"{API_PREFIX}/sessions/"
            if path.startswith(prefix) and len(path[len(prefix):].split("/")) == 1:
                payload = self.gateway.delete_session(unquote(path[len(prefix):]))
            elif (parts := self._attachment_delete_parts(path)) is not None:
                session_id, attachment_id = parts
                payload = self.gateway.delete_attachment(session_id, attachment_id)
            else:
                raise GatewayFault("not_found", 404, "Route was not found")
            self._send_json(HTTPStatus.OK, payload)
        except GatewayFault as exc:
            self._send_fault(exc)
        except Exception:
            self._send_fault(GatewayFault("gateway_error", 500, "Gateway request failed"))

    def log_message(self, format: str, *args: Any) -> None:
        # Keep provider and request details out of the default desktop output.
        return None

    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    @staticmethod
    def _evaluation_detail_id(path: str) -> str | None:
        prefix = f"{API_PREFIX}/evaluations/"
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix):]
        if remainder and "/" not in remainder:
            return unquote(remainder)
        return None

    @staticmethod
    def _evaluation_case_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/evaluations/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 3 and parts[1] == "cases":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _evaluation_case_history_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/evaluations/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 4 and parts[1] == "cases" and parts[3] == "history":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _evaluation_case_history_details_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/evaluations/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 5 and parts[1] == "cases" and parts[3] == "history" and parts[4] == "details":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _evaluation_resource_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/evaluations/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 3 and parts[1] == "resources":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _session_id(path: str) -> str | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix):]
        if not remainder:
            return None
        parts = remainder.split("/")
        if len(parts) == 1:
            return unquote(parts[0])
        if len(parts) == 2 and parts[1] == "messages":
            return unquote(parts[0])
        return None

    @staticmethod
    def _subresource_session_id(path: str, resource: str) -> str | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix):]
        parts = remainder.split("/")
        if len(parts) == 2 and parts[1] == resource:
            return unquote(parts[0])
        return None

    @staticmethod
    def _run_collection_session_id(path: str) -> str | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix):]
        parts = remainder.split("/")
        if len(parts) == 2 and parts[1] == "runs":
            return unquote(parts[0])
        return None

    @staticmethod
    def _run_events_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 4 and parts[1] == "runs" and parts[3] == "events":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _run_interrupt_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 4 and parts[1] == "runs" and parts[3] == "interrupt":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _run_resume_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 4 and parts[1] == "runs" and parts[3] == "resume":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _run_detail_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 3 and parts[1] == "runs":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _run_observation_parts(path: str) -> tuple[str, str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if (
            len(parts) == 5
            and parts[1] == "runs"
            and parts[3] == "observations"
        ):
            return unquote(parts[0]), unquote(parts[2]), unquote(parts[4])
        return None

    @staticmethod
    def _run_artifact_parts(path: str) -> tuple[str, str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 5 and parts[1] == "runs" and parts[3] == "artifacts":
            return unquote(parts[0]), unquote(parts[2]), unquote(parts[4])
        return None

    @staticmethod
    def _run_candidate_parts(path: str) -> tuple[str, str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 5 and parts[1] == "runs" and parts[3] == "candidates":
            return unquote(parts[0]), unquote(parts[2]), unquote(parts[4])
        return None

    @staticmethod
    def _run_chart_preview_parts(path: str) -> tuple[str, str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 5 and parts[1] == "runs" and parts[3] == "chart-previews":
            return unquote(parts[0]), unquote(parts[2]), unquote(parts[4])
        return None

    @staticmethod
    def _attachment_content_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 4 and parts[1] == "attachments" and parts[3] == "content":
            return unquote(parts[0]), unquote(parts[2])
        return None

    @staticmethod
    def _attachment_delete_parts(path: str) -> tuple[str, str] | None:
        prefix = f"{API_PREFIX}/sessions/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if len(parts) == 3 and parts[1] == "attachments":
            return unquote(parts[0]), unquote(parts[2])
        return None

    def _attachment_headers(self) -> tuple[str, str]:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        filenames = query.get("filename", [])
        filename = filenames[0] if len(filenames) == 1 else ""
        media_type = self.headers.get("X-ChartAgent-Media-Type", "")
        if not filename or not media_type:
            raise GatewayFault("invalid_request", 400, "Attachment filename and media type are required")
        return filename, media_type

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


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    data_dir: str | Path | None = None,
    database: str | Path | None = None,
    model: str | None = None,
    allowed_origins: Iterable[str] | None = None,
) -> None:
    """Run the gateway until interrupted."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("gateway host must be loopback")
    service = GatewayService(data_dir=data_dir, database=database, model=model)
    server = GatewayHTTPServer(
        (host, port),
        service,
        allowed_origins=allowed_origins or configured_origins(),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chartagent.gateway")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="durable data root; relative paths are resolved from the project root",
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    try:
        load_environment()
        serve(
            host=args.host,
            port=args.port,
            data_dir=args.data_dir,
            database=args.database,
            model=args.model,
        )
    except KeyboardInterrupt:
        return 0
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
