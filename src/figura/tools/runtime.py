"""Single-call synchronous dispatch for provider-neutral Figura tools."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from typing import Any

from ..json_schema import JsonValueError, canonical_json_dumps, normalize_json_value, validate_instance
from .contracts import (
    ReplayEffect,
    ToolContext,
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionResult,
    ToolFailure,
    ToolInvocation,
    ToolInvocationError,
    ToolOutcome,
    freeze_json_value,
)
from .limits import MAX_ARGUMENT_BYTES, MAX_ERROR_POINTER_BYTES, MAX_RESULT_BYTES
from .registry import ToolRegistry


_ARGUMENT_MESSAGES = {
    "invalid_json": "工具参数不是有效 JSON。",
    "duplicate_key": "工具参数包含重复字段。",
    "non_finite_number": "工具参数包含无效数值。",
    "not_object": "工具参数必须是 JSON 对象。",
    "schema": "工具参数未通过定义校验。",
}


class _DuplicateObjectKey(ValueError):
    pass


class _NonFiniteConstant(ValueError):
    pass


class ToolRuntime:
    """Validate and invoke exactly one registered handler per call."""

    __slots__ = ("_registry",)

    def __init__(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        object.__setattr__(self, "_registry", registry)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ToolRuntime is immutable")

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def invoke(self, invocation: ToolInvocation, context: ToolContext) -> ToolExecutionResult:
        if not isinstance(invocation, ToolInvocation):
            raise ToolInvocationError("invalid_invocation", "工具调用结构无效。")
        if not isinstance(context, ToolContext):
            raise ToolInvocationError("invalid_context", "工具调用上下文无效。")
        # Re-check the envelope so even a forcibly mutated frozen dataclass cannot
        # create an uncorrelated result.
        ToolInvocation(invocation.call_id, invocation.name, invocation.arguments_json)
        if context.call_id != invocation.call_id:
            raise ToolInvocationError("call_id_mismatch", "工具调用上下文不匹配。")

        definition = self._registry.get(invocation.name)
        if definition is None:
            return _failed(
                invocation.call_id,
                invocation.name,
                "unknown_tool",
                "请求的工具未注册。",
                retryable=False,
            )
        if (
            definition.replay_effect is ReplayEffect.IDEMPOTENT_LOCAL_WRITE
            and context.idempotency_key is None
        ):
            return _failed(
                invocation.call_id,
                invocation.name,
                "idempotency_key_required",
                "该工具需要幂等执行键。",
                retryable=False,
            )

        parsed, parse_error = _parse_arguments(invocation.arguments_json)
        if parse_error is not None:
            code, message = parse_error
            return _failed(invocation.call_id, invocation.name, code, message, retryable=False)
        if not isinstance(parsed, dict):
            return _failed(
                invocation.call_id,
                invocation.name,
                "invalid_arguments",
                _ARGUMENT_MESSAGES["not_object"],
                retryable=False,
            )

        issue = validate_instance(parsed, definition.parameters_schema)
        if issue is not None:
            return _failed(
                invocation.call_id,
                invocation.name,
                "invalid_arguments",
                _ARGUMENT_MESSAGES["schema"],
                retryable=True,
                field_path=issue.pointer or None,
            )
        validated_arguments = freeze_json_value(parsed)

        try:
            cancelled = context.cancellation.is_cancelled()
        except Exception:
            cancelled = True
        if cancelled:
            return _failed(
                invocation.call_id,
                invocation.name,
                "cancelled",
                "工具调用已取消。",
                retryable=False,
            )

        try:
            output = definition.handler(context, validated_arguments)
            if inspect.isawaitable(output):
                close = getattr(output, "close", None)
                if callable(close):
                    close()
                return _handler_failed(invocation)
        except ToolFailure as error:
            return ToolExecutionResult(
                call_id=invocation.call_id,
                tool_name=invocation.name,
                outcome=ToolOutcome.FAILED,
                error=error.error,
            )
        except Exception:
            return _handler_failed(invocation)

        return _success_or_failure(invocation, definition, output)


def _parse_arguments(raw: str) -> tuple[Any, tuple[str, str] | None]:
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError:
        return None, ("invalid_arguments", _ARGUMENT_MESSAGES["invalid_json"])
    if size > MAX_ARGUMENT_BYTES:
        return None, ("arguments_too_large", "工具参数超出允许大小。")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateObjectKey
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise _NonFiniteConstant

    try:
        value = json.loads(raw, object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    except _DuplicateObjectKey:
        return None, ("invalid_arguments", _ARGUMENT_MESSAGES["duplicate_key"])
    except _NonFiniteConstant:
        return None, ("invalid_arguments", _ARGUMENT_MESSAGES["non_finite_number"])
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError, OverflowError):
        return None, ("invalid_arguments", _ARGUMENT_MESSAGES["invalid_json"])

    try:
        value = normalize_json_value(value)
    except JsonValueError as error:
        message = (
            _ARGUMENT_MESSAGES["non_finite_number"]
            if str(error) == "JSON numbers must be finite"
            else _ARGUMENT_MESSAGES["invalid_json"]
        )
        return None, ("invalid_arguments", message)
    return value, None


def _success_or_failure(
    invocation: ToolInvocation,
    definition: ToolDefinition,
    output: object,
) -> ToolExecutionResult:
    if not isinstance(output, Mapping):
        return _failed(
            invocation.call_id,
            invocation.name,
            "invalid_result",
            "工具返回结果不符合定义。",
            retryable=False,
        )
    try:
        normalized = normalize_json_value(output)
        if not isinstance(normalized, dict):
            raise JsonValueError("result is not an object")
        serialized = canonical_json_dumps(normalized)
        output_size = len(serialized.encode("utf-8"))
    except Exception:
        return _failed(
            invocation.call_id,
            invocation.name,
            "invalid_result",
            "工具返回结果不符合定义。",
            retryable=False,
        )
    if output_size > MAX_RESULT_BYTES:
        return _failed(
            invocation.call_id,
            invocation.name,
            "result_too_large",
            "工具返回结果超出允许大小。",
            retryable=False,
        )
    issue = validate_instance(normalized, definition.result_schema)
    if issue is not None:
        return _failed(
            invocation.call_id,
            invocation.name,
            "invalid_result",
            "工具返回结果不符合定义。",
            retryable=False,
            field_path=issue.pointer or None,
        )
    return ToolExecutionResult(
        call_id=invocation.call_id,
        tool_name=invocation.name,
        outcome=ToolOutcome.SUCCEEDED,
        result=normalized,
    )


def _failed(
    call_id: str,
    tool_name: str,
    code: str,
    message: str,
    *,
    retryable: bool,
    field_path: str | None = None,
) -> ToolExecutionResult:
    if field_path is not None:
        try:
            if len(field_path.encode("utf-8")) > MAX_ERROR_POINTER_BYTES:
                field_path = None
        except UnicodeEncodeError:
            field_path = None
    return ToolExecutionResult(
        call_id=call_id,
        tool_name=tool_name,
        outcome=ToolOutcome.FAILED,
        error=ToolExecutionError(code, message, retryable, field_path),
    )


def _handler_failed(invocation: ToolInvocation) -> ToolExecutionResult:
    # Deliberately omit exception text from the result and diagnostics.
    return _failed(
        invocation.call_id,
        invocation.name,
        "handler_failed",
        "工具执行失败。",
        retryable=False,
    )
