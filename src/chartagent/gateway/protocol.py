"""Versioned, JSON-safe protocol objects for the local desktop gateway."""

from __future__ import annotations

import json
import hashlib
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
MAX_IDEMPOTENCY_KEY = 128
MAX_TERMINAL_CODE = 64
MAX_EVENT_KIND = 64
MAX_EVENT_PAYLOAD = 12000
MAX_CHECKPOINT_PAYLOAD = 64 * 1024
MAX_OPERATION_RESULT = 16 * 1024
MAX_RECOVERY_REASON = 240
MAX_OPERATION_ID = 160
SUPPORTED_PROVIDERS = ("openai", "qwen", "deepseek")
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


class RunTerminalReason(str, Enum):
    """Stable bounded reasons for an unsuccessful or interrupted run."""

    USER_CANCELLED = "user_cancelled"
    GATEWAY_RESTARTED = "gateway_restarted"
    PROVIDER_TIMEOUT = "provider_timeout"
    WORKER_ERROR = "worker_error"
    RUN_TIMEOUT = "run_timeout"
    AGENT_FAILED = "agent_failed"
    AGENT_UNAVAILABLE = "agent_unavailable"
    REVIEW_FAILED = "review_failed"
    REVIEW_INCOMPLETE = "review_incomplete"
    HISTORY_EXPIRED = "history_expired"


class RecoveryStatus(str, Enum):
    """Whether a terminal run has a safe, explicit continuation available."""

    AVAILABLE = "available"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class CheckpointPhase(str, Enum):
    """The last durable boundary reached by a run."""

    ACCEPTED = "accepted"
    MODEL = "model"
    TOOL = "tool"
    RENDER = "render"
    REVIEW = "review"
    PUBLICATION = "publication"
    FINAL = "final"


class OperationState(str, Enum):
    """Durable state of a resumable work unit."""

    NOT_STARTED = "not_started"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    UNKNOWN = "uncertain"  # compatibility spelling for persisted crash windows


class ContinuationKind(str, Enum):
    """How a child run relates to its parent."""

    RESUME = "resume"
    RETRY = "retry"


CHECKPOINT_SCHEMA_VERSION = 1
RECOVERY_UNAVAILABLE_CODE = "recovery_unavailable"
RECOVERY_BLOCKED_CODE = "recovery_blocked"
CHECKPOINT_EXPIRED_CODE = "checkpoint_expired"
CHECKPOINT_VERSION_CODE = "unsupported_checkpoint_version"
RESUME_IDEMPOTENCY_CONFLICT_CODE = "resume_idempotency_conflict"


IDEMPOTENCY_CONFLICT_CODE = "idempotency_conflict"
HISTORY_GAP_CODE = "history_gap"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunLineage:
    """Normalized parent/root relationship for continuation and retry runs."""

    parent_run_id: str | None = None
    root_run_id: str | None = None
    continuation_kind: ContinuationKind | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.parent_run_id:
            result["parentRunId"] = truncate_text(self.parent_run_id, MAX_RUN_ID)
        if self.root_run_id:
            result["rootRunId"] = truncate_text(self.root_run_id, MAX_RUN_ID)
        if self.continuation_kind:
            result["continuationKind"] = self.continuation_kind.value
        return result


@dataclass(frozen=True)
class RunRecovery:
    """Bounded public recovery projection; checkpoint payloads never leave storage."""

    status: RecoveryStatus = RecoveryStatus.UNAVAILABLE
    checkpoint_id: str | None = None
    checkpoint_version: int | None = None
    phase: CheckpointPhase | None = None
    next_action: str | None = None
    blocked_reason: str | None = None
    updated_at: str | None = None
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status.value}
        if self.checkpoint_id:
            result["checkpointId"] = truncate_text(self.checkpoint_id, MAX_RUN_ID)
        if self.checkpoint_version is not None:
            result["checkpointVersion"] = int(self.checkpoint_version)
        if self.phase:
            result["phase"] = self.phase.value
        if self.next_action:
            result["nextAction"] = truncate_text(self.next_action, 120)
        if self.blocked_reason:
            result["blockedReason"] = truncate_text(self.blocked_reason, MAX_RECOVERY_REASON)
        if self.updated_at:
            result["updatedAt"] = self.updated_at
        if self.expires_at is not None:
            result["expiresAt"] = self.expires_at
        return result


