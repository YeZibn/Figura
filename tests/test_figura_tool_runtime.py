from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pytest

from figura.tools import (
    CancellationSignal,
    ReplayEffect,
    ToolContext,
    ToolDefinition,
    ToolFailure,
    ToolInvocation,
    ToolInvocationError,
    ToolOutcome,
    ToolRegistry,
    ToolRuntime,
)
from figura.tools.limits import MAX_ARGUMENT_BYTES, MAX_RESULT_BYTES


def _definition(
    handler: object,
    *,
    replay_effect: ReplayEffect = ReplayEffect.RECONCILE_REQUIRED,
) -> ToolDefinition:
    return ToolDefinition(
        name="echo_value",
        description="Return the provided value.",
        parameters_schema={
            "type": "object",
            "properties": {"value": {"type": "integer", "minimum": 0}},
            "required": ["value"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        replay_effect=replay_effect,
        handler=handler,  # type: ignore[arg-type]
    )


def _runtime(
    handler: object,
    *,
    replay_effect: ReplayEffect = ReplayEffect.RECONCILE_REQUIRED,
) -> ToolRuntime:
    return ToolRuntime(ToolRegistry("test-v1", (_definition(handler, replay_effect=replay_effect),)))


def _context(call_id: str, *, cancelled: bool = False) -> ToolContext:
    return ToolContext("run-1", "session-1", call_id, CancellationSignal(lambda: cancelled))


def _echo_handler(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, Any]:
    assert context.run_id == "run-1"
    return {"value": arguments["value"]}


def test_valid_invocation_calls_handler_once_with_validated_arguments_and_context() -> None:
    calls: list[tuple[str, object]] = []

    def handler(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, Any]:
        calls.append((context.call_id, arguments))
        return {"value": arguments["value"]}

    invocation = ToolInvocation("call-17", "echo_value", '{"value":7}')
    result = _runtime(handler).invoke(invocation, _context("call-17"))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.call_id == "call-17"
    assert result.tool_name == "echo_value"
    assert result.result == {"value": 7}
    assert result.error is None
    assert len(calls) == 1
    assert calls[0][0] == "call-17"
    assert isinstance(calls[0][1], Mapping)
    with pytest.raises(TypeError):
        calls[0][1]["value"] = 8  # type: ignore[index]


def test_idempotent_local_write_requires_context_key_before_dispatch() -> None:
    calls: list[str | None] = []

    def handler(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, Any]:
        calls.append(context.idempotency_key)
        return {"value": arguments["value"]}

    runtime = _runtime(handler, replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE)
    invocation = ToolInvocation("call-idempotent", "echo_value", '{"value":7}')
    without_key = runtime.invoke(invocation, _context("call-idempotent"))

    assert without_key.outcome is ToolOutcome.FAILED
    assert without_key.error is not None
    assert without_key.error.code == "idempotency_key_required"
    assert calls == []

    key = "b" * 64
    with_key = runtime.invoke(
        invocation,
        ToolContext("run-1", "session-1", "call-idempotent", idempotency_key=key),
    )
    assert with_key.outcome is ToolOutcome.SUCCEEDED
    assert calls == [key]


@pytest.mark.parametrize(
    ("name", "arguments_json", "expected_code"),
    [
        ("echo_value", "{", "invalid_arguments"),
        ("echo_value", '{"value":1,"value":2}', "invalid_arguments"),
        ("echo_value", '{"value":NaN}', "invalid_arguments"),
        ("echo_value", '{"value":1e999}', "invalid_arguments"),
        ("echo_value", "[]", "invalid_arguments"),
        ("echo_value", '{"value":"7"}', "invalid_arguments"),
        ("missing_tool", '{"value":7}', "unknown_tool"),
    ],
)
def test_invalid_arguments_and_unknown_tools_never_invoke_handler(
    name: str, arguments_json: str, expected_code: str
) -> None:
    calls: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {"value": arguments["value"]}

    call_id = "call-invalid"
    result = _runtime(handler).invoke(
        ToolInvocation(call_id, name, arguments_json),
        _context(call_id),
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.call_id == call_id
    assert result.error is not None
    assert result.error.code == expected_code
    assert result.result is None
    assert calls == []


def test_argument_byte_limit_and_context_identity_are_checked_before_execution() -> None:
    calls: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {"value": arguments["value"]}

    runtime = _runtime(handler)
    too_large = '{"value":7}' + " " * MAX_ARGUMENT_BYTES
    oversized = runtime.invoke(ToolInvocation("call-large", "echo_value", too_large), _context("call-large"))
    assert oversized.error is not None
    assert oversized.error.code == "arguments_too_large"
    assert calls == []

    with pytest.raises(ToolInvocationError) as mismatch:
        runtime.invoke(ToolInvocation("call-a", "echo_value", '{"value":7}'), _context("call-b"))
    assert mismatch.value.code == "call_id_mismatch"
    assert calls == []


def test_cooperative_preinvoke_cancellation_returns_once_without_calling_handler() -> None:
    calls: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {"value": arguments["value"]}

    result = _runtime(handler).invoke(
        ToolInvocation("call-cancelled", "echo_value", '{"value":7}'),
        _context("call-cancelled", cancelled=True),
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.error is not None and result.error.code == "cancelled"
    assert result.error.retryable is False
    assert calls == []


def test_declared_failure_is_bounded_and_unexpected_exception_is_redacted_without_retry() -> None:
    declared_calls: list[int] = []

    def declared(_context: ToolContext, _arguments: Mapping[str, Any]) -> dict[str, Any]:
        declared_calls.append(1)
        raise ToolFailure("source_unavailable", "The source is unavailable.", retryable=True, field_path="/value")

    declared_result = _runtime(declared).invoke(
        ToolInvocation("call-declared", "echo_value", '{"value":7}'),
        _context("call-declared"),
    )
    assert declared_result.error is not None
    assert declared_result.error.code == "source_unavailable"
    assert declared_result.error.retryable is True
    assert declared_result.error.field_path == "/value"
    assert declared_result.call_id == "call-declared"
    assert declared_calls == [1]

    unexpected_calls: list[int] = []

    def unexpected(_context: ToolContext, _arguments: Mapping[str, Any]) -> dict[str, Any]:
        unexpected_calls.append(1)
        raise RuntimeError("secret path /Users/alice/private-token")

    unexpected_result = _runtime(unexpected).invoke(
        ToolInvocation("call-failed", "echo_value", '{"value":7}'),
        _context("call-failed"),
    )
    assert unexpected_result.error is not None
    assert unexpected_result.error.code == "handler_failed"
    assert unexpected_result.error.retryable is False
    assert "private-token" not in repr(unexpected_result)
    assert unexpected_result.call_id == "call-failed"
    assert unexpected_calls == [1]


@pytest.mark.parametrize(
    ("output", "expected_code"),
    [
        ({"value": "seven"}, "invalid_result"),
        ({"value": math.nan}, "invalid_result"),
        ({"value": "x" * MAX_RESULT_BYTES}, "result_too_large"),
        ("not an object", "invalid_result"),
    ],
)
def test_invalid_or_oversized_handler_outputs_become_bounded_failed_results(
    output: object, expected_code: str
) -> None:
    calls: list[int] = []

    def handler(_context: ToolContext, _arguments: Mapping[str, Any]) -> object:
        calls.append(1)
        return output

    result = _runtime(handler).invoke(
        ToolInvocation("call-output", "echo_value", '{"value":7}'),
        _context("call-output"),
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.call_id == "call-output"
    assert result.error is not None and result.error.code == expected_code
    assert result.result is None
    assert calls == [1]


def test_runtime_does_not_mutate_its_registry_reference() -> None:
    runtime = _runtime(_echo_handler)
    with pytest.raises(AttributeError):
        runtime._registry = ToolRegistry("empty-v1", ())  # type: ignore[misc]
