"""Physical JSON admission, independent from cumulative execution quotas."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import json
from io import StringIO
import math
import os
import re


DEFAULT_MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 64


class PayloadError(ValueError):
    """Safe rejection without retaining the offending value."""


class PayloadTooLarge(PayloadError):
    """The complete encoded payload exceeds the physical admission guard."""


@dataclass(frozen=True)
class ExecutionPayloadLimits:
    max_json_bytes: int = DEFAULT_MAX_JSON_BYTES

    def __post_init__(self) -> None:
        if type(self.max_json_bytes) is not int or self.max_json_bytes <= 0:
            raise PayloadError("execution payload limit must be a positive integer")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ExecutionPayloadLimits:
        values = os.environ if environ is None else environ
        raw = values.get("FIGURA_EXECUTION_PAYLOAD_MAX_BYTES", str(DEFAULT_MAX_JSON_BYTES))
        if not re.fullmatch(r"[0-9]+", raw.strip()):
            raise PayloadError("execution payload configuration is invalid")
        return cls(int(raw))


_LIMITS = ContextVar("figura_execution_payload_limits", default=ExecutionPayloadLimits())
_READ_LIMITS = ContextVar("figura_execution_payload_read_limits", default=ExecutionPayloadLimits())


def current_payload_limits() -> ExecutionPayloadLimits:
    return _LIMITS.get()


def current_payload_read_limits() -> ExecutionPayloadLimits:
    return _READ_LIMITS.get()


@contextmanager
def use_payload_read_limits(limits: ExecutionPayloadLimits):
    token = _READ_LIMITS.set(limits)
    try:
        yield
    finally:
        _READ_LIMITS.reset(token)


def payload_read_scope(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        with use_payload_limits(current_payload_read_limits()):
            return function(*args, **kwargs)
    return invoke


@contextmanager
def use_payload_limits(limits: ExecutionPayloadLimits):
    token = _LIMITS.set(limits)
    try:
        yield
    finally:
        _LIMITS.reset(token)


def payload_scope(method):
    """Propagate the owner's explicit immutable limits into nested helpers."""
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with use_payload_limits(self.payload_limits):
            return method(self, *args, **kwargs)
    return invoke


def utf8_size(value: str, maximum: int | None = None) -> int:
    if not isinstance(value, str):
        raise PayloadError("value must be UTF-8 text")
    limit = current_payload_limits().max_json_bytes if maximum is None else maximum
    # Avoid allocating an encoded copy of an arbitrarily large string.
    if len(value) > limit:
        raise PayloadTooLarge("JSON payload exceeds its byte guard")
    size = 0
    try:
        for offset in range(0, len(value), 8192):
            size += len(value[offset:offset + 8192].encode("utf-8"))
            if size > limit:
                raise PayloadTooLarge("JSON payload exceeds its byte guard")
    except UnicodeError:
        raise PayloadError("text is not valid UTF-8") from None
    return size


def opaque_call_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise PayloadError("call identity must be nonempty UTF-8 text")
    utf8_size(value)
    return value


def tool_name(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise PayloadError("tool name syntax is invalid")
    utf8_size(value)
    return value


def normalize_json(value: object, *, max_depth: int = MAX_JSON_DEPTH, maximum: int | None = None) -> object:
    limit = current_payload_limits().max_json_bytes if maximum is None else maximum
    lower_bound = 0
    def charge(size):
        nonlocal lower_bound
        lower_bound += size
        if lower_bound > limit:
            raise PayloadTooLarge("JSON payload exceeds its byte guard")

    def visit(item, depth):
        if item is None or type(item) in (bool, int):
            try:
                size = len(str(item)) if item is not None else 4
            except ValueError:
                raise PayloadError("JSON integer cannot be encoded safely") from None
            charge(size)
            return item
        if isinstance(item, str):
            charge(utf8_size(item, limit) + 2)
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise PayloadError("JSON numbers must be finite")
            charge(len(str(item)))
            return item
        if isinstance(item, Mapping):
            if depth > max_depth:
                raise PayloadError("JSON nesting is too deep")
            charge(2 + max(0, len(item) - 1))
            result = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise PayloadError("JSON object keys must be strings")
                charge(utf8_size(key, limit) + 3)
                result[key] = visit(nested, depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            if depth > max_depth:
                raise PayloadError("JSON nesting is too deep")
            charge(2 + max(0, len(item) - 1))
            return [visit(nested, depth + 1) for nested in item]
        raise PayloadError("value is not JSON-compatible")
    return visit(value, 0)


def encode_json(value: object, *, maximum: int | None = None) -> str:
    limit = current_payload_limits().max_json_bytes if maximum is None else maximum
    normalized = normalize_json(value, maximum=limit)
    output = StringIO()
    size = 0
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    try:
        for chunk in encoder.iterencode(normalized):
            size += utf8_size(chunk, limit)
            if size > limit:
                raise PayloadTooLarge("JSON payload exceeds its byte guard")
            output.write(chunk)
    except PayloadError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise PayloadError("JSON payload cannot be encoded within its guard") from None
    return output.getvalue()


def decode_json(raw: str, *, maximum: int | None = None) -> object:
    utf8_size(raw, maximum)
    # Bound depth before json.loads allocates containers. Strings can contain braces.
    depth = -1
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise PayloadError("JSON nesting is too deep")
        elif char in "]}":
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PayloadError("JSON object keys must be unique")
            result[key] = value
        return result

    def constant(_):
        raise PayloadError("JSON numbers must be finite")

    try:
        return normalize_json(json.loads(raw, object_pairs_hook=pairs, parse_constant=constant), maximum=maximum)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise PayloadError("JSON payload cannot be decoded safely") from None
