"""Shared panel-scope resolution for authorized chart observations."""

from __future__ import annotations

import copy
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from PIL import Image

from ....panels import PanelHandoff, normalize_bbox


@dataclass(frozen=True)
class ResolvedPanelScope:
    panel: PanelHandoff
    source_size: tuple[int, int]
    local_size: tuple[int, int]

    @property
    def origin(self) -> tuple[int, int]:
        return (self.panel.analysis_scope[0], self.panel.analysis_scope[1])

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self.panel.analysis_scope

    def envelope(self) -> dict[str, Any]:
        return {
            "mode": "panel",
            "panel_id": self.panel.panel_id,
            "attachment_id": self.panel.attachment_id,
            "source_image_size": list(self.source_size),
            "local_image_size": list(self.local_size),
            "source_bbox_px": list(self.panel.source_bbox),
            "analysis_scope": list(self.bbox),
            "source_origin_px": list(self.origin),
            "local_to_source": "x_source = x_local + source_origin_px[0]; y_source = y_local + source_origin_px[1]",
        }


def resolve_panel_scope(
    image_path: str,
    *,
    attachment_id: str,
    panel_id: str,
    panel_store: Any,
) -> tuple[ResolvedPanelScope | None, str | None]:
    if panel_store is None or not hasattr(panel_store, "get_panel_handoff"):
        return None, "panel scope registry is unavailable"
    try:
        with Image.open(image_path) as image:
            source_size = (image.width, image.height)
    except (OSError, ValueError):
        return None, "source image is unavailable"
    panel = panel_store.get_panel_handoff(panel_id, attachment_id=attachment_id)
    if panel is None:
        return None, f"panel scope {panel_id!r} is not registered for this attachment"
    try:
        with Image.open(image_path) as image:
            scope = normalize_bbox(panel.analysis_scope, width=image.width, height=image.height)
    except (OSError, ValueError):
        scope = None
    if scope is None:
        return None, f"panel scope {panel_id!r} has no usable analysis range"
    if tuple(scope) != tuple(panel.analysis_scope):
        return None, f"panel scope {panel_id!r} is outside the current source image"
    return ResolvedPanelScope(panel, source_size, (scope[2], scope[3])), None


