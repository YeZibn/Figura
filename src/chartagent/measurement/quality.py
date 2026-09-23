"""Measurement quality audit and envelope construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from .evidence import (
    MAX_MEASUREMENT_CHECKS,
    MAX_MEASUREMENT_ISSUES,
    MAX_MEASUREMENT_REFS,
    MEASUREMENT_ISSUE_SEVERITIES,
    MEASUREMENT_TOOLS,
    _bounded_confidence,
    _json_safe,
    _now,
    _text,
    build_measurement_evidence_refs,
    measurement_session_id,
    new_attempt_id,
)
from .scope import (
    measurement_target_fingerprint,
    normalize_measurement_target,
    normalize_observation_scope,
)

def _source_scope(data: Mapping[str, Any]) -> dict[str, object] | None:
    candidates = (
        data.get("effective_scope"),
        data.get("scope"),
        data.get("plot_area"),
        data.get("plot_frame"),
        data.get("plot_region"),
    )
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            safe = _json_safe(candidate)
            return safe if isinstance(safe, dict) else None
        if isinstance(candidate, (list, tuple)) and len(candidate) >= 4:
            return {"bbox_px": [int(float(value)) for value in candidate[:4]]}
    return None


def _confidence_map(data: Mapping[str, Any]) -> dict[str, float]:
    value = data.get("confidence")
    if not isinstance(value, Mapping):
        parsed = _bounded_confidence(value)
        return {"overall": parsed} if parsed is not None else {}
    result: dict[str, float] = {}
    for key, item in list(value.items())[:8]:
        parsed = _bounded_confidence(item)
        if parsed is not None:
            result[_text(key, 48)] = parsed
    return result


def _warning_issue(warning: str) -> tuple[str, str, str, str]:
    lowered = warning.lower()
    if "focus_empty" in lowered:
        return "measurement_focus_empty", "focus", "blocking", "更换为当前 attempt 中可解析的 evidence ref 或有界区域"
    if "focus_insufficient" in lowered:
        return "measurement_focus_insufficient", "focus", "blocking", "缩小或改用能产生完整证据的当前目标区域"
    if any(token in lowered for token in ("baseline", "zero-axis", "zero baseline")):
        return "baseline_uncertain", "baseline", "blocking", "复查零基线或在当前 panel 内重新测量"
    if any(token in lowered for token in ("calibration", "标定", "axis unresolved", "坐标")):
        return "axis_calibration_uncertain", "axes", "blocking", "补充坐标轴证据后重新测量"
    if any(token in lowered for token in ("unsupported", "perspective", "3d-like", "donut", "exploded")):
        return "unsupported_geometry", "geometry", "blocking", "改用适用的观测策略或保留未解析字段"
    if any(token in lowered for token in ("partial", "incomplete", "fragmented", "coverage")):
        return "measurement_coverage_partial", "coverage", "blocking", "针对缺失区域补充测量"
    if any(token in lowered for token in ("conflict", "disagrees", "ambiguous", "uncertain", "overlap", "dense", "outlier")):
        return "measurement_evidence_conflict", "evidence", "warning", "检查冲突证据，必要时在目标区域重新测量"
    if any(token in lowered for token in ("unresolved", "unavailable", "excluded")):
        return "measurement_evidence_incomplete", "evidence", "warning", "保留未解析字段并补充相关证据"
    return "sensor_warning", "measurement", "warning", "结合视觉证据复查该测量结果"


def _issue(
    code: str,
    location: str,
    severity: str,
    message: str,
    next_action: str,
) -> dict[str, str]:
    return {
        "code": _text(code, 64),
        "location": _text(location, 120),
        "severity": severity if severity in MEASUREMENT_ISSUE_SEVERITIES else "warning",
        "message": _text(message),
        "next_action": _text(next_action, 160),
    }


def _add_issue(issues: list[dict[str, str]], item: dict[str, str]) -> None:
    identity = (item.get("code"), item.get("location"), item.get("message"))
    if any((existing.get("code"), existing.get("location"), existing.get("message")) == identity for existing in issues):
        return
    if len(issues) < MAX_MEASUREMENT_ISSUES:
        issues.append(item)


def _check(checks: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    if len(checks) >= MAX_MEASUREMENT_CHECKS:
        return
    checks.append({"name": _text(name, 64), "status": _text(status, 24), "detail": _text(detail)})


def audit_measurement(
    data: Mapping[str, Any],
    *,
    source_tool: str,
    warnings: Iterable[object] = (),
    image_count: int = 0,
    source_attachment_id: str | None = None,
    source_panel_id: str | None = None,
    source_run_id: str | None = None,
    measurement_target: Mapping[str, Any] | None = None,
    observation_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit common evidence without changing chart-specific sensor fields."""
    chart_data = data if isinstance(data, Mapping) else {}
    warning_list = [_text(item) for item in warnings if isinstance(item, str) and _text(item)]
    warning_list.extend(
        _text(item)
        for item in chart_data.get("warnings", [])
        if isinstance(item, str) and _text(item) and _text(item) not in warning_list
    )
    issues: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []
    partial = False

    if source_tool not in MEASUREMENT_TOOLS:
        _add_issue(issues, _issue("unsupported_tool", "tool", "blocking", "工具不是受支持的图表测量传感器", "改用受支持的图表测量工具"))
    if not source_attachment_id:
        _add_issue(issues, _issue("source_unattributed", "source.attachment_id", "warning", "测量缺少授权附件归因", "通过授权 attachment 重新观察"))
    _check(checks, "source_scope", "passed" if source_attachment_id else "unknown", "attachment/panel attribution is available" if source_attachment_id else "attachment attribution is unavailable")
    if image_count <= 0:
        _add_issue(issues, _issue("visual_evidence_missing", "evidence.visual", "blocking", "测量没有可关联的视觉证据", "保留像素结果前补充 overlay 或源图观察"))
        _check(checks, "visual_evidence", "failed", "no bounded visual observation was attached")
    else:
        _check(checks, "visual_evidence", "passed", f"{min(image_count, 4)} bounded visual observation(s) attached")

    for warning in warning_list:
        code, location, severity, next_action = _warning_issue(warning)
        _add_issue(issues, _issue(code, location, severity, warning, next_action))

    if source_tool == "measure_bars":
        bars = chart_data.get("bars")
        baseline = chart_data.get("baseline")
        valid_bars = isinstance(bars, list) and bool(bars)
        _check(checks, "geometry", "passed" if valid_bars else "failed", "bar candidates are present" if valid_bars else "no bar candidates are present")
        if not valid_bars:
            _add_issue(issues, _issue("bar_geometry_missing", "bars", "blocking", "没有可用的柱体几何", "在当前 panel 内重新测量柱体"))
        if not isinstance(baseline, Mapping):
            _add_issue(issues, _issue("baseline_missing", "baseline", "blocking", "没有可用的零基线", "复查零基线后重新测量"))
            _check(checks, "baseline", "failed", "baseline is unavailable")
        else:
            _check(checks, "baseline", "passed", "baseline candidate is available")
        measured = [
            item.get("measure", {}).get("ratio")
            for item in bars
            if isinstance(item, Mapping) and isinstance(item.get("measure"), Mapping)
        ] if isinstance(bars, list) else []
        if measured and any(value is None for value in measured):
            partial = True
            _add_issue(issues, _issue("bar_values_partial", "bars.measure", "blocking", "部分柱体没有可用的测量值", "针对缺失柱体区域重新测量"))
            _check(checks, "coverage", "partial", "one or more bars have no ratio")
        elif valid_bars:
            _check(checks, "coverage", "passed", "all detected bars carry a ratio")
    elif source_tool in {"extract_line_series", "extract_scatter_points"}:
        series = chart_data.get("series")
        has_series = isinstance(series, list) and bool(series)
        frame = chart_data.get("plot_frame") or chart_data.get("frame")
        _check(checks, "geometry", "passed" if has_series else "failed", "series geometry is present" if has_series else "no series geometry is present")
        if not has_series:
            _add_issue(issues, _issue("series_geometry_missing", "series", "blocking", "没有可用的系列几何", "在当前 panel 内重新测量系列"))
        if not isinstance(frame, Mapping) or not frame.get("x_axis") or not frame.get("y_axis"):
            _add_issue(issues, _issue("cartesian_frame_incomplete", "plot_frame", "blocking", "笛卡尔绘图区或坐标轴不完整", "补充坐标轴/绘图区证据后重新测量"))
            _check(checks, "geometry_frame", "failed", "x/y axis geometry is incomplete")
        else:
            _check(checks, "geometry_frame", "passed", "x/y axis geometry is present")
        if source_tool == "extract_line_series":
            complete = all(
                isinstance(item, Mapping) and isinstance(item.get("trace"), Mapping) and bool(item["trace"].get("polyline_px"))
                for item in series
            ) if isinstance(series, list) else False
        else:
            complete = isinstance(chart_data.get("points"), list) and bool(chart_data.get("points"))
        if not complete:
            partial = True
            _add_issue(issues, _issue("series_coverage_partial", "series", "blocking", "系列或采样点证据不完整", "针对缺失系列或区域重新测量"))
            _check(checks, "coverage", "partial", "series geometry is incomplete")
        else:
            _check(checks, "coverage", "passed", "series geometry is populated")
    elif source_tool == "extract_pie_slices":
        sectors = chart_data.get("sectors")
        totals = chart_data.get("totals")
        has_sectors = isinstance(sectors, list) and bool(sectors)
        _check(checks, "geometry", "passed" if has_sectors else "failed", "sector geometry is present" if has_sectors else "no sector geometry is present")
        if not has_sectors:
            _add_issue(issues, _issue("sector_geometry_missing", "sectors", "blocking", "没有可用的饼图扇区几何", "在当前 panel 内重新测量饼图"))
        consistent = isinstance(totals, Mapping) and bool(totals.get("consistent"))
        if not consistent:
            _add_issue(issues, _issue("sector_total_inconsistent", "totals", "blocking", "扇区角度或比例总和未通过一致性检查", "复查圆心、半径和扇区边界后重新测量"))
            _check(checks, "coverage", "failed", "sector totals are not consistent")
        else:
            _check(checks, "coverage", "passed", "sector totals are consistent")

    for warning in warning_list:
        if any(token in warning.lower() for token in ("partial", "incomplete", "fragmented", "coverage", "unresolved", "unsupported")):
            partial = True
            break
    blocking = any(item.get("severity") == "blocking" for item in issues)
    confidence = _confidence_map(chart_data)
    if source_tool not in MEASUREMENT_TOOLS:
        status = "unsupported"
    elif blocking or partial:
        status = "partial"
    elif not source_run_id:
        status = "provisional"
    else:
        status = "complete"

    panel = _text(source_panel_id, 160) or None
    attachment = _text(source_attachment_id, 160) or None
    session_id = measurement_session_id(source_run_id, attachment, panel)
    attempt_id = new_attempt_id()
    scope = _source_scope(chart_data)
    effective_scope = _json_safe(chart_data.get("effective_scope")) if isinstance(chart_data.get("effective_scope"), Mapping) else scope
    if not isinstance(effective_scope, dict):
        effective_scope = scope
    target = normalize_measurement_target(measurement_target)
    if isinstance(observation_scope, Mapping) and (
        observation_scope.get("applied") is not None
        or observation_scope.get("status") in {"applied", "rejected", "focus_empty"}
    ):
        # The authorized adapter has already converted the model request into
        # local/source pixel regions. Re-normalizing that envelope as a fresh
        # panel_norm request would discard its bbox_px fields.
        requested_scope = _json_safe(dict(observation_scope))
        requested_scope = requested_scope if isinstance(requested_scope, dict) else None
    else:
        requested_scope = normalize_observation_scope(observation_scope)
    if target is not None:
        target["panel_id"] = target.get("panel_id") or panel
        target["parent_attempt_id"] = target.get("parent_attempt_id")
    evidence_refs = build_measurement_evidence_refs(chart_data, source_tool=source_tool)
    focus = chart_data.get("focus")
    focus_payload = _json_safe(focus) if isinstance(focus, Mapping) else None
    captions: list[str] = []
    return {
        "status": status,
        "effective_scope": effective_scope,
        "reference": {
            "session_id": session_id,
            "attempt_id": attempt_id,
            "attachment_id": attachment,
            "panel_id": panel,
        },
        "attempt": {
            "attempt_id": attempt_id,
            "session_id": session_id,
            "run_id": _text(source_run_id, 128) or None,
            "parent_attempt_id": None,
            "tool": _text(source_tool, 80),
            "scope": scope,
            "effective_scope": effective_scope,
            "observation_scope": requested_scope,
            "target": target,
            "target_fingerprint": measurement_target_fingerprint(target, tool=source_tool),
            "created_at": _now(),
        },
        "target": target,
        "observation_scope": requested_scope,
        "source": {
            "attachment_id": attachment,
            "panel_id": panel,
            "scope": scope,
            "effective_scope": effective_scope,
            "observation_scope": requested_scope,
        },
        "quality": {
            "confidence": confidence,
            "checks": checks[:MAX_MEASUREMENT_CHECKS],
            "issues": issues[:MAX_MEASUREMENT_ISSUES],
            "warnings": warning_list[:12],
            "blocking": blocking,
        },
        "evidence": {
            "visual_count": max(0, min(int(image_count), 4)),
            "captions": captions,
            "refs": evidence_refs,
            "focus": focus_payload,
            "effective_scope": effective_scope,
        },
        "execution": {
            "status": "completed" if source_tool in MEASUREMENT_TOOLS else "failed",
        },
        "diagnostics": {
            "status": status,
            "warnings": warning_list[:12],
            "issue_count": len(issues[:MAX_MEASUREMENT_ISSUES]),
        },
    }


