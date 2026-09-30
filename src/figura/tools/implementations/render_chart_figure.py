"""Render an accepted ChartFigure and persist its PNG by tool-call identity."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from figura.charts.chartfigure import (
    ChartFigure,
    ChartFigureParseError,
    chart_figure_digest,
    parse_chart_figure_json,
    validate_chart_figure,
)
from figura.charts.chartfigure.rendering import render_chart_figure_image
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ToolFactKind
from figura.runtime.records import (
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolResultFact,
)
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.sources.chart_renders import FiguraChartRenderService
from figura.tools.contracts import (
    ReplayEffect,
    ToolContext,
    ToolDefinition,
    ToolFailure,
    ToolOutcome,
)


class _ChartFigureSummary(Protocol):
    figure_ref: _ChartFigureReference
    figure_digest: str


class _ChartFigureReference(Protocol):
    run_id: str
    call_id: str


class _ExecutionState(Protocol):
    chart_figures: tuple[_ChartFigureSummary, ...]


_PARAMETERS_SCHEMA = {
    "type": "object",
    "properties": {
        "figure_ref": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "call_id": {"type": "string", "minLength": 1, "maxLength": 256},
            },
            "required": ["run_id", "call_id"],
            "additionalProperties": False,
        }
    },
    "required": ["figure_ref"],
    "additionalProperties": False,
}

_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "figure_ref": _PARAMETERS_SCHEMA["properties"]["figure_ref"],
        "figure_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "image_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "media_type": {"type": "string", "const": "image/png"},
        "byte_count": {"type": "integer", "minimum": 1, "maximum": MAX_IMAGE_BYTES},
        "width": {"type": "integer", "minimum": 1, "maximum": 1280},
        "height": {"type": "integer", "minimum": 1, "maximum": 1962},
    },
    "required": [
        "figure_ref",
        "figure_digest",
        "image_sha256",
        "media_type",
        "byte_count",
        "width",
        "height",
    ],
    "additionalProperties": False,
}


def render_chart_figure_definition(
    execution_state_for_run: Callable[[str, str], _ExecutionState],
    coordinator: RunCoordinator,
    renders: FiguraChartRenderService,
) -> ToolDefinition:
    def render(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        raw_reference = arguments["figure_ref"]
        reference_run_id = raw_reference["run_id"]
        reference_call_id = raw_reference["call_id"]
        try:
            execution_state = execution_state_for_run(context.session_id, context.run_id)
        except RunError:
            raise ToolFailure(
                "execution_state_unavailable",
                "当前 Session 的运行状态暂时无法读取。",
                retryable=True,
            ) from None

        summary = next(
            (
                item
                for item in execution_state.chart_figures
                if item.figure_ref.run_id == reference_run_id
                and item.figure_ref.call_id == reference_call_id
            ),
            None,
        )
        if summary is None:
            raise ToolFailure(
                "figure_reference_not_found",
                "Figure 引用不存在，或不属于当前 Session 的已接受历史。",
            )

        try:
            figure = _accepted_figure(
                context.session_id,
                reference_run_id,
                reference_call_id,
                summary.figure_digest,
                coordinator,
            )
        except RunError:
            raise ToolFailure(
                "figure_unavailable",
                "已接受的 Figure 内容当前无法读取。",
                retryable=True,
            ) from None
        except (ChartFigureParseError, ValueError):
            raise ToolFailure("figure_integrity_error", "已接受的 Figure 内容未通过完整性检查。") from None

        try:
            png, _width, _height = render_chart_figure_image(figure)
        except (ValueError, RuntimeError):
            raise ToolFailure("chart_render_failed", "Figure 当前无法生成 PNG 图像。") from None

        try:
            png, width, height = renders.store(context.run_id, context.call_id, png)
        except RunError as error:
            retryable = error.code is RunErrorCode.STORAGE_ERROR
            raise ToolFailure(
                "chart_render_storage_failed",
                "生成的 PNG 图像当前无法保存或校验。",
                retryable=retryable,
            ) from None

        return {
            "figure_ref": {"run_id": reference_run_id, "call_id": reference_call_id},
            "figure_digest": summary.figure_digest,
            "image_sha256": hashlib.sha256(png).hexdigest(),
            "media_type": "image/png",
            "byte_count": len(png),
            "width": width,
            "height": height,
        }

    return ToolDefinition(
        name="render_chart_figure",
        description=(
            "将同一 Session 中已接受的 ChartFigure 绘制为一个 PNG 画布。"
            "只传入 Figure 的 run_id 与 call_id；返回图像摘要，图像会附加到下一次模型请求。"
        ),
        parameters_schema=_PARAMETERS_SCHEMA,
        result_schema=_RESULT_SCHEMA,
        replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE,
        handler=render,
    )


def _accepted_figure(
    session_id: str,
    reference_run_id: str,
    reference_call_id: str,
    expected_digest: str,
    coordinator: RunCoordinator,
) -> ChartFigure:
    state = coordinator.read_run_state(session_id, reference_run_id)
    if state.run.session_id != session_id:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)

    calls = {
        fact.tool_sequence: fact.payload
        for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact)
    }
    results = {
        fact.payload.tool_call_sequence: fact.payload
        for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(fact.payload, ToolResultFact)
    }
    attempts: dict[int, list[ToolAttemptStartedFact]] = {}
    for fact in state.tool_facts:
        if (
            fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
            and isinstance(fact.payload, ToolAttemptStartedFact)
        ):
            attempts.setdefault(fact.payload.tool_call_sequence, []).append(fact.payload)

    for sequence, call in calls.items():
        if call.tool_name != "assemble_chart_figure" or call.call_id != reference_call_id:
            continue
        result = results.get(sequence)
        if (
            result is None
            or result.outcome is not ToolOutcome.SUCCEEDED
            or result.tool_name != call.tool_name
            or result.call_id != call.call_id
            or not any(
                attempt.call_id == call.call_id and attempt.attempt_id == result.attempt_id
                for attempt in attempts.get(sequence, ())
            )
            or not isinstance(result.result, Mapping)
            or result.result.get("figure_digest") != expected_digest
            or result.result.get("figure_ref") != {"run_id": reference_run_id, "call_id": reference_call_id}
        ):
            break
        figure = parse_chart_figure_json(call.arguments_json)
        issues = validate_chart_figure(figure)
        if issues or chart_figure_digest(figure) != expected_digest:
            break
        return figure
    raise ValueError("accepted Figure facts do not agree")
