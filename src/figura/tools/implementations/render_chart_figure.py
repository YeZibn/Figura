"""Render an accepted ChartFigure and persist its PNG by tool-call identity."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from figura.agent.execution_resources import ChartFigureContent, RunExecutionState, ToolResourceRef
from figura.charts.chartfigure.rendering import render_chart_figure_image
from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.sources.chart_renders import FiguraChartRenderService
from figura.tools import ToolOutcome
from figura.tools.contracts import (
    ReplayEffect,
    ToolContext,
    ToolDefinition,
    ToolFailure,
)


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
    execution_state_for_run: Callable[[str, str], RunExecutionState],
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

        try:
            resource = execution_state.get(
                ToolResourceRef("chart_figure", reference_run_id, reference_call_id)
            )
        except RunError as error:
            if error.code is RunErrorCode.RUN_NOT_FOUND:
                raise ToolFailure(
                    "figure_reference_not_found",
                    "Figure 引用不存在，或不属于当前 Session 的已接受历史。",
                ) from None
            raise ToolFailure(
                "figure_unavailable",
                "已接受的 Figure 内容当前无法读取。",
                retryable=True,
            ) from None

        content = resource.content
        if (
            not isinstance(content, ChartFigureContent)
            or content.outcome is not ToolOutcome.SUCCEEDED
            or content.result is None
        ):
            raise ToolFailure(
                "figure_reference_not_found",
                "Figure 引用不存在，或不属于当前 Session 的已接受历史。",
            )

        try:
            png, _width, _height = render_chart_figure_image(content.result.figure)
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
            "figure_digest": content.result.figure_digest,
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
