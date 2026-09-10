"""Versioned, JSON-safe protocol objects for the local desktop gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

GATEWAY_VERSION = "v1"
MAX_SESSION_NAME = 128
MAX_MESSAGE_TEXT = 12000
MAX_ERROR_MESSAGE = 240
MAX_ATTACHMENT_IDS = 16
MAX_ATTACHMENT_ID = 128


class GatewayFault(Exception):
    """An expected failure that can be represented safely over HTTP."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message[:MAX_ERROR_MESSAGE]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": GATEWAY_VERSION,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": GATEWAY_VERSION,
            "session": self.session.to_dict(),
            "messages": [message.to_dict() for message in self.messages],
            "attachments": [dict(attachment) for attachment in self.attachments],
        }


def success(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add the protocol version to a successful response payload."""
    return {"version": GATEWAY_VERSION, **dict(payload)}
