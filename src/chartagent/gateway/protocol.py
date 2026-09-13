"""Versioned, JSON-safe protocol objects for the local desktop gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from ..trace import sanitize_payload, truncate_text

GATEWAY_VERSION = "v1"
MAX_SESSION_NAME = 128
MAX_MESSAGE_TEXT = 12000
MAX_ERROR_MESSAGE = 240
MAX_ATTACHMENT_IDS = 16
MAX_ATTACHMENT_ID = 128
MAX_RUN_ID = 128
MAX_EVENT_KIND = 64
MAX_EVENT_PAYLOAD = 12000
MAX_ARTIFACT_CAPTION = 500
MAX_ARTIFACT_TITLE = 240
MAX_ARTIFACT_CHART_TYPE = 64


class GatewayFault(Exception):
    """An expected failure that can be represented safely over HTTP."""

    def __init__(self, code: str, status: int, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message[:MAX_ERROR_MESSAGE]
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        error = {
            "version": GATEWAY_VERSION,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.reason:
            error["error"]["reason"] = self.reason
        return error


class RunStatus(str, Enum):
    """External lifecycle states for a Gateway run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunAccepted:
    """Bounded response returned before an asynchronous run completes."""

    run_id: str
    session_id: str
    status: RunStatus = RunStatus.RUNNING

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "sessionId": self.session_id,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class ObservationReference:
    """Safe metadata for a temporary generated visual observation."""

    observation_id: str
    media_type: str
    caption: str
    byte_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "observationId": self.observation_id,
            "mediaType": self.media_type,
            "caption": truncate_text(self.caption, 500),
            "byteCount": self.byte_count,
        }


@dataclass(frozen=True)
class GeneratedChartReference:
    """Safe metadata for a durable, user-facing generated chart artifact."""

    artifact_id: str
    media_type: str
    caption: str
    byte_count: int
    chart_type: str
    title: str
    width: int
    height: int
    status: str = "available"
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifactKind": "generated_chart",
            "artifactId": self.artifact_id,
            "mediaType": self.media_type,
            "caption": truncate_text(self.caption, MAX_ARTIFACT_CAPTION),
            "byteCount": max(0, int(self.byte_count)),
            "chartType": truncate_text(self.chart_type, MAX_ARTIFACT_CHART_TYPE),
            "title": truncate_text(self.title, MAX_ARTIFACT_TITLE),
            "width": max(0, int(self.width)),
            "height": max(0, int(self.height)),
            "status": self.status,
        }
        if self.reason:
            result["reason"] = truncate_text(self.reason, MAX_ERROR_MESSAGE)
        return result


@dataclass(frozen=True)
class RunEvent:
    """A bounded event envelope shared by JSON and SSE transports."""

    run_id: str
    sequence: int
    kind: str
    payload: Mapping[str, Any] = None  # type: ignore[assignment]
    timestamp: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", truncate_text(self.kind, MAX_EVENT_KIND))
        payload = sanitize_payload(self.payload or {})
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_EVENT_PAYLOAD:
            payload = {
                "truncated": True,
                "preview": truncate_text(encoded, MAX_EVENT_PAYLOAD // 2),
            }
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "timestamp", self.timestamp or utc_timestamp())

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def _validate_text(value: object, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise GatewayFault("invalid_request", 400, f"{field} must be text")
    clean = value.strip()
    if not clean:
        raise GatewayFault("invalid_request", 400, f"{field} must not be empty")
    if len(clean) > limit:
        raise GatewayFault("invalid_request", 400, f"{field} exceeds the size limit")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in clean):
        raise GatewayFault("invalid_request", 400, f"{field} contains unsupported control characters")
    return clean


def validate_session_name(value: object) -> str:
    return _validate_text(value, field="name", limit=MAX_SESSION_NAME)


def validate_message_text(value: object) -> str:
    return _validate_text(value, field="text", limit=MAX_MESSAGE_TEXT)


def validate_attachment_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ATTACHMENT_IDS:
        raise GatewayFault("invalid_request", 400, "attachmentIds must be a bounded list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.startswith("att_") or len(item) > MAX_ATTACHMENT_ID:
            raise GatewayFault("invalid_request", 400, "attachmentIds contains an invalid ID")
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in item):
            raise GatewayFault("invalid_request", 400, "attachmentIds contains an invalid ID")
        if item in result:
            raise GatewayFault("invalid_request", 400, "attachmentIds contains duplicate IDs")
        result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class ConversationText:
    id: str
    kind: str
    text: str
    timestamp: str
    attachment_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "timestamp": self.timestamp,
        }
        if self.attachment_ids:
            result["attachmentIds"] = list(self.attachment_ids)
        return result


@dataclass(frozen=True)
class SessionSummary:
    id: str
    name: str
    updated_at: str
    run_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "updatedAt": self.updated_at,
            "runCount": self.run_count,
        }


@dataclass(frozen=True)
class AttachmentSummary:
    """Safe attachment metadata exposed by the gateway protocol."""

    attachment_id: str
    filename: str
    media_type: str
    byte_count: int
    sha256: str
    status: str
    preview_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "media_type": self.media_type,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "status": self.status,
            "preview_available": self.preview_available,
        }


@dataclass(frozen=True)
class SessionTranscript:
    session: SessionSummary
    messages: tuple[ConversationText, ...] = ()
    attachments: tuple[Mapping[str, Any], ...] = ()
    runs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": GATEWAY_VERSION,
            "session": self.session.to_dict(),
            "messages": [message.to_dict() for message in self.messages],
            "attachments": [dict(attachment) for attachment in self.attachments],
            "runs": [dict(run) for run in self.runs],
        }


def success(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add the protocol version to a successful response payload."""
    return {"version": GATEWAY_VERSION, **dict(payload)}
