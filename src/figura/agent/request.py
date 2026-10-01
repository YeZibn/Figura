"""Projection from durable Figura conversation facts to a bounded Provider request."""

from __future__ import annotations

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.prompting.execution import build_execution_instruction
from figura.agent.prompting.loader import build_static_instruction
from figura.agent.prompting.observations import build_observation_messages
from figura.agent.prompting.tools import build_tool_instruction
from figura.memory import (
    AssistantMessage,
    MemoryMessage,
    ToolMessage,
    UserMessage,
    project_run_messages,
    project_session_history,
)
from figura.providers import (
    MessageRole,
    ProviderContinuation,
    ProviderId,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderToolCall,
)
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ActionKind, RunStatus
from figura.runtime.records import RunState
from figura.tools import ToolRegistry, project_provider_tools


_MAX_COMPLETION_TOKENS = 4096


class AgentRequestBuilder:
    """Build one validated model request from Session history and the current Run."""

    __slots__ = ("_execution_state", "_execution_images")

    def __init__(
        self,
        execution_state: RunExecutionStateService,
        execution_images: RunExecutionImageReader,
    ) -> None:
        if not isinstance(execution_state, RunExecutionStateService):
            raise TypeError("execution_state must be a RunExecutionStateService")
        if not isinstance(execution_images, RunExecutionImageReader):
            raise TypeError("execution_images must be a RunExecutionImageReader")
        object.__setattr__(self, "_execution_state", execution_state)
        object.__setattr__(self, "_execution_images", execution_images)

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
        execution_state = self._execution_state.build(state, prior_run_states)
        messages = self._provider_messages(
            (*history.messages, *project_run_messages(state)),
            selected_provider=provider_id,
            continuations=_continuations_by_response((*prior_run_states, state)),
            registry=registry,
        )
        messages = (
            *messages,
            *build_observation_messages(state, execution_state, self._execution_images),
        )
        try:
            tools = project_provider_tools(registry)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        request = ProviderRequest(
            provider_id=provider_id,
            model_id=state.run.model,
            instructions=(
                build_static_instruction(),
                build_tool_instruction(registry),
                build_execution_instruction(execution_state),
            ),
            messages=messages,
            options=ProviderOptions(
                max_completion_tokens=_MAX_COMPLETION_TOKENS,
                stream=False,
            ),
            tools=tools,
        )
        return request

    def _provider_messages(
        self,
        messages: tuple[MemoryMessage, ...],
        *,
        selected_provider: ProviderId,
        continuations: dict[tuple[str, str], ProviderContinuation],
        registry: ToolRegistry,
    ) -> tuple[ProviderMessage, ...]:
        projected: list[ProviderMessage] = []
        resolved_calls_by_response: dict[tuple[str, str], set[str]] = {}
        for index, message in enumerate(messages):
            if not isinstance(message, AssistantMessage):
                continue
            key = (message.run_id, message.source_record_id)
            paired = set()
            for following in messages[index + 1 :]:
                if not isinstance(following, ToolMessage):
                    break
                paired.add(following.tool_call_id)
            resolved_calls_by_response[key] = paired
        for message in messages:
            if isinstance(message, UserMessage):
                projected.append(
                    ProviderMessage(
                        MessageRole.USER,
                        _user_text(message.text, message.attachment_ids),
                    )
                )
            elif isinstance(message, AssistantMessage):
                paired_calls = resolved_calls_by_response.get(
                    (message.run_id, message.source_record_id), set()
                )
                if any(
                    call.registry_version != registry.version and call.call_id not in paired_calls
                    for call in message.tool_calls
                ):
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                continuation = continuations.get(
                    (message.run_id, message.source_record_id)
                )
                if continuation is not None and continuation.provider_id is not selected_provider:
                    continuation = None
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


def _continuations_by_response(
    states: tuple[RunState, ...],
) -> dict[tuple[str, str], ProviderContinuation]:
    result: dict[tuple[str, str], ProviderContinuation] = {}
    for state in states:
        if not isinstance(state, RunState):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        for fact in state.provider_continuations:
            key = (fact.run_id, fact.response_record_id)
            if fact.run_id != state.run.run_id or key in result:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            try:
                result[key] = ProviderContinuation(
                    provider_id=ProviderId(fact.provider_id),
                    format_version=fact.format_version,
                    reasoning_content=fact.reasoning_content,
                )
            except (TypeError, ValueError):
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    return result


def _user_text(text: str, attachment_ids: tuple[str, ...]) -> str:
    if not attachment_ids:
        return text
    return f"{text}\n\n本条消息附件 ID：{', '.join(attachment_ids)}"
