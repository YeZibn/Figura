"""A deliberately small HTTP client for real-chart diagnostic runs.

The client is an observer/driver for the public local Gateway. It must not
instantiate an Agent or dispatch chart tools directly, because doing so would
measure a different execution path from the frontend.
"""

from __future__ import annotations

import json
import mimetypes
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .manifest import DiagnosticSample


DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765/api/v1"
DEFAULT_DIAGNOSTIC_TEXT = (
    "请分析附件中的图表，按照当前图表理解链路完成拆解、局部提取、测量、组装和生成。"
    "请保留完整过程，遇到测量或审核问题时按已有机制处理。"
)
TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class DiagnosticGatewayError(RuntimeError):
    """A bounded Gateway or transport error; no provider fallback is attempted."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:500]
        self.status = status
        self.session_id: str | None = None
        self.run_id: str | None = None


@dataclass(frozen=True)
class DiagnosticRun:
    """The run boundary and the final/partial history returned by the Gateway."""

    session_id: str
    run_id: str
    requested_provider: str
    provider: str | None
    model: str | None
    status: str
    history: Mapping[str, Any]
    timed_out: bool = False


class GatewayDiagnosticClient:
    """Submit one explicitly selected provider run through the Gateway API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
        opener: Any = urlopen,
    ) -> None:
        configured = (base_url or DEFAULT_GATEWAY_URL).strip().rstrip("/")
        if not configured.startswith(("http://", "https://")):
            raise DiagnosticGatewayError("invalid_gateway_url", "Gateway URL 必须是 HTTP(S) 地址")
        self.base_url = configured
        self.timeout = max(0.1, float(timeout))
        self.poll_interval = min(10.0, max(0.1, float(poll_interval)))
        self._opener = opener

    def create_session(self, name: str) -> str:
        payload = self._request_json(
            "/sessions",
            method="POST",
            body={"name": name[:128]},
        )
        session = payload.get("session")
        if not isinstance(session, Mapping) or not isinstance(session.get("id"), str):
            raise DiagnosticGatewayError("invalid_gateway_response", "Gateway 未返回有效 session")
        return str(session["id"])

    def upload_attachment(self, session_id: str, sample: DiagnosticSample) -> str:
        try:
            content = sample.asset_path.read_bytes()
        except OSError as exc:
            raise DiagnosticGatewayError("sample_unavailable", "样本图片无法读取") from exc
        suffix = sample.asset_path.suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix) or mimetypes.guess_type(sample.asset_path.name)[0]
        if not media_type or not media_type.startswith("image/"):
            raise DiagnosticGatewayError("unsupported_sample_type", "诊断样本必须是图片")
        path = f"/sessions/{quote(session_id, safe='')}/attachments?filename={quote(sample.asset_path.name, safe='')}"
        payload = self._request_json(
            path,
            method="POST",
            body=content,
            headers={
                "Content-Type": "application/octet-stream",
                "X-ChartAgent-Media-Type": media_type,
            },
        )
        attachment = payload.get("attachment")
        if not isinstance(attachment, Mapping) or not isinstance(attachment.get("attachment_id"), str):
            raise DiagnosticGatewayError("invalid_gateway_response", "Gateway 未返回有效 attachment")
        return str(attachment["attachment_id"])

    def start_run(
        self,
        session_id: str,
        *,
        attachment_id: str,
        provider: str,
        text: str = DEFAULT_DIAGNOSTIC_TEXT,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        provider = provider.strip()
        if not provider:
            raise DiagnosticGatewayError("provider_required", "真实诊断必须显式指定 provider")
        if not attachment_id.strip():
            raise DiagnosticGatewayError("attachment_required", "真实诊断需要附件")
        key = idempotency_key or f"chart-diagnostic-{uuid.uuid4().hex}"
        payload = self._request_json(
            f"/sessions/{quote(session_id, safe='')}/runs",
            method="POST",
            body={
                "text": text[:12000],
                "attachmentIds": [attachment_id],
                "provider": provider,
            },
            headers={"Idempotency-Key": key},
        )
        run = payload.get("run")
        if not isinstance(run, Mapping) or not isinstance(run.get("runId"), str):
            raise DiagnosticGatewayError("invalid_gateway_response", "Gateway 未返回有效 run")
        returned_provider = run.get("provider")
        if returned_provider is not None and returned_provider != provider:
            raise DiagnosticGatewayError(
                "provider_mismatch",
                f"Gateway 使用了非请求 provider: {returned_provider!r}",
            )
        return run

    def get_run_history(self, session_id: str, run_id: str, *, after: int = 0) -> Mapping[str, Any]:
        return self._request_json(
            f"/sessions/{quote(session_id, safe='')}/runs/{quote(run_id, safe='')}?after={max(0, int(after))}",
            method="GET",
        )

    def wait_for_run(
        self,
        session_id: str,
        run: Mapping[str, Any],
        *,
        timeout: float = 900.0,
    ) -> DiagnosticRun:
        run_id = str(run["runId"])
        requested_provider = str(run.get("provider") or "")
        if not requested_provider:
            raise DiagnosticGatewayError("provider_missing", "Gateway run 没有记录 provider")
        deadline = time.monotonic() + max(0.1, float(timeout))
        history: Mapping[str, Any] = {}
        while True:
            history = self.get_run_history(session_id, run_id)
            summary = history.get("run")
            if not isinstance(summary, Mapping):
                raise DiagnosticGatewayError("invalid_gateway_response", "run history 缺少 run 摘要")
            status = str(summary.get("status") or "unknown")
            if status in TERMINAL_STATUSES:
                return self._make_run(session_id, run_id, requested_provider, history)
            if time.monotonic() >= deadline:
                return self._make_run(
                    session_id,
                    run_id,
                    requested_provider,
                    history,
                    timed_out=True,
                )
            time.sleep(self.poll_interval)

    def run_sample(
        self,
        sample: DiagnosticSample,
        *,
        provider: str,
        session_name: str | None = None,
        text: str = DEFAULT_DIAGNOSTIC_TEXT,
        timeout: float = 900.0,
    ) -> DiagnosticRun:
        """Run one sample end-to-end without silently switching providers."""

        provider = provider.strip()
        if not provider:
            raise DiagnosticGatewayError("provider_required", "真实诊断必须显式指定 provider")
        session_id = self.create_session(
            session_name or f"diagnostic-{sample.case_id}-{uuid.uuid4().hex[:8]}"
        )
        try:
            attachment_id = self.upload_attachment(session_id, sample)
            accepted = self.start_run(
                session_id,
                attachment_id=attachment_id,
                provider=provider,
                text=text,
            )
            result = self.wait_for_run(session_id, accepted, timeout=timeout)
            return result
        except DiagnosticGatewayError as exc:
            exc.session_id = session_id
            if "accepted" in locals():
                exc.run_id = str(accepted.get("runId")) if accepted.get("runId") else None
            raise

    def _make_run(
        self,
        session_id: str,
        run_id: str,
        requested_provider: str,
        history: Mapping[str, Any],
        *,
        timed_out: bool = False,
    ) -> DiagnosticRun:
        summary = history.get("run")
        summary = summary if isinstance(summary, Mapping) else {}
        provider = summary.get("provider")
        if provider is not None and provider != requested_provider:
            raise DiagnosticGatewayError(
                "provider_mismatch",
                f"Gateway history 使用了非请求 provider: {provider!r}",
            )
        return DiagnosticRun(
            session_id=session_id,
            run_id=run_id,
            requested_provider=requested_provider,
            provider=str(provider) if provider is not None else None,
            model=str(summary["model"]) if summary.get("model") is not None else None,
            status=str(summary.get("status") or "unknown"),
            history=history,
            timed_out=timed_out,
        )

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        body: Mapping[str, Any] | bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        data: bytes | None
        request_headers = {"Accept": "application/json"}
        if isinstance(body, bytes):
            data = body
        elif body is None:
            data = None
        else:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(getattr(response, "status", 200))
        except HTTPError as exc:
            detail = _error_detail(exc)
            raise DiagnosticGatewayError("gateway_http_error", detail, status=exc.code) from exc
        except URLError as exc:
            raise DiagnosticGatewayError("gateway_unreachable", "无法连接本地 Gateway") from exc
        except TimeoutError as exc:
            raise DiagnosticGatewayError("gateway_timeout", "Gateway 请求超时") from exc
        except OSError as exc:
            raise DiagnosticGatewayError("gateway_transport_error", "Gateway 传输失败") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DiagnosticGatewayError("gateway_response_too_large", "Gateway 响应超过限制", status=status)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiagnosticGatewayError("invalid_gateway_response", "Gateway 返回了非 JSON 响应", status=status) from exc
        if not isinstance(payload, dict):
            raise DiagnosticGatewayError("invalid_gateway_response", "Gateway 返回格式不是对象", status=status)
        if status >= 400 or "error" in payload:
            error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
            raise DiagnosticGatewayError(
                str(error.get("code") or "gateway_error"),
                str(error.get("message") or "Gateway 请求失败"),
                status=status,
            )
        return payload


def _error_detail(error: HTTPError) -> str:
    try:
        raw = error.read(MAX_RESPONSE_BYTES)
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, Mapping):
            detail = payload.get("error")
            if isinstance(detail, Mapping) and detail.get("message"):
                return str(detail["message"])[:500]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return f"Gateway HTTP {error.code}"