@dataclass(frozen=True)
class RunAccepted:
    """Bounded response returned before an asynchronous run completes."""

    run_id: str
    session_id: str
    status: RunStatus = RunStatus.RUNNING
    provider: str | None = None
    model: str | None = None
    terminal_code: str | None = None
    terminal_message: str | None = None
    retry_of: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    continuation_kind: ContinuationKind | None = None
    recovery: RunRecovery | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "runId": self.run_id,
            "sessionId": self.session_id,
            "status": self.status.value,
        }
        if self.provider:
            result["provider"] = self.provider
        if self.model:
            result["model"] = self.model
        if self.terminal_code:
            result["terminalCode"] = truncate_text(self.terminal_code, MAX_TERMINAL_CODE)
        if self.terminal_message:
            result["terminalMessage"] = truncate_text(self.terminal_message, MAX_ERROR_MESSAGE)
        if self.retry_of:
            result["retryOf"] = truncate_text(self.retry_of, MAX_RUN_ID)
        lineage = RunLineage(self.parent_run_id or self.retry_of, self.root_run_id, self.continuation_kind)
        result.update(lineage.to_dict())
        if self.recovery is not None:
            result["recovery"] = self.recovery.to_dict()
        return result


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

    artifact_id: str | None
    media_type: str
    caption: str
    byte_count: int
    chart_type: str
    title: str
    width: int
    height: int
    status: str = "available"
    reason: str | None = None
    candidate_id: str | None = None
    review_id: str | None = None
    chart_spec_digest: str | None = None
    candidate_status: str | None = None
    review_status: str | None = None
    publication_status: str | None = None
    review_mode: str | None = None
    review: Mapping[str, Any] | None = None
    figure_id: str | None = None
    collection_id: str | None = None
    child_chart_ids: tuple[str, ...] = ()
    source: Mapping[str, Any] | None = None
    layout: Mapping[str, Any] | None = None
    coverage: Mapping[str, Any] | None = None
    chart_types: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifactKind": "generated_chart",
            "mediaType": self.media_type,
            "caption": truncate_text(self.caption, MAX_ARTIFACT_CAPTION),
            "byteCount": max(0, int(self.byte_count)),
            "chartType": truncate_text(self.chart_type, MAX_ARTIFACT_CHART_TYPE),
            "title": truncate_text(self.title, MAX_ARTIFACT_TITLE),
            "width": max(0, int(self.width)),
            "height": max(0, int(self.height)),
            "status": self.status,
        }
        if self.artifact_id:
            result["artifactId"] = self.artifact_id
        if self.candidate_id:
            result["candidateId"] = self.candidate_id
        if self.review_id:
            result["reviewId"] = self.review_id
        if self.chart_spec_digest:
            result["chartSpecDigest"] = self.chart_spec_digest
        if self.candidate_status:
            result["candidateStatus"] = self.candidate_status
        if self.review_status:
            result["reviewStatus"] = self.review_status
        if self.publication_status:
            result["publicationStatus"] = self.publication_status
        if self.review_mode:
            result["reviewMode"] = truncate_text(self.review_mode, 32)
        if self.figure_id:
            result["figureId"] = truncate_text(self.figure_id, 128)
        if self.collection_id:
            result["collectionId"] = truncate_text(self.collection_id, 128)
        if self.child_chart_ids:
            result["childChartIds"] = [truncate_text(item, 128) for item in self.child_chart_ids[:16]]
        if self.chart_types:
            result["chartTypes"] = [truncate_text(item, 64) for item in self.chart_types[:16]]
        for key, value in (("source", self.source), ("layout", self.layout), ("coverage", self.coverage)):
            if isinstance(value, Mapping):
                result[key] = sanitize_payload(value)
        if isinstance(self.review, Mapping):
            result["review"] = sanitize_payload(self.review)
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
            if self.kind == "tool_result":
                payload = _truncate_tool_result_payload(payload)
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


