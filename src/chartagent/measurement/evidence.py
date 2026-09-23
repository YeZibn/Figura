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
        "complete",
        "partial",
        "unsupported",
        "failed",
    }
)
MEASUREMENT_ISSUE_SEVERITIES = frozenset({"blocking", "warning", "info"})
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
_PATH_PATTERN = re.compile(r"(?:/(?:Users|private|tmp|var|home|opt|etc)/|[A-Za-z]:\\)")
_COMPACT_REF_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,15}$")
_LEGACY_REF_PATTERN = re.compile(
    r"^(?P<kind>series|bar|bars|line|point|points|sector|sectors|legend|axis|axes|geometry|evidence)[_-]?(?P<index>\d+)$",
    re.IGNORECASE,
)
MEASUREMENT_FOCUS_MODES = frozenset({"include", "exclude"})
OBSERVATION_COORDINATE_SPACES = frozenset({"panel_norm", "panel_px", "source_px"})
OBSERVATION_REGION_ROLES = frozenset(
    {
        "plot",
        "legend",
        "axes",
        "x_axis",
        "y_axis",
        "data_labels",
        "annotation",
        "baseline",
        "geometry",
        "panel",
    }
)
MAX_OBSERVATION_REGIONS = 16
MAX_OBSERVATION_OBJECTIVES = 8
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


def _has_numeric_value(value: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        if _finite_number(value.get(key)) is not None:
            return True
    for nested_key in ("measure", "value", "data"):
        nested = value.get(nested_key)
        if isinstance(nested, Mapping) and any(_finite_number(nested.get(key)) is not None for key in keys):
            return True
    return False


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
        entry["has_numeric_value"] = bool(
            _has_numeric_value(item, "x", "y", "value", "ratio")
            or isinstance(item.get("trace"), Mapping) and bool(item["trace"].get("polyline_px"))
        )
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
            entry["has_numeric_value"] = _has_numeric_value(item, "value", "ratio", "height", "length")
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
            entry["has_numeric_value"] = _has_numeric_value(item, "x", "y", "value")
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
            entry["has_numeric_value"] = _has_numeric_value(item, "value", "ratio", "angle_deg", "angle")
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
