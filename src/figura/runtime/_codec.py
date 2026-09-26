"""Strict versioned codecs for the first durable Figura execution facts."""

from __future__ import annotations

import json
from typing import Any

from figura.providers.models import ProviderUsage

from .errors import RunError, RunErrorCode
from .models import (
    EventKind,
    ExecutionRecord,
    FinalAnswerFact,
    ModelResponseFact,
    RecordKind,
    RunInput,
    RunStreamEvent,
)

MAX_RECORD_JSON_BYTES = 256 * 1024
MAX_EVENT_JSON_BYTES = 16 * 1024


def encode_payload(kind: RecordKind, payload: object) -> str:
    """Validate and serialize a typed payload using canonical JSON."""
    value = payload_to_dict(kind, payload)
    return _dump_bounded(value, MAX_RECORD_JSON_BYTES)


def decode_payload(kind: RecordKind, raw: str) -> RunInput | ModelResponseFact | FinalAnswerFact:
    value = _load_bounded(raw, MAX_RECORD_JSON_BYTES)
    if not isinstance(value, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    schema_version = value.get("schema_version")
    if schema_version != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)

    if kind is RecordKind.INPUT:
        _require_keys(value, {"schema_version", "text", "attachment_ids", "requested_provider", "requested_model"})
        text = _bounded_string(value["text"], 64 * 1024)
        attachments = value["attachment_ids"]
        if not isinstance(attachments, list) or any(not isinstance(item, str) for item in attachments):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        provider = _bounded_string(value["requested_provider"], 64)
        model = _bounded_string(value["requested_model"], 128)
        return RunInput(text, tuple(attachments), provider, model, schema_version)

    if kind is RecordKind.MODEL_RESPONSE:
        _require_keys(value, {"schema_version", "provider_id", "model_id", "assistant_content", "finish_reason", "usage", "provider_response_id"})
        usage_raw = value["usage"]
        usage: ProviderUsage | None = None
        if usage_raw is not None:
            if not isinstance(usage_raw, dict):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            _require_keys(usage_raw, {"prompt_tokens", "completion_tokens", "total_tokens"})
            counts: dict[str, int | None] = {}
            for key, count in usage_raw.items():
                if count is not None and (type(count) is not int or count < 0 or count > 2**31 - 1):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                counts[key] = count
            usage = ProviderUsage(**counts)
        response_id = value["provider_response_id"]
        if response_id is not None:
            response_id = _bounded_string(response_id, 512)
        return ModelResponseFact(
            provider_id=_bounded_string(value["provider_id"], 64),
            model_id=_bounded_string(value["model_id"], 128),
            assistant_content=_bounded_string(value["assistant_content"], 128 * 1024),
            finish_reason=_bounded_string(value["finish_reason"], 32),
            usage=usage,
            provider_response_id=response_id,
            schema_version=schema_version,
        )

    if kind is RecordKind.FINAL_ANSWER:
        _require_keys(value, {"schema_version", "response_record_id", "artifact_refs", "guard_version"})
        refs = value["artifact_refs"]
        if not isinstance(refs, list) or len(refs) > 64:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return FinalAnswerFact(
            response_record_id=_bounded_string(value["response_record_id"], 128),
            artifact_refs=tuple(_bounded_string(ref, 128) for ref in refs),
            guard_version=_bounded_string(value["guard_version"], 64),
            schema_version=schema_version,
        )
    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def payload_to_dict(kind: RecordKind, payload: object) -> dict[str, Any]:
    if kind is RecordKind.INPUT and isinstance(payload, RunInput):
        if payload.schema_version != 1:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        if payload.attachment_ids:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return {
            "schema_version": 1,
            "text": _bounded_string(payload.text, 64 * 1024),
            "attachment_ids": [],
            "requested_provider": _bounded_string(payload.requested_provider, 64),
            "requested_model": _bounded_string(payload.requested_model, 128),
        }
    if kind is RecordKind.MODEL_RESPONSE and isinstance(payload, ModelResponseFact):
        if payload.schema_version != 1:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        usage = payload.usage
        usage_dict = None
        if usage is not None:
            usage_dict = {
                "prompt_tokens": _bounded_count(usage.prompt_tokens),
                "completion_tokens": _bounded_count(usage.completion_tokens),
                "total_tokens": _bounded_count(usage.total_tokens),
            }
        response_id = payload.provider_response_id
        if response_id is not None:
            response_id = _bounded_string(response_id, 512)
        return {
            "schema_version": 1,
            "provider_id": _bounded_string(payload.provider_id, 64),
            "model_id": _bounded_string(payload.model_id, 128),
            "assistant_content": _bounded_string(payload.assistant_content, 128 * 1024),
            "finish_reason": _bounded_string(payload.finish_reason, 32),
            "usage": usage_dict,
            "provider_response_id": response_id,
        }
    if kind is RecordKind.FINAL_ANSWER and isinstance(payload, FinalAnswerFact):
        if payload.schema_version != 1:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        if payload.guard_version != "text-only-v1" or payload.artifact_refs:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return {
            "schema_version": 1,
            "response_record_id": _bounded_string(payload.response_record_id, 128),
            "artifact_refs": [],
            "guard_version": "text-only-v1",
        }
    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


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


def _dump_bounded(value: object, maximum: int) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        encoded_length = len(raw.encode("utf-8"))
    except (TypeError, ValueError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    except UnicodeEncodeError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    if encoded_length > maximum:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return raw


def _load_bounded(raw: str, maximum: int) -> object:
    if not isinstance(raw, str):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        if len(raw.encode("utf-8")) > maximum:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
    except UnicodeEncodeError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _require_keys(value: dict[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _bounded_string(value: object, maximum_bytes: int) -> str:
    if not isinstance(value, str):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        if len(value.encode("utf-8")) > maximum_bytes:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    except UnicodeEncodeError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return value


def _bounded_count(value: object) -> int | None:
    if value is not None and (type(value) is not int or value < 0 or value > 2**31 - 1):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return value
