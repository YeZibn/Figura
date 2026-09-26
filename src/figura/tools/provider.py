"""Narrow adapters between tool contracts and Provider-owned values."""

from __future__ import annotations

from figura.json_schema import JsonValueError, normalize_json_value
from figura.providers.models import FunctionTool, ProviderToolCall

from .contracts import ToolInvocation, ToolInvocationError
from .registry import ToolRegistry


def project_provider_tools(registry: ToolRegistry) -> tuple[FunctionTool, ...]:
    """Project ordered public metadata without exposing handlers or context."""

    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    projected: list[FunctionTool] = []
    for definition in registry:
        try:
            parameters = normalize_json_value(definition.parameters_schema)
        except JsonValueError:
            raise ToolInvocationError("invalid_tool_definition", "工具定义无效。") from None
        projected.append(
            FunctionTool(
                name=definition.name,
                description=definition.description,
                parameters=parameters,
            )
        )
    return tuple(projected)


def normalize_provider_tool_call(call: ProviderToolCall) -> ToolInvocation:
    """Convert a normalized Provider call into the provider-neutral envelope."""

    if not isinstance(call, ProviderToolCall):
        raise ToolInvocationError("invalid_invocation", "工具调用结构无效。")
    return ToolInvocation(call_id=call.call_id, name=call.name, arguments_json=call.arguments)
