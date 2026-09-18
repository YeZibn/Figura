"""Provider history message assembly helpers."""

from __future__ import annotations

from openai.types.chat import ChatCompletionMessageParam

from ..client.models import NormalizedResult, ToolCall


def assistant_entry(
    result: NormalizedResult,
    *,
    include_reasoning: bool = False,
) -> ChatCompletionMessageParam:
    entry: dict = {"role": "assistant", "content": result.content}
    if include_reasoning and result.reasoning:
        # DeepSeek thinking + tools requires this exact provider-private field
        # on the assistant message that precedes a tool result. Callers must
        # keep the default false for ordinary records and user-facing output.
        entry["reasoning_content"] = result.reasoning
    if result.tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in result.tool_calls
        ]
    return entry  # type: ignore[return-value]


def tool_entry(call: ToolCall, observation: str) -> ChatCompletionMessageParam:
    return {"role": "tool", "tool_call_id": call.id, "content": observation}  # type: ignore[return-value]


__all__ = ["assistant_entry", "tool_entry"]
