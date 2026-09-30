"""Projection from durable Figura conversation facts to a bounded Provider request."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from figura.memory import (
    AssistantMessage,
    MemoryMessage,
    ToolMessage,
    UserMessage,
    project_run_messages,
    project_session_history,
)
from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import (
    AttachmentContent,
    ChartFigureContent,
    ChartRenderContent,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.agent.execution_state import RunExecutionStateService
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
from figura.runtime.models import ActionKind, RecordKind, Run, RunStatus, ToolFactKind
from figura.runtime.records import (
    ProviderContinuationFact,
    RunState,
    ToolCallFact,
    ToolResultFact,
)
from figura.tools import ToolOutcome, ToolRegistry, project_provider_tools


_SYSTEM_INSTRUCTION = Path(__file__).with_name("assets").joinpath("system-v1.md").read_text(
    encoding="utf-8"
)
_MAX_COMPLETION_TOKENS = 4096
_MEASUREMENT_TOOLS = frozenset({"measure_bars", "measure_lines", "measure_scatter", "measure_pie"})


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
            current_run=state.run,
            continuations=_continuations_by_response(
                state.provider_continuations, state.run.run_id
            ),
            registry=registry,
        )
        messages = (
            *messages,
            ProviderMessage(MessageRole.USER, _image_inventory(execution_state)),
            *self._tool_image_messages(state, execution_state),
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

    def _tool_image_messages(
        self,
        state: RunState,
        execution_state: RunExecutionState,
    ) -> tuple[ProviderMessage, ...]:
        response_id = next(
            (
                record.record_id
                for record in reversed(state.records)
                if record.record_kind is RecordKind.MODEL_RESPONSE
            ),
            None,
        )
        if response_id is None:
            return ()
        calls = sorted(
            (
                (fact.tool_sequence, fact.payload)
                for fact in state.tool_facts
                if fact.fact_kind is ToolFactKind.TOOL_CALL
                and isinstance(fact.payload, ToolCallFact)
                and fact.payload.response_record_id == response_id
            ),
            key=lambda item: item[1].position,
        )
        if not calls:
            return ()

        results = {
            fact.payload.tool_call_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_RESULT
            and isinstance(fact.payload, ToolResultFact)
        }
        if any(sequence not in results for sequence, _call in calls):
            raise RunError(RunErrorCode.INVALID_TRANSITION)

        blocks: list[TextBlock | ImageBlock] = []
        loaded_sources: set[ImageResourceRef] = set()
        for sequence, call in calls:
            result = results[sequence]
            if result.call_id != call.call_id or result.tool_name != call.tool_name:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if result.outcome is not ToolOutcome.SUCCEEDED:
                continue
            if not isinstance(result.result, Mapping):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

            if call.tool_name == "load_image":
                kind = result.result.get("source_kind")
                source_id = result.result.get("source_id")
                name = result.result.get("name")
                if (
                    not isinstance(kind, str)
                    or kind not in {"attachment", "panel"}
                    or not isinstance(source_id, str)
                    or not isinstance(name, str)
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                ref = ImageResourceRef(kind, source_id)
                if ref in loaded_sources:
                    continue
                resource = execution_state.get(ref)
                if isinstance(resource.content, AttachmentContent):
                    expected_name = resource.content.filename
                elif isinstance(resource.content, PanelContent):
                    expected_name = resource.content.name
                else:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if name != expected_name:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                loaded_sources.add(ref)
                image = self._source_image_block(state.run.session_id, execution_state, ref)
                blocks.extend((TextBlock(f"已加载图像 {kind}:{source_id}（{name}）。"), image))
                continue

            if call.tool_name == "extract_text" or call.tool_name in _MEASUREMENT_TOOLS:
                resource_kind = "ocr" if call.tool_name == "extract_text" else "measurement"
                ref = ToolResourceRef(resource_kind, state.run.run_id, call.call_id)
                content = execution_state.get(ref).content
                if resource_kind == "ocr":
                    if not isinstance(content, OcrContent):
                        raise RunError(RunErrorCode.INTEGRITY_ERROR)
                    outcome, observation_result, source_ref = (
                        content.outcome,
                        content.result,
                        content.source_ref,
                    )
                else:
                    if not isinstance(content, MeasurementContent) or content.tool_name != call.tool_name:
                        raise RunError(RunErrorCode.INTEGRITY_ERROR)
                    outcome, observation_result, source_ref = (
                        content.outcome,
                        content.result,
                        content.source_ref,
                    )
                if (
                    outcome is not ToolOutcome.SUCCEEDED
                    or observation_result is None
                    or source_ref is None
                    or _thaw_json(observation_result) != _thaw_json(result.result)
                    or result.result.get("source_kind") != source_ref.kind
                    or result.result.get("source_id") != source_ref.id
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                image_bytes, _width, _height = self._execution_images.read(
                    state.run.session_id, execution_state, ref
                )
                label = "OCR 结果" if resource_kind == "ocr" else "测量结果"
                blocks.extend((
                    TextBlock(f"{label}图像回看：{call.tool_name}；调用 ID：{call.call_id}。"),
                    ImageBlock("image/png", image_bytes),
                ))
                continue

            if call.tool_name == "render_chart_figure":
                ref = ToolResourceRef("chart_render", state.run.run_id, call.call_id)
                content = execution_state.get(ref).content
                if (
                    not isinstance(content, ChartRenderContent)
                    or content.result is None
                    or content.figure_ref is None
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                expected_result = _thaw_json(content.result)
                if not isinstance(expected_result, dict):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                expected_result["figure_ref"] = {
                    "run_id": content.figure_ref.run_id,
                    "call_id": content.figure_ref.call_id,
                }
                if expected_result != result.result:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                image_bytes, _width, _height = self._execution_images.read(
                    state.run.session_id, execution_state, ref
                )
                blocks.extend((
                    TextBlock(
                        f"Figure 图像回看：render_chart_figure；运行 ID：{state.run.run_id}；"
                        f"调用 ID：{call.call_id}。"
                    ),
                    ImageBlock("image/png", image_bytes),
                ))

        if not blocks:
            return ()
        return (ProviderMessage(MessageRole.USER, tuple(blocks)),)

    def _source_image_block(
        self,
        session_id: str,
        state: RunExecutionState,
        ref: ImageResourceRef,
    ) -> ImageBlock:
        resource = state.get(ref)
        if isinstance(resource.content, AttachmentContent):
            media_type = resource.content.media_type
        elif isinstance(resource.content, PanelContent):
            media_type = "image/png"
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        image_bytes, _width, _height = self._execution_images.read_source(session_id, state, ref)
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return ImageBlock(media_type, image_bytes)


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
    attachments = [
        f"- attachment:{resource.ref.id}：{resource.content.filename}"
        for resource in state.list("attachment")
        if isinstance(resource.ref, ImageResourceRef)
        and isinstance(resource.content, AttachmentContent)
    ]
    panels = [
        f"- panel:{resource.ref.id}：{resource.content.name}（源附件 attachment:{resource.content.source_attachment_id}）"
        for resource in state.list("panel")
        if isinstance(resource.ref, ImageResourceRef)
        and isinstance(resource.content, PanelContent)
    ]

    observations: list[str] = []
    for kind in ("ocr", "measurement"):
        for resource in state.list(kind):
            if not isinstance(resource.ref, ToolResourceRef):
                continue
            content = resource.content
            if isinstance(content, OcrContent):
                tool_name = "extract_text"
                detail = (
                    f"snippets={len(content.result.get('snippets', ()))}, "
                    f"available={content.result.get('available')}"
                    if content.result is not None
                    else f"error={content.error.code if content.error else 'unknown'}"
                )
                source_ref = content.source_ref
                outcome = content.outcome.value
            elif isinstance(content, MeasurementContent):
                tool_name = content.tool_name
                if content.result is None:
                    detail = f"error={content.error.code if content.error else 'unknown'}"
                else:
                    status = content.result.get("status", "unknown")
                    counts = [
                        f"{key}={len(content.result[key])}"
                        for key in ("bars", "series", "sectors")
                        if isinstance(content.result.get(key), (tuple, list))
                    ]
                    detail = ", ".join((f"status={status}", *counts))
                source_ref = content.source_ref
                outcome = content.outcome.value
            else:
                continue
            source = (
                f"{source_ref.kind}:{source_ref.id}"
                if source_ref is not None
                else "unavailable"
            )
            observations.append(
                f"- {kind}:{resource.ref.run_id}:{resource.ref.call_id}；"
                f"tool={tool_name}；source={source}；outcome={outcome}；{detail}"
            )

    figures: list[str] = []
    for resource in state.list("chart_figure"):
        if not isinstance(resource.ref, ToolResourceRef) or not isinstance(resource.content, ChartFigureContent):
            continue
        content = resource.content
        if content.result is None:
            figures.append(
                f"- chart_figure:{resource.ref.run_id}:{resource.ref.call_id}；"
                f"outcome={content.outcome.value}；error={content.error.code if content.error else 'unknown'}"
            )
            continue
        figure = content.result.figure
        charts = "; ".join(
            f"{chart.chart_id}/{chart.chart_spec.metadata.chart_type.value}/"
            f"{json.dumps(chart.chart_spec.metadata.title, ensure_ascii=False)}"
            for chart in figure.charts
        )
        figures.append(
            f"- chart_figure:{resource.ref.run_id}:{resource.ref.call_id}；"
            f"title={json.dumps(figure.title, ensure_ascii=False)}；"
            f"digest={content.result.figure_digest}；charts=[{charts}]"
        )

    renders: list[str] = []
    for resource in state.list("chart_render"):
        if not isinstance(resource.ref, ToolResourceRef) or not isinstance(resource.content, ChartRenderContent):
            continue
        content = resource.content
        figure_ref = (
            f"chart_figure:{content.figure_ref.run_id}:{content.figure_ref.call_id}"
            if content.figure_ref is not None
            else "unavailable"
        )
        detail = (
            f"png={content.result.get('width')}x{content.result.get('height')}"
            if content.result is not None
            else f"error={content.error.code if content.error else 'unknown'}"
        )
        renders.append(
            f"- chart_render:{resource.ref.run_id}:{resource.ref.call_id}；"
            f"figure={figure_ref}；outcome={content.outcome.value}；{detail}"
        )

    return (
        "当前 Run 可访问资源索引（完整工具结果仍以对话历史为准）。\n"
        f"附件：\n{chr(10).join(attachments) or '- 无'}\n"
        f"Panel：\n{chr(10).join(panels) or '- 无'}\n"
        f"OCR 与测量：\n{chr(10).join(observations) or '- 无'}\n"
        f"ChartFigure：\n{chr(10).join(figures) or '- 无'}\n"
        f"ChartRender：\n{chr(10).join(renders) or '- 无'}\n"
        "需要查看原图时使用 load_image；extract_text 与测量工具可直接选择附件或 Panel。"
        "图像观察回看只附加紧接上一轮已提交工具批次的图像。"
    )


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value
