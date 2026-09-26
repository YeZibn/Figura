"""Shared request construction and response normalization helpers."""

from __future__ import annotations

import base64
import copy
import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..config import ProviderProfile
from ..errors import ProviderFailureCode, ProviderProtocolError
from ..models import (
    FinishReason,
    FunctionTool,
    ImageBlock,
    InstructionBlock,
    MessageRole,
    ProviderContinuation,
    ProviderId,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
    TextBlock,
)
from ..validation import (
    MAX_TOOL_CALLS_PER_RESPONSE,
    fail,
    validate_request,
    validate_tools_for_endpoint,
)


_MAX_RESPONSE_TEXT_CHARS = 1_048_576
_MAX_RESPONSE_ID_CHARS = 256
_MAX_USAGE_VALUE = 2_147_483_647
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def resolve_options(
    request: ProviderRequest, profile: ProviderProfile
) -> tuple[bool, str | None]:
    thinking_mode = (
        request.options.thinking_mode
        if request.options.thinking_mode is not None
        else profile.thinking_mode
    )
    reasoning_effort = (
        request.options.reasoning_effort
        if request.options.reasoning_effort is not None
        else profile.reasoning_effort
    )
    return thinking_mode, reasoning_effort


class ProviderPolicy:
    provider_id: ProviderId

    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    def validate_configuration(self) -> ProviderFailureCode | None:
        """Return a safe reason when provider options cannot be honored."""
        if self.profile.configuration_error is not None:
            return self.profile.configuration_error
        return None

    def build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        raise NotImplementedError

    def normalize(self, raw_response: Any, request: ProviderRequest) -> ProviderResponse:
        choices = value(raw_response, "choices", ()) or ()
        choice = next(
            (candidate for candidate in choices if value(candidate, "index", 0) == 0),
            None,
        )
        if choice is None:
            raise ProviderProtocolError()
        message = value(choice, "message")
        if message is None:
            raise ProviderProtocolError()
        content = value(message, "content") or ""
        reasoning = value(message, "reasoning_content") or ""
        if not isinstance(content, str) or not isinstance(reasoning, str):
            raise ProviderProtocolError()
        tool_calls = tuple(
            _normalized_tool_call(
                value(call, "id"),
                value(value(call, "function"), "name"),
                value(value(call, "function"), "arguments"),
            )
            for call in (value(message, "tool_calls", ()) or ())
        )
        if len(tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE:
            raise ProviderProtocolError()
        return _response(
            self.provider_id,
            request.model_id,
            content,
            tool_calls,
            _finish_reason(value(choice, "finish_reason")),
            _usage(value(raw_response, "usage")),
            _bounded_response_id(value(raw_response, "id")),
            reasoning,
        )

    def normalize_stream(
        self, events: Iterable[Any], request: ProviderRequest
    ) -> ProviderResponse:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_parts: dict[int, dict[str, str]] = {}
        finish_reason: FinishReason | None = None
        provider_response_id: str | None = None
        usage: ProviderUsage | None = None

        for event in events:
            event_id = value(event, "id")
            if provider_response_id is None and isinstance(event_id, str):
                provider_response_id = _bounded_response_id(event_id)
            event_usage = _usage(value(event, "usage"))
            if event_usage is not None:
                usage = event_usage
            choices = value(event, "choices", ()) or ()
            for choice in choices:
                if value(choice, "index", 0) != 0:
                    continue
                delta = value(choice, "delta")
                text = value(delta, "content")
                if isinstance(text, str):
                    content_parts.append(text)
                reasoning = value(delta, "reasoning_content")
                if isinstance(reasoning, str):
                    reasoning_parts.append(reasoning)
                for fallback_index, tool_delta in enumerate(value(delta, "tool_calls", ()) or ()):
                    index = value(tool_delta, "index")
                    if type(index) is not int or index < 0:
                        index = len(tool_parts) + fallback_index
                    if index >= MAX_TOOL_CALLS_PER_RESPONSE:
                        raise ProviderProtocolError()
                    entry = tool_parts.setdefault(index, {"call_id": "", "name": "", "arguments": ""})
                    if len(tool_parts) > MAX_TOOL_CALLS_PER_RESPONSE:
                        raise ProviderProtocolError()
                    call_id = value(tool_delta, "id")
                    if isinstance(call_id, str):
                        entry["call_id"] += call_id
                    function = value(tool_delta, "function")
                    name = value(function, "name")
                    arguments = value(function, "arguments")
                    if isinstance(name, str):
                        entry["name"] += name
                    if isinstance(arguments, str):
                        entry["arguments"] += arguments
                raw_finish = value(choice, "finish_reason")
                if raw_finish is not None:
                    finish_reason = _finish_reason(raw_finish)

        if finish_reason is None:
            raise ProviderProtocolError(
                ProviderFailureCode.INCOMPLETE_STREAM,
                outcome_known=False,
                transient=True,
            )
        if sum(map(len, content_parts)) > _MAX_RESPONSE_TEXT_CHARS:
            raise ProviderProtocolError()
        if sum(map(len, reasoning_parts)) > _MAX_RESPONSE_TEXT_CHARS:
            raise ProviderProtocolError()
        tool_calls: list[ProviderToolCall] = []
        for index in sorted(tool_parts):
            entry = tool_parts[index]
            tool_calls.append(_normalized_tool_call(entry["call_id"], entry["name"], entry["arguments"]))
        return _response(
            self.provider_id,
            request.model_id,
            "".join(content_parts),
            tuple(tool_calls),
            finish_reason,
            usage,
            provider_response_id,
            "".join(reasoning_parts),
        )

    def _base_payload(
        self,
        request: ProviderRequest,
        *,
        developer_role_supported: bool,
        provider_id: ProviderId,
    ) -> dict[str, Any]:
        validate_request(request, provider_id)
        validate_tools_for_endpoint(request.tools, provider_id, self.profile.base_url or "")
        self._validate_thinking_options(request)
        messages = [
            _instruction_message(item, developer_role_supported)
            for item in request.instructions
        ]
        messages.extend(_conversation_message(message) for message in request.messages)
        payload: dict[str, Any] = {
            "model": request.model_id,
            "messages": messages,
            "max_completion_tokens": request.options.max_completion_tokens,
            "stream": request.options.stream,
        }
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]
            payload["tool_choice"] = "auto"
        return payload

    def _validate_thinking_options(self, request: ProviderRequest) -> None:
        thinking_mode, reasoning_effort = resolve_options(request, self.profile)
        if reasoning_effort is None:
            return
        if not isinstance(reasoning_effort, str) or not reasoning_effort:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "reasoning_effort 不能为空。")
        if reasoning_effort == "none" and thinking_mode:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "reasoning_effort=none 与 thinking_mode=true 冲突。")
        if reasoning_effort != "none" and not thinking_mode:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "启用 reasoning_effort 时必须启用 thinking_mode。")


