"""Build the image feedback messages for the latest committed tool batch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from types import MappingProxyType

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import (
    AttachmentContent,
    ChartRenderContent,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.providers import ImageBlock, MessageRole, ProviderMessage, TextBlock
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RecordKind, ToolFactKind
from figura.runtime.records import RunState, ToolCallFact, ToolResultFact
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.tools import ToolOutcome


_MEASUREMENT_TOOLS = frozenset({"measure_bars", "measure_lines", "measure_scatter", "measure_pie"})


def build_observation_messages(
    state: RunState,
    execution_state: RunExecutionState,
    image_reader: RunExecutionImageReader,
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
            image = _source_image_block(state.run.session_id, execution_state, ref, image_reader)
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
            image_bytes, _width, _height = image_reader.read(
                state.run.session_id, execution_state, ref
            )
            label = "OCR 结果" if resource_kind == "ocr" else "测量结果"
            blocks.extend((
                TextBlock(f"{label}图像回看：{call.tool_name}；调用 ID：{call.call_id}。"),
                ImageBlock("image/png", image_bytes, MappingProxyType(asdict(ref)), "annotated"),
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
            image_bytes, _width, _height = image_reader.read(
                state.run.session_id, execution_state, ref
            )
            blocks.extend((
                TextBlock(
                    f"Figure 图像回看：render_chart_figure；运行 ID：{state.run.run_id}；"
                    f"调用 ID：{call.call_id}。"
                ),
                ImageBlock("image/png", image_bytes, MappingProxyType(asdict(ref)), "rendered"),
            ))

    if not blocks:
        return ()
    return (ProviderMessage(MessageRole.USER, tuple(blocks)),)


def _source_image_block(
    session_id: str,
    state: RunExecutionState,
    ref: ImageResourceRef,
    image_reader: RunExecutionImageReader,
) -> ImageBlock:
    resource = state.get(ref)
    if isinstance(resource.content, AttachmentContent):
        media_type = resource.content.media_type
    elif isinstance(resource.content, PanelContent):
        media_type = "image/png"
    else:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    image_bytes, _width, _height = image_reader.read_source(session_id, state, ref)
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
    return ImageBlock(media_type, image_bytes, MappingProxyType(asdict(ref)), "original")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value
