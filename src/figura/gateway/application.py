"""Composition root and bounded JSON application for the local Figura Gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from figura.agent import AgentExecutor, AgentRequestBuilder
from figura.attachments import FiguraAttachmentService
from figura.providers import MODEL_IDS, ProviderFactory, ProviderId
from figura.runtime import (
    FiguraRunStore,
    RunCoordinator,
    RunCreateRequest,
    RunError,
    RunErrorCode,
    RunStatus,
)
from figura.runtime._run_lock import PerRunExecutionLock
from figura.runtime.tool_execution import DurableToolExecutor
from figura.tools import ToolRegistry, ToolRuntime

from .dispatcher import DispatcherFull, RunDispatcher
from .web_projection import attachment, run_handle, run_history, session_snapshot


_API_PREFIX = "/api/v1"
_JSON_LIMIT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class GatewayResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class FiguraGatewayApplication:
    def __init__(
        self,
        coordinator: RunCoordinator,
        attachments: FiguraAttachmentService,
        providers: ProviderFactory,
        dispatcher: RunDispatcher,
        *,
        allowed_origins: tuple[str, ...],
    ) -> None:
        self.coordinator = coordinator
        self.attachments = attachments
        self.providers = providers
        self.dispatcher = dispatcher
        self.allowed_origins = frozenset(allowed_origins)

    def close(self) -> None:
        self.dispatcher.close()

    def origin_allowed(self, method: str, headers: Mapping[str, str]) -> bool:
        origin = _header(headers, "origin")
        if origin is None:
            return method.upper() in {"GET", "HEAD"}
        return origin in self.allowed_origins

    def handle(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> GatewayResponse:
        method = method.upper()
        if not self.origin_allowed(method, headers):
            return self._error(403, "origin_not_allowed", "浏览器来源不受允许。")
        if method == "OPTIONS":
            return GatewayResponse(
                204,
                self._cors_headers(headers)
                | {
                    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Idempotency-Key",
                    "Access-Control-Max-Age": "600",
                },
                b"",
            )
        try:
            parsed = urlsplit(target)
            path = parsed.path
            query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
            if path == f"{_API_PREFIX}/health" and method == "GET":
                return self._json(200, self._health(), headers)
            if path == f"{_API_PREFIX}/sessions" and method == "GET":
                sessions = [
                    {
                        "id": entry.session.session_id,
                        "name": entry.session.name,
                        "createdAt": entry.session.created_at,
                        "updatedAt": entry.latest_activity,
                        "runCount": entry.run_count,
                    }
                    for entry in self.coordinator.list_session_entries()
                ]
                return self._json(200, {"sessions": sessions}, headers)
            if path == f"{_API_PREFIX}/sessions" and method == "POST":
                payload = _read_json(body)
                if set(payload) - {"name"}:
                    raise _BadRequest
                name = payload.get("name")
                if name is not None and not isinstance(name, str):
                    raise _BadRequest
                session = self.coordinator.create_session(name)
                projection = session_snapshot(
                    self.coordinator.read_session_snapshot(session.session_id)
                )["session"]
                return self._json(201, {"session": projection}, headers)

            parts = _path_parts(path)
            if parts is None or len(parts) < 2 or parts[0] != "sessions":
                return self._error(404, "not_found", "未找到请求的 Figura 资源。", headers)
            session_id = parts[1]
            if len(parts) == 2 and method == "GET":
                snapshot = self.coordinator.read_session_snapshot(session_id)
                return self._json(200, session_snapshot(snapshot), headers)
            if len(parts) == 3 and parts[2] == "attachments":
                if method == "GET":
                    return self._json(
                        200,
                        {"attachments": [attachment(item) for item in self.attachments.list(session_id)]},
                        headers,
                    )
                if method == "POST":
                    filename_values = query.get("filename", [])
                    if len(filename_values) != 1 or not filename_values[0]:
                        raise _BadRequest
                    metadata = self.attachments.upload(session_id, filename_values[0], body)
                    return self._json(201, {"attachment": attachment(metadata)}, headers)
            if len(parts) == 5 and parts[2] == "attachments" and parts[4] == "content" and method == "GET":
                image = self.attachments.resolve(session_id, parts[3])
                return GatewayResponse(
                    200,
                    self._cors_headers(headers)
                    | {
                        "Content-Type": image.media_type,
                        "Content-Length": str(len(image.image_bytes)),
                        "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff",
                    },
                    image.image_bytes,
                )
            if len(parts) == 4 and parts[2] == "attachments" and method == "DELETE":
                self.attachments.delete(session_id, parts[3])
                return self._json(204, None, headers)
            if len(parts) == 3 and parts[2] == "runs" and method == "POST":
                payload = _read_json(body)
                if set(payload) != {"text", "attachmentIds", "providerId"}:
                    raise _BadRequest
                text = payload["text"]
                attachment_ids = payload["attachmentIds"]
                provider_value = payload["providerId"]
                key = _header(headers, "idempotency-key")
                if (
                    not isinstance(text, str)
                    or not isinstance(attachment_ids, list)
                    or any(not isinstance(item, str) for item in attachment_ids)
                    or not isinstance(provider_value, str)
                    or not key
                ):
                    raise _BadRequest
                try:
                    provider_id = ProviderId(provider_value)
                except ValueError:
                    raise RunError(RunErrorCode.INVALID_REQUEST) from None
                run = self.coordinator.create_run(
                    RunCreateRequest(
                        session_id=session_id,
                        text=text,
                        attachment_ids=tuple(attachment_ids),
                        provider_id=provider_id.value,
                        model_id=MODEL_IDS[provider_id],
                        idempotency_key=key,
                    )
                )
                if run.status is RunStatus.RUNNING:
                    try:
                        self.dispatcher.ensure_scheduled(run)
                    except DispatcherFull:
                        return self._error(
                            503,
                            "dispatcher_unavailable",
                            "本地运行队列暂时不可用，请使用相同幂等键重试。",
                            headers,
                        )
                return self._json(202, {"run": run_handle(run)}, headers)

            if len(parts) == 5 and parts[2] == "runs" and parts[4] == "history" and method == "GET":
                after_sequence = _read_cursor(query)
                state = self.coordinator.read_run_state(session_id, parts[3])
                return self._json(200, run_history(state, after_sequence), headers)
            if len(parts) == 5 and parts[2] == "runs" and parts[4] == "events" and method == "GET":
                return self._error(426, "stream_required", "请使用事件流连接读取 Run 事件。", headers)
            return self._error(404, "not_found", "未找到请求的 Figura 资源。", headers)
        except _BadRequest:
            return self._error(400, "invalid_request", "请求内容无效。", headers)
        except RunError as error:
            status, code, message = _map_run_error(error)
            if path.endswith("/attachments") and method == "POST" and error.code in {
                RunErrorCode.UNSUPPORTED_PAYLOAD,
                RunErrorCode.INVALID_REQUEST,
            }:
                status, code, message = 400, error.code.value, error.safe_message
            return self._error(status, code, message, headers)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return self._error(400, "invalid_request", "请求内容无效。", headers)
        except Exception:
            return self._error(500, "internal_error", "Figura 本地服务暂时无法处理请求。", headers)

    def _health(self) -> dict[str, object]:
        provider_statuses = []
        for item in self.providers.availability():
            provider_statuses.append(
                {
                    "providerId": item.provider_id.value,
                    "modelId": item.model_id,
                    "available": item.available,
                    "reasonCode": item.reason_code,
                }
            )
        return {
            "version": "v1",
            "status": "ok",
            "service": "figura",
            "providers": provider_statuses,
        }

    def _json(
        self,
        status: int,
        value: object,
        request_headers: Mapping[str, str],
    ) -> GatewayResponse:
        body = b"" if status == 204 else json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        return GatewayResponse(
            status,
            self._cors_headers(request_headers)
            | {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
            body,
        )

    def _error(
        self,
        status: int,
        code: str,
        message: str,
        request_headers: Mapping[str, str] | None = None,
    ) -> GatewayResponse:
        return self._json(
            status,
            {"error": {"code": code, "message": message}},
            request_headers or {},
        )

    def _cors_headers(self, request_headers: Mapping[str, str]) -> dict[str, str]:
        origin = _header(request_headers, "origin")
        result = {"Vary": "Origin"}
        if origin in self.allowed_origins:
            result["Access-Control-Allow-Origin"] = origin
        return result


def create_application(
    project_root: str | Path,
    *,
    data_dir: str | Path | None = None,
    provider_factory: ProviderFactory | None = None,
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:1421",),
    max_workers: int = 3,
    max_queued: int = 8,
) -> FiguraGatewayApplication:
    root = Path(project_root).expanduser().resolve()
    selected_data_dir = Path(data_dir).expanduser() if data_dir is not None else root / ".figura"
    if not selected_data_dir.is_absolute():
        selected_data_dir = root / selected_data_dir
    store = FiguraRunStore(selected_data_dir)
    attachment_service = FiguraAttachmentService(store)
    factory = provider_factory or ProviderFactory.from_env()
    registry = ToolRegistry("figura-web-v1", ())
    runtime = ToolRuntime(registry)
    lock = PerRunExecutionLock(store.data_root)
    coordinator = RunCoordinator(store, factory)
    tools = DurableToolExecutor(store, registry, runtime, execution_lock=lock)
    agent = AgentExecutor(
        coordinator,
        factory,
        tools,
        lock,
        AgentRequestBuilder(attachment_service),
    )
    dispatcher = RunDispatcher(agent, max_workers=max_workers, max_queued=max_queued)
    return FiguraGatewayApplication(
        coordinator,
        attachment_service,
        factory,
        dispatcher,
        allowed_origins=allowed_origins,
    )


def recover_running_runs(application: FiguraGatewayApplication) -> int:
    """Schedule persisted running Runs through the ordinary safe executor path."""
    scheduled = 0
    for run in application.coordinator.list_running_runs():
        if application.dispatcher.ensure_scheduled(run, wait_for_capacity=True):
            scheduled += 1
    return scheduled


def _read_json(body: bytes) -> dict[str, object]:
    if not body or len(body) > _JSON_LIMIT_BYTES:
        raise _BadRequest
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise _BadRequest
    return value


def _path_parts(path: str) -> list[str] | None:
    if not path.startswith(f"{_API_PREFIX}/"):
        return None
    parts = path[len(_API_PREFIX) + 1 :].split("/")
    if any(not part for part in parts):
        return None
    return parts


def _read_cursor(query: Mapping[str, list[str]]) -> int:
    values = query.get("afterSequence", ["0"])
    if len(values) != 1:
        raise _BadRequest
    try:
        value = int(values[0])
    except ValueError:
        raise _BadRequest from None
    if value < 0 or str(value) != values[0]:
        raise _BadRequest
    return value


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _map_run_error(error: RunError) -> tuple[int, str, str]:
    if error.code is RunErrorCode.INVALID_REQUEST:
        return 400, error.code.value, error.safe_message
    if error.code in {RunErrorCode.SESSION_NOT_FOUND, RunErrorCode.RUN_NOT_FOUND}:
        return 404, "not_found", error.safe_message
    if error.code in {
        RunErrorCode.IDEMPOTENCY_CONFLICT,
        RunErrorCode.INVALID_TRANSITION,
        RunErrorCode.STALE_CHECKPOINT,
    }:
        return 409, error.code.value, error.safe_message
    if error.code is RunErrorCode.PROVIDER_UNAVAILABLE:
        return 503, error.code.value, error.safe_message
    if error.code is RunErrorCode.UNSUPPORTED_PAYLOAD:
        return 404, "not_found", "未找到可用的 Figura 资源。"
    return 500, "internal_error", "Figura 本地服务暂时无法处理请求。"


class _BadRequest(Exception):
    pass
