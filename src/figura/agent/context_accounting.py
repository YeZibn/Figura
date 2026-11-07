"""Call-time context accounting for prepared Figura requests.

Counts in this module are local estimates for explaining pressure and selecting
soft compaction targets. They are deliberately not persisted or exposed through
the Gateway protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping

from figura.providers.models import ImageBlock, ProviderRequest
from figura.providers.token_estimation import (
    ContextEstimate,
    IMAGE_TOKENS,
    cached_encoding,
    estimate_text_tokens,
)
from figura.providers.validation import request_projection


@dataclass(frozen=True, repr=False)
class RequestContextProjection:
    """Private call-time ownership indexes and selected resource entries."""

    history_message_indices: tuple[int, ...]
    current_input_message_index: int
    summary_instruction_index: int | None
    execution_instruction_index: int
    resource_entries: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class RequestContextAccounting:
    """Ephemeral component estimates; independently encoded values may overlap."""

    full_input_tokens: int | None
    history_input_tokens: int | None
    current_input_tokens: int | None
    summary_tokens: int | None
    raw_history_tokens: int | None
    resource_directory_tokens: int | None
    policy_tools_state_tokens: int | None
    selected_image_count: int
    image_tokens: int
    context_capacity_tokens: int | None
    estimator_version: str | None
    pressure_reason: str

    def safe_diagnostic(self) -> dict[str, int | str | None]:
        """Return only counts and a safe reason code; never include request text."""
        return {
            "full_input_tokens": self.full_input_tokens,
            "history_input_tokens": self.history_input_tokens,
            "current_input_tokens": self.current_input_tokens,
            "summary_tokens": self.summary_tokens,
            "raw_history_tokens": self.raw_history_tokens,
            "resource_directory_tokens": self.resource_directory_tokens,
            "policy_tools_state_tokens": self.policy_tools_state_tokens,
            "selected_image_count": self.selected_image_count,
            "image_tokens": self.image_tokens,
            "context_capacity_tokens": self.context_capacity_tokens,
            "estimator_version": self.estimator_version,
            "pressure_reason": self.pressure_reason,
        }


def account_request_context(
    request: ProviderRequest,
    projection: RequestContextProjection,
    estimate: ContextEstimate | None,
) -> RequestContextAccounting:
    if not isinstance(request, ProviderRequest) or not isinstance(
        projection, RequestContextProjection
    ):
        raise TypeError("request context projection is invalid")

    image_count = sum(
        1
        for message in request.messages
        if not isinstance(message.content, str)
        for block in message.content
        if isinstance(block, ImageBlock)
    )
    encoding = cached_encoding()
    if encoding is None:
        return RequestContextAccounting(
            estimate.input_tokens if isinstance(estimate, ContextEstimate) else None,
            None,
            None,
            None,
            None,
            None,
            None,
            image_count,
            image_count * IMAGE_TOKENS,
            estimate.context_window_tokens if isinstance(estimate, ContextEstimate) else None,
            estimate.estimator_version if isinstance(estimate, ContextEstimate) else None,
            "estimate_unavailable",
        )

    wire = request_projection(request)
    messages = wire["messages"]
    if any(index < 0 or index >= len(messages) for index in projection.history_message_indices):
        raise ValueError("history ownership index is outside the request")
    if not 0 <= projection.current_input_message_index < len(messages):
        raise ValueError("current input ownership index is outside the request")
    if not 0 <= projection.execution_instruction_index < len(wire["instructions"]):
        raise ValueError("execution instruction index is outside the request")

    raw_history_messages = [messages[index] for index in projection.history_message_indices]
    raw_history_images = sum(
        _projected_image_count(request.messages[index])
        for index in projection.history_message_indices
    )
    raw_history_tokens = (
        0 if not raw_history_messages else _estimate_json(
            {"messages": raw_history_messages}, encoding
        )
    )
    if raw_history_tokens is not None:
        raw_history_tokens += raw_history_images * IMAGE_TOKENS

    current_message = messages[projection.current_input_message_index]
    current_image_count = _projected_image_count(
        request.messages[projection.current_input_message_index]
    )
    current_input_tokens = _estimate_json({"messages": [current_message]}, encoding)
    if current_input_tokens is not None:
        current_input_tokens += current_image_count * IMAGE_TOKENS

    instructions = wire["instructions"]
    summary_tokens = None
    if projection.summary_instruction_index is not None:
        index = projection.summary_instruction_index
        if not 0 <= index < len(instructions):
            raise ValueError("summary instruction ownership index is outside the request")
        summary_tokens = _estimate_json({"instructions": [instructions[index]]}, encoding)

    resource_directory_tokens = (
        0 if not projection.resource_entries else _estimate_json(
            {"resources": list(projection.resource_entries)}, encoding
        )
    )

    # Count the remaining request-owned policy/state/schema components as one
    # separate diagnostic slice. Emptying only the resource array avoids
    # attributing that array twice while retaining the exact instruction shell.
    non_history_messages = [
        message for index, message in enumerate(messages)
        if index not in set(projection.history_message_indices)
        and index != projection.current_input_message_index
    ]
    non_summary_instructions = []
    for index, instruction in enumerate(instructions):
        if index == projection.summary_instruction_index:
            continue
        if index == projection.execution_instruction_index:
            instruction = _execution_instruction_without_resources(instruction)
        non_summary_instructions.append(instruction)
    policy_tools_state_tokens = _estimate_json(
        {
            "instructions": non_summary_instructions,
            "messages": non_history_messages,
            "tools": wire["tools"],
            "options": wire["options"],
        },
        encoding,
    )

    history_input_tokens = None
    if raw_history_tokens is not None and summary_tokens is not None:
        history_input_tokens = _estimate_json(
            {
                "messages": raw_history_messages,
                "summary_instruction": (
                    None if projection.summary_instruction_index is None
                    else instructions[projection.summary_instruction_index]
                ),
            },
            encoding,
        )
        if history_input_tokens is not None:
            history_input_tokens += raw_history_images * IMAGE_TOKENS
    elif projection.summary_instruction_index is None and raw_history_tokens is not None:
        history_input_tokens = raw_history_tokens

    capacity = (
        estimate.context_window_tokens
        if isinstance(estimate, ContextEstimate)
        else None
    )
    full_tokens = estimate.input_tokens if isinstance(estimate, ContextEstimate) else None
    reason = _pressure_reason(full_tokens, capacity, history_input_tokens, resource_directory_tokens)
    return RequestContextAccounting(
        full_tokens,
        history_input_tokens,
        current_input_tokens,
        summary_tokens,
        raw_history_tokens,
        resource_directory_tokens,
        policy_tools_state_tokens,
        image_count,
        image_count * IMAGE_TOKENS,
        capacity,
        estimate.estimator_version if isinstance(estimate, ContextEstimate) else None,
        reason,
    )


def estimate_json_tokens(value: object) -> int | None:
    """Estimate a content-free projection with the shared local encoding."""
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    return estimate_text_tokens(encoded)


def _estimate_json(value: object, encoding) -> int | None:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        return len(encoding.encode_ordinary(encoded))
    except Exception:
        return None


def _execution_instruction_without_resources(instruction: Mapping[str, object]) -> dict[str, object]:
    content = instruction.get("content")
    if not isinstance(content, str) or "\n" not in content:
        return dict(instruction)
    prefix, serialized = content.split("\n", 1)
    try:
        payload = json.loads(serialized)
    except (TypeError, ValueError):
        return dict(instruction)
    if not isinstance(payload, dict) or not isinstance(payload.get("resources"), list):
        return dict(instruction)
    payload["resources"] = []
    return {**instruction, "content": prefix + "\n" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )}


def _projected_image_count(message) -> int:
    if isinstance(message.content, str):
        return 0
    return sum(1 for block in message.content if isinstance(block, ImageBlock))


def _pressure_reason(
    full_tokens: int | None,
    capacity: int | None,
    history_tokens: int | None,
    directory_tokens: int | None,
) -> str:
    if type(full_tokens) is not int or type(capacity) is not int or capacity <= 0:
        return "estimate_unavailable"
    if full_tokens / capacity < 0.8:
        return "below_trigger"
    if directory_tokens is not None and directory_tokens > 0:
        return "directory_reducible"
    if history_tokens is not None and history_tokens > 0:
        return "history_reducible"
    return "protected_content"
