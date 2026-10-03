"""Single-call synchronous dispatch for provider-neutral Figura tools."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from figura.shared.json_schema import JsonValueError, canonical_json_dumps, normalize_json_value, validate_instance
from figura.shared.payloads import PayloadError, PayloadTooLarge, decode_json, encode_json, payload_scope
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
    ToolOutcomeUnknown,
    freeze_json_value,
)
from .limits import MAX_ERROR_POINTER_BYTES
from .registry import ToolRegistry


_ARGUMENT_MESSAGES = {
    "invalid_json": "工具参数不是有效 JSON。",
    "duplicate_key": "工具参数包含重复字段。",
    "non_finite_number": "工具参数包含无效数值。",
    "not_object": "工具参数必须是 JSON 对象。",
    "schema": "工具参数未通过定义校验。",
}


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

    @property
    def payload_limits(self):
        return self.registry.payload_limits

    @payload_scope
    def invoke(self, invocation: ToolInvocation, context: ToolContext, *, durable: bool = False) -> ToolExecutionResult:
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
            if durable:
                raise
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
                if durable and definition.replay_effect is not ReplayEffect.REPLAY_SAFE:
                    raise ToolOutcomeUnknown()
                return _handler_failed(invocation)
        except ToolFailure as error:
            return ToolExecutionResult(
                call_id=invocation.call_id,
                tool_name=invocation.name,
                outcome=ToolOutcome.FAILED,
                error=error.error,
            )
        except ToolOutcomeUnknown:
            raise
        except Exception:
            if durable and definition.replay_effect is not ReplayEffect.REPLAY_SAFE:
                raise ToolOutcomeUnknown() from None
            return _handler_failed(invocation)

        result = _success_or_failure(invocation, definition, output)
        if durable and result.outcome is ToolOutcome.FAILED and definition.replay_effect is not ReplayEffect.REPLAY_SAFE:
            raise ToolOutcomeUnknown()
        return result


def _parse_arguments(raw: str) -> tuple[Any, tuple[str, str] | None]:
    try:
        return decode_json(raw), None
    except PayloadTooLarge:
        return None, ("arguments_too_large", "工具参数超出允许大小。")
    except PayloadError:
        return None, ("invalid_arguments", _ARGUMENT_MESSAGES["invalid_json"])


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
        encode_json({"call_id": invocation.call_id, "tool_name": invocation.name,
            "outcome": "succeeded", "result": output, "error": None})
        normalized = normalize_json_value(output)
        if not isinstance(normalized, dict):
            raise JsonValueError("result is not an object")
        encode_json(normalized)
    except PayloadTooLarge:
        return _failed(invocation.call_id, invocation.name, "result_too_large", "工具返回结果超出允许大小。", retryable=False)
    except Exception:
        return _failed(
            invocation.call_id,
            invocation.name,
            "invalid_result",
            "工具返回结果不符合定义。",
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
