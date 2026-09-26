"""Provider-neutral contracts for defining and executing Figura tools."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeAlias

from ..json_schema import JsonValueError, canonical_json_dumps, normalize_json_value
from .limits import (
    MAX_CALL_ID_BYTES,
    MAX_ERROR_MESSAGE_BYTES,
    MAX_ERROR_POINTER_BYTES,
    MAX_RESULT_BYTES,
    MAX_TOOL_DESCRIPTION_BYTES,
)


_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
ToolHandler: TypeAlias = Callable[["ToolContext", Mapping[str, Any]], object]


class ReplayEffect(str, Enum):
    REPLAY_SAFE = "replay_safe"
    IDEMPOTENT_LOCAL_WRITE = "idempotent_local_write"
    RECONCILE_REQUIRED = "reconcile_required"


class ToolOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolDefinitionError(ValueError):
    """A tool definition or registry cannot satisfy the declared contract."""


class ToolInvocationError(ValueError):
    """A malformed invocation identity cannot safely receive a result envelope."""

    def __init__(self, code: str, message: str) -> None:
        if not _ERROR_CODE.fullmatch(code) or _utf8_size(message) > MAX_ERROR_MESSAGE_BYTES:
            raise ValueError("ToolInvocationError fields must be bounded")
        self.code = code
        self.message = message
        super().__init__(message)


class CancellationSignal:
    """Read-only cooperative cancellation check supplied to a handler."""

    __slots__ = ("_check",)

    def __init__(self, check: Callable[[], bool] | None = None) -> None:
        if check is not None and not callable(check):
            raise TypeError("cancellation check must be callable")
        object.__setattr__(self, "_check", check or (lambda: False))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("CancellationSignal is immutable")

    def is_cancelled(self) -> bool:
        return bool(self._check())


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    session_id: str
    call_id: str
    cancellation: CancellationSignal = field(default_factory=CancellationSignal, repr=False, compare=False)
    idempotency_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        _validate_call_id(self.call_id)
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str)
            or len(self.idempotency_key) != 64
            or any(character not in "0123456789abcdef" for character in self.idempotency_key)
        ):
            raise ValueError("idempotency_key must be a lowercase SHA-256 hex digest")
        if not isinstance(self.cancellation, CancellationSignal):
            raise TypeError("cancellation must be a CancellationSignal")


@dataclass(frozen=True)
class ToolInvocation:
    call_id: str
    name: str
    arguments_json: str = field(repr=False)

    def __post_init__(self) -> None:
        try:
            _validate_call_id(self.call_id)
        except ToolInvocationError:
            raise
        if not isinstance(self.name, str) or not _TOOL_NAME.fullmatch(self.name):
            raise ToolInvocationError("invalid_tool_name", "工具调用名称无效。")
        if not isinstance(self.arguments_json, str):
            raise ToolInvocationError("invalid_arguments", "工具调用参数必须是 JSON 字符串。")


@dataclass(frozen=True)
class ToolExecutionError:
    code: str
    message: str
    retryable: bool
    field_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _ERROR_CODE.fullmatch(self.code):
            raise ValueError("tool error code is invalid")
        if not isinstance(self.message, str) or _utf8_size(self.message) > MAX_ERROR_MESSAGE_BYTES:
            raise ValueError("tool error message exceeds its byte limit")
        if type(self.retryable) is not bool:
            raise ValueError("tool error retryable must be a boolean")
        if self.field_path is not None:
            if (
                not isinstance(self.field_path, str)
                or _utf8_size(self.field_path) > MAX_ERROR_POINTER_BYTES
                or not _is_json_pointer(self.field_path)
            ):
                raise ValueError("tool error field_path must be a bounded JSON Pointer")


class ToolFailure(Exception):
    """Handler-declared safe failure with a bounded public error contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        field_path: str | None = None,
    ) -> None:
        self.error = ToolExecutionError(code, message, retryable, field_path)
        super().__init__(self.error.message)


