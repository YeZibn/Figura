"""Conservative transport classification and safe persisted retry deadlines."""
from __future__ import annotations

import random
import socket
import ssl
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from .errors import ProviderFailure, ProviderFailureCode


def retry_deadline(attempt_number: int, retry_after_seconds: float | None = None) -> str:
    delay = random.uniform(0, min(30.0, 2.0 ** (attempt_number - 1)))
    if retry_after_seconds is not None:
        delay = max(delay, retry_after_seconds)
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def retry_after(headers: object) -> float | None:
    try:
        raw = headers.get("retry-after")
        if not isinstance(raw, str) or len(raw) > 128:
            return None
        if raw.isascii() and raw.isdigit():
            seconds = float(raw)
        else:
            stamp = parsedate_to_datetime(raw)
            if stamp.tzinfo is None:
                return None
            seconds = (stamp - datetime.now(timezone.utc)).total_seconds()
        # datetime supports a finite range; invalid/unrepresentable deadlines are ignored.
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return max(0.0, seconds)
    except (AttributeError, ValueError, OverflowError, TypeError):
        return None


def classify_failure(error: Exception) -> ProviderFailure:
    code = ProviderFailureCode.TRANSPORT_ERROR
    known, transient, status, after = False, False, None, None
    if isinstance(error, APIStatusError):
        status = error.status_code if type(error.status_code) is int and 100 <= error.status_code <= 599 else None
        known = status is not None and status < 500 and status != 408
        code = ProviderFailureCode.PROVIDER_REJECTED if known else ProviderFailureCode.PROVIDER_UNAVAILABLE
        transient = status in {408, 429, 500, 502, 503, 504}
        # Whitelist metadata only; neither body nor its message is persisted.
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            detail = body.get("error", body)
            if isinstance(detail, dict) and any(detail.get(key) in {
                "insufficient_quota", "quota_exceeded", "insufficient_balance", "billing_hard_limit_reached", "account_deactivated"
            } for key in ("code", "type")):
                transient = False
        after = retry_after(error.response.headers) if transient else None
    elif isinstance(error, (APITimeoutError, APIConnectionError)):
        code = ProviderFailureCode.TIMEOUT if isinstance(error, APITimeoutError) else ProviderFailureCode.CONNECTION_ERROR
        cause = error.__cause__
        chain = []
        while cause is not None and len(chain) < 8:
            chain.append(cause)
            cause = cause.__cause__
        permanent = any(isinstance(item, ssl.SSLError) or (isinstance(item, socket.gaierror) and item.errno != socket.EAI_AGAIN) for item in chain)
        no_send = any(isinstance(item, (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError, socket.gaierror)) for item in chain)
        known = permanent or no_send
        transient = not permanent and (isinstance(error, APITimeoutError) or any(isinstance(item, (httpx.NetworkError, httpx.TimeoutException)) or (isinstance(item, socket.gaierror) and item.errno == socket.EAI_AGAIN) for item in chain))
    message = {
        ProviderFailureCode.TIMEOUT: "等待模型服务商响应超时。",
        ProviderFailureCode.CONNECTION_ERROR: "与模型服务商的连接失败。",
        ProviderFailureCode.PROVIDER_REJECTED: "模型服务商拒绝了本次请求。",
        ProviderFailureCode.PROVIDER_UNAVAILABLE: "模型服务商暂时无法完成本次请求。",
    }.get(code, "模型请求传输失败。")
    return ProviderFailure(code, known, transient, message, status, after)
