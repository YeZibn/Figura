"""Versioned codecs for persisted tool calls, attempts, and results."""

from __future__ import annotations

import re
from typing import Any

from figura.shared.payloads import PayloadError, decode_json, payload_read_scope, utf8_size
from figura.shared.json_schema import JsonValueError, canonical_json_dumps, normalize_json_value
from figura.tools.contracts import ReplayEffect, ToolExecutionError, ToolOutcome, freeze_json_value

from ..errors import RunError, RunErrorCode
from ..models import ToolFactKind
from ..records import ToolAttemptStartedFact, ToolCallFact, ToolResultFact
from .common import (
    _bounded_string,
    _dump_bounded,
    _nonempty_string,
    _require_keys,
)


MAX_TOOL_FACT_JSON_BYTES = 512 * 1024


MAX_TOOL_CALLS_PER_RESPONSE = 64


MAX_TOOL_CALL_ARGUMENT_BYTES = 64 * 1024


MAX_TOOL_RESULT_JSON_BYTES = 256 * 1024


_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def encode_tool_fact(kind: ToolFactKind, payload: object) -> str:
    """Encode one versioned tool fact, including its bounded envelope."""
    return _dump_bounded(_tool_fact_to_dict(kind, payload), MAX_TOOL_FACT_JSON_BYTES if payload.schema_version == 1 else None)


