"""Projection from durable Figura conversation facts to a bounded Provider request."""

from __future__ import annotations

from pathlib import Path

from figura.attachments import FiguraAttachmentService
from figura.memory import (
    AssistantMessage,
    MemoryMessage,
    ToolMessage,
    UserMessage,
    project_run_messages,
    project_session_history,
)
from figura.providers import (
    ImageBlock,
    InstructionBlock,
    InstructionRole,
    MessageRole,
    ProviderContinuation,
    ProviderId,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderToolCall,
    TextBlock,
)
from figura.providers.errors import ProviderCallError
from figura.providers.validation import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_COUNT,
    MAX_TOTAL_IMAGE_BYTES,
    validate_request,
)
from figura.runtime import RunError, RunErrorCode
from figura.runtime.domain.models import (
    ActionKind,
    ProviderContinuationFact,
    Run,
    RunState,
    RunStatus,
)
from figura.tools import ToolRegistry, project_provider_tools


_SYSTEM_INSTRUCTION = Path(__file__).with_name("assets").joinpath("system-v1.md").read_text(
    encoding="utf-8"
)
_MAX_COMPLETION_TOKENS = 4096


class AgentRequestBuilder:
    """Build one validated model request from Session history and the current Run."""

    __slots__ = ("_attachments",)

    def __init__(self, attachments: FiguraAttachmentService | None = None) -> None:
        if attachments is not None and not isinstance(attachments, FiguraAttachmentService):
            raise TypeError("attachments must be a FiguraAttachmentService")
        object.__setattr__(self, "_attachments", attachments)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AgentRequestBuilder is immutable")

    def build(
        self,
        state: RunState,
        registry: ToolRegistry,
        prior_run_states: tuple[RunState, ...] = (),
    ) -> ProviderRequest:
        if not isinstance(state, RunState) or not isinstance(registry, ToolRegistry):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if (
            state.run.status is not RunStatus.RUNNING
            or state.checkpoint.next_action is None
            or state.checkpoint.next_action.action_kind is not ActionKind.MODEL
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        try:
            provider_id = ProviderId(state.run.provider)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        history = project_session_history(state.run, prior_run_states)
        messages = self._provider_messages(
            (*history.messages, *project_run_messages(state)),
            session_id=state.run.session_id,
            current_run=state.run,
            continuations=_continuations_by_response(
                state.provider_continuations, state.run.run_id
            ),
            registry=registry,
        )
        try:
            tools = project_provider_tools(registry)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        request = ProviderRequest(
            provider_id=provider_id,
            model_id=state.run.model,
            instructions=(InstructionBlock(InstructionRole.SYSTEM, _SYSTEM_INSTRUCTION),),
            messages=messages,
            options=ProviderOptions(
                max_completion_tokens=_MAX_COMPLETION_TOKENS,
                stream=False,
            ),
            tools=tools,
        )
        try:
            validate_request(request, provider_id)
        except ProviderCallError:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        return request

    def _provider_messages(
        self,
        messages: tuple[MemoryMessage, ...],
        *,
        session_id: str,
        current_run: Run,
        continuations: dict[str, ProviderContinuationFact],
        registry: ToolRegistry,
    ) -> tuple[ProviderMessage, ...]:
        projected: list[ProviderMessage] = []
        for message in messages:
            if isinstance(message, UserMessage):
                projected.append(
                    ProviderMessage(
                        MessageRole.USER,
                        self._user_content(session_id, message.text, message.attachment_ids),
                    )
                )
            elif isinstance(message, AssistantMessage):
                if any(call.registry_version != registry.version for call in message.tool_calls):
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                continuation = None
                if message.run_id == current_run.run_id:
                    continuation_fact = continuations.get(message.source_record_id)
                    if continuation_fact is not None:
                        try:
                            continuation = ProviderContinuation(
                                provider_id=ProviderId(continuation_fact.provider_id),
                                format_version=continuation_fact.format_version,
                                reasoning_content=continuation_fact.reasoning_content,
                            )
                        except (TypeError, ValueError):
                            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
                projected.append(
                    ProviderMessage(
                        role=MessageRole.ASSISTANT,
                        content=message.content,
                        tool_calls=tuple(
                            ProviderToolCall(
                                call_id=call.call_id,
                                name=call.tool_name,
                                arguments=call.arguments_json,
                            )
                            for call in message.tool_calls
                        ),
                        continuation=continuation,
                    )
                )
            elif isinstance(message, ToolMessage):
                projected.append(
                    ProviderMessage(
                        role=MessageRole.TOOL,
                        content=message.content,
                        tool_call_id=message.tool_call_id,
                    )
                )
            else:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return tuple(projected)

    def _user_content(
        self,
        session_id: str,
        text: str,
        attachment_ids: tuple[str, ...],
    ) -> str | tuple[TextBlock | ImageBlock, ...]:
        if not attachment_ids:
            return text
        if len(attachment_ids) > MAX_IMAGE_COUNT or self._attachments is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

        images: list[ImageBlock] = []
        total_image_bytes = 0
        for attachment_id in attachment_ids:
            image = self._attachments.resolve(session_id, attachment_id)
            if (
                not isinstance(image, ImageBlock)
                or not isinstance(image.image_bytes, bytes)
                or not image.image_bytes
                or len(image.image_bytes) > MAX_IMAGE_BYTES
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            total_image_bytes += len(image.image_bytes)
            if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            images.append(image)
        return (TextBlock(text), *images)


def _continuations_by_response(
    facts: tuple[ProviderContinuationFact, ...],
    run_id: str,
) -> dict[str, ProviderContinuationFact]:
    result: dict[str, ProviderContinuationFact] = {}
    for fact in facts:
        if fact.run_id != run_id or fact.response_record_id in result:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        result[fact.response_record_id] = fact
    return result
