"""Bounded lifecycle and quality helpers for chart measurements.

The observation sensors intentionally keep their chart-specific payloads.  This
module only owns the small, serializable envelope around those payloads so a
measurement can be inspected, persisted, and rejected before it is used as a
deterministic ChartSpec source.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Iterable, Sequence
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
MAX_MEASUREMENT_TARGET_FIELDS = 8
MAX_MEASUREMENT_TARGET_ID = 128
MAX_MEASUREMENT_REGION_KIND = 48
MAX_MEASUREMENT_REFS = 64
MAX_MEASUREMENT_REF_ID = 24
MAX_MEASUREMENT_POLYGON_POINTS = 32
MAX_REPAIR_ATTEMPTS = 3
_PATH_PATTERN = re.compile(r"(?:/(?:Users|private|tmp|var|home|opt|etc)/|[A-Za-z]:\\)")
_COMPACT_REF_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,15}$")
_LEGACY_REF_PATTERN = re.compile(
    r"^(?P<kind>series|bar|bars|line|point|points|sector|sectors|legend|axis|axes|geometry|evidence)[_-]?(?P<index>\d+)$",
    re.IGNORECASE,
)
MEASUREMENT_FOCUS_MODES = frozenset({"include", "exclude"})
MEASUREMENT_REGION_KINDS = frozenset(
    {
        "panel",
        "baseline",
        "bars",
        "axes",
        "series",
        "points",
        "sectors",
        "legend",
        "geometry",
        "evidence",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, limit: int = MAX_MEASUREMENT_TEXT) -> str:
    text = str(value or "").strip()
    return _PATH_PATTERN.sub("[路径已省略]", text)[:limit]


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


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 4:
        return None
    values = tuple(_finite_number(item) for item in value[:4])
    if any(item is None for item in values):
        return None
    left, top, width, height = (float(item) for item in values if item is not None)
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        return None
    return (left, top, width, height)


def _image_size(value: object) -> tuple[int, int] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        return None
    width = _finite_number(value[0])
    height = _finite_number(value[1])
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return (int(round(width)), int(round(height)))


def _polygon(value: object) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    points: list[tuple[float, float]] = []
    for item in list(value)[:MAX_MEASUREMENT_POLYGON_POINTS]:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) < 2:
            continue
        x = _finite_number(item[0])
        y = _finite_number(item[1])
        if x is None or y is None or x < 0 or y < 0:
            continue
        points.append((x, y))
    return tuple(points) if len(points) >= 3 else None


def _evidence_ref_prefix(kind: str | None) -> str:
    return {
        "series": "S",
        "line": "S",
        "bar": "B",
        "bars": "B",
        "point": "P",
        "points": "P",
        "sector": "C",
        "sectors": "C",
        "legend": "L",
        "axis": "A",
        "axes": "A",
        "geometry": "G",
        "evidence": "E",
    }.get(str(kind or "").strip().lower(), "E")


def compact_evidence_ref(
    value: object,
    *,
    kind: str | None = None,
    index: int | None = None,
) -> str | None:
    """Normalize internal candidate IDs to short model-facing evidence refs."""
    text = _text(value, MAX_MEASUREMENT_REF_ID).strip()
    if not text and index is None:
        return None
    legacy = _LEGACY_REF_PATTERN.match(text)
    if legacy:
        text = f"{_evidence_ref_prefix(legacy.group('kind'))}{int(legacy.group('index'))}"
    elif text.isdigit() and index is None:
        text = f"{_evidence_ref_prefix(kind)}{int(text)}"
    elif index is not None and not text:
        text = f"{_evidence_ref_prefix(kind)}{max(1, int(index))}"
    else:
        text = text.upper()
    if not _COMPACT_REF_PATTERN.fullmatch(text):
        return None
    return text[:MAX_MEASUREMENT_REF_ID]


def normalize_evidence_refs(value: object, *, kind: str | None = None) -> tuple[str, ...]:
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    refs: list[str] = []
    for item in raw_values:
        ref = compact_evidence_ref(item, kind=kind)
        if ref and ref not in refs:
            refs.append(ref)
        if len(refs) >= MAX_MEASUREMENT_REFS:
            break
    return tuple(refs)


def _candidate_bbox(value: object) -> list[float] | None:
    """Extract a small local bbox from a chart candidate without raw pixels."""
    if not isinstance(value, Mapping):
        return None
    candidates: list[object] = [value.get("bbox_px"), value.get("bbox")]
    for key in ("geometry", "total_geometry", "trace"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            candidates.extend((nested.get("bbox_px"), nested.get("bbox")))
    for raw in candidates:
        bbox = _bbox(raw)
        if bbox is not None:
            return [round(item, 3) for item in bbox]
    x = _finite_number(value.get("x_px"))
    y = _finite_number(value.get("y_px"))
    if x is not None and y is not None:
        return [round(max(0.0, x - 4.0), 3), round(max(0.0, y - 4.0), 3), 8.0, 8.0]
    return None


def _union_bboxes(values: Sequence[Sequence[float]]) -> list[float] | None:
    boxes = [_bbox(value) for value in values]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return [round(left, 3), round(top, 3), round(right - left, 3), round(bottom - top, 3)]


def _polyline_bbox(value: object) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    points = [
        (_finite_number(item[0]), _finite_number(item[1]))
        for item in value
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) >= 2
    ]
    points = [(x, y) for x, y in points if x is not None and y is not None]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3)]


def build_measurement_evidence_refs(
    data: Mapping[str, Any],
    *,
    source_tool: str,
) -> list[dict[str, Any]]:
    """Build one bounded ref index shared by model output and target resolution."""
    refs: list[dict[str, Any]] = []
    series_refs: dict[str, str] = {}
    series = data.get("series") if isinstance(data.get("series"), list) else []
    for index, item in enumerate(series[:MAX_MEASUREMENT_REFS], start=1):
        if not isinstance(item, Mapping):
            continue
        internal_id = _text(item.get("id"), 80)
        ref = f"S{index}"
        if internal_id:
            series_refs[internal_id] = ref
        entry: dict[str, Any] = {"ref": ref, "kind": "series"}
        label = item.get("label")
        if isinstance(label, str) and label.strip():
            entry["label"] = _text(label, 120)
        color = item.get("color")
        if isinstance(color, str) and color.strip():
            entry["color"] = _text(color, 24)
        bbox = _candidate_bbox(item)
        if bbox is None and isinstance(item.get("trace"), Mapping):
            bbox = _polyline_bbox(item["trace"].get("polyline_px"))
        if bbox is not None:
            entry["bbox_px"] = bbox
        refs.append(entry)

    if source_tool == "measure_bars":
        bars = data.get("bars") if isinstance(data.get("bars"), list) else []
        for index, item in enumerate(bars[:MAX_MEASUREMENT_REFS - len(refs)], start=1):
            if not isinstance(item, Mapping):
                continue
            entry = {"ref": f"B{index}", "kind": "bar"}
            series_id = _text(item.get("series_id"), 80)
            if series_id and series_id in series_refs:
                entry["series_ref"] = series_refs[series_id]
            category = item.get("category") or item.get("category_label")
            if isinstance(category, str) and category.strip():
                entry["label"] = _text(category, 120)
            bbox = _candidate_bbox(item)
            if bbox is not None:
                entry["bbox_px"] = bbox
            refs.append(entry)
    elif source_tool in {"extract_line_series", "extract_scatter_points"}:
        points = data.get("points") if isinstance(data.get("points"), list) else []
        for index, item in enumerate(points[:MAX_MEASUREMENT_REFS - len(refs)], start=1):
            if not isinstance(item, Mapping):
                continue
            entry = {"ref": f"P{index}", "kind": "point"}
            series_id = _text(item.get("series_id"), 80)
            if series_id and series_id in series_refs:
                entry["series_ref"] = series_refs[series_id]
            bbox = _candidate_bbox(item)
            if bbox is not None:
                entry["bbox_px"] = bbox
            refs.append(entry)
    elif source_tool == "extract_pie_slices":
        sectors = data.get("sectors") if isinstance(data.get("sectors"), list) else []
        for index, item in enumerate(sectors[:MAX_MEASUREMENT_REFS - len(refs)], start=1):
            if not isinstance(item, Mapping):
                continue
            entry = {"ref": f"C{index}", "kind": "sector"}
            association = item.get("association")
            if isinstance(association, Mapping) and isinstance(association.get("label"), str):
                entry["label"] = _text(association["label"], 120)
            bbox = _candidate_bbox(item)
            if bbox is not None:
                entry["bbox_px"] = bbox
            refs.append(entry)

    legend = data.get("legend") if isinstance(data.get("legend"), list) else []
    for index, item in enumerate(legend[:MAX_MEASUREMENT_REFS - len(refs)], start=1):
        if not isinstance(item, Mapping):
            continue
        entry = {"ref": f"L{index}", "kind": "legend"}
        label = item.get("label")
        if isinstance(label, str) and label.strip():
            entry["label"] = _text(label, 120)
        bbox = _candidate_bbox(item)
        if bbox is not None:
            entry["bbox_px"] = bbox
        refs.append(entry)
    return refs[:MAX_MEASUREMENT_REFS]


@dataclass(frozen=True)
class MeasurementTarget:
    """Bounded, source-coordinate focus target for a repair measurement."""

    target_id: str
    panel_id: str | None
    parent_attempt_id: str | None
    region_kind: str
    refs: tuple[str, ...] = ()
    mode: str = "include"
    fields: tuple[str, ...] = ()
    bbox_source_px: tuple[float, float, float, float] | None = None
    source_image_size: tuple[int, int] | None = None
    reason: str = ""
    bbox_local_px: tuple[float, float, float, float] | None = None
    polygon_source_px: tuple[tuple[float, float], ...] | None = None
    local_image_size: tuple[int, int] | None = None
    local_to_source: dict[str, Any] | None = None
    clipped: bool = False

    @classmethod
    def from_mapping(cls, value: object) -> "MeasurementTarget | None":
        if not isinstance(value, Mapping):
            return None
        target_id = _text(value.get("target_id") or value.get("targetId"), MAX_MEASUREMENT_TARGET_ID)
        region_kind = _text(value.get("region_kind") or value.get("regionKind") or "panel", MAX_MEASUREMENT_REGION_KIND).lower()
        if not region_kind:
            return None
        if region_kind not in MEASUREMENT_REGION_KINDS:
            region_kind = "geometry"
        refs = normalize_evidence_refs(value.get("refs") or value.get("target_refs"))
        raw_mode = value.get("mode")
        mode = str(raw_mode or "include").strip().lower()
        if mode not in MEASUREMENT_FOCUS_MODES:
            return None
        raw_fields = value.get("fields")
        fields = tuple(
            _text(item, 80)
            for item in raw_fields
            if _text(item, 80)
        )[:MAX_MEASUREMENT_TARGET_FIELDS] if isinstance(raw_fields, (list, tuple)) else ()
        bbox_source_px = _bbox(value.get("bbox_source_px") or value.get("bboxSourcePx"))
        bbox_local_px = _bbox(value.get("bbox_px") or value.get("bbox_local_px") or value.get("bboxLocalPx"))
        polygon_source_px = _polygon(value.get("polygon_source_px") or value.get("polygonSourcePx"))
        if not target_id:
            seed = json.dumps(
                {
                    "refs": list(refs),
                    "mode": mode,
                    "fields": list(fields),
                    "bbox_source_px": list(bbox_source_px) if bbox_source_px else None,
                    "bbox_local_px": list(bbox_local_px) if bbox_local_px else None,
                    "polygon_source_px": polygon_source_px,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            target_id = f"focus-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
        if not refs and bbox_source_px is None and bbox_local_px is None and polygon_source_px is None:
            return None
        return cls(
            target_id=target_id,
            panel_id=_text(value.get("panel_id") or value.get("panelId"), 160) or None,
            parent_attempt_id=_text(value.get("parent_attempt_id") or value.get("parentAttemptId"), 160) or None,
            region_kind=region_kind,
            refs=refs,
            mode=mode,
            fields=fields,
            bbox_source_px=bbox_source_px,
            source_image_size=_image_size(value.get("source_image_size") or value.get("sourceImageSize")),
            reason=_text(value.get("reason"), 240),
            bbox_local_px=bbox_local_px,
            polygon_source_px=polygon_source_px,
            local_image_size=_image_size(value.get("local_image_size") or value.get("localImageSize")),
            local_to_source=_json_safe(value.get("local_to_source") or value.get("localToSource")) if isinstance(value.get("local_to_source") or value.get("localToSource"), Mapping) else None,
            clipped=bool(value.get("clipped")),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "target_id": self.target_id,
            "panel_id": self.panel_id,
            "parent_attempt_id": self.parent_attempt_id,
            "region_kind": self.region_kind,
            "refs": list(self.refs[:MAX_MEASUREMENT_REFS]),
            "mode": self.mode if self.mode in MEASUREMENT_FOCUS_MODES else "include",
            "fields": list(self.fields[:MAX_MEASUREMENT_TARGET_FIELDS]),
            "reason": self.reason[:MAX_MEASUREMENT_TEXT],
            "clipped": bool(self.clipped),
        }
        if self.bbox_source_px is not None:
            result["bbox_source_px"] = [round(value, 3) for value in self.bbox_source_px]
        if self.polygon_source_px is not None:
            result["polygon_source_px"] = [
                [round(point[0], 3), round(point[1], 3)]
                for point in self.polygon_source_px[:MAX_MEASUREMENT_POLYGON_POINTS]
            ]
        if self.source_image_size is not None:
            result["source_image_size"] = list(self.source_image_size)
        if self.bbox_local_px is not None:
            result["bbox_px"] = [round(value, 3) for value in self.bbox_local_px]
        if self.local_image_size is not None:
            result["local_image_size"] = list(self.local_image_size)
        if self.local_to_source is not None:
            result["local_to_source"] = _json_safe(self.local_to_source)
        return result

    def fingerprint(self, *, tool: str | None = None) -> str:
        """Return a stable identity that ignores model-generated labels/reasons."""
        payload = {
            "tool": _text(tool, 80),
            "panel_id": self.panel_id,
            "region_kind": self.region_kind,
            "refs": list(self.refs),
            "mode": self.mode,
            "fields": list(self.fields),
            "bbox_source_px": list(self.bbox_source_px) if self.bbox_source_px else None,
            "source_image_size": list(self.source_image_size) if self.source_image_size else None,
            "polygon_source_px": [list(point) for point in self.polygon_source_px] if self.polygon_source_px else None,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        return f"mt_{digest}"


def normalize_measurement_target(value: object) -> dict[str, Any] | None:
    """Normalize a model or adapter target without inventing a source bbox."""
    target = MeasurementTarget.from_mapping(value)
    if target is None:
        return None
    return target.to_dict()


def measurement_target_fingerprint(value: object, *, tool: str | None = None) -> str | None:
    target = MeasurementTarget.from_mapping(value)
    return target.fingerprint(tool=tool) if target is not None else None


def _repair_error(code: str, message: str, *, status: str = "blocked") -> dict[str, Any]:
    return {
        "status": status,
        "code": _text(code, 80),
        "location": "measurement_target",
        "message": _text(message),
        "next_action": "由主 Agent 根据当前 evidence.refs 决定接受、舍弃或调用同一测量工具做定向补充",
    }


def _repair_limit(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = MAX_REPAIR_ATTEMPTS
    return max(1, min(MAX_REPAIR_ATTEMPTS, parsed))


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


def _repair_action(
    *,
    source_tool: str,
    source_attachment_id: str | None,
    source_panel_id: str | None,
    source_attempt_id: str,
    issues: Sequence[Mapping[str, Any]],
    target: dict[str, Any] | None,
    status: str,
) -> dict[str, Any] | None:
    if status not in {"remeasure_required", "partial"}:
        return None
    fields: list[str] = []
    for issue in issues:
        location = _text(issue.get("location"), 120)
        if location and location not in fields:
            fields.append(location)
        if len(fields) >= MAX_MEASUREMENT_TARGET_FIELDS:
            break
    resolved_target = dict(target or {})
    resolved_target.setdefault("target_id", f"panel-review-{source_attempt_id[:24]}")
    resolved_target.setdefault("panel_id", source_panel_id)
    resolved_target.setdefault("parent_attempt_id", source_attempt_id)
    resolved_target.setdefault("region_kind", "panel")
    resolved_target.setdefault("fields", fields)
    if not resolved_target.get("reason"):
        resolved_target["reason"] = "；".join(
            _text(issue.get("next_action") or issue.get("message"), 120)
            for issue in issues[:3]
        )
    return {
        "action": "remeasure",
        "status": "available",
        "tool": _text(source_tool, 80),
        "attachment_id": _text(source_attachment_id, 160) or None,
        "panel_id": _text(source_panel_id, 160) or None,
        "parent_attempt_id": source_attempt_id,
        "fields": fields,
        "target": normalize_measurement_target(resolved_target) or resolved_target,
        "next_action": "使用当前 panel 和 parent_attempt_id 发起一次有界的定向重测，然后重新读取 measurement 质量结果",
    }


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
    target = normalize_measurement_target(measurement_target)
    if target is not None:
        target["panel_id"] = target.get("panel_id") or panel
        target["parent_attempt_id"] = target.get("parent_attempt_id")
    repair_action = _repair_action(
        source_tool=source_tool,
        source_attachment_id=attachment,
        source_panel_id=panel,
        source_attempt_id=attempt_id,
        issues=issues,
        target=target,
        status=status,
    )
    evidence_refs = build_measurement_evidence_refs(chart_data, source_tool=source_tool)
    focus = chart_data.get("focus")
    focus_payload = _json_safe(focus) if isinstance(focus, Mapping) else None
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
            "target": target,
            "target_fingerprint": measurement_target_fingerprint(target, tool=source_tool),
            "created_at": _now(),
        },
        "target": target,
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
            "focus_suggestion": repair_action,
            "repair_action": repair_action,
        },
        "evidence": {
            "visual_count": max(0, min(int(image_count), 4)),
            "captions": captions,
            "refs": evidence_refs,
            "focus": focus_payload,
        },
        "decision": {
            "status": "pending",
            "selected_refs": [],
            "discarded_refs": [],
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
            quality = dict(envelope.get("quality") or {})
            repair_action = quality.get("repair_action")
            if isinstance(repair_action, dict):
                repair_action = dict(repair_action)
                repair_action["parent_attempt_id"] = parent_attempt_id[:160]
                repair_target = repair_action.get("target")
                if isinstance(repair_target, dict):
                    repair_target = dict(repair_target)
                    repair_target["parent_attempt_id"] = parent_attempt_id[:160]
                    repair_action["target"] = repair_target
                quality["repair_action"] = repair_action
                envelope["quality"] = quality
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
    target: dict[str, Any] | None = None
    target_fingerprint: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[dict[str, Any], ...] = ()
    selected_refs: tuple[str, ...] = ()
    discarded_refs: tuple[str, ...] = ()
    focus_mode: str | None = None
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
        raw_refs = evidence.get("refs") if isinstance(evidence, Mapping) else []
        if not raw_refs:
            raw_refs = value.get("evidence_refs")
        evidence_refs = tuple(item for item in raw_refs[:MAX_MEASUREMENT_REFS] if isinstance(item, Mapping)) if isinstance(raw_refs, list) else ()
        decision = value.get("decision") if isinstance(value.get("decision"), Mapping) else {}
        if not decision:
            decision = {
                "selected_refs": value.get("selected_refs"),
                "discarded_refs": value.get("discarded_refs"),
            }
        focus = evidence.get("focus") if isinstance(evidence, Mapping) else None
        scope = _json_safe(attempt.get("scope") or source.get("scope"))
        target = _json_safe(value.get("target") or attempt.get("target"))
        target = target if isinstance(target, dict) else None
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
            target=target,
            target_fingerprint=_text(attempt.get("target_fingerprint"), 80) or measurement_target_fingerprint(target, tool=attempt.get("tool")),
            quality=quality if isinstance(quality, dict) else {},
            evidence=evidence if isinstance(evidence, dict) else {},
            evidence_refs=tuple(dict(item) for item in evidence_refs),
            selected_refs=normalize_evidence_refs(decision.get("selected_refs")),
            discarded_refs=normalize_evidence_refs(decision.get("discarded_refs")),
            focus_mode=_text(focus.get("mode"), 24) or None if isinstance(focus, Mapping) else None,
            created_at=_text(attempt.get("created_at"), 64) or _now(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementAttempt | None":
        if not isinstance(value, Mapping):
            return None
        quality = _json_safe(value.get("quality") or {})
        evidence = _json_safe(value.get("evidence") or {})
        raw_refs = evidence.get("refs") if isinstance(evidence, Mapping) else []
        if not raw_refs:
            raw_refs = value.get("evidence_refs")
        evidence_refs = tuple(item for item in raw_refs[:MAX_MEASUREMENT_REFS] if isinstance(item, Mapping)) if isinstance(raw_refs, list) else ()
        decision = value.get("decision") if isinstance(value.get("decision"), Mapping) else {}
        if not decision:
            decision = {
                "selected_refs": value.get("selected_refs"),
                "discarded_refs": value.get("discarded_refs"),
            }
        focus = evidence.get("focus") if isinstance(evidence, Mapping) else None
        scope = _json_safe(value.get("scope"))
        target = _json_safe(value.get("target"))
        target = target if isinstance(target, dict) else None
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
            target=target,
            target_fingerprint=_text(value.get("target_fingerprint"), 80) or measurement_target_fingerprint(target, tool=value.get("tool")),
            quality=quality if isinstance(quality, dict) else {},
            evidence=evidence if isinstance(evidence, dict) else {},
            evidence_refs=tuple(dict(item) for item in evidence_refs),
            selected_refs=normalize_evidence_refs(decision.get("selected_refs")),
            discarded_refs=normalize_evidence_refs(decision.get("discarded_refs")),
            focus_mode=_text(focus.get("mode"), 24) or None if isinstance(focus, Mapping) else None,
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
            "target": _json_safe(self.target),
            "target_fingerprint": self.target_fingerprint,
            "quality": _json_safe(self.quality),
            "evidence": _json_safe(self.evidence),
            "evidence_refs": _json_safe(list(self.evidence_refs)),
            "selected_refs": list(self.selected_refs),
            "discarded_refs": list(self.discarded_refs),
            "focus_mode": self.focus_mode,
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
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS
    selected_refs: tuple[str, ...] = ()
    discarded_refs: tuple[str, ...] = ()
    decision_status: str = "pending"
    decision_attempt_id: str | None = None
    focus_mode: str | None = None

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
            max_repair_attempts=_repair_limit(value.get("max_repair_attempts", MAX_REPAIR_ATTEMPTS)),
            selected_refs=normalize_evidence_refs(value.get("selected_refs")),
            discarded_refs=normalize_evidence_refs(value.get("discarded_refs")),
            decision_status=_text(value.get("decision_status"), 32) or "pending",
            decision_attempt_id=_text(value.get("decision_attempt_id"), 160) or None,
            focus_mode=_text(value.get("focus_mode"), 24) or None,
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
        if attempt.target is not None:
            if self.repair_attempt_count >= self.max_repair_attempts:
                return False
            if self.has_target(attempt.target, tool=attempt.tool):
                return False
        self.attempts.append(attempt)
        self.attempts = self.attempts[-MAX_MEASUREMENT_ATTEMPTS:]
        self.current_attempt_id = attempt.attempt_id
        self.selected_refs = ()
        self.discarded_refs = ()
        self.decision_status = "pending"
        self.decision_attempt_id = None
        self.focus_mode = attempt.focus_mode
        return True

    @property
    def repair_attempt_count(self) -> int:
        return sum(1 for item in self.attempts if item.target is not None)

    @property
    def repair_budget_remaining(self) -> int:
        return max(0, self.max_repair_attempts - self.repair_attempt_count)

    def pending_repair_action(self) -> dict[str, Any] | None:
        current = next(
            (item for item in reversed(self.attempts) if item.attempt_id == self.current_attempt_id),
            None,
        )
        if current is None or not isinstance(current.quality, Mapping):
            return None
        action = current.quality.get("repair_action")
        if not isinstance(action, Mapping):
            return None
        result = dict(action)
        result["budget_remaining"] = self.repair_budget_remaining
        if self.repair_budget_remaining <= 0:
            result["status"] = "exhausted"
            result["next_action"] = "修复预算已用尽；保留当前失败证据，不得继续创建定向重测"
        return result

    def has_target(self, target: Mapping[str, Any] | None, *, tool: str | None = None) -> bool:
        fingerprint = measurement_target_fingerprint(target, tool=tool)
        return bool(fingerprint and any(item.target_fingerprint == fingerprint for item in self.attempts))

    def current_attempt(self) -> MeasurementAttempt | None:
        return next(
            (item for item in reversed(self.attempts) if item.attempt_id == self.current_attempt_id),
            None,
        )

    def evidence_refs(self) -> tuple[dict[str, Any], ...]:
        current = self.current_attempt()
        if current is None:
            return ()
        return current.evidence_refs

    def resolve_refs(
        self,
        refs: object,
        *,
        mode: str = "include",
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Resolve compact refs against the current attempt's bounded index."""
        normalized_refs = normalize_evidence_refs(refs)
        if not normalized_refs:
            return [], _repair_error("measurement_target_refs_empty", "measurement_target.refs must contain at least one known evidence ref")
        if mode not in MEASUREMENT_FOCUS_MODES:
            return [], _repair_error("measurement_target_mode_invalid", "measurement_target.mode must be include or exclude")
        index = {str(item.get("ref")): dict(item) for item in self.evidence_refs() if isinstance(item, Mapping)}
        missing = [ref for ref in normalized_refs if ref not in index]
        if missing:
            return [], {
                **_repair_error("measurement_target_ref_unknown", "one or more measurement target refs are not in the current attempt"),
                "missing_refs": missing[:MAX_MEASUREMENT_REFS],
            }
        resolved = [index[ref] for ref in normalized_refs]
        if not any(isinstance(item.get("bbox_px"), list) for item in resolved):
            return [], _repair_error("measurement_target_ref_unbounded", "the selected evidence refs have no bounded geometry")
        return resolved, None

    def record_decision(
        self,
        *,
        attempt_id: str,
        selected_refs: object = (),
        discarded_refs: object = (),
        status: str = "selected",
    ) -> bool:
        if attempt_id != self.current_attempt_id:
            return False
        selected = normalize_evidence_refs(selected_refs)
        discarded = normalize_evidence_refs(discarded_refs)
        available = {str(item.get("ref")) for item in self.evidence_refs() if isinstance(item, Mapping)}
        if any(ref not in available for ref in (*selected, *discarded)):
            return False
        if set(selected) & set(discarded):
            return False
        self.selected_refs = selected
        self.discarded_refs = discarded
        self.decision_status = _text(status, 32) or "selected"
        self.decision_attempt_id = attempt_id
        current_index = next(
            (index for index, item in enumerate(self.attempts) if item.attempt_id == attempt_id),
            None,
        )
        current = self.current_attempt()
        if current_index is not None and current is not None:
            self.attempts[current_index] = replace(
                current,
                selected_refs=selected,
                discarded_refs=discarded,
            )
        self.focus_mode = current.focus_mode if current else self.focus_mode
        return True

    def validate_repair_target(
        self,
        target: Mapping[str, Any] | None,
        *,
        tool: str,
        parent_attempt_id: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        normalized = normalize_measurement_target(target)
        if normalized is None:
            return None, _repair_error("measurement_target_invalid", "measurement_target is invalid")
        if self.panel_id and normalized.get("panel_id") not in {None, self.panel_id}:
            return None, _repair_error("measurement_panel_mismatch", "measurement target does not belong to the current panel")
        current_parent = parent_attempt_id or self.current_attempt_id
        requested_parent = normalized.get("parent_attempt_id") or current_parent
        if not requested_parent or requested_parent != self.current_attempt_id:
            return None, _repair_error("measurement_parent_mismatch", "measurement target parent attempt is not the current attempt")
        if self.repair_attempt_count >= self.max_repair_attempts:
            return None, _repair_error("measurement_repair_budget_exhausted", "measurement repair budget is exhausted", status="exhausted")
        if self.has_target(normalized, tool=tool):
            return None, _repair_error("measurement_target_duplicate", "equivalent measurement target was already attempted", status="rejected")
        refs = normalized.get("refs") if isinstance(normalized.get("refs"), list) else []
        if refs:
            resolved, ref_error = self.resolve_refs(refs, mode=str(normalized.get("mode") or "include"))
            if ref_error is not None:
                return None, ref_error
            regions = [item.get("bbox_px") for item in resolved if isinstance(item.get("bbox_px"), list)]
            normalized["resolved_refs"] = [str(item.get("ref")) for item in resolved]
            normalized["resolved_regions_px"] = regions[:MAX_MEASUREMENT_REFS]
            union = _union_bboxes(regions)
            if union is not None:
                normalized["bbox_px"] = union
            if normalized.get("region_kind") == "panel":
                kinds = [str(item.get("kind") or "") for item in resolved]
                normalized["region_kind"] = kinds[0] if kinds and kinds[0] in MEASUREMENT_REGION_KINDS else "geometry"
        normalized["panel_id"] = self.panel_id or normalized.get("panel_id")
        normalized["parent_attempt_id"] = requested_parent
        return normalized, None

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
            "max_repair_attempts": self.max_repair_attempts,
            "selected_refs": list(self.selected_refs),
            "discarded_refs": list(self.discarded_refs),
            "decision_status": self.decision_status,
            "decision_attempt_id": self.decision_attempt_id,
            "focus_mode": self.focus_mode,
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
    require_decision: bool = True,
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
            "repair_action": _json_safe(quality.get("repair_action")) if isinstance(quality.get("repair_action"), Mapping) else None,
            "next_action": "根据 issue 补充观察或在目标区域重新测量",
        }
    if require_decision and attempt.evidence_refs and any(
        isinstance(item, Mapping) and isinstance(item.get("bbox_px"), list)
        for item in attempt.evidence_refs
    ):
        if (
            session.decision_attempt_id != attempt.attempt_id
            or session.decision_status not in {"selected", "accepted"}
            or not session.selected_refs
        ):
            return None, {
                "status": "blocked",
                "code": "measurement_decision_required",
                "location": f"{location}.selected_refs",
                "message": "主 Agent 尚未明确选择当前 attempt 的测量证据",
                "measurement_status": attempt.status,
                "available_refs": [item.get("ref") for item in attempt.evidence_refs[:MAX_MEASUREMENT_REFS]],
                "next_action": "先根据 overlay 和 evidence.refs 提交 measurement_decision，再组装 ChartSpec",
            }
    return {
        "status": "accepted",
        "session_id": session.session_id,
        "attempt_id": attempt.attempt_id,
        "attachment_id": attempt.attachment_id,
        "panel_id": attempt.panel_id,
        "tool": attempt.tool,
        "quality": _json_safe(attempt.quality),
        "selected_refs": list(session.selected_refs),
        "discarded_refs": list(session.discarded_refs),
        "decision_status": session.decision_status,
    }, None


__all__ = [
    "MEASUREMENT_TOOLS",
    "MEASUREMENT_STATUSES",
    "MEASUREMENT_FOCUS_MODES",
    "MAX_REPAIR_ATTEMPTS",
    "MeasurementTarget",
    "MeasurementAttempt",
    "MeasurementSession",
    "attach_measurement_quality",
    "audit_measurement",
    "build_measurement_evidence_refs",
    "compact_evidence_ref",
    "measurement_from_data",
    "measurement_gate",
    "measurement_target_fingerprint",
    "measurement_session_id",
    "normalize_evidence_refs",
    "normalize_measurement_target",
    "register_measurement",
    "sessions_from_state",
    "sessions_to_state",
]
