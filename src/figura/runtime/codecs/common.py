"""Shared bounded JSON primitives used by persisted Runtime codecs."""

from __future__ import annotations

import json

from ..errors import RunError, RunErrorCode


def _nonempty_string(value: object, maximum: int) -> str:
    result = _bounded_string(value, maximum)
    if not result:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return result


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

