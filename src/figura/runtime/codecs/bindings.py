"""Private durable Provider operation binding contract."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timezone
import math
import re
from types import MappingProxyType

from figura.shared.payloads import decode_json, encode_json, PayloadError, payload_read_scope
from ..records import ProviderRequestBinding
from ..errors import RunError, RunErrorCode
from figura.providers.token_estimation import ContextEstimate

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OPTIONS = {"max_completion_tokens", "stream", "thinking_mode", "reasoning_effort", "timeout_seconds"}
_MANIFEST = {"prompt_digest", "registry_version", "registry_digest", "adapter_contract_version", "images"}
_IMAGE = {"source_ref", "observation_kind", "media_type", "byte_count", "sha256"}


def binding_dict(binding: ProviderRequestBinding) -> dict:
    compatibility_fields = {
        "context_projection",
        "context_checkpoint_revision",
        "context_compaction_operation_id",
    }
    value = {
        item.name: getattr(binding, item.name)
        for item in fields(binding)
        if item.name != "context_estimate"
        and (binding.schema_version >= 3 or item.name not in compatibility_fields)
    }
    if binding.schema_version in {2, 3}:
        estimate = binding.context_estimate
        value["context_estimate"] = None if estimate is None else {
            item.name: getattr(estimate, item.name) for item in fields(ContextEstimate)
        }
    return value


def _digest(value: object) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def validate_binding(binding: ProviderRequestBinding) -> None:
    if not isinstance(binding, ProviderRequestBinding):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    for name in ("operation_id", "run_id", "created_at", "provider_id", "model_id"):
        if not isinstance(getattr(binding, name), str) or not getattr(binding, name):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        created = datetime.fromisoformat(binding.created_at.replace("Z", "+00:00"))
        if created.utcoffset() != timezone.utc.utcoffset(created):
            raise ValueError
    except (ValueError, TypeError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    if any(type(getattr(binding, name)) is not int for name in ("schema_version", "request_contract_version", "retry_policy_version", "max_attempts")):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if binding.provider_id not in {"qwen", "deepseek", "mimo"} or any(
        type(value) is not int or value < minimum for value, minimum in (
            (binding.base_record_sequence, 1), (binding.base_tool_sequence, 0))
    ) or binding.schema_version not in {1, 2, 3} or binding.request_contract_version != 1 or binding.retry_policy_version != 1 or binding.max_attempts != 4 or binding.generation_only is not True:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if binding.schema_version < 3:
        if (
            binding.context_projection != "full"
            or binding.context_checkpoint_revision is not None
            or binding.context_compaction_operation_id is not None
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    else:
        if binding.context_projection not in {"full", "checkpoint", "fallback"}:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if binding.context_projection == "checkpoint":
            if (
                type(binding.context_checkpoint_revision) is not int
                or binding.context_checkpoint_revision < 1
                or not isinstance(binding.context_compaction_operation_id, str)
                or not binding.context_compaction_operation_id
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        elif binding.context_projection == "fallback":
            if (
                binding.context_checkpoint_revision is not None
                or not isinstance(binding.context_compaction_operation_id, str)
                or not binding.context_compaction_operation_id
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        elif (
            binding.context_checkpoint_revision is not None
            or binding.context_compaction_operation_id is not None
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    estimate = binding.context_estimate
    if binding.schema_version == 1 and estimate is not None:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if estimate is not None and (
        not isinstance(estimate, ContextEstimate)
        or type(estimate.input_tokens) is not int or estimate.input_tokens < 0
        or (estimate.context_window_tokens is not None and (
            type(estimate.context_window_tokens) is not int or estimate.context_window_tokens <= 0))
        or not isinstance(estimate.estimator_version, str) or not estimate.estimator_version
    ):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if not _digest(binding.endpoint_binding) or not _digest(binding.request_fingerprint):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    options = binding.options
    if not isinstance(options, Mapping) or set(options) != _OPTIONS or options["stream"] is not False or type(options["thinking_mode"]) is not bool:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    completion = options["max_completion_tokens"]
    if completion is not None and (type(completion) is not int or completion <= 0):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if options["reasoning_effort"] is not None and not isinstance(options["reasoning_effort"], str):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    timeout = options["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    manifest = binding.asset_manifest
    if not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST or not _digest(manifest["prompt_digest"]) or not _digest(manifest["registry_digest"]) or not isinstance(manifest["registry_version"], str) or not manifest["registry_version"] or type(manifest["adapter_contract_version"]) is not int or manifest["adapter_contract_version"] != 1 or not isinstance(manifest["images"], (tuple, list)):
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


def encode_binding(binding: ProviderRequestBinding) -> str:
    try:
        validate_binding(binding)
        return encode_json(binding_dict(binding))
    except (PayloadError, TypeError, AttributeError, OverflowError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@payload_read_scope
def decode_binding(raw: str) -> ProviderRequestBinding:
    try:
        value = decode_json(raw)
        if not isinstance(value, dict):
            raise ValueError
        keys = {item.name for item in fields(ProviderRequestBinding)}
        schema_version = value.get("schema_version")
        if schema_version == 1:
            keys.remove("context_estimate")
        if schema_version in {1, 2}:
            keys.difference_update({
                "context_projection",
                "context_checkpoint_revision",
                "context_compaction_operation_id",
            })
        if set(value) != keys:
            raise ValueError
        if schema_version in {1, 2}:
            value["context_projection"] = "full"
            value["context_checkpoint_revision"] = None
            value["context_compaction_operation_id"] = None
        estimate = value.get("context_estimate")
        if estimate is not None:
            if not isinstance(estimate, dict) or set(estimate) != {item.name for item in fields(ContextEstimate)}:
                raise ValueError
            value["context_estimate"] = ContextEstimate(**estimate)
        value["options"] = _freeze(value["options"])
        value["asset_manifest"] = _freeze(value["asset_manifest"])
        binding = ProviderRequestBinding(**value)
        validate_binding(binding)
        return binding
    except (PayloadError, TypeError, ValueError, RunError, OverflowError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