@dataclass(frozen=True)
class ToolExecutionResult:
    call_id: str
    tool_name: str
    outcome: ToolOutcome
    result: Mapping[str, Any] | None = field(default=None, repr=False)
    error: ToolExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_call_id(self.call_id)
        if not isinstance(self.tool_name, str) or not _TOOL_NAME.fullmatch(self.tool_name):
            raise ValueError("tool execution result name is invalid")
        if not isinstance(self.outcome, ToolOutcome):
            raise ValueError("tool execution result outcome is invalid")
        if self.outcome is ToolOutcome.SUCCEEDED:
            if self.error is not None or not isinstance(self.result, Mapping):
                raise ValueError("successful result must contain only an object result")
            try:
                normalized = normalize_json_value(self.result)
            except JsonValueError:
                raise ValueError("successful result must contain bounded JSON data") from None
            if not isinstance(normalized, dict):
                raise ValueError("successful result must contain a JSON object")
            try:
                result_size = len(canonical_json_dumps(normalized).encode("utf-8"))
            except (JsonValueError, UnicodeEncodeError):
                raise ValueError("successful result must contain bounded JSON data") from None
            if result_size > MAX_RESULT_BYTES:
                raise ValueError("successful result exceeds its byte limit")
            object.__setattr__(self, "result", freeze_json_value(normalized))
        elif self.result is not None or not isinstance(self.error, ToolExecutionError):
            raise ValueError("failed result must contain only an error")


@dataclass(frozen=True)
class ToolDefinition:
    """One validated handler contract.

    Handlers using ``idempotent_local_write`` must deduplicate the local effect
    by ``ToolContext.idempotency_key`` and return the original result when that
    key has already been applied.
    """

    name: str
    description: str
    parameters_schema: Mapping[str, Any]
    result_schema: Mapping[str, Any]
    replay_effect: ReplayEffect | str
    handler: ToolHandler = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _TOOL_NAME.fullmatch(self.name):
            raise ToolDefinitionError("tool name must contain 1 to 64 ASCII letters, digits, '_' or '-'")
        if not isinstance(self.description, str):
            raise ToolDefinitionError("tool description must be a string")
        try:
            description_size = _utf8_size(self.description)
        except UnicodeEncodeError:
            raise ToolDefinitionError("tool description must be valid UTF-8") from None
        if description_size > MAX_TOOL_DESCRIPTION_BYTES:
            raise ToolDefinitionError("tool description exceeds its byte limit")
        try:
            replay_effect = ReplayEffect(self.replay_effect)
        except (TypeError, ValueError):
            raise ToolDefinitionError("tool replay_effect is unsupported") from None
        object.__setattr__(self, "replay_effect", replay_effect)
        if not _is_sync_handler(self.handler):
            raise ToolDefinitionError("tool handler must be a synchronous callable accepting context and arguments")
        object.__setattr__(self, "parameters_schema", _freeze_schema(self.parameters_schema))
        object.__setattr__(self, "result_schema", _freeze_schema(self.result_schema))


def _validate_call_id(value: object) -> None:
    if not isinstance(value, str):
        raise ToolInvocationError("invalid_call_id", "工具调用 ID 无效。")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise ToolInvocationError("invalid_call_id", "工具调用 ID 无效。") from None
    if not value or size > MAX_CALL_ID_BYTES:
        raise ToolInvocationError("invalid_call_id", "工具调用 ID 无效。")


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _is_json_pointer(value: str) -> bool:
    if value == "":
        return True
    if not value.startswith("/"):
        return False
    for segment in value.split("/")[1:]:
        index = 0
        while index < len(segment):
            if segment[index] == "~":
                if index + 1 >= len(segment) or segment[index + 1] not in "01":
                    return False
                index += 2
            else:
                index += 1
    return True


def _is_sync_handler(handler: object) -> bool:
    if not callable(handler):
        return False
    target = handler if not hasattr(handler, "__call__") or inspect.isfunction(handler) else handler.__call__
    if inspect.iscoroutinefunction(target) or inspect.isasyncgenfunction(target):
        return False
    try:
        inspect.signature(handler).bind(None, {})
    except (TypeError, ValueError):
        return False
    return True


def _freeze_schema(schema: object) -> Mapping[str, Any]:
    if not isinstance(schema, Mapping):
        raise ToolDefinitionError("tool schemas must be JSON objects")
    try:
        normalized = normalize_json_value(schema)
    except JsonValueError:
        raise ToolDefinitionError("tool schemas must contain bounded JSON values") from None
    if not isinstance(normalized, dict):
        raise ToolDefinitionError("tool schemas must be JSON objects")
    return freeze_json_value(normalized)


def freeze_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json_value(item) for item in value)
    return value
