"""Safe, session-scoped panel handoff contracts.

Panel records deliberately contain coordinates and bounded metadata only.  They
never carry local filesystem paths or image bytes across the Gateway boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MAX_PANEL_ID = 128
MAX_PANEL_NAME = 240
MAX_PANEL_SLUG = 96
MAX_PANEL_WARNINGS = 12
MAX_PANEL_EVIDENCE = 12
PANEL_SCHEMA_VERSION = 1
_SAFE_SLUG = re.compile(r"[^a-z0-9]+")


def _bounded_text(value: object, limit: int, default: str = "") -> str:
    text = " ".join(str(value or default).split())
    return text[:limit]


def panel_slug(value: object) -> str:
    text = _SAFE_SLUG.sub("-", _bounded_text(value, MAX_PANEL_NAME).lower()).strip("-")
    return (text or "panel")[:MAX_PANEL_SLUG]


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_bbox(value: object, *, width: int | None = None, height: int | None = None) -> list[int] | None:
    """Normalize a pixel bbox and clamp it to an optional image size."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 4:
        return None
    numbers = [_number(item) for item in value[:4]]
    if any(item is None for item in numbers):
        return None
    left, top, box_width, box_height = (int(round(item)) for item in numbers if item is not None)
    if box_width <= 0 or box_height <= 0:
        return None
    if width is not None and height is not None:
        left = max(0, min(max(0, int(width) - 1), left))
        top = max(0, min(max(0, int(height) - 1), top))
        box_width = min(box_width, max(1, int(width) - left))
        box_height = min(box_height, max(1, int(height) - top))
    return [left, top, max(1, box_width), max(1, box_height)]


