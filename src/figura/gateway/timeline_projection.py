"""Safe, read-only projections of durable Figura tool facts."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping

from figura.agent.execution_resources import (
    AttachmentContent,
    ChartFigureContent,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunStatus, ToolFactKind
from figura.runtime.records import (
    RunState,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolResultFact,
)
from figura.tools import ToolOutcome


_TOOL_LABELS = {
    "load_image": "读取图像",
    "decompose_chart_image": "拆分图像",
    "extract_text": "提取文字",
    "measure_chart": "测量图表",
    "assemble_chart_figure": "装配图表",
    "render_chart_figure": "绘制图表",
}
_OBSERVATION_TOOLS = frozenset(
    {"extract_text", "measure_chart"}
)
_ERROR_LABELS = {
    "image_not_available": "图像不可用",
    "image_unavailable": "图像暂时无法读取",
    "invalid_region": "图像区域无效",
    "invalid_observation_scope": "观察范围无效",
    "figure_reference_not_found": "Figure 引用不可用",
    "measurement_reference_not_found": "测量引用不可用",
    "measurement_reference_not_succeeded": "测量尚未成功",
    "chart_render_failed": "图表无法绘制",
}
_MAX_SUMMARY = 180


def run_timeline(state: RunState, owns_execution: bool) -> dict[str, object]:
    calls, attempts, results = _tool_facts(state)
    steps = []
    for sequence, call_fact in sorted(calls.items()):
        call = call_fact.payload
        attempt_facts = attempts.get(sequence, ())
        result_fact = results.get(sequence)
        status = _call_status(state, attempt_facts, result_fact, owns_execution)
        updated_at = (
            result_fact.created_at
            if result_fact is not None
            else attempt_facts[-1].created_at
            if attempt_facts
            else call_fact.created_at
        )
        steps.append(
            {
                "callId": call.call_id,
                "toolSequence": sequence,
                "toolName": call.tool_name,
                "createdAt": call_fact.created_at,
                "updatedAt": updated_at,
                "status": status,
                "summary": _step_summary(call.tool_name, status, result_fact),
            }
        )
    return {"runId": state.run.run_id, "steps": steps}


def tool_call_detail(
    state: RunState,
    call_id: str,
    execution: RunExecutionState,
    owns_execution: bool,
) -> dict[str, object]:
    calls, attempts, results = _tool_facts(state)
    call_entry = next(
        ((sequence, fact) for sequence, fact in calls.items() if fact.payload.call_id == call_id),
        None,
    )
    if call_entry is None:
        raise RunError(RunErrorCode.RUN_NOT_FOUND)
    sequence, call_fact = call_entry
    call = call_fact.payload
    attempt_facts = attempts.get(sequence, ())
    result_fact = results.get(sequence)
    status = _call_status(state, attempt_facts, result_fact, owns_execution)
    updated_at = (
        result_fact.created_at
        if result_fact
        else attempt_facts[-1].created_at
        if attempt_facts
        else call_fact.created_at
    )
    base: dict[str, object] = {
        "runId": state.run.run_id,
        "callId": call.call_id,
        "toolName": call.tool_name,
        "status": status,
        "createdAt": call_fact.created_at,
        "updatedAt": updated_at,
    }
    if call.tool_name not in _TOOL_LABELS:
        return base

    arguments = _arguments(call.arguments_json)
    source = _source_for_call(call, arguments, execution)
    base.update(
        {
            "argumentSummary": _argument_summary(call, arguments, source, execution),
            "resultSummary": _result_summary(call.tool_name, result_fact),
            "attempts": [_attempt_summary(attempt, result_fact) for attempt in attempt_facts],
            "errorSummary": _error_summary(result_fact),
            "source": source,
            "observationAvailable": _observation_available(
                state.run.run_id, call, result_fact, execution
            ),
        }
    )
    return base


def observation_ref(
    state: RunState, call_id: str, execution: RunExecutionState
) -> ToolResourceRef:
    calls, _attempts, results = _tool_facts(state)
    entry = next(
        ((sequence, fact) for sequence, fact in calls.items() if fact.payload.call_id == call_id),
        None,
    )
    if entry is None:
        raise RunError(RunErrorCode.RUN_NOT_FOUND)
    sequence, call_fact = entry
    call = call_fact.payload
    result_fact = results.get(sequence)
    if (
        call.tool_name not in _OBSERVATION_TOOLS
        or result_fact is None
        or not isinstance(result_fact.payload, ToolResultFact)
        or result_fact.payload.outcome is not ToolOutcome.SUCCEEDED
    ):
        raise RunError(RunErrorCode.RUN_NOT_FOUND)
    kind = "ocr" if call.tool_name == "extract_text" else "measurement"
    ref = ToolResourceRef(kind, state.run.run_id, call.call_id)
    resource = execution.get(ref)
    if (
        not isinstance(resource.content, (OcrContent, MeasurementContent))
        or resource.content.outcome is not ToolOutcome.SUCCEEDED
        or resource.content.source_ref is None
    ):
        raise RunError(RunErrorCode.RUN_NOT_FOUND)
    execution.get(resource.content.source_ref)
    return ref


def _tool_facts(
    state: RunState,
) -> tuple[
    dict[int, ToolExecutionFact],
    dict[int, tuple[ToolExecutionFact, ...]],
    dict[int, ToolExecutionFact],
]:
    calls: dict[int, ToolExecutionFact] = {}
    attempt_lists: dict[int, list[ToolExecutionFact]] = defaultdict(list)
    results: dict[int, ToolExecutionFact] = {}
    for fact in state.tool_facts:
        if fact.fact_kind is ToolFactKind.TOOL_CALL and isinstance(fact.payload, ToolCallFact):
            if fact.tool_sequence in calls:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            calls[fact.tool_sequence] = fact
        elif (
            fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
            and isinstance(fact.payload, ToolAttemptStartedFact)
        ):
            attempt_lists[fact.payload.tool_call_sequence].append(fact)
        elif fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(
            fact.payload, ToolResultFact
        ):
            if fact.payload.tool_call_sequence in results:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            results[fact.payload.tool_call_sequence] = fact
    if set(attempt_lists) - set(calls) or set(results) - set(calls):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    for sequence, call_fact in calls.items():
        call = call_fact.payload
        call_attempts = attempt_lists.get(sequence, ())
        if any(
            not isinstance(fact.payload, ToolAttemptStartedFact)
            or fact.payload.tool_call_sequence != sequence
            or fact.payload.call_id != call.call_id
            for fact in call_attempts
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        result_fact = results.get(sequence)
        if result_fact is not None:
            result = result_fact.payload
            if (
                not isinstance(result, ToolResultFact)
                or result.tool_call_sequence != sequence
                or result.call_id != call.call_id
                or result.tool_name != call.tool_name
                or not any(
                    isinstance(fact.payload, ToolAttemptStartedFact)
                    and fact.payload.attempt_id == result.attempt_id
                    for fact in call_attempts
                )
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return calls, {key: tuple(value) for key, value in attempt_lists.items()}, results


def _call_status(
    state: RunState,
    attempts: tuple[ToolExecutionFact, ...],
    result_fact: ToolExecutionFact | None,
    owns_execution: bool,
) -> str:
    if result_fact is not None:
        result = result_fact.payload
        if not isinstance(result, ToolResultFact):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return "completed" if result.outcome is ToolOutcome.SUCCEEDED else "failed"
    if not attempts:
        return "pending" if state.run.status is RunStatus.RUNNING else "not_started"
    if state.run.status is not RunStatus.RUNNING:
        return "unknown"
    return "running" if owns_execution else "needs_reconciliation"


def _step_summary(
    tool_name: str, status: str, result_fact: ToolExecutionFact | None
) -> str:
    label = _TOOL_LABELS.get(tool_name, tool_name)
    if result_fact is None:
        return _short(f"{label} · {_status_label(status)}")
    result = result_fact.payload
    if not isinstance(result, ToolResultFact):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if result.outcome is ToolOutcome.FAILED:
        return _short(f"{label} · {_error_summary(result_fact) or '执行失败'}")
    summary = _result_summary(tool_name, result_fact)
    return _short(f"{label} · {summary}" if summary else f"{label} · 已完成")


def _result_summary(tool_name: str, result_fact: ToolExecutionFact | None) -> str:
    if result_fact is None:
        return "尚无已提交结果"
    result = result_fact.payload
    if not isinstance(result, ToolResultFact):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if result.outcome is ToolOutcome.FAILED:
        return _error_summary(result_fact) or "执行失败"
    value = result.result
    if not isinstance(value, Mapping):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if tool_name == "load_image":
        return _dimensions(value, "已读取图像")
    if tool_name == "decompose_chart_image":
        panels = value.get("panels")
        names = (
            [
                item.get("name")
                for item in panels
                if isinstance(item, Mapping) and isinstance(item.get("name"), str)
            ]
            if isinstance(panels, (tuple, list))
            else []
        )
        return (
            f"拆分为 {len(panels)} 个 Panel"
            + (f"：{_join_labels(names)}" if names else "")
            if isinstance(panels, (tuple, list))
            else "拆分已完成"
        )
    if tool_name == "extract_text":
        snippets = value.get("snippets")
        count = len(snippets) if isinstance(snippets, (tuple, list)) else 0
        availability = "结果可用" if value.get("available") is True else "无可用结果"
        suffix = "（结果已截断）" if value.get("truncated") is True else ""
        return f"{availability} · {count} 条文字记录{suffix}"
    if tool_name == "measure_chart":
        chart_type = value.get("chart_type")
        observations = value.get("observations")
        if not isinstance(observations, Mapping):
            return f"{_measurement_status(value.get('status'))} · 观察结构不可用"
        family_labels = {
            "bar": ("柱状图", "bars", "个柱体"),
            "line": ("折线图", "series", "个系列"),
            "scatter": ("散点/气泡图", "series", "个系列"),
            "pie": ("饼图/甜甜圈图", "sectors", "个扇区"),
            "area": ("面积图", "series", "个系列"),
            "histogram": ("直方图", "bins", "个区间"),
            "box_plot": ("箱线图", "groups", "个分组"),
            "radar": ("雷达图", "spokes", "个维度"),
            "heatmap": ("热力图", "cells", "个单元格"),
            "treemap": ("矩形树图", "nodes", "个矩形"),
        }
        family = family_labels.get(chart_type) if isinstance(chart_type, str) else None
        if family is None:
            return f"{_measurement_status(value.get('status'))} · 图表家族未知"
        label, key, item_label = family
        items = observations.get(key)
        if key == "series":
            series = items if isinstance(items, (tuple, list)) else ()
            item_count = len(series)
            subkey = "points" if chart_type in {"line", "scatter"} else "segments"
            if chart_type == "radar":
                subkey = "vertices"
            detail_count = sum(
                len(item.get(subkey, ()))
                for item in series
                if isinstance(item, Mapping) and isinstance(item.get(subkey, ()), (tuple, list))
            )
            measure = f"{item_count} 个系列、{detail_count} 个观察项"
        else:
            count = len(items) if isinstance(items, (tuple, list)) else 0
            measure = f"{count} {item_label}"
        return f"{_measurement_status(value.get('status'))} · {label} · {measure}"
    if tool_name == "assemble_chart_figure":
        title = value.get("title")
        charts = value.get("charts")
        count = len(charts) if isinstance(charts, (tuple, list)) else 0
        chart_labels = (
            [
                _safe_word(chart.get("title"), "未命名子图")
                + "（"
                + _safe_word(chart.get("chart_type"), "图表类型未知")
                + "）"
                for chart in charts
                if isinstance(chart, Mapping)
            ]
            if isinstance(charts, (tuple, list))
            else []
        )
        suffix = "：" + _join_labels(chart_labels) if chart_labels else ""
        return _short(f"{_safe_word(title, 'Figure')} · {count} 个子图{suffix}")
    if tool_name == "render_chart_figure":
        return _dimensions(value, "已生成 PNG")
    return "已完成"


def _attempt_summary(
    attempt_fact: ToolExecutionFact, result_fact: ToolExecutionFact | None
) -> dict[str, object]:
    attempt = attempt_fact.payload
    if not isinstance(attempt, ToolAttemptStartedFact):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    result = result_fact.payload if result_fact else None
    matches_result = isinstance(result, ToolResultFact) and result.attempt_id == attempt.attempt_id
    outcome = result.outcome if matches_result else None
    return {
        "attemptNumber": attempt.attempt_number,
        "startedAt": attempt_fact.created_at,
        "finishedAt": result_fact.created_at if matches_result and result_fact else None,
        "status": (
            "completed"
            if outcome is ToolOutcome.SUCCEEDED
            else "failed"
            if outcome is ToolOutcome.FAILED
            else "unknown"
            if result_fact
            else "running"
        ),
        "errorSummary": (
            _error_summary(result_fact)
            if matches_result and outcome is ToolOutcome.FAILED
            else None
        ),
    }


def _argument_summary(
    call: ToolCallFact,
    arguments: Mapping[str, object],
    source: dict[str, object] | None,
    execution: RunExecutionState,
) -> str:
    label = _TOOL_LABELS[call.tool_name]
    source_label = _safe_word(source.get("name") if source else None, "图像来源")
    if call.tool_name == "decompose_chart_image":
        panels = arguments.get("panels")
        count = len(panels) if isinstance(panels, (tuple, list)) else 0
        return _short(f"将「{source_label}」拆分为 {count} 个 Panel")
    if call.tool_name in _OBSERVATION_TOOLS:
        scope = arguments.get("observation_scope")
        if isinstance(scope, Mapping):
            included = scope.get("include")
            excluded = scope.get("exclude")
            include_count = len(included) if isinstance(included, (tuple, list)) else 0
            exclude_count = len(excluded) if isinstance(excluded, (tuple, list)) else 0
            scope_summary = f"；范围包含 {include_count} 区域、排除 {exclude_count} 区域"
        else:
            scope_summary = "；范围为完整图像"
        return _short(f"从「{source_label}」执行{label}{scope_summary}")
    if call.tool_name == "load_image":
        return _short(f"读取「{source_label}」")
    if call.tool_name == "assemble_chart_figure":
        try:
            resource = execution.get(
                ToolResourceRef("chart_figure", execution.run_id, call.call_id)
            )
        except RunError:
            return "装配一个多图表画布"
        content = resource.content
        if isinstance(content, ChartFigureContent) and content.result:
            return _short(f"装配 Figure「{content.result.figure.title}」")
        return "装配一个多图表画布"
    if call.tool_name == "render_chart_figure":
        reference = arguments.get("figure_ref")
        if isinstance(reference, Mapping):
            run_id, referenced_call = reference.get("run_id"), reference.get("call_id")
            if isinstance(run_id, str) and isinstance(referenced_call, str):
                try:
                    resource = execution.get(ToolResourceRef("chart_figure", run_id, referenced_call))
                except RunError:
                    return "绘制已装配的图表画布"
                content = resource.content
                if isinstance(content, ChartFigureContent) and content.result:
                    return _short(f"绘制 Figure「{content.result.figure.title}」")
        return "绘制已装配的图表画布"
    return label


def _source_for_call(
    call: ToolCallFact,
    arguments: Mapping[str, object],
    execution: RunExecutionState,
) -> dict[str, object] | None:
    if call.tool_name == "decompose_chart_image":
        kind, source_id = "attachment", arguments.get("attachment_id")
    elif call.tool_name in {"load_image", *_OBSERVATION_TOOLS}:
        kind, source_id = arguments.get("source_kind"), arguments.get("source_id")
    else:
        return None
    if kind not in {"attachment", "panel"} or not isinstance(source_id, str):
        return None
    try:
        resource = execution.get(ImageResourceRef(kind, source_id))
    except RunError:
        return None
    content = resource.content
    if isinstance(content, AttachmentContent):
        name = content.filename
    elif isinstance(content, PanelContent):
        name = content.name
    else:
        return None
    return {"kind": kind, "id": source_id, "name": _short(name, 96)}


def _observation_available(
    run_id: str,
    call: ToolCallFact,
    result_fact: ToolExecutionFact | None,
    execution: RunExecutionState,
) -> bool:
    if call.tool_name not in _OBSERVATION_TOOLS or result_fact is None:
        return False
    result = result_fact.payload
    if not isinstance(result, ToolResultFact) or result.outcome is not ToolOutcome.SUCCEEDED:
        return False
    kind = "ocr" if call.tool_name == "extract_text" else "measurement"
    try:
        resource = execution.get(ToolResourceRef(kind, run_id, call.call_id))
    except RunError:
        return False
    content = resource.content
    return (
        isinstance(content, (OcrContent, MeasurementContent))
        and content.outcome is ToolOutcome.SUCCEEDED
        and content.source_ref is not None
    )


def _arguments(value: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    if not isinstance(parsed, dict):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return parsed


def _error_summary(result_fact: ToolExecutionFact | None) -> str | None:
    if (
        result_fact is None
        or not isinstance(result_fact.payload, ToolResultFact)
        or result_fact.payload.error is None
    ):
        return None
    return _ERROR_LABELS.get(result_fact.payload.error.code, "工具执行失败")


def _dimensions(value: Mapping[str, object], prefix: str) -> str:
    width, height = value.get("width"), value.get("height")
    if type(width) is int and type(height) is int and width > 0 and height > 0:
        return f"{prefix} · {width} × {height}"
    size = value.get("image_size")
    if isinstance(size, Mapping):
        width, height = size.get("width"), size.get("height")
        if type(width) is int and type(height) is int and width > 0 and height > 0:
            return f"{prefix} · {width} × {height}"
    return prefix


def _join_labels(values: list[str]) -> str:
    return "、".join(_short(value, 32) for value in values[:3]) + ("等" if len(values) > 3 else "")


def _safe_word(value: object, fallback: str) -> str:
    return _short(value, 64) if isinstance(value, str) and value.strip() else fallback


def _measurement_status(value: object) -> str:
    return {
        "measured": "已测量",
        "partial": "部分测量",
        "no_evidence": "没有测量证据",
        "unsupported": "图表不受支持",
    }.get(value, "测量状态未知")


def _short(value: str, limit: int = _MAX_SUMMARY) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


def _status_label(status: str) -> str:
    return {
        "pending": "等待执行",
        "running": "运行中",
        "needs_reconciliation": "等待结果核对",
        "unknown": "状态未知",
        "completed": "已完成",
        "failed": "失败",
        "not_started": "未执行",
    }.get(status, "状态未知")
