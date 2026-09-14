"""Provider history message assembly helpers."""

from __future__ import annotations

from openai.types.chat import ChatCompletionMessageParam

from ..client.models import NormalizedResult, ToolCall


def assistant_entry(result: NormalizedResult) -> ChatCompletionMessageParam:
    entry: dict = {"role": "assistant", "content": result.content}
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
