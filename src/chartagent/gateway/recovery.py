"""Versioned, bounded recovery checkpoint values.

Checkpoints are a journal boundary, not a second event stream.  This module
keeps the representation deliberately boring: JSON-safe state, opaque
references, a digest, and a version that can be rejected when the shape
changes. Provider responses, image bytes, credentials, and local paths never
belong in a checkpoint; the only provider-private exception is bounded
DeepSeek reasoning required for an authorized tool continuation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..memory.context import PRIVATE_REASONING_LIMIT, sanitize_payload as sanitize_memory_payload
from ..trace import sanitize_payload as sanitize_trace_payload, truncate_text
from .protocol import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointPhase,
    MAX_CHECKPOINT_PAYLOAD,
    MAX_OPERATION_RESULT,
    MAX_RECOVERY_REASON,
    RecoveryStatus,
)


class CheckpointError(ValueError):
    """A checkpoint is malformed, oversized, expired, or unsupported."""


_REMOVED_KEYS = frozenset({
    "path", "local_path", "managed_path", "canonical_path", "filesystem_path", "uri", "url",
    "image_bytes", "bytes", "data_url", "raw_response", "raw_provider_response",
})
_REFERENCE_PREFIXES = ("att_", "obs_", "cand_", "art_", "review_")
_LOCAL_PATH = re.compile(r"(?:/(?:Users|private|tmp|var|home|opt|etc)/|[A-Za-z]:\\)")


def _has_oversized_private_reasoning(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            (str(key).lower() == "reasoning_content" and isinstance(item, str) and len(item) > PRIVATE_REASONING_LIMIT)
            or _has_oversized_private_reasoning(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_oversized_private_reasoning(item) for item in value)
    return False


def _strip_internal(value: Any, *, depth: int = 0) -> Any:
    """Remove storage/process details after the generic trace sanitization."""
    if depth > 8:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:64]:
            key = str(raw_key)
            if key.lower() in _REMOVED_KEYS or key.lower().endswith("_path"):
                continue
            result[key] = _strip_internal(raw_value, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_strip_internal(item, depth=depth + 1) for item in value[:64]]
    if isinstance(value, tuple):
        return [_strip_internal(item, depth=depth + 1) for item in value[:64]]
    if isinstance(value, str):
        return _LOCAL_PATH.sub("[PATH_OMITTED]", value)
    return value


def sanitize_checkpoint_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return bounded JSON-safe state suitable for durable recovery."""
    if state is None:
        state = {}
    if not isinstance(state, Mapping):
        raise CheckpointError("checkpoint state must be an object")
    if _has_oversized_private_reasoning(state):
        raise CheckpointError("provider reasoning context exceeds checkpoint limit")
    # This is the authorized checkpoint boundary. It is the only durable
    # path allowed to retain DeepSeek's exact reasoning_content for a later
    # tool continuation; ordinary memory and trace sanitizers remove it.
    clean = _strip_internal(sanitize_memory_payload(state, preserve_private_reasoning=True))
    if not isinstance(clean, dict):
        raise CheckpointError("checkpoint state must be an object")
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_CHECKPOINT_PAYLOAD:
        raise CheckpointError("checkpoint payload exceeds the size limit")
    return clean


def _valid_reference(value: Any, *, prefix: str | None = None) -> bool:
    if not isinstance(value, str) or not value or len(value) > 160:
        return False
    if "/" in value or "\\" in value or any(ord(char) < 33 for char in value):
        return False
    return value.startswith(prefix or _REFERENCE_PREFIXES)


