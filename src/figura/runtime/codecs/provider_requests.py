"""Canonical immutable logical Provider request contract."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timezone
import math
import re
from types import MappingProxyType

from figura.shared.payloads import decode_json, encode_json, PayloadError, payload_read_scope
from figura.providers.token_estimation import ContextEstimate
from ..records import ProviderRequestRecord
from ..errors import RunError, RunErrorCode

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OPTIONS = {
    "max_completion_tokens", "thinking_mode", "reasoning_effort",
    "connect_timeout_seconds", "write_timeout_seconds",
}
_MANIFEST = {"prompt_digest", "registry_version", "registry_digest", "adapter_contract_version", "images"}
_IMAGE = {"source_ref", "observation_kind", "media_type", "byte_count", "sha256"}
_REQUEST_FIELDS = {item.name for item in fields(ProviderRequestRecord)}


def _digest(value: object) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def validate_provider_request(request: ProviderRequestRecord) -> None:
    if not isinstance(request, ProviderRequestRecord):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    for name in ("request_id", "run_id", "created_at", "provider_id", "model_id"):
        if not isinstance(getattr(request, name), str) or not getattr(request, name):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        created = datetime.fromisoformat(request.created_at.replace("Z", "+00:00"))
        if created.utcoffset() != timezone.utc.utcoffset(created):
            raise ValueError
    except (ValueError, TypeError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    if request.purpose not in {"agent_turn", "context_compaction", "historical_import"}:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.purpose == "context_compaction":
        if not isinstance(request.compaction_operation_id, str) or not request.compaction_operation_id:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    elif request.compaction_operation_id is not None:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    integer_fields = (
        "schema_version", "request_contract_version", "stream_contract_version",
        "timeout_policy_version", "retry_policy_version", "max_attempts",
    )
    if any(type(getattr(request, name)) is not int for name in integer_fields):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if (
        request.schema_version != 2 or request.request_contract_version != 2
        or request.stream_contract_version != 1 or request.timeout_policy_version != 1
        or request.retry_policy_version != 1 or request.max_attempts != 4
        or request.provider_id not in {"qwen", "deepseek", "mimo"}
        or type(request.base_record_sequence) is not int or request.base_record_sequence < 1
        or type(request.base_tool_sequence) is not int or request.base_tool_sequence < 0
        or not _digest(request.endpoint_identity) or not _digest(request.request_fingerprint)
    ):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.purpose == "historical_import":
        # Historical attempts without a frozen request descriptor remain inspectable,
        # but can never be claimed for dispatch or retry.
        if request.generation_only is not False or any(value != "0" * 64 for value in (
            request.request_fingerprint, request.endpoint_identity,
            request.prompt_digest, request.tool_registry_digest,
        )):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return
    if request.generation_only is not True:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if not isinstance(request.options, Mapping) or set(request.options) != _OPTIONS:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if type(request.options["thinking_mode"]) is not bool:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    completion = request.options["max_completion_tokens"]
    if completion is not None and (type(completion) is not int or completion <= 0):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.options["reasoning_effort"] is not None and not isinstance(request.options["reasoning_effort"], str):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    for name in ("connect_timeout_seconds", "write_timeout_seconds"):
        timeout = request.options[name]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    manifest = request.asset_manifest
    if (
        not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST
        or not _digest(manifest["prompt_digest"]) or not _digest(manifest["registry_digest"])
        or not isinstance(manifest["registry_version"], str) or not manifest["registry_version"]
        or type(manifest["adapter_contract_version"]) is not int
        or manifest["adapter_contract_version"] != 1
        or not isinstance(manifest["images"], (tuple, list))
    ):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.prompt_digest != manifest["prompt_digest"] or request.tool_registry_digest != manifest["registry_digest"]:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    for image in manifest["images"]:
        if not isinstance(image, Mapping) or set(image) != _IMAGE or image["observation_kind"] not in {"original", "annotated", "rendered"} or image["media_type"] not in {"image/jpeg", "image/png", "image/gif", "image/webp"} or type(image["byte_count"]) is not int or image["byte_count"] <= 0 or not _digest(image["sha256"]):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        ref = image["source_ref"]
        if not isinstance(ref, Mapping):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if image["observation_kind"] == "original":
            valid = set(ref) == {"kind", "id"} and ref["kind"] in {"attachment", "panel"}
        else:
            kinds = {"ocr", "measurement"} if image["observation_kind"] == "annotated" else {"chart_render"}
            valid = set(ref) == {"kind", "run_id", "call_id"} and ref["kind"] in kinds
        if not valid or any(not isinstance(value, str) or not value for value in ref.values()):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    estimate = request.context_estimate
    if estimate is not None and (
        not isinstance(estimate, ContextEstimate)
        or type(estimate.input_tokens) is not int or estimate.input_tokens < 0
        or (estimate.context_window_tokens is not None and (type(estimate.context_window_tokens) is not int or estimate.context_window_tokens <= 0))
        or not isinstance(estimate.estimator_version, str) or not estimate.estimator_version
    ):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.context_projection not in {"full", "checkpoint", "fallback"}:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.context_projection == "checkpoint":
        if type(request.context_checkpoint_revision) is not int or request.context_checkpoint_revision < 1 or not isinstance(request.context_checkpoint_operation_id, str) or not request.context_checkpoint_operation_id:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    elif request.context_checkpoint_revision is not None:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if request.context_projection == "fallback":
        if not isinstance(request.context_checkpoint_operation_id, str) or not request.context_checkpoint_operation_id:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    elif request.context_projection == "full" and request.context_checkpoint_operation_id is not None:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def encode_provider_request(request: ProviderRequestRecord) -> str:
    try:
        validate_provider_request(request)
        value = {item.name: getattr(request, item.name) for item in fields(ProviderRequestRecord)}
        estimate = request.context_estimate
        value["context_estimate"] = None if estimate is None else {
            item.name: getattr(estimate, item.name) for item in fields(ContextEstimate)
        }
        return encode_json(value)
    except (PayloadError, TypeError, AttributeError, OverflowError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None


@payload_read_scope
def decode_provider_request(raw: str) -> ProviderRequestRecord:
    try:
        value = decode_json(raw)
        if not isinstance(value, dict) or set(value) != _REQUEST_FIELDS:
            raise ValueError
        estimate = value["context_estimate"]
        if estimate is not None:
            if not isinstance(estimate, dict) or set(estimate) != {item.name for item in fields(ContextEstimate)}:
                raise ValueError
            value["context_estimate"] = ContextEstimate(**estimate)
        value["options"] = _freeze(value["options"])
        value["asset_manifest"] = _freeze(value["asset_manifest"])
        request = ProviderRequestRecord(**value)
        validate_provider_request(request)
        return request
    except (PayloadError, TypeError, ValueError, RunError, OverflowError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
