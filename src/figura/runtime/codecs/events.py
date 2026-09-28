"""Strict bounded codecs for persisted Run stream events."""

from __future__ import annotations

import json

from ..errors import RunError, RunErrorCode
from ..models import EventKind
from .common import _bounded_string, _dump_bounded, _load_bounded, _require_keys


MAX_EVENT_JSON_BYTES = 16 * 1024


def encode_event_payload(kind: EventKind, payload: dict[str, object]) -> str:
    expected = {
        EventKind.RUN_CREATED: {"session_id", "ordinal"},
        EventKind.RUN_COMPLETED: {"final_artifact_refs"},
        EventKind.RUN_FAILED: {"terminal_code"},
        EventKind.RUN_INTERRUPTED: {"terminal_code"},
    }[kind]
    if set(payload) != expected:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    safe: dict[str, object]
    if kind is EventKind.RUN_CREATED:
        ordinal = payload["ordinal"]
        if type(ordinal) is not int or ordinal < 1:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        safe = {"session_id": _bounded_string(payload["session_id"], 128), "ordinal": ordinal}
    elif kind is EventKind.RUN_COMPLETED:
        refs = payload["final_artifact_refs"]
        if not isinstance(refs, (list, tuple)) or len(refs) != 0:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        safe = {"final_artifact_refs": []}
    else:
        code = _bounded_string(payload["terminal_code"], 64)
        safe = {"terminal_code": code}
    return _dump_bounded(safe, MAX_EVENT_JSON_BYTES)


def decode_event_payload(kind: EventKind, raw: str) -> dict[str, object]:
    value = _load_bounded(raw, MAX_EVENT_JSON_BYTES)
    if not isinstance(value, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    expected = {
        EventKind.RUN_CREATED: {"session_id", "ordinal"},
        EventKind.RUN_COMPLETED: {"final_artifact_refs"},
        EventKind.RUN_FAILED: {"terminal_code"},
        EventKind.RUN_INTERRUPTED: {"terminal_code"},
    }[kind]
    _require_keys(value, expected)
    encoded = encode_event_payload(kind, value)
    normalized = json.loads(encoded)
    if kind is EventKind.RUN_COMPLETED:
        normalized["final_artifact_refs"] = tuple(normalized["final_artifact_refs"])
    return normalized