def authorized_references(state: Mapping[str, Any]) -> dict[str, list[str]]:
    """Extract only opaque attachment/artifact references from checkpoint state."""
    result: dict[str, list[str]] = {"attachmentIds": [], "observationIds": [], "candidateIds": [], "artifactIds": [], "reviewIds": []}
    mapping = {
        "attachmentIds": "att_",
        "attachments": "att_",
        "observationIds": "obs_",
        "observations": "obs_",
        "candidateIds": "cand_",
        "candidates": "cand_",
        "artifactIds": "art_",
        "artifacts": "art_",
        "reviewIds": "review_",
        "reviews": "review_",
    }
    for key, prefix in mapping.items():
        value = state.get(key)
        values = value if isinstance(value, list) else [value]
        target = {
            "attachments": "attachmentIds", "attachmentIds": "attachmentIds",
            "observations": "observationIds", "observationIds": "observationIds",
            "candidates": "candidateIds", "candidateIds": "candidateIds",
            "artifacts": "artifactIds", "artifactIds": "artifactIds",
            "reviews": "reviewIds", "reviewIds": "reviewIds",
        }[key]
        for item in values:
            if _valid_reference(item, prefix=prefix) and item not in result[target]:
                result[target].append(item)
    return result


def checkpoint_digest(state: Mapping[str, Any], *, version: int = CHECKPOINT_SCHEMA_VERSION) -> str:
    """Digest canonical checkpoint state and schema version."""
    clean = sanitize_checkpoint_state(state)
    encoded = json.dumps({"version": int(version), "state": clean}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def serialize_checkpoint(
    state: Mapping[str, Any],
    *,
    phase: CheckpointPhase | str,
    next_action: str,
    version: int = CHECKPOINT_SCHEMA_VERSION,
) -> tuple[str, str]:
    """Serialize validated state and return ``(json, sha256)``."""
    if int(version) != CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointError("unsupported checkpoint version")
    try:
        normalized_phase = CheckpointPhase(phase).value
    except ValueError as exc:
        raise CheckpointError("unsupported checkpoint phase") from exc
    if not isinstance(next_action, str) or not next_action.strip() or len(next_action) > 120:
        raise CheckpointError("checkpoint next action is invalid")
    clean = sanitize_checkpoint_state(state)
    encoded = json.dumps(
        {"version": int(version), "phase": normalized_phase, "nextAction": truncate_text(next_action, 120), "state": clean},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded) > MAX_CHECKPOINT_PAYLOAD:
        raise CheckpointError("checkpoint payload exceeds the size limit")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deserialize_checkpoint(payload: str, digest: str | None = None, *, version: int = CHECKPOINT_SCHEMA_VERSION) -> dict[str, Any]:
    """Validate and decode a stored checkpoint without exposing raw storage."""
    if not isinstance(payload, str) or len(payload) > MAX_CHECKPOINT_PAYLOAD:
        raise CheckpointError("checkpoint payload is unavailable")
    if digest and hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
        raise CheckpointError("checkpoint digest mismatch")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CheckpointError("checkpoint payload is invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("version") != int(version):
        raise CheckpointError("unsupported checkpoint version")
    if not isinstance(parsed.get("state"), dict) or not isinstance(parsed.get("phase"), str):
        raise CheckpointError("checkpoint payload is invalid")
    try:
        CheckpointPhase(parsed["phase"])
    except ValueError as exc:
        raise CheckpointError("unsupported checkpoint phase") from exc
    return parsed


@dataclass(frozen=True)
class RecoveryCheckpoint:
    """Internal checkpoint row with a public projection helper."""

    checkpoint_id: str
    run_id: str
    version: int
    phase: str
    next_action: str
    state: dict[str, Any]
    digest: str
    status: RecoveryStatus
    blocked_reason: str | None
    created_at: str
    expires_at: float
    sequence: int = 0

    def public(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "checkpointId": self.checkpoint_id,
            "checkpointVersion": self.version,
            "phase": self.phase,
            "nextAction": self.next_action,
            "status": self.status.value,
            "updatedAt": self.created_at,
            "expiresAt": self.expires_at,
        }
        if self.blocked_reason:
            result["blockedReason"] = truncate_text(self.blocked_reason, MAX_RECOVERY_REASON)
        return result


def bounded_operation_result(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    clean = _strip_internal(sanitize_trace_payload(value))
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_OPERATION_RESULT:
        return json.dumps({"truncated": True}, ensure_ascii=False, separators=(",", ":"))
    return encoded


__all__ = [
    "CheckpointError", "RecoveryCheckpoint", "authorized_references",
    "bounded_operation_result", "checkpoint_digest", "deserialize_checkpoint",
    "sanitize_checkpoint_state", "serialize_checkpoint",
]
