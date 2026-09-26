from __future__ import annotations

from typing import Any

import pytest

from figura.providers.models import ProviderToolCall
from figura.tools import (
    CancellationSignal,
    ReplayEffect,
    ToolContext,
    ToolDefinition,
    ToolDefinitionError,
    ToolExecutionError,
    ToolExecutionResult,
    ToolInvocation,
    ToolInvocationError,
    ToolOutcome,
    ToolRegistry,
    normalize_provider_tool_call,
    project_provider_tools,
)


def _handler(_context: ToolContext, arguments: Any) -> dict[str, Any]:
    return {"accepted": bool(arguments.get("value"))}


def _definition(
    name: str = "inspect_chart",
    *,
    handler: object = _handler,
    parameters_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
    replay_effect: ReplayEffect | str = ReplayEffect.REPLAY_SAFE,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Run {name}.",
        parameters_schema=parameters_schema or {
            "type": "object",
            "properties": {"value": {"type": "boolean"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        result_schema=result_schema or {
            "type": "object",
            "properties": {"accepted": {"type": "boolean"}},
            "required": ["accepted"],
            "additionalProperties": False,
        },
        replay_effect=replay_effect,
        handler=handler,  # type: ignore[arg-type]
    )


def test_contracts_are_typed_bounded_and_keep_handler_out_of_repr() -> None:
    handler = _handler
    definition = _definition(handler=handler)
    invocation = ToolInvocation("call-1", "inspect_chart", '{"value":true}')
    context = ToolContext("run-1", "session-1", "call-1", CancellationSignal(lambda: False))
    result = ToolExecutionResult(
        call_id="call-1",
        tool_name="inspect_chart",
        outcome=ToolOutcome.SUCCEEDED,
        result={"accepted": True},
    )

    assert definition.replay_effect is ReplayEffect.REPLAY_SAFE
    assert invocation.arguments_json == '{"value":true}'
    assert context.cancellation.is_cancelled() is False
    assert result.result == {"accepted": True}
    assert '"value":true' not in repr(invocation)
    assert "accepted" not in repr(result)
    assert handler.__name__ not in repr(definition)
    with pytest.raises(TypeError):
        result.result["accepted"] = False  # type: ignore[index]
    with pytest.raises(ValueError):
        ToolExecutionResult(
            "call-1", "inspect_chart", ToolOutcome.SUCCEEDED, {"accepted": True},
            ToolExecutionError("failed", "failure", False),
        )


@pytest.mark.parametrize(
    ("call_id", "name", "arguments"),
    [
        ("", "inspect_chart", "{}"),
        ("x" * 257, "inspect_chart", "{}"),
        ("call-1", "bad name", "{}"),
        ("call-1", "inspect_chart", None),
    ],
)
def test_malformed_invocation_identity_raises_bounded_error(
    call_id: str, name: str, arguments: object
) -> None:
    with pytest.raises(ToolInvocationError) as error:
        ToolInvocation(call_id, name, arguments)  # type: ignore[arg-type]

    assert len(error.value.message.encode("utf-8")) <= 512
    assert error.value.code


def test_registry_preserves_order_and_exposes_read_only_lookup() -> None:
    registry = ToolRegistry("toolset-v1", (_definition("first"), _definition("second")))

    assert registry.version == "toolset-v1"
    assert [item.name for item in registry] == ["first", "second"]
    assert registry.get("second") is registry["second"]
    with pytest.raises(TypeError):
        registry.by_name["third"] = _definition("third")  # type: ignore[index]
    with pytest.raises(AttributeError):
        registry.version = "toolset-v2"  # type: ignore[misc]


def test_registry_rejects_duplicate_names_unknown_effects_and_invalid_schemas() -> None:
    with pytest.raises(ToolDefinitionError):
        ToolRegistry("v1", (_definition(), _definition()))
    with pytest.raises(ToolDefinitionError):
        _definition(replay_effect="repeat_whenever")
    with pytest.raises(ToolDefinitionError):
        ToolRegistry(
            "v1",
            (_definition(parameters_schema={"type": "object", "$ref": "#/$defs/x"}),),
        )
    with pytest.raises(ToolDefinitionError):
        ToolRegistry("", ())


def test_definition_schema_copies_and_registry_projection_are_isolated() -> None:
    source_schema = {
        "type": "object",
        "properties": {"value": {"type": "boolean"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    definition = _definition("check", parameters_schema=source_schema)
    source_schema["properties"]["other"] = {"type": "string"}
    registry = ToolRegistry("v1", (definition,))

    projected = project_provider_tools(registry)
    assert projected[0].name == "check"
    assert projected[0].description == "Run check."
    assert projected[0].parameters == {
        "type": "object",
        "properties": {"value": {"type": "boolean"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    assert not hasattr(projected[0], "handler")
    projected[0].parameters["properties"]["local_only"] = {"type": "null"}
    assert "local_only" not in definition.parameters_schema["properties"]


def test_provider_call_adapter_preserves_call_id_name_and_raw_arguments() -> None:
    invocation = normalize_provider_tool_call(
        ProviderToolCall("call-provider-1", "inspect_chart", '{"value":true}')
    )

    assert invocation == ToolInvocation("call-provider-1", "inspect_chart", '{"value":true}')
