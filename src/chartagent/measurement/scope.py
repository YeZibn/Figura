"""Measurement target and observation scope normalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence

from .evidence import (
    MAX_MEASUREMENT_POLYGON_POINTS,
    MAX_MEASUREMENT_REFS,
    MAX_MEASUREMENT_REGION_KIND,
    MAX_MEASUREMENT_TARGET_FIELDS,
    MAX_MEASUREMENT_TARGET_ID,
    MAX_MEASUREMENT_TEXT,
    MAX_OBSERVATION_OBJECTIVES,
    MAX_OBSERVATION_REGIONS,
    MEASUREMENT_FOCUS_MODES,
    MEASUREMENT_REGION_KINDS,
    OBSERVATION_COORDINATE_SPACES,
    OBSERVATION_REGION_ROLES,
    _bbox,
    _image_size,
    _json_safe,
    _polygon,
    _text,
    normalize_evidence_refs,
)

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


def _observation_region(value: object, *, coordinate_space: str) -> dict[str, Any] | None:
    """Normalize one model-provided observation region without inventing pixels."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = {"bbox": list(value)}
    if not isinstance(value, Mapping):
        return None
    role = _text(value.get("role") or value.get("region_kind") or value.get("regionKind") or "geometry", MAX_MEASUREMENT_REGION_KIND).lower()
    if role not in OBSERVATION_REGION_ROLES:
        role = "geometry"
    bbox_key = {
        "panel_norm": ("bbox_norm", "bbox"),
        "panel_px": ("bbox_px", "bbox_local_px", "bbox"),
        "source_px": ("bbox_source_px", "bbox_px", "bbox"),
    }.get(coordinate_space, ("bbox",))
    bbox = None
    for key in bbox_key:
        bbox = _bbox(value.get(key))
        if bbox is not None:
            break
    polygon_key = {
        "panel_norm": ("polygon_norm", "polygon"),
        "panel_px": ("polygon_px", "polygon_local_px", "polygon"),
        "source_px": ("polygon_source_px", "polygon_px", "polygon"),
    }.get(coordinate_space, ("polygon",))
    polygon = None
    for key in polygon_key:
        polygon = _polygon(value.get(key))
        if polygon is not None:
            break
    if bbox is None and polygon is None:
        return None
    if coordinate_space == "panel_norm":
        if bbox is not None and (bbox[0] + bbox[2] > 1 or bbox[1] + bbox[3] > 1):
            return None
        if polygon is not None and any(x > 1 or y > 1 for x, y in polygon):
            return None
    result: dict[str, Any] = {"role": role}
    if bbox is not None:
        result["bbox"] = [round(item, 6) for item in bbox]
    if polygon is not None:
        result["polygon"] = [[round(x, 6), round(y, 6)] for x, y in polygon[:MAX_MEASUREMENT_POLYGON_POINTS]]
    label = _text(value.get("label") or value.get("name"), 96)
    if label:
        result["label"] = label
    return result


@dataclass(frozen=True)
class ObservationScope:
    """The model's bounded first-observation request.

    Unlike ``MeasurementTarget``, this object has no parent attempt and is
    valid before a measurement session exists.  Pixel conversion and panel
    authorization happen in the chart adapter, not in the model-facing schema.
    """

    panel_id: str | None
    coordinate_space: str
    include: tuple[dict[str, Any], ...] = ()
    exclude: tuple[dict[str, Any], ...] = ()
    objectives: tuple[str, ...] = ()
    attachment_id: str | None = None
    reason: str = ""
    scope_id: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "ObservationScope | None":
        if not isinstance(value, Mapping):
            return None
        coordinate_space = str(value.get("coordinate_space") or value.get("coordinateSpace") or "panel_norm").strip().lower()
        aliases = {"normalized": "panel_norm", "panel_normalized": "panel_norm", "source": "source_px", "local_px": "panel_px"}
        coordinate_space = aliases.get(coordinate_space, coordinate_space)
        if coordinate_space not in OBSERVATION_COORDINATE_SPACES:
            return None
        raw_include = value.get("include")
        raw_exclude = value.get("exclude")
        if isinstance(raw_include, Mapping):
            raw_include = [raw_include]
        if isinstance(raw_exclude, Mapping):
            raw_exclude = [raw_exclude]
        # A direct bbox is a convenient single-include shorthand.
        if raw_include is None and any(key in value for key in ("bbox", "bbox_norm", "bbox_px", "bbox_source_px", "polygon", "polygon_norm", "polygon_px", "polygon_source_px")):
            raw_include = [value]
        include = tuple(
            region
            for raw in (raw_include if isinstance(raw_include, (list, tuple)) else ())
            if (region := _observation_region(raw, coordinate_space=coordinate_space)) is not None
        )[:MAX_OBSERVATION_REGIONS]
        exclude = tuple(
            region
            for raw in (raw_exclude if isinstance(raw_exclude, (list, tuple)) else ())
            if (region := _observation_region(raw, coordinate_space=coordinate_space)) is not None
        )[:MAX_OBSERVATION_REGIONS]
        raw_objectives = value.get("objectives") or value.get("objective") or value.get("analysis_targets") or ()
        if isinstance(raw_objectives, str):
            raw_objectives = [raw_objectives]
        objectives = tuple(_text(item, 96) for item in raw_objectives if _text(item, 96))[:MAX_OBSERVATION_OBJECTIVES] if isinstance(raw_objectives, (list, tuple)) else ()
        return cls(
            panel_id=_text(value.get("panel_id") or value.get("panelId"), 160) or None,
            coordinate_space=coordinate_space,
            include=include,
            exclude=exclude,
            objectives=objectives,
            attachment_id=_text(value.get("attachment_id") or value.get("source_attachment_id"), 160) or None,
            reason=_text(value.get("reason"), 240),
            scope_id=_text(value.get("scope_id") or value.get("scopeId"), MAX_MEASUREMENT_TARGET_ID) or None,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "scope_id": self.scope_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
            "coordinate_space": self.coordinate_space,
            "include": [dict(item) for item in self.include[:MAX_OBSERVATION_REGIONS]],
            "exclude": [dict(item) for item in self.exclude[:MAX_OBSERVATION_REGIONS]],
            "objectives": list(self.objectives[:MAX_OBSERVATION_OBJECTIVES]),
            "reason": self.reason[:MAX_MEASUREMENT_TEXT],
        }
        return result

    def fingerprint(self, *, tool: str | None = None) -> str:
        payload = self.to_dict()
        payload.pop("scope_id", None)
        payload.pop("reason", None)
        payload["tool"] = _text(tool, 80)
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
        return f"os_{digest}"


def normalize_observation_scope(value: object) -> dict[str, Any] | None:
    scope = ObservationScope.from_mapping(value)
    if scope is None:
        return None
    return scope.to_dict()


def observation_scope_fingerprint(value: object, *, tool: str | None = None) -> str | None:
    scope = ObservationScope.from_mapping(value)
    return scope.fingerprint(tool=tool) if scope is not None else None


def normalize_measurement_target(value: object) -> dict[str, Any] | None:
    """Normalize a model or adapter target without inventing a source bbox."""
    target = MeasurementTarget.from_mapping(value)
    if target is None:
        return None
    return target.to_dict()


def measurement_target_fingerprint(value: object, *, tool: str | None = None) -> str | None:
    target = MeasurementTarget.from_mapping(value)
    return target.fingerprint(tool=tool) if target is not None else None