def attach_measurement_quality(
    data: Mapping[str, Any],
    *,
    source_tool: str,
    warnings: Iterable[object] = (),
    image_count: int = 0,
    source_attachment_id: str | None = None,
    source_panel_id: str | None = None,
    source_run_id: str | None = None,
    parent_attempt_id: str | None = None,
    measurement_target: Mapping[str, Any] | None = None,
    observation_scope: Mapping[str, Any] | None = None,
    captions: Iterable[object] = (),
) -> dict[str, Any]:
    """Copy chart data and attach a fresh bounded measurement envelope."""
    result = dict(data)
    envelope = audit_measurement(
        result,
        source_tool=source_tool,
        warnings=warnings,
        image_count=image_count,
        source_attachment_id=source_attachment_id,
        source_panel_id=source_panel_id,
        source_run_id=source_run_id,
        measurement_target=measurement_target,
        observation_scope=observation_scope,
    )
    attempt = dict(envelope.get("attempt") or {})
    if isinstance(parent_attempt_id, str) and parent_attempt_id:
        attempt["parent_attempt_id"] = parent_attempt_id[:160]
        envelope["attempt"] = attempt
        if isinstance(envelope.get("target"), dict):
            target = dict(envelope["target"])
            target["parent_attempt_id"] = parent_attempt_id[:160]
            envelope["target"] = target
            attempt["target"] = target
            attempt["target_fingerprint"] = measurement_target_fingerprint(target, tool=attempt.get("tool"))
            envelope["attempt"] = attempt
    evidence = dict(envelope.get("evidence") or {})
    evidence["captions"] = [_text(item, 160) for item in captions if _text(item, 160)][:4]
    envelope["evidence"] = evidence
    result["measurement"] = envelope
    return result


def measurement_from_data(data: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, Mapping):
        return None
    value = data.get("measurement")
    return dict(value) if isinstance(value, Mapping) else None
