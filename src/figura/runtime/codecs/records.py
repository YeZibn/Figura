"""Versioned codecs for Run input, Provider response, and continuation records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from figura.providers.models import ProviderId, ProviderUsage
from figura.shared.image_limits import MAX_IMAGE_COUNT

from ..errors import RunError, RunErrorCode
from ..models import RecordKind
from ..records import (
    FinalAnswerFact,
    ModelResponseFact,
    ProviderContinuationFact,
    RunInput,
)
from .common import (
    _bounded_count,
    _bounded_string,
    _dump_bounded,
    _load_bounded,
    _nonempty_string,
    _require_keys,
)


MAX_RECORD_JSON_BYTES = 256 * 1024


MAX_PROVIDER_CONTINUATION_BYTES = 512 * 1024


def encode_payload(kind: RecordKind, payload: object) -> str:
    """Validate and serialize a typed payload using canonical JSON."""
    value = payload_to_dict(kind, payload)
    return _dump_bounded(value, MAX_RECORD_JSON_BYTES)


def decode_payload(
    kind: RecordKind,
    raw: str,
    *,
    expected_schema_version: int | None = None,
) -> RunInput | ModelResponseFact | FinalAnswerFact:
    value = _load_bounded(raw, MAX_RECORD_JSON_BYTES)
    if not isinstance(value, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    supported_versions = {1, 2} if kind is RecordKind.MODEL_RESPONSE else {1}
    if schema_version not in supported_versions:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    if expected_schema_version is not None and schema_version != expected_schema_version:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if kind is RecordKind.INPUT:
        _require_keys(value, {"schema_version", "text", "attachment_ids", "requested_provider", "requested_model"})
        text = _bounded_string(value["text"], 64 * 1024)
        attachments = _validate_attachment_ids(value["attachment_ids"], persisted=True)
        provider = _bounded_string(value["requested_provider"], 64)
        model = _bounded_string(value["requested_model"], 128)
        return RunInput(text, attachments, provider, model, schema_version)

    if kind is RecordKind.MODEL_RESPONSE:
        expected_keys = {
            "schema_version",
            "provider_id",
            "model_id",
            "assistant_content",
            "finish_reason",
            "usage",
            "provider_response_id",
        }
        if schema_version == 2:
            expected_keys.add("continuation_ref")
        _require_keys(value, expected_keys)
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
        continuation_ref = value.get("continuation_ref")
        if continuation_ref is not None:
            continuation_ref = _nonempty_string(continuation_ref, 128)
        return ModelResponseFact(
            provider_id=_bounded_string(value["provider_id"], 64),
            model_id=_bounded_string(value["model_id"], 128),
            assistant_content=_bounded_string(value["assistant_content"], 128 * 1024),
            finish_reason=_bounded_string(value["finish_reason"], 32),
            usage=usage,
            provider_response_id=response_id,
            continuation_ref=continuation_ref,
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
        attachments = _validate_attachment_ids(payload.attachment_ids)
        return {
            "schema_version": 1,
            "text": _bounded_string(payload.text, 64 * 1024),
            "attachment_ids": list(attachments),
            "requested_provider": _bounded_string(payload.requested_provider, 64),
            "requested_model": _bounded_string(payload.requested_model, 128),
        }
    if kind is RecordKind.MODEL_RESPONSE and isinstance(payload, ModelResponseFact):
        if type(payload.schema_version) is not int or payload.schema_version not in {1, 2}:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        if payload.schema_version == 1 and payload.continuation_ref is not None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
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
        result: dict[str, Any] = {
            "schema_version": payload.schema_version,
            "provider_id": _bounded_string(payload.provider_id, 64),
            "model_id": _bounded_string(payload.model_id, 128),
            "assistant_content": _bounded_string(payload.assistant_content, 128 * 1024),
            "finish_reason": _bounded_string(payload.finish_reason, 32),
            "usage": usage_dict,
            "provider_response_id": response_id,
        }
        if payload.schema_version == 2:
            result["continuation_ref"] = (
                _nonempty_string(payload.continuation_ref, 128)
                if payload.continuation_ref is not None
                else None
            )
        return result
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


def _validate_attachment_ids(value: object, *, persisted: bool = False) -> tuple[str, ...]:
    error_code = RunErrorCode.INTEGRITY_ERROR if persisted else RunErrorCode.UNSUPPORTED_PAYLOAD
    if not isinstance(value, (tuple, list)) or len(value) > MAX_IMAGE_COUNT:
        raise RunError(error_code)
    try:
        attachment_ids = tuple(_nonempty_string(item, 128) for item in value)
    except RunError:
        raise RunError(error_code) from None
    if len(set(attachment_ids)) != len(attachment_ids):
        raise RunError(error_code)
    return attachment_ids


def validate_provider_continuation_fact(
    fact: object,
    *,
    persisted: bool = False,
) -> ProviderContinuationFact:
    """Validate one private continuation payload before write or after read."""
    invalid_code = RunErrorCode.INTEGRITY_ERROR if persisted else RunErrorCode.UNSUPPORTED_PAYLOAD
    if not isinstance(fact, ProviderContinuationFact):
        raise RunError(invalid_code)
    try:
        ProviderId(fact.provider_id)
    except (TypeError, ValueError):
        raise RunError(invalid_code) from None
    for value in (fact.continuation_id, fact.run_id, fact.response_record_id):
        if not isinstance(value, str) or not value:
            raise RunError(invalid_code)
        try:
            if len(value.encode("utf-8")) > 128:
                raise RunError(invalid_code)
        except UnicodeEncodeError:
            raise RunError(invalid_code) from None
    if type(fact.format_version) is not int:
        raise RunError(invalid_code)
    if fact.format_version != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    if type(fact.schema_version) is not int:
        raise RunError(invalid_code)
    if fact.schema_version != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    content = fact.reasoning_content
    if (
        (content is not None and not isinstance(content, str))
        or (fact.provider_id != ProviderId.DEEPSEEK.value and not content)
    ):
        raise RunError(invalid_code)
    if isinstance(content, str):
        try:
            if len(content.encode("utf-8")) > MAX_PROVIDER_CONTINUATION_BYTES:
                raise RunError(invalid_code)
        except UnicodeEncodeError:
            raise RunError(invalid_code) from None
    for value, maximum in ((fact.created_at, 64),):
        if not isinstance(value, str) or not value:
            raise RunError(invalid_code)
        try:
            if len(value.encode("utf-8")) > maximum:
                raise RunError(invalid_code)
        except UnicodeEncodeError:
            raise RunError(invalid_code) from None
    try:
        timestamp = datetime.fromisoformat(
            fact.created_at[:-1] + "+00:00"
            if fact.created_at.endswith("Z")
            else fact.created_at
        )
    except ValueError:
        raise RunError(invalid_code) from None
    if timestamp.utcoffset() != timezone.utc.utcoffset(None):
        raise RunError(invalid_code)
    return fact

