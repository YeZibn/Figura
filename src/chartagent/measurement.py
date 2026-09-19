"""Bounded lifecycle and quality helpers for chart measurements.

The observation sensors intentionally keep their chart-specific payloads.  This
module only owns the small, serializable envelope around those payloads so a
measurement can be inspected, persisted, and rejected before it is used as a
deterministic ChartSpec source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Iterable
from uuid import uuid4


MEASUREMENT_TOOLS = frozenset(
    {
        "measure_bars",
        "extract_line_series",
        "extract_pie_slices",
        "extract_scatter_points",
    }
)
MEASUREMENT_STATUSES = frozenset(
    {
        "provisional",
        "accepted",
        "remeasure_required",
        "partial",
        "unsupported",
        "failed",
    }
)
MEASUREMENT_ISSUE_SEVERITIES = frozenset({"blocking", "warning", "info"})
MAX_MEASUREMENT_ATTEMPTS = 8
MAX_MEASUREMENT_ISSUES = 16
MAX_MEASUREMENT_CHECKS = 16
MAX_MEASUREMENT_TEXT = 240
MAX_MEASUREMENT_SCOPE_KEYS = 16


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, limit: int = MAX_MEASUREMENT_TEXT) -> str:
    return str(value or "").strip()[:limit]


def _bounded_confidence(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return max(0.0, min(1.0, parsed))


def _json_safe(value: object, *, depth: int = 0) -> object:
    """Return a small JSON-safe value without paths or image/provider bytes."""
    if depth > 5:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in list(value.items())[:MAX_MEASUREMENT_SCOPE_KEYS]:
            name = str(key)
            lowered = name.lower()
            if lowered in {
                "path",
                "image_path",
                "local_path",
                "canonical_path",
                "bytes",
                "image_bytes",
                "raw_response",
                "raw_provider_response",
                "provider_payload",
            } or lowered.endswith("_path"):
                continue
            result[name[:80]] = _json_safe(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:MAX_MEASUREMENT_SCOPE_KEYS]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            return None
        return value
    return _text(value, 120)


def measurement_session_id(run_id: str | None, attachment_id: str | None, panel_id: str | None) -> str:
    """Create a stable opaque session key for one run/source scope."""
    seed = "|".join(
        (
            _text(run_id, 128) or "unbound-run",
            _text(attachment_id, 160) or "unknown-attachment",
            _text(panel_id, 160) or "__source__",
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"ms_{digest}"


def new_attempt_id() -> str:
    return f"matt_{uuid4().hex}"


def _source_scope(data: Mapping[str, Any]) -> dict[str, object] | None:
    candidates = (
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
    elif blocking:
        status = "remeasure_required"
    elif partial:
        status = "partial"
    elif not source_run_id:
        status = "provisional"
    else:
        status = "accepted"

    panel = _text(source_panel_id, 160) or None
    attachment = _text(source_attachment_id, 160) or None
    session_id = measurement_session_id(source_run_id, attachment, panel)
    attempt_id = new_attempt_id()
    scope = _source_scope(chart_data)
    captions: list[str] = []
    return {
        "status": status,
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
            "created_at": _now(),
        },
        "source": {
            "attachment_id": attachment,
            "panel_id": panel,
            "scope": scope,
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
    )
    attempt = dict(envelope.get("attempt") or {})
    if isinstance(parent_attempt_id, str) and parent_attempt_id:
        attempt["parent_attempt_id"] = parent_attempt_id[:160]
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


@dataclass(frozen=True)
class MeasurementAttempt:
    attempt_id: str
    session_id: str
    run_id: str | None
    attachment_id: str | None
    panel_id: str | None
    parent_attempt_id: str | None
    tool: str
    status: str
    scope: dict[str, Any] | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_measurement(cls, value: Mapping[str, Any]) -> "MeasurementAttempt | None":
        reference = value.get("reference") if isinstance(value.get("reference"), Mapping) else {}
        attempt = value.get("attempt") if isinstance(value.get("attempt"), Mapping) else {}
        source = value.get("source") if isinstance(value.get("source"), Mapping) else {}
        attempt_id = _text(reference.get("attempt_id") or attempt.get("attempt_id"), 160)
        session_id = _text(reference.get("session_id") or attempt.get("session_id"), 160)
        if not attempt_id or not session_id:
            return None
        status = _text(value.get("status"), 32)
        if status not in MEASUREMENT_STATUSES:
            status = "provisional"
        quality = _json_safe(value.get("quality") or {})
        evidence = _json_safe(value.get("evidence") or {})
        scope = _json_safe(attempt.get("scope") or source.get("scope"))
        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            run_id=_text(attempt.get("run_id"), 128) or None,
            attachment_id=_text(reference.get("attachment_id") or source.get("attachment_id"), 160) or None,
            panel_id=_text(reference.get("panel_id") or source.get("panel_id"), 160) or None,
            parent_attempt_id=_text(attempt.get("parent_attempt_id"), 160) or None,
            tool=_text(attempt.get("tool"), 80),
            status=status,
            scope=scope if isinstance(scope, dict) else None,
            quality=quality if isinstance(quality, dict) else {},
            evidence=evidence if isinstance(evidence, dict) else {},
            created_at=_text(attempt.get("created_at"), 64) or _now(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementAttempt | None":
        if not isinstance(value, Mapping):
            return None
        quality = _json_safe(value.get("quality") or {})
        evidence = _json_safe(value.get("evidence") or {})
        scope = _json_safe(value.get("scope"))
        attempt_id = _text(value.get("attempt_id"), 160)
        session_id = _text(value.get("session_id"), 160)
        if not attempt_id or not session_id:
            return None
        status = _text(value.get("status"), 32)
        if status not in MEASUREMENT_STATUSES:
            status = "provisional"
        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            run_id=_text(value.get("run_id"), 128) or None,
            attachment_id=_text(value.get("attachment_id"), 160) or None,
            panel_id=_text(value.get("panel_id"), 160) or None,
            parent_attempt_id=_text(value.get("parent_attempt_id"), 160) or None,
            tool=_text(value.get("tool"), 80),
            status=status,
            scope=scope if isinstance(scope, dict) else None,
            quality=quality if isinstance(quality, dict) else {},
            evidence=evidence if isinstance(evidence, dict) else {},
            created_at=_text(value.get("created_at"), 64) or _now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
            "parent_attempt_id": self.parent_attempt_id,
            "tool": self.tool,
            "status": self.status,
            "scope": _json_safe(self.scope),
            "quality": _json_safe(self.quality),
            "evidence": _json_safe(self.evidence),
            "created_at": self.created_at,
        }

    def reference(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
        }


@dataclass
class MeasurementSession:
    session_id: str
    run_id: str | None
    attachment_id: str | None
    panel_id: str | None
    attempts: list[MeasurementAttempt] = field(default_factory=list)
    current_attempt_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementSession | None":
        session_id = _text(value.get("session_id"), 160)
        if not session_id:
            return None
        raw_attempts = value.get("attempts") if isinstance(value.get("attempts"), list) else []
        attempts: list[MeasurementAttempt] = []
        for raw in raw_attempts[:MAX_MEASUREMENT_ATTEMPTS]:
            if not isinstance(raw, Mapping):
                continue
            attempt = MeasurementAttempt.from_dict(raw)
            if attempt is not None and attempt.session_id == session_id:
                attempts.append(attempt)
        session = cls(
            session_id=session_id,
            run_id=_text(value.get("run_id"), 128) or None,
            attachment_id=_text(value.get("attachment_id"), 160) or None,
            panel_id=_text(value.get("panel_id"), 160) or None,
            attempts=attempts,
            current_attempt_id=_text(value.get("current_attempt_id"), 160) or None,
        )
        if session.current_attempt_id and not any(item.attempt_id == session.current_attempt_id for item in attempts):
            session.current_attempt_id = attempts[-1].attempt_id if attempts else None
        return session

    def add_attempt(self, attempt: MeasurementAttempt) -> bool:
        if attempt.session_id != self.session_id:
            return False
        if self.attachment_id and attempt.attachment_id and self.attachment_id != attempt.attachment_id:
            return False
        if self.panel_id and attempt.panel_id and self.panel_id != attempt.panel_id:
            return False
        if any(item.attempt_id == attempt.attempt_id for item in self.attempts):
            return False
        self.attempts.append(attempt)
        self.attempts = self.attempts[-MAX_MEASUREMENT_ATTEMPTS:]
        self.current_attempt_id = attempt.attempt_id
        return True

    def accepted_attempt(self) -> MeasurementAttempt | None:
        for attempt in reversed(self.attempts):
            if attempt.attempt_id == self.current_attempt_id and attempt.status == "accepted":
                issues = attempt.quality.get("issues", []) if isinstance(attempt.quality, Mapping) else []
                if not any(isinstance(item, Mapping) and item.get("severity") == "blocking" for item in issues):
                    return attempt
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
            "current_attempt_id": self.current_attempt_id,
            "attempts": [item.to_dict() for item in self.attempts[-MAX_MEASUREMENT_ATTEMPTS:]],
        }


def sessions_from_state(value: object) -> dict[str, MeasurementSession]:
    result: dict[str, MeasurementSession] = {}
    if isinstance(value, Mapping):
        values = list(value.values())
    elif isinstance(value, list):
        values = value
    else:
        values = []
    for item in values[:32]:
        if not isinstance(item, Mapping):
            continue
        session = MeasurementSession.from_dict(item)
        if session is not None:
            result[session.session_id] = session
    return result


def sessions_to_state(sessions: Mapping[str, MeasurementSession]) -> dict[str, Any]:
    return {
        key: session.to_dict()
        for key, session in list(sessions.items())[:32]
        if isinstance(session, MeasurementSession)
    }


def register_measurement(sessions: dict[str, MeasurementSession], data: Mapping[str, Any]) -> MeasurementSession | None:
    measurement = measurement_from_data(data)
    if measurement is None:
        return None
    attempt = MeasurementAttempt.from_measurement(measurement)
    if attempt is None:
        return None
    session = sessions.get(attempt.session_id)
    if session is None:
        session = MeasurementSession(
            session_id=attempt.session_id,
            run_id=attempt.run_id,
            attachment_id=attempt.attachment_id,
            panel_id=attempt.panel_id,
        )
        sessions[session.session_id] = session
    session.add_attempt(attempt)
    while len(sessions) > 32:
        sessions.pop(next(iter(sessions)))
    return session


def measurement_gate(
    reference: object,
    context: Mapping[str, Any] | None,
    *,
    expected_attachment_id: str | None = None,
    expected_panel_id: str | None = None,
    location: str = "measurement_ref",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate a model-provided reference against code-owned session state."""
    if not isinstance(reference, Mapping):
        return None, {
            "status": "blocked",
            "code": "measurement_reference_invalid",
            "location": location,
            "message": "measurement_ref must be a structured server-issued reference",
            "next_action": "重新读取当前测量观察并使用其 measurement.reference",
        }
    required = ("session_id", "attempt_id", "attachment_id")
    if any(not isinstance(reference.get(key), str) or not str(reference.get(key)).strip() for key in required):
        return None, {
            "status": "blocked",
            "code": "measurement_reference_incomplete",
            "location": location,
            "message": "measurement_ref is missing a required source or attempt identity",
            "next_action": "重新读取当前测量观察，不要手写 measurement_ref",
        }
    if expected_attachment_id and reference.get("attachment_id") != expected_attachment_id:
        return None, {
            "status": "blocked",
            "code": "measurement_source_mismatch",
            "location": location,
            "message": "measurement attachment does not match the assembled source",
            "next_action": "恢复同一 attachment 的测量证据",
        }
    if expected_panel_id and reference.get("panel_id") != expected_panel_id:
        return None, {
            "status": "blocked",
            "code": "measurement_panel_mismatch",
            "location": location,
            "message": "measurement panel does not match the assembled source",
            "next_action": "恢复同一 panel 的测量证据",
        }
    if not isinstance(context, Mapping):
        return None, {
            "status": "blocked",
            "code": "measurement_context_unavailable",
            "location": location,
            "message": "server-owned measurement session is unavailable in this run",
            "next_action": "重新观察当前 panel 后再组装",
        }
    raw_session = context.get(str(reference["session_id"]))
    session = raw_session if isinstance(raw_session, MeasurementSession) else MeasurementSession.from_dict(raw_session) if isinstance(raw_session, Mapping) else None
    if session is None:
        return None, {
            "status": "blocked",
            "code": "measurement_session_not_found",
            "location": location,
            "message": "measurement session is not registered for the current run",
            "next_action": "重新观察当前 panel 的测量结果",
        }
    attempt = next((item for item in session.attempts if item.attempt_id == reference.get("attempt_id")), None)
    if attempt is None:
        return None, {
            "status": "blocked",
            "code": "measurement_attempt_not_found",
            "location": location,
            "message": "measurement attempt is not registered for the current session",
            "next_action": "重新读取当前测量观察并重试组装",
        }
    if attempt.attachment_id != reference.get("attachment_id") or attempt.panel_id != reference.get("panel_id"):
        return None, {
            "status": "blocked",
            "code": "measurement_lineage_mismatch",
            "location": location,
            "message": "measurement attempt lineage does not match its reference",
            "next_action": "只使用当前 attachment/panel 下的最新测量证据",
        }
    if attempt.status != "accepted":
        quality = attempt.quality if isinstance(attempt.quality, Mapping) else {}
        issues = list(quality.get("issues", []))[:4] if isinstance(quality.get("issues"), list) else []
        return None, {
            "status": "blocked",
            "code": "measurement_not_accepted",
            "location": location,
            "message": f"measurement attempt status is {attempt.status}, not accepted",
            "measurement_status": attempt.status,
            "issues": _json_safe(issues),
            "next_action": "根据 issue 补充观察或在目标区域重新测量",
        }
    return {
        "status": "accepted",
        "session_id": session.session_id,
        "attempt_id": attempt.attempt_id,
        "attachment_id": attempt.attachment_id,
        "panel_id": attempt.panel_id,
        "tool": attempt.tool,
        "quality": _json_safe(attempt.quality),
    }, None


__all__ = [
    "MEASUREMENT_TOOLS",
    "MEASUREMENT_STATUSES",
    "MeasurementAttempt",
    "MeasurementSession",
    "attach_measurement_quality",
    "audit_measurement",
    "measurement_from_data",
    "measurement_gate",
    "measurement_session_id",
    "register_measurement",
    "sessions_from_state",
    "sessions_to_state",
]