@payload_read_scope
def decode_tool_fact(kind: ToolFactKind, schema_version: int, raw: str) -> object:
    """Decode one tool fact from its strict, versioned JSON representation."""
    value = _load_tool_json(raw)
    if not isinstance(value, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if value.get("schema_version") != schema_version:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if schema_version not in {1, 2}:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    if schema_version == 1:
        utf8_size(raw, MAX_TOOL_FACT_JSON_BYTES)
    if value.get("fact_kind") != kind.value:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if kind is ToolFactKind.TOOL_CALL:
        _require_keys(
            value,
            {"schema_version", "fact_kind", "response_record_id", "call_id", "tool_name", "arguments_json", "position", "registry_version"},
        )
        return ToolCallFact(
            response_record_id=_nonempty_string(value["response_record_id"], 128),
            call_id=_nonempty_string(value["call_id"], 256 if schema_version == 1 else None),
            tool_name=_tool_name(value["tool_name"]),
            arguments_json=_tool_arguments(value["arguments_json"], legacy=schema_version == 1),
            position=_position(value["position"], legacy=schema_version == 1),
            registry_version=_nonempty_string(value["registry_version"], 128),
            schema_version=schema_version,
        )

    if kind is ToolFactKind.TOOL_ATTEMPT_STARTED:
        _require_keys(
            value,
            {"schema_version", "fact_kind", "tool_call_sequence", "call_id", "attempt_id", "attempt_number", "replay_effect", "registry_version"},
        )
        try:
            replay_effect = ReplayEffect(value["replay_effect"])
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        return ToolAttemptStartedFact(
            tool_call_sequence=_positive_int(value["tool_call_sequence"]),
            call_id=_nonempty_string(value["call_id"], 256 if schema_version == 1 else None),
            attempt_id=_nonempty_string(value["attempt_id"], 128),
            attempt_number=_positive_int(value["attempt_number"]),
            replay_effect=replay_effect,
            registry_version=_nonempty_string(value["registry_version"], 128),
            schema_version=schema_version,
        )

    if kind is ToolFactKind.TOOL_RESULT:
        _require_keys(
            value,
            {"schema_version", "fact_kind", "tool_call_sequence", "attempt_id", "call_id", "tool_name", "outcome", "result", "error"},
        )
        try:
            outcome = ToolOutcome(value["outcome"])
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        result_raw = value["result"]
        error_raw = value["error"]
        result: dict[str, object] | None = None
        error: ToolExecutionError | None = None
        if outcome is ToolOutcome.SUCCEEDED:
            if not isinstance(result_raw, dict) or error_raw is not None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            result = _bounded_result(result_raw, legacy=schema_version == 1)
        else:
            if result_raw is not None or not isinstance(error_raw, dict):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            _require_keys(error_raw, {"code", "message", "retryable", "field_path"})
            error = _tool_error_from_dict(error_raw)
        return ToolResultFact(
            tool_call_sequence=_positive_int(value["tool_call_sequence"]),
            attempt_id=_nonempty_string(value["attempt_id"], 128),
            call_id=_nonempty_string(value["call_id"], 256 if schema_version == 1 else None),
            tool_name=_tool_name(value["tool_name"]),
            outcome=outcome,
            result=freeze_json_value(result) if result is not None else None,
            error=error,
            schema_version=schema_version,
        )
    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def validate_tool_call_batch(calls: tuple[ToolCallFact, ...]) -> None:
    """Validate provider order and aggregate bounds before any store write."""
    if not isinstance(calls, tuple) or not calls:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    seen_call_ids: set[str] = set()
    for index, call in enumerate(calls):
        if not isinstance(call, ToolCallFact) or call.position != index:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if call.call_id in seen_call_ids:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        seen_call_ids.add(call.call_id)
        encode_tool_fact(ToolFactKind.TOOL_CALL, call)
    _dump_bounded([_tool_fact_to_dict(ToolFactKind.TOOL_CALL, call) for call in calls], None)


def _tool_fact_to_dict(kind: ToolFactKind, payload: object) -> dict[str, Any]:
    if kind is ToolFactKind.TOOL_CALL and isinstance(payload, ToolCallFact):
        if payload.schema_version not in {1, 2}:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        return {
            "schema_version": payload.schema_version,
            "fact_kind": kind.value,
            "response_record_id": _nonempty_string(payload.response_record_id, 128),
            "call_id": _nonempty_string(payload.call_id, 256 if payload.schema_version == 1 else None),
            "tool_name": _tool_name(payload.tool_name),
            "arguments_json": _tool_arguments(payload.arguments_json, legacy=payload.schema_version == 1),
            "position": _position(payload.position, legacy=payload.schema_version == 1),
            "registry_version": _nonempty_string(payload.registry_version, 128),
        }
    if kind is ToolFactKind.TOOL_ATTEMPT_STARTED and isinstance(payload, ToolAttemptStartedFact):
        if payload.schema_version not in {1, 2}:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        try:
            effect = ReplayEffect(payload.replay_effect)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        return {
            "schema_version": payload.schema_version,
            "fact_kind": kind.value,
            "tool_call_sequence": _positive_int(payload.tool_call_sequence),
            "call_id": _nonempty_string(payload.call_id, 256 if payload.schema_version == 1 else None),
            "attempt_id": _nonempty_string(payload.attempt_id, 128),
            "attempt_number": _positive_int(payload.attempt_number),
            "replay_effect": effect.value,
            "registry_version": _nonempty_string(payload.registry_version, 128),
        }
    if kind is ToolFactKind.TOOL_RESULT and isinstance(payload, ToolResultFact):
        if payload.schema_version not in {1, 2}:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        try:
            outcome = ToolOutcome(payload.outcome)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        result: dict[str, object] | None = None
        error: dict[str, object] | None = None
        if outcome is ToolOutcome.SUCCEEDED:
            if payload.error is not None or payload.result is None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            result = _bounded_result(payload.result, legacy=payload.schema_version == 1)
        else:
            if payload.result is not None or not isinstance(payload.error, ToolExecutionError):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            error = _tool_error_to_dict(payload.error)
        return {
            "schema_version": payload.schema_version,
            "fact_kind": kind.value,
            "tool_call_sequence": _positive_int(payload.tool_call_sequence),
            "attempt_id": _nonempty_string(payload.attempt_id, 128),
            "call_id": _nonempty_string(payload.call_id, 256 if payload.schema_version == 1 else None),
            "tool_name": _tool_name(payload.tool_name),
            "outcome": outcome.value,
            "result": result,
            "error": error,
        }
    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _load_tool_json(raw: str) -> object:
    try:
        return decode_json(raw)
    except PayloadError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _tool_arguments(value: object, *, legacy: bool = False) -> str:
    try:
        parsed = decode_json(value, maximum=MAX_TOOL_CALL_ARGUMENT_BYTES if legacy else None)
        if not isinstance(parsed, dict):
            raise PayloadError("arguments must be an object")
    except PayloadError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return value


def _bounded_result(value: object, *, legacy: bool = False) -> dict[str, object]:
    try:
        normalized = normalize_json_value(value)
        if not isinstance(normalized, dict):
            raise JsonValueError("result must be a JSON object")
        if len(canonical_json_dumps(normalized).encode("utf-8")) > MAX_TOOL_RESULT_JSON_BYTES and legacy:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return normalized
    except RunError:
        raise
    except (JsonValueError, UnicodeEncodeError, TypeError, ValueError, RecursionError, OverflowError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None


def _tool_error_to_dict(error: ToolExecutionError) -> dict[str, object]:
    if not isinstance(error, ToolExecutionError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        validated = ToolExecutionError(error.code, error.message, error.retryable, error.field_path)
    except (TypeError, ValueError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    if not _ERROR_CODE.fullmatch(validated.code):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return {
        "code": validated.code,
        "message": _bounded_string(validated.message, 512),
        "retryable": validated.retryable,
        "field_path": validated.field_path,
    }


def _tool_error_from_dict(value: dict[str, object]) -> ToolExecutionError:
    code = _bounded_string(value["code"], 64)
    message = _bounded_string(value["message"], 512)
    retryable = value["retryable"]
    field_path = value["field_path"]
    if not _ERROR_CODE.fullmatch(code) or type(retryable) is not bool:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    if field_path is not None and not isinstance(field_path, str):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        return ToolExecutionError(code, message, retryable, field_path)
    except (TypeError, ValueError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None


def _tool_name(value: object) -> str:
    name = _bounded_string(value, None)
    if not _TOOL_NAME.fullmatch(name):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return name


def _positive_int(value: object) -> int:
    if type(value) is not int or value < 1:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return value


def _position(value: object, *, legacy: bool = False) -> int:
    if type(value) is not int or value < 0 or (legacy and value >= MAX_TOOL_CALLS_PER_RESPONSE):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return value

