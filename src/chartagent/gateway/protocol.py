"""Versioned, JSON-safe protocol objects for the local desktop gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

GATEWAY_VERSION = "v1"
MAX_SESSION_NAME = 128
MAX_MESSAGE_TEXT = 12000
MAX_ERROR_MESSAGE = 240


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


@dataclass(frozen=True)
class ConversationText:
    id: str
    kind: str
    text: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "timestamp": self.timestamp,
        }


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