def stable_panel_id(
    attachment_sha256: str,
    name: object,
    chart_type: object,
    source_bbox: Sequence[int],
) -> str:
    """Create an opaque identity independent of a run-local panel ordinal."""
    payload = {
        "attachment": str(attachment_sha256),
        "name": panel_slug(name),
        "chart_type": _bounded_text(chart_type, 64, "unknown").lower(),
        "bbox": list(source_bbox[:4]),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
    return f"panel_{digest}"


def bbox_iou(first: Sequence[int] | None, second: Sequence[int] | None) -> float:
    a = normalize_bbox(first)
    b = normalize_bbox(second)
    if a is None or b is None:
        return 0.0
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    union = aw * ah + bw * bh - intersection
    return float(intersection / union) if union else 0.0


@dataclass(frozen=True)
class PanelHandoff:
    session_id: str
    attachment_id: str
    attachment_sha256: str
    panel_id: str
    revision: int
    name: str
    slug: str
    role: str
    chart_type: str
    source_bbox: tuple[int, int, int, int]
    analysis_scope: tuple[int, int, int, int]
    confidence: float = 0.0
    status: str = "active"
    warnings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    origin_run_id: str | None = None
    supersedes_panel_id: str | None = None
    schema_version: int = PANEL_SCHEMA_VERSION
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id or not self.attachment_id or not self.attachment_sha256:
            raise ValueError("PanelHandoff requires session, attachment, and content hash")
        if not self.panel_id or len(self.panel_id) > MAX_PANEL_ID:
            raise ValueError("panel_id is invalid")
        if self.revision < 1:
            raise ValueError("panel revision must be positive")
        if self.status not in {"active", "stale", "superseded", "invalid"}:
            raise ValueError("panel status is invalid")
        if normalize_bbox(self.source_bbox) is None or normalize_bbox(self.analysis_scope) is None:
            raise ValueError("panel bboxes are invalid")

    @property
    def source_origin(self) -> tuple[int, int]:
        return (self.analysis_scope[0], self.analysis_scope[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "attachmentId": self.attachment_id,
            "attachmentSha256": self.attachment_sha256,
            "panelId": self.panel_id,
            "revision": self.revision,
            "name": self.name,
            "slug": self.slug,
            "role": self.role,
            "chartType": self.chart_type,
            "sourceBbox": list(self.source_bbox),
            "analysisScope": list(self.analysis_scope),
            "sourceOriginPx": list(self.source_origin),
            "localToSource": "x_source = x_local + source_origin_px[0]; y_source = y_local + source_origin_px[1]",
            "confidence": max(0.0, min(1.0, float(self.confidence))),
            "status": self.status,
            "warnings": list(self.warnings[:MAX_PANEL_WARNINGS]),
            "evidence": list(self.evidence[:MAX_PANEL_EVIDENCE]),
            "originRunId": self.origin_run_id,
            "supersedesPanelId": self.supersedes_panel_id,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PanelHandoff":
        source = normalize_bbox(value.get("sourceBbox", value.get("source_bbox")))
        scope = normalize_bbox(value.get("analysisScope", value.get("analysis_scope"))) or source
        if source is None or scope is None:
            raise ValueError("panel record has no valid bbox")
        name = _bounded_text(value.get("name"), MAX_PANEL_NAME, "Panel")
        chart_type = _bounded_text(value.get("chartType", value.get("chart_type")), 64, "unknown")
        return cls(
            session_id=_bounded_text(value.get("sessionId", value.get("session_id")), 128),
            attachment_id=_bounded_text(value.get("attachmentId", value.get("attachment_id")), 128),
            attachment_sha256=_bounded_text(value.get("attachmentSha256", value.get("attachment_sha256")), 128),
            panel_id=_bounded_text(value.get("panelId", value.get("panel_id")), MAX_PANEL_ID),
            revision=max(1, int(value.get("revision", 1))),
            name=name,
            slug=panel_slug(value.get("slug") or name),
            role=_bounded_text(value.get("role"), 64, "region"),
            chart_type=chart_type,
            source_bbox=tuple(source),
            analysis_scope=tuple(scope),
            confidence=max(0.0, min(1.0, float(value.get("confidence", 0.0) or 0.0))),
            status=_bounded_text(value.get("status"), 32, "active"),
            warnings=tuple(_bounded_text(item, 160) for item in value.get("warnings", []) if isinstance(item, str))[:MAX_PANEL_WARNINGS],
            evidence=tuple(_bounded_text(item, 96) for item in value.get("evidence", []) if isinstance(item, str))[:MAX_PANEL_EVIDENCE],
            origin_run_id=value.get("originRunId", value.get("origin_run_id")) if isinstance(value.get("originRunId", value.get("origin_run_id")), str) else None,
            supersedes_panel_id=value.get("supersedesPanelId", value.get("supersedes_panel_id")) if isinstance(value.get("supersedesPanelId", value.get("supersedes_panel_id")), str) else None,
            schema_version=int(value.get("schemaVersion", value.get("schema_version", PANEL_SCHEMA_VERSION)) or PANEL_SCHEMA_VERSION),
            updated_at=value.get("updatedAt", value.get("updated_at")) if isinstance(value.get("updatedAt", value.get("updated_at")), str) else None,
        )


@dataclass(frozen=True)
class ActiveSourceContext:
    session_id: str
    attachment_ids: tuple[str, ...] = ()
    reason: str = "explicit"
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "attachmentIds": list(self.attachment_ids[:16]),
            "reason": self.reason,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class CandidateLineage:
    candidate_id: str
    parent_candidate_id: str | None = None
    chart_spec_digest: str | None = None
    source_attachment_ids: tuple[str, ...] = field(default_factory=tuple)
    panel_ids: tuple[str, ...] = field(default_factory=tuple)
    attempt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidate_id,
            "parentCandidateId": self.parent_candidate_id,
            "chartSpecDigest": self.chart_spec_digest,
            "sourceAttachmentIds": list(self.source_attachment_ids[:16]),
            "panelIds": list(self.panel_ids[:32]),
            "attempt": max(0, int(self.attempt)),
        }


def handoff_from_panel(
    *,
    session_id: str,
    attachment_id: str,
    attachment_sha256: str,
    panel: Mapping[str, Any],
    origin_run_id: str | None = None,
    panel_id: str | None = None,
    revision: int = 1,
    supersedes_panel_id: str | None = None,
) -> PanelHandoff:
    source_bbox = normalize_bbox(panel.get("bbox_px") or panel.get("source_bbox"))
    layout = panel.get("layout_context") if isinstance(panel.get("layout_context"), Mapping) else {}
    scope_value = panel.get("analysis_scope")
    if not isinstance(scope_value, Mapping):
        scope_value = layout.get("analysis_scope") if isinstance(layout, Mapping) else None
    analysis_scope = normalize_bbox(scope_value.get("bbox_px") if isinstance(scope_value, Mapping) else None) or source_bbox
    if source_bbox is None or analysis_scope is None:
        raise ValueError("panel has no valid source scope")
    name = _bounded_text(panel.get("name"), MAX_PANEL_NAME, "Panel")
    chart_type = _bounded_text(panel.get("chart_type"), 64, "unknown")
    return PanelHandoff(
        session_id=session_id,
        attachment_id=attachment_id,
        attachment_sha256=attachment_sha256,
        panel_id=panel_id or stable_panel_id(attachment_sha256, name, chart_type, source_bbox),
        revision=max(1, int(revision)),
        name=name,
        slug=panel_slug(panel.get("slug") or name),
        role=_bounded_text(panel.get("role"), 64, "region"),
        chart_type=chart_type,
        source_bbox=tuple(source_bbox),
        analysis_scope=tuple(analysis_scope),
        confidence=max(0.0, min(1.0, float(panel.get("confidence", 0.0) or 0.0))),
        status="active",
        warnings=tuple(str(item)[:160] for item in panel.get("warnings", []) if isinstance(item, str))[:MAX_PANEL_WARNINGS],
        evidence=tuple(str(item)[:96] for item in panel.get("evidence", []) if isinstance(item, str))[:MAX_PANEL_EVIDENCE],
        origin_run_id=origin_run_id,
        supersedes_panel_id=supersedes_panel_id,
    )


__all__ = [
    "ActiveSourceContext",
    "CandidateLineage",
    "PANEL_SCHEMA_VERSION",
    "PanelHandoff",
    "bbox_iou",
    "handoff_from_panel",
    "normalize_bbox",
    "panel_slug",
    "stable_panel_id",
]