def _instruction_message(
    instruction: InstructionBlock, developer_role_supported: bool
) -> dict[str, Any]:
    role = instruction.role.value
    if role == "developer" and not developer_role_supported:
        role = "system"
    return {"role": role, "content": instruction.content}


def _conversation_message(message: ProviderMessage) -> dict[str, Any]:
    content = message.content
    if isinstance(content, str):
        wire_content: Any = content
    else:
        wire_content = []
        for block in content:
            if isinstance(block, TextBlock):
                wire_content.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageBlock):
                encoded = base64.b64encode(block.image_bytes).decode("ascii")
                wire_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{block.media_type};base64,{encoded}"},
                    }
                )

    result: dict[str, Any] = {"role": message.role.value, "content": wire_content}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        result["tool_call_id"] = message.tool_call_id
    if message.continuation is not None:
        result["reasoning_content"] = message.continuation.reasoning_content
    return result


def _tool_payload(tool: FunctionTool) -> dict[str, Any]:
    function: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "parameters": copy.deepcopy(dict(tool.parameters)),
    }
    if tool.strict is True:
        function["strict"] = True
    return {"type": "function", "function": function}


def _response(
    provider_id: ProviderId,
    model_id: str,
    assistant_content: str,
    tool_calls: tuple[ProviderToolCall, ...],
    finish_reason: FinishReason,
    usage: ProviderUsage | None,
    provider_response_id: str | None,
    reasoning_content: str,
) -> ProviderResponse:
    if not isinstance(assistant_content, str) or len(assistant_content) > _MAX_RESPONSE_TEXT_CHARS:
        raise ProviderProtocolError()
    if not isinstance(reasoning_content, str) or len(reasoning_content) > _MAX_RESPONSE_TEXT_CHARS:
        raise ProviderProtocolError()
    continuation = (
        ProviderContinuation(provider_id, 1, reasoning_content)
        if reasoning_content
        else None
    )
    return ProviderResponse(
        provider_id=provider_id,
        model_id=model_id,
        assistant_content=assistant_content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        provider_response_id=provider_response_id,
        continuation=continuation,
    )


def _normalized_tool_call(call_id: Any, name: Any, arguments: Any) -> ProviderToolCall:
    if (
        not isinstance(call_id, str)
        or not call_id
        or len(call_id) > _MAX_RESPONSE_ID_CHARS
        or not isinstance(name, str)
        or not _TOOL_NAME.fullmatch(name)
        or not isinstance(arguments, str)
        or len(arguments) > _MAX_RESPONSE_TEXT_CHARS
    ):
        raise ProviderProtocolError()
    return ProviderToolCall(call_id=call_id, name=name, arguments=arguments)


def _finish_reason(raw_reason: Any) -> FinishReason:
    if not isinstance(raw_reason, str):
        return FinishReason.OTHER
    if raw_reason in {"stop", "end_turn"}:
        return FinishReason.STOP
    if raw_reason in {"tool_calls", "function_call"}:
        return FinishReason.TOOL_CALLS
    if raw_reason in {"length", "max_tokens"}:
        return FinishReason.LENGTH
    if raw_reason in {"content_filter", "safety"}:
        return FinishReason.CONTENT_FILTER
    return FinishReason.OTHER


def _bounded_response_id(response_id: Any) -> str | None:
    if isinstance(response_id, str) and 0 < len(response_id) <= _MAX_RESPONSE_ID_CHARS:
        return response_id
    return None


def _usage(raw_usage: Any) -> ProviderUsage | None:
    if raw_usage is None:
        return None
    values: dict[str, int | None] = {}
    for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw_value = value(raw_usage, field_name)
        values[field_name] = (
            raw_value
            if type(raw_value) is int and 0 <= raw_value <= _MAX_USAGE_VALUE
            else None
        )
    if not any(item is not None for item in values.values()):
        return None
    return ProviderUsage(**values)
