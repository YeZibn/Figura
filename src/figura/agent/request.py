"""Projection from durable Figura conversation facts to a bounded Provider request."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from pathlib import Path

from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
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
from figura.runtime.models import ActionKind, RecordKind, Run, RunStatus, ToolFactKind
from figura.runtime.records import (
    ProviderContinuationFact,
    RunState,
    ToolCallFact,
    ToolResultFact,
)
from figura.tools import ToolOutcome, ToolRegistry, project_provider_tools
from figura.tools.measurements.visualization import render_measurement_overlay


_SYSTEM_INSTRUCTION = Path(__file__).with_name("assets").joinpath("system-v1.md").read_text(
    encoding="utf-8"
)
_MAX_COMPLETION_TOKENS = 4096
_MEASUREMENT_TOOLS = frozenset({"measure_bars", "measure_lines", "measure_scatter", "measure_pie"})


class AgentRequestBuilder:
    """Build one validated model request from Session history and the current Run."""

    __slots__ = ("_attachments", "_execution_state", "_chart_renders")

    def __init__(
        self,
        attachments: FiguraAttachmentService,
        execution_state: RunExecutionStateService,
        chart_renders: FiguraChartRenderService,
    ) -> None:
        if not isinstance(attachments, FiguraAttachmentService):
            raise TypeError("attachments must be a FiguraAttachmentService")
        if not isinstance(execution_state, RunExecutionStateService):
            raise TypeError("execution_state must be a RunExecutionStateService")
        if not isinstance(chart_renders, FiguraChartRenderService):
            raise TypeError("chart_renders must be a FiguraChartRenderService")
        object.__setattr__(self, "_attachments", attachments)
        object.__setattr__(self, "_execution_state", execution_state)
        object.__setattr__(self, "_chart_renders", chart_renders)

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
        available_attachments = {item.attachment_id: item for item in execution_state.available_attachments}
        available_panels = {item.panel_id: item for item in execution_state.panels}
        blocks: list[TextBlock | ImageBlock] = []
        response_id = next(
            (record.record_id for record in reversed(state.records) if record.record_kind is RecordKind.MODEL_RESPONSE),
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
        results = {
            fact.payload.tool_call_sequence: fact.payload
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_RESULT
            and isinstance(fact.payload, ToolResultFact)
        }
        observations = {
            item.call_id: item
            for item in execution_state.measurements
            if item.run_id == state.run.run_id
        }
        render_observations = {
            item.call_id: item
            for item in execution_state.chart_renders
            if item.run_id == state.run.run_id
        }
        loaded_sources: set[tuple[str, str]] = set()
        for sequence, call in calls:
            result = results.get(sequence)
            if result is None or result.outcome is not ToolOutcome.SUCCEEDED or not isinstance(result.result, Mapping):
                continue
            if call.tool_name == "load_image":
                kind, source_id, name = (
                    result.result.get("source_kind"),
                    result.result.get("source_id"),
                    result.result.get("name"),
                )
                if (
                    not isinstance(kind, str) or kind not in {"attachment", "panel"}
                    or not isinstance(source_id, str) or not isinstance(name, str)
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                identity = (kind, source_id)
                if identity in loaded_sources:
                    continue
                loaded_sources.add(identity)
                image = self._resolve_source_image(
                    state.run.session_id, kind, source_id, available_attachments, available_panels
                )
                blocks.extend((TextBlock(f"已加载图像 {kind}:{source_id}（{name}）。"), image))
                continue
            if call.tool_name == "extract_text":
                kind, source_id = _tool_source_identity(call.arguments_json)
                if (
                    result.result.get("source_kind") != kind
                    or result.result.get("source_id") != source_id
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                image = self._resolve_source_image(
                    state.run.session_id, kind, source_id, available_attachments, available_panels
                )
                try:
                    annotated_bytes = render_measurement_overlay(
                        image.image_bytes,
                        result.result,
                        call.tool_name,
                    )
                except (TypeError, ValueError, OSError):
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
                if not annotated_bytes or len(annotated_bytes) > MAX_IMAGE_BYTES:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                blocks.extend((
                    TextBlock(f"OCR 结果图像回看：extract_text；调用 ID：{call.call_id}。"),
                    ImageBlock("image/png", annotated_bytes),
                ))
                continue
            if call.tool_name == "render_chart_figure":
                observation = render_observations.get(call.call_id)
                figure_ref = _tool_figure_reference(call.arguments_json)
                result_ref = result.result.get("figure_ref")
                if (
                    observation is None
                    or observation.outcome is not ToolOutcome.SUCCEEDED
                    or observation.result is None
                    or observation.figure_ref.run_id != figure_ref[0]
                    or observation.figure_ref.call_id != figure_ref[1]
                    or not isinstance(result_ref, Mapping)
                    or result_ref != {"run_id": figure_ref[0], "call_id": figure_ref[1]}
                    or dict(observation.result)
                    != {key: value for key, value in result.result.items() if key != "figure_ref"}
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                try:
                    image_bytes, width, height = self._chart_renders.resolve(
                        state.run.run_id, call.call_id
                    )
                except RunError:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
                if (
                    hashlib.sha256(image_bytes).hexdigest() != result.result.get("image_sha256")
                    or len(image_bytes) != result.result.get("byte_count")
                    or width != result.result.get("width")
                    or height != result.result.get("height")
                    or result.result.get("media_type") != "image/png"
                ):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                blocks.extend((
                    TextBlock(
                        f"Figure 图像回看：render_chart_figure；运行 ID：{state.run.run_id}；"
                        f"调用 ID：{call.call_id}。"
                    ),
                    ImageBlock("image/png", image_bytes),
                ))
                continue
            if call.tool_name not in _MEASUREMENT_TOOLS:
                continue
            observation = observations.get(call.call_id)
            if (
                observation is None
                or observation.outcome is not ToolOutcome.SUCCEEDED
                or observation.result is None
                or observation.source_kind != result.result.get("source_kind")
                or observation.source_id != result.result.get("source_id")
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            image = self._resolve_source_image(
                state.run.session_id,
                observation.source_kind,
                observation.source_id,
                available_attachments,
                available_panels,
            )
            try:
                annotated_bytes = render_measurement_overlay(
                    image.image_bytes,
                    observation.result,
                    call.tool_name,
                )
            except (TypeError, ValueError, OSError):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
            if not annotated_bytes or len(annotated_bytes) > MAX_IMAGE_BYTES:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            blocks.extend((
                TextBlock(f"测量结果图像回看：{call.tool_name}；调用 ID：{call.call_id}。"),
                ImageBlock("image/png", annotated_bytes),
            ))
        if not blocks:
            return ()
        return (ProviderMessage(MessageRole.USER, tuple(blocks)),)

    def _resolve_source_image(
        self,
        session_id: str,
        kind: str,
        source_id: str,
        available_attachments: Mapping[str, object],
        available_panels: Mapping[str, object],
    ) -> ImageBlock:
        if kind == "attachment":
            if source_id not in available_attachments:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            image = self._attachments.resolve(session_id, source_id)
        elif kind == "panel":
            if source_id not in available_panels:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            _record, image, _width, _height = self._execution_state.resolve_panel(session_id, source_id)
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if (
            not isinstance(image, ImageBlock)
            or not isinstance(image.image_bytes, bytes)
            or not image.image_bytes
            or len(image.image_bytes) > MAX_IMAGE_BYTES
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return image


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


def _tool_source_identity(arguments_json: str) -> tuple[str, str]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate tool argument")
            result[key] = value
        return result

    try:
        arguments = json.loads(arguments_json, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    if not isinstance(arguments, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    kind, source_id = arguments.get("source_kind"), arguments.get("source_id")
    if (
        not isinstance(kind, str)
        or kind not in {"attachment", "panel"}
        or not isinstance(source_id, str)
        or not source_id
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return kind, source_id


def _tool_figure_reference(arguments_json: str) -> tuple[str, str]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate tool argument")
            result[key] = value
        return result

    try:
        arguments = json.loads(arguments_json, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"figure_ref"}
        or not isinstance(arguments["figure_ref"], dict)
        or set(arguments["figure_ref"]) != {"run_id", "call_id"}
        or not isinstance(arguments["figure_ref"].get("run_id"), str)
        or not arguments["figure_ref"]["run_id"]
        or not isinstance(arguments["figure_ref"].get("call_id"), str)
        or not arguments["figure_ref"]["call_id"]
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return arguments["figure_ref"]["run_id"], arguments["figure_ref"]["call_id"]


def _image_inventory(state: RunExecutionState) -> str:
    attachments = "\n".join(
        f"- 附件 {item.attachment_id}：{item.filename}"
        for item in state.available_attachments
    ) or "- 无可用附件"
    panels = "\n".join(
        f"- Panel {item.panel_id}：{item.name}（源附件 {item.source_attachment_id}）"
        for item in state.panels
    ) or "- 无已提交 Panel"
    figures = "\n".join(
        "- Figure ref "
        f"{json.dumps({'run_id': item.figure_ref.run_id, 'call_id': item.figure_ref.call_id}, ensure_ascii=False)}；"
        f"digest {item.figure_digest}；标题 {json.dumps(item.title, ensure_ascii=False)}\n"
        + "\n".join(
            f"  - chart_id={chart.chart_id}；类型={chart.chart_type.value}；标题={json.dumps(chart.title, ensure_ascii=False)}"
            for chart in item.charts
        )
        for item in state.chart_figures
    ) or "- 无已接受 Figure"
    return (
        "当前 Session 图像清单（这里只是名称和 ID，尚未提供图像内容）。\n"
        f"可用附件：\n{attachments}\n"
        f"已提交 Panel：\n{panels}\n"
        f"已接受 Figure：\n{figures}\n"
        "需要查看原图时使用 load_image；extract_text、measure_bars、measure_lines、measure_scatter、measure_pie 可直接选择来源观察，无需先加载图像。"
        "矩形也用四点多边形提交给 decompose_chart_image。完整 Figure 内容保存在对应 Figure ref 的工具调用历史中。"
    )
