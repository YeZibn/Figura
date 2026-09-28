"""Versioned codecs for persisted tool calls, attempts, and results."""

from __future__ import annotations

import json
import re
from typing import Any

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


MAX_TOOL_CALL_AGGREGATE_ARGUMENT_BYTES = 1024 * 1024


MAX_TOOL_RESULT_JSON_BYTES = 256 * 1024


_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def encode_tool_fact(kind: ToolFactKind, payload: object) -> str:
    """Encode one versioned tool fact, including its bounded envelope."""
    return _dump_bounded(_tool_fact_to_dict(kind, payload), MAX_TOOL_FACT_JSON_BYTES)


def decode_tool_fact(kind: ToolFactKind, schema_version: int, raw: str) -> object:
    """Decode one tool fact from its strict, versioned JSON representation."""
    value = _load_tool_json(raw)
    if not isinstance(value, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if value.get("schema_version") != schema_version:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if schema_version != 1:
        raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
    if value.get("fact_kind") != kind.value:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    if kind is ToolFactKind.TOOL_CALL:
        _require_keys(
            value,
            {"schema_version", "fact_kind", "response_record_id", "call_id", "tool_name", "arguments_json", "position", "registry_version"},
        )
        return ToolCallFact(
            response_record_id=_nonempty_string(value["response_record_id"], 128),
            call_id=_nonempty_string(value["call_id"], 256),
            tool_name=_tool_name(value["tool_name"]),
            arguments_json=_tool_arguments(value["arguments_json"]),
            position=_position(value["position"]),
            registry_version=_nonempty_string(value["registry_version"], 128),
            schema_version=1,
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
            call_id=_nonempty_string(value["call_id"], 256),
            attempt_id=_nonempty_string(value["attempt_id"], 128),
            attempt_number=_positive_int(value["attempt_number"]),
            replay_effect=replay_effect,
            registry_version=_nonempty_string(value["registry_version"], 128),
            schema_version=1,
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
            result = _bounded_result(result_raw)
        else:
            if result_raw is not None or not isinstance(error_raw, dict):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            _require_keys(error_raw, {"code", "message", "retryable", "field_path"})
            error = _tool_error_from_dict(error_raw)
        return ToolResultFact(
            tool_call_sequence=_positive_int(value["tool_call_sequence"]),
            attempt_id=_nonempty_string(value["attempt_id"], 128),
            call_id=_nonempty_string(value["call_id"], 256),
            tool_name=_tool_name(value["tool_name"]),
            outcome=outcome,
            result=freeze_json_value(result) if result is not None else None,
            error=error,
            schema_version=1,
        )
    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def validate_tool_call_batch(calls: tuple[ToolCallFact, ...]) -> None:
    """Validate provider order and aggregate bounds before any store write."""
    if not isinstance(calls, tuple) or not 1 <= len(calls) <= MAX_TOOL_CALLS_PER_RESPONSE:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    seen_call_ids: set[str] = set()
    total_argument_bytes = 0
    for index, call in enumerate(calls):
        if not isinstance(call, ToolCallFact) or call.position != index:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if call.call_id in seen_call_ids:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        seen_call_ids.add(call.call_id)
        encode_tool_fact(ToolFactKind.TOOL_CALL, call)
        total_argument_bytes += len(call.arguments_json.encode("utf-8"))
        if total_argument_bytes > MAX_TOOL_CALL_AGGREGATE_ARGUMENT_BYTES:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _tool_fact_to_dict(kind: ToolFactKind, payload: object) -> dict[str, Any]:
    if kind is ToolFactKind.TOOL_CALL and isinstance(payload, ToolCallFact):
        if payload.schema_version != 1:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        return {
            "schema_version": 1,
            "fact_kind": kind.value,
            "response_record_id": _nonempty_string(payload.response_record_id, 128),
            "call_id": _nonempty_string(payload.call_id, 256),
            "tool_name": _tool_name(payload.tool_name),
            "arguments_json": _tool_arguments(payload.arguments_json),
            "position": _position(payload.position),
            "registry_version": _nonempty_string(payload.registry_version, 128),
        }
    if kind is ToolFactKind.TOOL_ATTEMPT_STARTED and isinstance(payload, ToolAttemptStartedFact):
        if payload.schema_version != 1:
            raise RunError(RunErrorCode.UNSUPPORTED_VERSION)
        try:
            effect = ReplayEffect(payload.replay_effect)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        return {
            "schema_version": 1,
            "fact_kind": kind.value,
            "tool_call_sequence": _positive_int(payload.tool_call_sequence),
            "call_id": _nonempty_string(payload.call_id, 256),
            "attempt_id": _nonempty_string(payload.attempt_id, 128),
            "attempt_number": _positive_int(payload.attempt_number),
            "replay_effect": effect.value,
            "registry_version": _nonempty_string(payload.registry_version, 128),
        }
    if kind is ToolFactKind.TOOL_RESULT and isinstance(payload, ToolResultFact):
        if payload.schema_version != 1:
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
            result = _bounded_result(payload.result)
        else:
            if payload.result is not None or not isinstance(payload.error, ToolExecutionError):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            error = _tool_error_to_dict(payload.error)
        return {
            "schema_version": 1,
            "fact_kind": kind.value,
            "tool_call_sequence": _positive_int(payload.tool_call_sequence),
            "attempt_id": _nonempty_string(payload.attempt_id, 128),
            "call_id": _nonempty_string(payload.call_id, 256),
            "tool_name": _tool_name(payload.tool_name),
            "outcome": outcome.value,
            "result": result,
            "error": error,
        }
    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _load_tool_json(raw: str) -> object:
    if not isinstance(raw, str):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        if len(raw.encode("utf-8")) > MAX_TOOL_FACT_JSON_BYTES:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except RunError:
        raise
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError, OverflowError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _tool_arguments(value: object) -> str:
    if not isinstance(value, str):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        if len(value.encode("utf-8")) > MAX_TOOL_CALL_ARGUMENT_BYTES:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        parsed = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(parsed, dict):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        normalized = normalize_json_value(parsed)
        # Validate Unicode scalars without canonicalizing the stored raw JSON.
        canonical_json_dumps(normalized).encode("utf-8")
    except RunError:
        raise
    except (TypeError, ValueError, UnicodeEncodeError, JsonValueError, RecursionError, OverflowError):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return value


def _bounded_result(value: object) -> dict[str, object]:
    try:
        normalized = normalize_json_value(value)
        if not isinstance(normalized, dict):
            raise JsonValueError("result must be a JSON object")
        if len(canonical_json_dumps(normalized).encode("utf-8")) > MAX_TOOL_RESULT_JSON_BYTES:
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
    name = _bounded_string(value, 64)
    if not _TOOL_NAME.fullmatch(name):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return name


def _positive_int(value: object) -> int:
    if type(value) is not int or value < 1:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return value


def _position(value: object) -> int:
    if type(value) is not int or not 0 <= value < MAX_TOOL_CALLS_PER_RESPONSE:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return value

