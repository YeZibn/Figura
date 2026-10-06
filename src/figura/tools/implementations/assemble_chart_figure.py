"""Model-callable Figure assembly and measurement-reference validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.charts.chartfigure import (
    CHART_FIGURE_SCHEMA,
    ChartFigure,
    ChartFigureParseError,
    chart_figure_digest,
    parse_chart_figure,
    validate_chart_figure,
)
from figura.charts.chartspec import ChartType
from figura.agent.execution_resources import MeasurementContent, RunExecutionState, ToolResourceRef
from figura.runtime.errors import RunError
from figura.tools.contracts import (
    ReplayEffect,
    ToolContext,
    ToolDefinition,
    ToolFailure,
    ToolOutcome,
)


_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "figure_ref": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "minLength": 1},
                "call_id": {"type": "string", "minLength": 1},
            },
            "required": ["run_id", "call_id"],
            "additionalProperties": False,
        },
        "figure_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "title": {"type": "string", "maxLength": 160},
        "charts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chart_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
                    "chart_type": {"type": "string", "enum": [kind.value for kind in ChartType]},
                    "title": {"type": "string", "maxLength": 160},
                },
                "required": ["chart_id", "chart_type", "title"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 4,
        },
    },
    "required": ["figure_ref", "figure_digest", "title", "charts"],
    "additionalProperties": False,
}

_MEASUREMENT_TOOLS = frozenset({"measure_chart"})


def assemble_chart_figure_definition(
    execution_state_for_run: Callable[[str, str], RunExecutionState],
) -> ToolDefinition:
    def assemble(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        try:
            figure = parse_chart_figure(arguments)
        except ChartFigureParseError as error:
            issue = error.issue
            raise ToolFailure(
                issue.code,
                issue.message,
                field_path=issue.field_path or None,
            ) from None

        issues = validate_chart_figure(figure)
        if issues:
            issue = issues[0]
            raise ToolFailure(
                issue.code,
                issue.message,
                field_path=issue.field_path or None,
            )

        try:
            state = execution_state_for_run(context.session_id, context.run_id)
        except RunError:
            raise ToolFailure(
                "execution_state_unavailable",
                "当前 Session 的运行状态暂时无法读取。",
                retryable=True,
            ) from None

        for chart_index, chart in enumerate(figure.charts):
            for reference_index, reference in enumerate(chart.measurement_refs):
                resource_ref = ToolResourceRef("measurement", reference.run_id, reference.call_id)
                field_path = f"/charts/{chart_index}/measurement_refs/{reference_index}"
                try:
                    resource = state.get(resource_ref)
                except RunError:
                    raise ToolFailure(
                        "measurement_reference_not_found",
                        "测量引用不存在，或不属于当前 Session 的已授权历史。",
                        field_path=f"{field_path}/call_id",
                    )
                observation = resource.content
                if (
                    not isinstance(observation, MeasurementContent)
                    or observation.tool_name not in _MEASUREMENT_TOOLS
                ):
                    raise ToolFailure(
                        "measurement_reference_not_found",
                        "测量引用不存在，或不属于当前 Session 的已授权历史。",
                        field_path=f"{field_path}/call_id",
                    )
                if observation.outcome is not ToolOutcome.SUCCEEDED:
                    raise ToolFailure(
                        "measurement_reference_not_succeeded",
                        "测量引用尚未成功提交。",
                        field_path=field_path,
                    )

        return {
            "figure_ref": {"run_id": context.run_id, "call_id": context.call_id},
            "figure_digest": chart_figure_digest(figure),
            "title": figure.title,
            "charts": [
                {
                    "chart_id": chart.chart_id,
                    "chart_type": chart.chart_spec.metadata.chart_type.value,
                    "title": chart.chart_spec.metadata.title,
                }
                for chart in figure.charts
            ],
        }

    return ToolDefinition(
        name="assemble_chart_figure",
        description=(
            "将 1–4 个完整有效的 ChartSpec 按顺序装配为新的 Figure，返回 figure_ref、摘要与 digest，不绘制图像。"
            "修改已有 Figure 时读取其完整内容后提交完整新 Figure。measurement_refs 只能引用当前授权历史中实际采用的成功 measure_chart 观察；校验不证明数据真值。"
            "十类 ChartSpec 均使用各自原生数据与坐标结构，字段语义见参数 Schema。"
        ),
        parameters_schema=CHART_FIGURE_SCHEMA,
        result_schema=_RESULT_SCHEMA,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=assemble,
    )
