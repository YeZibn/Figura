"""Shared bounded JSON primitives used by persisted Runtime codecs."""

from __future__ import annotations

from figura.shared.payloads import PayloadError, encode_json, decode_json, utf8_size

from ..errors import RunError, RunErrorCode


def _nonempty_string(value: object, maximum: int | None) -> str:
    result = _bounded_string(value, maximum)
    if not result:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return result


def _dump_bounded(value: object, maximum: int | None) -> str:
    try:
        return encode_json(value, maximum=maximum)
    except PayloadError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None


def _load_bounded(raw: str, maximum: int | None) -> object:
    if not isinstance(raw, str):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    try:
        return decode_json(raw, maximum=maximum)
    except PayloadError:
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _require_keys(value: dict[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _bounded_string(value: object, maximum_bytes: int | None) -> str:
    if not isinstance(value, str):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    try:
        utf8_size(value, maximum_bytes)
    except PayloadError:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
    return value


def _bounded_count(value: object) -> int | None:
    if value is not None and (type(value) is not int or value < 0 or value > 2**31 - 1):
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return value
