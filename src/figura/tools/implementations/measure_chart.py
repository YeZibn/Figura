"""Unified family-explicit chart measurement tool and adapter router."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from figura.charts.chartspec.models import ChartType
from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import RunExecutionState
from figura.tools.contracts import ReplayEffect, ToolContext, ToolDefinition, ToolFailure
from figura.tools.measurements.contracts import (
    MEASUREMENT_RESULT_SCHEMA,
    MeasurementResult,
    MeasurementSensorResult,
    PreparedMeasurementImage,
    validate_measurement_result,
)
from figura.tools.measurements.observation_scope import ObservationScopeError, decode_scoped_image
from figura.tools.measurements.support import build_axis_support
from figura.tools.measurements.context import shared_observation

from .measurement_schema import OBSERVATION_SCOPE
from .measurement_source import MeasurementSource, resolve_measurement_source


MeasurementAdapter = Callable[[PreparedMeasurementImage], MeasurementSensorResult]
_OBSERVATION_SCOPE_SCHEMA = {
    **OBSERVATION_SCOPE,
    "anyOf": [
        {"properties": {"include": {"type": "array"}}, "required": ["include"]},
        {"properties": {"exclude": {"type": "array"}}, "required": ["exclude"]},
    ],
}

MEASURE_CHART_PARAMETERS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "source_kind": {
            "description": "授权图像来源类型，只能是 Attachment 或 Panel。",
            "type": "string",
            "enum": ["attachment", "panel"],
        },
        "source_id": {
            "description": "来源清单中的不透明资源 ID；不是工具调用 ID、路径或 URL。",
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
        },
        "chart_type": {
            "description": "由 Agent 明确选择的图表家族。气泡图选择 scatter，甜甜圈图选择 pie。",
            "type": "string",
            "enum": [chart_type.value for chart_type in ChartType],
        },
        "observation_scope": _OBSERVATION_SCOPE_SCHEMA,
    },
    "required": ["source_kind", "source_id", "chart_type"],
    "additionalProperties": False,
}


def measure_chart_definition(
    image_inventory: Callable[[str, str], RunExecutionState],
    image_reader: RunExecutionImageReader,
    adapters: Mapping[ChartType | str, MeasurementAdapter],
) -> ToolDefinition:
    """Build a single measurement definition backed by all ten explicit sensors."""
    normalized_adapters: dict[ChartType, MeasurementAdapter] = {}
    for key, adapter in adapters.items():
        try:
            chart_type = key if isinstance(key, ChartType) else ChartType(key)
        except (TypeError, ValueError):
            raise ValueError("measurement adapter family is unsupported") from None
        if not callable(adapter) or chart_type in normalized_adapters:
            raise ValueError("measurement adapters must have unique callable family entries")
        normalized_adapters[chart_type] = adapter
    missing = set(ChartType) - set(normalized_adapters)
    if missing:
        raise ValueError("measure_chart requires a sensor for every advertised family")

    def measure(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, object]:
        source_kind = arguments["source_kind"]
        source_id = arguments["source_id"]
        chart_type = ChartType(arguments["chart_type"])
        source = resolve_measurement_source(
            context.session_id,
            source_kind,
            source_id,
            image_inventory,
            image_reader,
            context.run_id,
        )
        scope = arguments.get("observation_scope")
        prepared = _prepare_source(source, scope)
        try:
            with shared_observation(prepared.rgb, prepared.observation_mask):
                sensor_result = normalized_adapters[chart_type](prepared)
        except ToolFailure:
            raise
        except Exception:
            raise ToolFailure("measurement_failed", "图表观察未能完成。") from None
        if not isinstance(sensor_result, MeasurementSensorResult):
            raise ToolFailure("invalid_measurement_result", "图表观察结果不符合统一合同。")

        result = MeasurementResult(
            chart_type=chart_type,
            source_kind=source.source_kind,
            source_id=source.source_id,
            image_size=(source.width, source.height),
            coordinate_system=source.coordinate_system,
            status=sensor_result.status,
            plot_area_px=sensor_result.plot_area_px,
            observations=sensor_result.observations,
            confidence=sensor_result.confidence,
            warnings=sensor_result.warnings,
            truncated=sensor_result.truncated,
            issues=sensor_result.issues,
            evidence=sensor_result.evidence,
            calibrations=sensor_result.calibrations,
            value_provenance=sensor_result.value_provenance,
        )
        supported_result = build_axis_support(result.to_dict(), scope)
        issue = validate_measurement_result(supported_result)
        if issue is not None:
            raise ToolFailure(
                "invalid_measurement_result",
                "图表观察结果未通过统一合同校验。",
                field_path=issue.field_path or None,
            )
        return supported_result

    return ToolDefinition(
        name="measure_chart",
        description=(
            "对已授权的 Attachment 或 Panel 执行一次明确家族的图表视觉观察。必须提供 chart_type：bar、line、scatter、pie、area、"
            "histogram、box_plot、radar、heatmap 或 treemap；气泡图归入 scatter，甜甜圈图归入 pie。"
            "家族由 Agent 根据用户描述、当前视觉上下文或 load_image 后观察结果选择；本工具不调用模型、不分类、不改选家族，也不自动重试。"
            "结果是保留原图像素坐标与不确定性的候选证据，不会自动成为 ChartSpec。非空数值带 value_provenance，coverage 描述实际范围，issues 保留缺口与冲突；未校准的数值保持 null；partial、unsupported、警告和截断情况由 Agent 决定后续动作。"
            "可选 observation_scope 使用来源内 0–1000 归一化多边形，include 取并集、exclude 优先扣除；无效或无可观察像素时失败，不会扩大到全图。"
            '示例：{"include":[[[100,100],[900,100],[900,900],[100,900]]],"exclude":[[[700,100],[900,100],[900,250],[700,250]]] }。'
        ),
        parameters_schema=MEASURE_CHART_PARAMETERS_SCHEMA,
        result_schema=MEASUREMENT_RESULT_SCHEMA,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        handler=measure,
    )


def _prepare_source(
    source: MeasurementSource,
    observation_scope: Mapping[str, Any] | None,
) -> PreparedMeasurementImage:
    try:
        rgb, mask = decode_scoped_image(source.image_bytes, observation_scope)
    except ObservationScopeError:
        raise ToolFailure(
            "invalid_observation_scope",
            "图像观察范围无效或不包含可观察像素。",
            field_path="/observation_scope",
        ) from None
    except ValueError:
        raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True) from None
    if rgb.shape[:2] != (source.height, source.width):
        raise ToolFailure("image_unavailable", "图像尺寸与来源记录不一致。")
    return PreparedMeasurementImage(
        source_kind=source.source_kind,
        source_id=source.source_id,
        coordinate_system=source.coordinate_system,
        width=source.width,
        height=source.height,
        rgb=rgb,
        observation_mask=mask,
    )
