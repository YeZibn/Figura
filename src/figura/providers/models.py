"""Figura-owned, in-memory model-provider request and response contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


class ProviderId(str, Enum):
    QWEN = "qwen"
    DEEPSEEK = "deepseek"
    MIMO = "mimo"


MODEL_IDS: Mapping[ProviderId, str] = MappingProxyType({
    ProviderId.QWEN: "qwen3.8-flash",
    ProviderId.DEEPSEEK: "deepseek-flash",
    ProviderId.MIMO: "mimo-v2.6-flash",
})


class InstructionRole(str, Enum):
    SYSTEM = "system"
    DEVELOPER = "developer"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(str, Enum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


@dataclass(frozen=True)
class InstructionBlock:
    role: InstructionRole
    content: str


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ImageBlock:
    media_type: str
    image_bytes: bytes = field(repr=False)


ContentBlock: TypeAlias = TextBlock | ImageBlock
MessageContent: TypeAlias = str | tuple[ContentBlock, ...]


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ProviderContinuation:
    """Provider-private data needed to continue a later call.

    The payload is deliberately excluded from repr and public projections. It
    is transient in this change; durable ownership belongs to a later change.
    """

    provider_id: ProviderId
    format_version: int
    reasoning_content: str = field(repr=False)


@dataclass(frozen=True)
class ProviderMessage:
    role: MessageRole
    content: MessageContent = ""
    tool_calls: tuple[ProviderToolCall, ...] = ()
    tool_call_id: str | None = None
    continuation: ProviderContinuation | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.content, list):
            object.__setattr__(self, "content", tuple(self.content))
        if isinstance(self.tool_calls, list):
            object.__setattr__(self, "tool_calls", tuple(self.tool_calls))


@dataclass(frozen=True)
class FunctionTool:
    name: str
    parameters: Mapping[str, Any]
    description: str = ""
    strict: bool | None = None


@dataclass(frozen=True)
class ProviderOptions:
    max_completion_tokens: int
    stream: bool = False
    thinking_mode: bool | None = None
    reasoning_effort: str | None = None
    schema_version: int = 1


@dataclass(frozen=True)
class ProviderRequest:
    provider_id: ProviderId | str
    model_id: str
    instructions: tuple[InstructionBlock, ...]
    messages: tuple[ProviderMessage, ...]
    options: ProviderOptions
    tools: tuple[FunctionTool, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.instructions, list):
            object.__setattr__(self, "instructions", tuple(self.instructions))
        if isinstance(self.messages, list):
            object.__setattr__(self, "messages", tuple(self.messages))
        if isinstance(self.tools, list):
            object.__setattr__(self, "tools", tuple(self.tools))


@dataclass(frozen=True)
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResponse:
    provider_id: ProviderId
    model_id: str
    assistant_content: str
    tool_calls: tuple[ProviderToolCall, ...]
    finish_reason: FinishReason
    usage: ProviderUsage | None = None
    provider_response_id: str | None = None
    continuation: ProviderContinuation | None = field(default=None, repr=False)

    def to_public_dict(self) -> dict[str, Any]:
        """Return a bounded projection that omits provider-private continuation."""
        return {
            "provider_id": self.provider_id.value,
            "model_id": self.model_id,
            "assistant_content": self.assistant_content,
            "tool_calls": [
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in self.tool_calls
            ],
            "finish_reason": self.finish_reason.value,
            "usage": (
                {
                    "prompt_tokens": self.usage.prompt_tokens,
                    "completion_tokens": self.usage.completion_tokens,
                    "total_tokens": self.usage.total_tokens,
                }
                if self.usage is not None
                else None
            ),
            "provider_response_id": self.provider_response_id,
        }


@dataclass(frozen=True)
class ProviderAvailability:
    provider_id: ProviderId
    model_id: str
    available: bool
    reason_code: str | None = None