def _truncate_tool_result_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bound only the diagnostic body while retaining call correlation fields."""
    identity_fields = (
        "tool_name",
        "tool_display_name",
        "tool_label",
        "call_id",
        "status",
        "tool_status",
        "turn",
    )
    identity = {
        field: payload[field] if isinstance(payload[field], (bool, int, float)) else truncate_text(payload[field], 160)
        for field in identity_fields
        if field in payload
    }
    optional = {
        field: payload[field]
        for field in ("image_count", "observations", "artifacts")
        if field in payload
    }
    body = payload.get("result")
    encoded_body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def fit(optional_fields: Mapping[str, Any]) -> dict[str, Any] | None:
        """Find the largest preview that still fits the event envelope."""
        base = dict(identity)
        base.update(optional_fields)

        def candidate(preview: str) -> dict[str, Any]:
            result = dict(base)
            result["result"] = {"truncated": True, "preview": preview}
            return result

        empty = candidate("")
        if len(json.dumps(empty, ensure_ascii=False, separators=(",", ":"))) > MAX_EVENT_PAYLOAD:
            return None
        low, high = 0, len(encoded_body)
        best = empty
        while low <= high:
            middle = (low + high) // 2
            current = candidate(truncate_text(encoded_body, middle))
            encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) <= MAX_EVENT_PAYLOAD:
                best = current
                low = middle + 1
            else:
                high = middle - 1
        return best

    return fit(optional) or fit({}) or {
        "tool_name": identity.get("tool_name", ""),
        "call_id": identity.get("call_id", ""),
        "status": identity.get("status", ""),
        "result": {"truncated": True, "preview": ""},
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


def validate_provider(value: object, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or value.strip().lower() not in SUPPORTED_PROVIDERS:
        raise GatewayFault("invalid_provider", 400, "provider must be openai, qwen, or deepseek")
    return value.strip().lower()


def validate_idempotency_key(value: object, *, allow_none: bool = True) -> str | None:
    """Validate the opaque request key without accepting control characters."""
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise GatewayFault("invalid_request", 400, "Idempotency-Key must be text")
    clean = value.strip()
    if not clean or len(clean) > MAX_IDEMPOTENCY_KEY:
        raise GatewayFault("invalid_request", 400, "Idempotency-Key is invalid")
    if any(ord(char) < 33 or ord(char) > 126 for char in clean):
        raise GatewayFault("invalid_request", 400, "Idempotency-Key is invalid")
    return clean


def request_fingerprint(
    session_id: str,
    text: str,
    attachment_ids: tuple[str, ...],
    provider: str | None,
) -> str:
    """Create a stable digest for work-affecting, already-normalized inputs."""
    payload = json.dumps(
        {
            "sessionId": session_id,
            "text": text,
            "attachmentIds": list(attachment_ids),
            "provider": provider,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ConversationText:
    id: str
    kind: str
    text: str
    timestamp: str
    attachment_ids: tuple[str, ...] = ()
    association_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "timestamp": self.timestamp,
        }
        if self.attachment_ids:
            result["attachmentIds"] = list(self.attachment_ids)
        if self.association_status:
            result["associationStatus"] = self.association_status
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
    active_source_attachment_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": GATEWAY_VERSION,
            "session": self.session.to_dict(),
            "messages": [message.to_dict() for message in self.messages],
            "attachments": [dict(attachment) for attachment in self.attachments],
            "runs": [dict(run) for run in self.runs],
            "activeSourceAttachmentIds": list(self.active_source_attachment_ids[:16]),
        }


def success(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add the protocol version to a successful response payload."""
    return {"version": GATEWAY_VERSION, **dict(payload)}