def resolve_measurement_target(
    value: object,
    scope: ResolvedPanelScope,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a source-image repair target into the current panel crop."""
    if value is None:
        return None, None
    if not isinstance(value, Mapping):
        return None, "measurement target must be an object"
    from ....measurement import MeasurementTarget

    target = MeasurementTarget.from_mapping(value)
    if target is None:
        return None, "measurement target is malformed"
    if target.panel_id and target.panel_id != scope.panel.panel_id:
        return None, "measurement target does not belong to the selected panel"
    if target.source_image_size and tuple(target.source_image_size) != tuple(scope.source_size):
        return None, "measurement target source_image_size does not match the attachment"

    source_bbox = target.bbox_source_px
    if source_bbox is None and target.bbox_local_px is not None:
        # Direct sensor callers may already use local coordinates.  The
        # authorized adapter still emits the canonical source counterpart.
        source_bbox = (
            target.bbox_local_px[0] + scope.origin[0],
            target.bbox_local_px[1] + scope.origin[1],
            target.bbox_local_px[2],
            target.bbox_local_px[3],
        )
    result = target.to_dict()
    result["panel_id"] = scope.panel.panel_id
    result["source_image_size"] = list(scope.source_size)
    result["local_image_size"] = list(scope.local_size)
    result["local_to_source"] = {
        "origin_px": list(scope.origin),
        "scale": [1.0, 1.0],
        "equation": "x_source = x_local + origin_px[0]; y_source = y_local + origin_px[1]",
    }
    if source_bbox is None:
        result["bbox_px"] = None
        return result, None

    left, top, width, height = (float(item) for item in source_bbox)
    panel_left, panel_top, panel_width, panel_height = (float(item) for item in scope.bbox)
    right = min(left + width, panel_left + panel_width)
    bottom = min(top + height, panel_top + panel_height)
    clipped_left = max(left, panel_left)
    clipped_top = max(top, panel_top)
    if right <= clipped_left or bottom <= clipped_top:
        return None, "measurement target does not intersect the selected panel"
    clipped = bool(
        clipped_left != left
        or clipped_top != top
        or right != left + width
        or bottom != top + height
    )
    source_resolved = [
        round(clipped_left, 3),
        round(clipped_top, 3),
        round(right - clipped_left, 3),
        round(bottom - clipped_top, 3),
    ]
    result["bbox_source_px"] = source_resolved
    result["bbox_px"] = [
        round(clipped_left - scope.origin[0], 3),
        round(clipped_top - scope.origin[1], 3),
        round(right - clipped_left, 3),
        round(bottom - clipped_top, 3),
    ]
    result["clipped"] = clipped
    return result, None


def measurement_target_region(
    value: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
) -> list[int] | None:
    """Return a bounded local focus bbox for a sensor image."""
    if not isinstance(value, Mapping):
        return None
    raw = value.get("bbox_px") or value.get("bbox_local_px") or value.get("bbox_source_px")
    if not isinstance(raw, Sequence) or len(raw) < 4:
        return None
    try:
        left, top, box_width, box_height = (float(item) for item in raw[:4])
    except (TypeError, ValueError):
        return None
    if any(item != item or item in {float("inf"), float("-inf")} for item in (left, top, box_width, box_height)):
        return None
    right = min(float(width), left + box_width)
    bottom = min(float(height), top + box_height)
    left = max(0.0, left)
    top = max(0.0, top)
    if right <= left or bottom <= top:
        return None
    return [int(round(left)), int(round(top)), max(1, int(round(right - left))), max(1, int(round(bottom - top)))]


@contextmanager
def scoped_image_path(image_path: str, scope: ResolvedPanelScope) -> Iterator[str]:
    """Yield a short-lived local crop path for legacy image-path sensors."""
    with Image.open(image_path) as image:
        crop = image.convert("RGB").crop(
            (
                scope.bbox[0],
                scope.bbox[1],
                scope.bbox[0] + scope.bbox[2],
                scope.bbox[1] + scope.bbox[3],
            )
        )
    temporary = tempfile.NamedTemporaryFile(prefix="figura_panel_", suffix=".png", delete=False)
    temporary_path = Path(temporary.name)
    try:
        crop.save(temporary, format="PNG")
        temporary.close()
        yield str(temporary_path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def localize_layout_context(layout_context: Mapping[str, Any] | None, scope: ResolvedPanelScope) -> dict[str, Any]:
    """Translate known pixel evidence from source coordinates to crop coordinates."""
    origin_x, origin_y = scope.origin
    local_width, local_height = scope.local_size

    def translate(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {name: translate(item, name) for name, item in value.items()}
        if isinstance(value, list):
            if key in {"bbox_px", "source_bbox_px", "scope_bbox_px", "boundary_bbox_px"} and len(value) >= 4:
                return [int(value[0]) - origin_x, int(value[1]) - origin_y, int(value[2]), int(value[3])]
            if key in {"point_px", "center_px"} and len(value) >= 2:
                return [float(value[0]) - origin_x, float(value[1]) - origin_y]
            if key in {"points_px", "polygon_px", "polyline_px"}:
                return [[float(point[0]) - origin_x, float(point[1]) - origin_y] if isinstance(point, list) and len(point) >= 2 else point for point in value]
            return [translate(item, key) for item in value]
        return value

    context = copy.deepcopy(dict(layout_context or {}))
    context = translate(context)
    context["image_size"] = [local_width, local_height]
    context["source_image_size"] = list(scope.source_size)
    context["source_origin_px"] = list(scope.origin)
    context["analysis_scope"] = {
        "role": "panel_scope",
        "bbox_px": [0, 0, local_width, local_height],
        "source_bbox_px": list(scope.bbox),
        "source_origin_px": list(scope.origin),
        "confidence": scope.panel.confidence,
        "evidence": ["persisted_panel_handoff"],
    }
    panel = dict(context.get("panel") or {})
    panel.update({"id": scope.panel.panel_id, "name": scope.panel.name, "source_bbox_px": list(scope.panel.source_bbox), "scope_bbox_px": list(scope.bbox)})
    context["panel"] = panel
    context["source_attachment_id"] = scope.panel.attachment_id
    return context


def attach_source_coordinates(value: Any, scope: ResolvedPanelScope, *, key: str = "") -> Any:
    """Keep local evidence intact while adding source-coordinate counterparts."""
    origin_x, origin_y = scope.origin
    if isinstance(value, dict):
        result = {name: attach_source_coordinates(item, scope, key=name) for name, item in value.items()}
        return result
    if isinstance(value, list):
        if key in {"bbox", "bbox_px", "source_bbox_px"} and len(value) >= 4 and all(isinstance(item, (int, float)) for item in value[:4]):
            return list(value)
        if key in {"point_px", "center_px"} and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            return list(value)
        return [attach_source_coordinates(item, scope, key=key) for item in value]
    return value


def add_scope_metadata(data: Any, scope: ResolvedPanelScope) -> Any:
    """Add source bbox aliases recursively without changing existing local fields."""
    ox, oy = scope.origin

    def transform_bbox(value: Sequence[Any]) -> list[int]:
        return [int(round(float(value[0]) + ox)), int(round(float(value[1]) + oy)), int(round(float(value[2]))), int(round(float(value[3])))]

    def transform_point(value: Sequence[Any]) -> list[float]:
        return [round(float(value[0]) + ox, 3), round(float(value[1]) + oy, 3)]

    def visit(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            result = {name: visit(item, name) for name, item in value.items()}
            bbox = value.get("bbox")
            bbox_px = value.get("bbox_px")
            if isinstance(bbox, list) and len(bbox) >= 4 and all(isinstance(item, (int, float)) for item in bbox[:4]):
                result["source_bbox"] = transform_bbox(bbox)
            if isinstance(bbox_px, list) and len(bbox_px) >= 4 and all(isinstance(item, (int, float)) for item in bbox_px[:4]):
                result["source_bbox_px"] = transform_bbox(bbox_px)
            point = value.get("point_px")
            center = value.get("center_px")
            if isinstance(point, list) and len(point) >= 2 and all(isinstance(item, (int, float)) for item in point[:2]):
                result["source_point_px"] = transform_point(point)
            if isinstance(center, list) and len(center) >= 2 and all(isinstance(item, (int, float)) for item in center[:2]):
                result["source_center_px"] = transform_point(center)
            return result
        if isinstance(value, list):
            if key in {"bbox", "bbox_px"} and len(value) >= 4 and all(isinstance(item, (int, float)) for item in value[:4]):
                return list(value)
            if key in {"point_px", "center_px"} and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
                return list(value)
            return [visit(item, key) for item in value]
        return value

    result = visit(data)
    if isinstance(result, dict):
        result["scope"] = scope.envelope()
        result["source_image_size"] = list(scope.source_size)
        result["local_image_size"] = list(scope.local_size)
    return result


__all__ = [
    "ResolvedPanelScope",
    "add_scope_metadata",
    "localize_layout_context",
    "measurement_target_region",
    "resolve_measurement_target",
    "resolve_panel_scope",
    "scoped_image_path",
]
