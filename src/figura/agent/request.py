"""Projection from durable Figura conversation facts to a bounded Provider request."""

from __future__ import annotations

from pathlib import Path

from figura.sources.attachments import FiguraAttachmentService
from figura.memory import (
    AssistantMessage,
    MemoryMessage,
    ToolMessage,
    UserMessage,
    project_run_messages,
    project_session_history,
)
from figura.agent.execution_state import RunExecutionState, RunExecutionStateService
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
from figura.providers.validation import validate_request
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ActionKind, Run, RunStatus
from figura.runtime.records import ProviderContinuationFact, RunState
from figura.tools import ToolRegistry, project_provider_tools
from figura.agent.execution_state import latest_loaded_images


_SYSTEM_INSTRUCTION = Path(__file__).with_name("assets").joinpath("system-v1.md").read_text(
    encoding="utf-8"
)
_MAX_COMPLETION_TOKENS = 4096


class AgentRequestBuilder:
    """Build one validated model request from Session history and the current Run."""

    __slots__ = ("_attachments", "_execution_state")

    def __init__(
        self,
        attachments: FiguraAttachmentService,
        execution_state: RunExecutionStateService,
    ) -> None:
        if not isinstance(attachments, FiguraAttachmentService):
            raise TypeError("attachments must be a FiguraAttachmentService")
        if not isinstance(execution_state, RunExecutionStateService):
            raise TypeError("execution_state must be a RunExecutionStateService")
        object.__setattr__(self, "_attachments", attachments)
        object.__setattr__(self, "_execution_state", execution_state)

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
            current_run=state.run,
            continuations=_continuations_by_response(
                state.provider_continuations, state.run.run_id
            ),
            registry=registry,
        )
        messages = (
            *messages,
            ProviderMessage(MessageRole.USER, _image_inventory(execution_state)),
            *self._loaded_image_messages(state, execution_state),
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
                        _user_text(message.text, message.attachment_ids),
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

    def _loaded_image_messages(
        self,
        state: RunState,
        execution_state: RunExecutionState,
    ) -> tuple[ProviderMessage, ...]:
        available_attachments = {item.attachment_id: item for item in execution_state.available_attachments}
        available_panels = {item.panel_id: item for item in execution_state.panels}
        blocks: list[TextBlock | ImageBlock] = []
        for kind, source_id, name in latest_loaded_images(state):
            if kind == "attachment":
                if source_id not in available_attachments:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                image = self._attachments.resolve(state.run.session_id, source_id)
            else:
                if source_id not in available_panels:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                _record, image, _width, _height = self._execution_state.resolve_panel(
                    state.run.session_id, source_id
                )
            if (
                not isinstance(image, ImageBlock)
                or not isinstance(image.image_bytes, bytes)
                or not image.image_bytes
                or len(image.image_bytes) > MAX_IMAGE_BYTES
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            blocks.extend((TextBlock(f"已加载图像 {kind}:{source_id}（{name}）。"), image))
        if not blocks:
            return ()
        return (ProviderMessage(MessageRole.USER, tuple(blocks)),)


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


def _user_text(text: str, attachment_ids: tuple[str, ...]) -> str:
    if not attachment_ids:
        return text
    return f"{text}\n\n本条消息附件 ID：{', '.join(attachment_ids)}"


def _image_inventory(state: RunExecutionState) -> str:
    attachments = "\n".join(
        f"- 附件 {item.attachment_id}：{item.filename}"
        for item in state.available_attachments
    ) or "- 无可用附件"
    panels = "\n".join(
        f"- Panel {item.panel_id}：{item.name}（源附件 {item.source_attachment_id}）"
        for item in state.panels
    ) or "- 无已提交 Panel"
    return (
        "当前 Session 图像清单（这里只是名称和 ID，尚未提供图像内容）。\n"
        f"可用附件：\n{attachments}\n"
        f"已提交 Panel：\n{panels}\n"
        "需要观察图像时，先用 load_image 显式读取。矩形也用四点多边形提交给 decompose_chart_image。"
    )
