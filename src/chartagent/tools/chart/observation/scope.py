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
    requested_attachment = value.get("attachment_id") or value.get("source_attachment_id")
    if requested_attachment is not None and str(requested_attachment) != scope.panel.attachment_id:
        return None, "measurement target does not belong to the selected attachment"
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
    if source_bbox is not None:
        source_left, source_top, source_width, source_height = (float(item) for item in source_bbox)
        if (
            source_left < 0
            or source_top < 0
            or source_left + source_width > scope.source_size[0]
            or source_top + source_height > scope.source_size[1]
        ):
            return None, "measurement target bbox is outside the selected source image"
    result = target.to_dict()
    result["panel_id"] = scope.panel.panel_id
    for key in ("attachment_id", "target_fingerprint", "resolved_refs"):
        if value.get(key) is not None:
            result[key] = value.get(key)
    result["source_image_size"] = list(scope.source_size)
    result["local_image_size"] = list(scope.local_size)
    result["local_to_source"] = {
        "origin_px": list(scope.origin),
        "scale": [1.0, 1.0],
        "equation": "x_source = x_local + origin_px[0]; y_source = y_local + origin_px[1]",
    }
    if target.polygon_source_px is not None:
        source_points = list(target.polygon_source_px[:32])
        if any(
            point[0] < 0
            or point[1] < 0
            or point[0] > scope.source_size[0]
            or point[1] > scope.source_size[1]
            for point in source_points
        ):
            return None, "measurement target polygon is outside the selected source image"
        panel_left, panel_top, panel_width, panel_height = (float(item) for item in scope.bbox)
        panel_right = panel_left + panel_width
        panel_bottom = panel_top + panel_height
        if (
            max(point[0] for point in source_points) < panel_left
            or min(point[0] for point in source_points) > panel_right
            or max(point[1] for point in source_points) < panel_top
            or min(point[1] for point in source_points) > panel_bottom
        ):
            return None, "measurement target polygon does not intersect the selected panel"
        result["polygon_source_px"] = [
            [
                round(max(panel_left, min(panel_right, point[0])), 3),
                round(max(panel_top, min(panel_bottom, point[1])), 3),
            ]
            for point in source_points
        ]
        result["polygon_px"] = [
            [
                round(max(0.0, min(float(scope.local_size[0]), point[0] - scope.origin[0])), 3),
                round(max(0.0, min(float(scope.local_size[1]), point[1] - scope.origin[1])), 3),
            ]
            for point in source_points
        ]
    raw_regions = value.get("resolved_regions_px") or value.get("regions_px")
    if isinstance(raw_regions, Sequence) and not isinstance(raw_regions, (str, bytes)):
        bounded_regions: list[list[float]] = []
        for raw_region in list(raw_regions)[:32]:
            if not isinstance(raw_region, Sequence) or isinstance(raw_region, (str, bytes)) or len(raw_region) < 4:
                continue
            try:
                local_left, local_top, local_width, local_height = (float(item) for item in raw_region[:4])
            except (TypeError, ValueError):
                continue
            local_left = max(0.0, min(float(scope.local_size[0]), local_left))
            local_top = max(0.0, min(float(scope.local_size[1]), local_top))
            local_right = max(local_left, min(float(scope.local_size[0]), local_left + max(0.0, local_width)))
            local_bottom = max(local_top, min(float(scope.local_size[1]), local_top + max(0.0, local_height)))
            if local_right > local_left and local_bottom > local_top:
                bounded_regions.append([
                    round(local_left, 3),
                    round(local_top, 3),
                    round(local_right - local_left, 3),
                    round(local_bottom - local_top, 3),
                ])
        if bounded_regions:
            result["resolved_regions_px"] = bounded_regions
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


def _scope_region_pixels(
    region: Mapping[str, Any],
    *,
    coordinate_space: str,
    scope: ResolvedPanelScope,
) -> tuple[dict[str, Any] | None, str | None]:
    """Convert one normalized first-observation region to source/local pixels."""
    raw_bbox = region.get("bbox")
    raw_polygon = region.get("polygon")
    panel_left, panel_top, panel_width, panel_height = (float(item) for item in scope.bbox)
    source_width, source_height = scope.source_size

    def bbox_from_values(values: Sequence[Any], *, normalized: bool, origin: tuple[float, float] = (0.0, 0.0)) -> list[float] | None:
        if len(values) < 4:
            return None
        try:
            left, top, width, height = (float(item) for item in values[:4])
        except (TypeError, ValueError):
            return None
        if any(item != item or item in {float("inf"), float("-inf")} for item in (left, top, width, height)) or width <= 0 or height <= 0:
            return None
        if normalized:
            if left < 0 or top < 0 or left + width > 1 or top + height > 1:
                return None
            left = panel_left + left * panel_width
            top = panel_top + top * panel_height
            width *= panel_width
            height *= panel_height
        else:
            left += origin[0]
            top += origin[1]
        return [left, top, width, height]

    if coordinate_space == "panel_norm":
        source_bbox = bbox_from_values(raw_bbox, normalized=True) if isinstance(raw_bbox, Sequence) else None
    elif coordinate_space == "panel_px":
        source_bbox = bbox_from_values(raw_bbox, normalized=False, origin=scope.origin) if isinstance(raw_bbox, Sequence) else None
    else:
        source_bbox = bbox_from_values(raw_bbox, normalized=False) if isinstance(raw_bbox, Sequence) else None
    source_points: list[list[float]] = []
    if isinstance(raw_polygon, Sequence) and not isinstance(raw_polygon, (str, bytes)):
        for point in list(raw_polygon)[:32]:
            if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) < 2:
                return None, "observation_scope polygon contains an invalid point"
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None, "observation_scope polygon contains a non-numeric point"
            if coordinate_space == "panel_norm":
                if not (0 <= x <= 1 and 0 <= y <= 1):
                    return None, "observation_scope polygon is outside panel_norm"
                x, y = panel_left + x * panel_width, panel_top + y * panel_height
            elif coordinate_space == "panel_px":
                x, y = x + scope.origin[0], y + scope.origin[1]
            source_points.append([x, y])
        if len(source_points) < 3:
            return None, "observation_scope polygon needs at least three points"
    if source_bbox is None and not source_points:
        return None, "observation_scope region has no bounded geometry"

    if source_bbox is not None:
        left, top, width, height = source_bbox
        right, bottom = left + width, top + height
        if left < panel_left or top < panel_top or right > panel_left + panel_width or bottom > panel_top + panel_height:
            return None, "observation_scope region is outside the selected panel"
        if left < 0 or top < 0 or right > source_width or bottom > source_height:
            return None, "observation_scope region is outside the source image"
    if source_points:
        if any(x < panel_left or y < panel_top or x > panel_left + panel_width or y > panel_top + panel_height for x, y in source_points):
            return None, "observation_scope polygon is outside the selected panel"
        if any(x < 0 or y < 0 or x > source_width or y > source_height for x, y in source_points):
            return None, "observation_scope polygon is outside the source image"

    result = {"role": str(region.get("role") or "geometry")[:48]}
    if source_bbox is not None:
        result["bbox_source_px"] = [round(item, 3) for item in source_bbox]
        result["bbox_px"] = [
            round(source_bbox[0] - scope.origin[0], 3),
            round(source_bbox[1] - scope.origin[1], 3),
            round(source_bbox[2], 3),
            round(source_bbox[3], 3),
        ]
    if source_points:
        result["polygon_source_px"] = [[round(x, 3), round(y, 3)] for x, y in source_points]
        result["polygon_px"] = [[round(x - scope.origin[0], 3), round(y - scope.origin[1], 3)] for x, y in source_points]
    if region.get("label"):
        result["label"] = str(region["label"])[:96]
    return result, None


def _union_regions(regions: Sequence[Mapping[str, Any]], *, source: bool = False) -> list[int] | None:
    boxes = [item.get("bbox_source_px" if source else "bbox_px") for item in regions if isinstance(item, Mapping)]
    valid = [box for box in boxes if isinstance(box, Sequence) and len(box) >= 4]
    if not valid:
        return None
    left = min(float(item[0]) for item in valid)
    top = min(float(item[1]) for item in valid)
    right = max(float(item[0]) + float(item[2]) for item in valid)
    bottom = max(float(item[1]) + float(item[3]) for item in valid)
    return [int(round(left)), int(round(top)), max(1, int(round(right - left))), max(1, int(round(bottom - top)))]


def resolve_observation_scope(
    value: object,
    scope: ResolvedPanelScope,
) -> tuple[dict[str, Any] | None, str | None]:
    """Authorize and convert a first-observation scope without creating an attempt."""
    from ....measurement import ObservationScope, observation_scope_fingerprint

    if value is None:
        return None, None
    requested = ObservationScope.from_mapping(value)
    if requested is None:
        return None, "observation_scope is malformed"
    requested_attachment = requested.attachment_id
    if requested_attachment and requested_attachment != scope.panel.attachment_id:
        return None, "observation_scope does not belong to the selected attachment"
    if requested.panel_id and requested.panel_id != scope.panel.panel_id:
        return None, "observation_scope does not belong to the selected panel"
    if not requested.include and not requested.exclude:
        return None, "observation_scope must contain at least one bounded include or exclude region"
    include: list[dict[str, Any]] = []
    exclude: list[dict[str, Any]] = []
    for raw, destination in ((requested.include, include), (requested.exclude, exclude)):
        for region in raw[:16]:
            resolved, error = _scope_region_pixels(region, coordinate_space=requested.coordinate_space, scope=scope)
            if error is not None or resolved is None:
                return None, error or "observation_scope region is invalid"
            destination.append(resolved)
    include_area = _union_regions(include)
    if include and include_area is None:
        return None, "observation_scope include regions have no usable area"
    resolved = {
        "scope_id": requested.scope_id or observation_scope_fingerprint(requested.to_dict()),
        "attachment_id": scope.panel.attachment_id,
        "panel_id": scope.panel.panel_id,
        "coordinate_space": requested.coordinate_space,
        "requested": requested.to_dict(),
        "applied": True,
        "status": "applied",
        "include": include,
        "exclude": exclude,
        "include_regions_px": [item["bbox_px"] for item in include if item.get("bbox_px") is not None],
        "exclude_regions_px": [item["bbox_px"] for item in exclude if item.get("bbox_px") is not None],
        "include_polygons_px": [item["polygon_px"] for item in include if item.get("polygon_px") is not None],
        "exclude_polygons_px": [item["polygon_px"] for item in exclude if item.get("polygon_px") is not None],
        "regions_px": [item["bbox_px"] for item in include if item.get("bbox_px") is not None],
        "polygons_px": [item["polygon_px"] for item in include if item.get("polygon_px") is not None],
        "search_area": include_area or [0, 0, scope.local_size[0], scope.local_size[1]],
        "search_scope": "scoped_include" if include_area else "panel_excluding_scope",
        "source_regions": include + exclude,
        "source_bbox_px": _union_regions(include, source=True) or list(scope.bbox),
        "objectives": list(requested.objectives),
        "reason": requested.reason,
        "overlay": {
            "panel_id": scope.panel.panel_id,
            "source_bbox_px": _union_regions(include, source=True) or list(scope.bbox),
            "include": include,
            "exclude": exclude,
        },
    }
    return resolved, None


def measurement_target_region(
    value: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
) -> list[int] | None:
    """Return a bounded local focus bbox for a sensor image."""
    regions = measurement_target_regions(value, width=width, height=height)
    if not regions:
        return None
    left = min(item[0] for item in regions)
    top = min(item[1] for item in regions)
    right = max(item[0] + item[2] for item in regions)
    bottom = max(item[1] + item[3] for item in regions)
    return [left, top, max(1, right - left), max(1, bottom - top)]


def measurement_target_regions(
    value: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
) -> list[list[int]]:
    """Return all bounded local focus regions, preserving disjoint refs."""
    if not isinstance(value, Mapping):
        return []
    raw_regions = value.get("resolved_regions_px") or value.get("regions_px")
    if not isinstance(raw_regions, Sequence) or isinstance(raw_regions, (str, bytes)):
        raw_regions = [value.get("bbox_px") or value.get("bbox_local_px") or value.get("bbox_source_px")]
    regions: list[list[int]] = []
    for raw in list(raw_regions)[:32]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 4:
            continue
        try:
            left, top, box_width, box_height = (float(item) for item in raw[:4])
        except (TypeError, ValueError):
            continue
        if any(item != item or item in {float("inf"), float("-inf")} for item in (left, top, box_width, box_height)):
            continue
        right = min(float(width), left + box_width)
        bottom = min(float(height), top + box_height)
        left = max(0.0, left)
        top = max(0.0, top)
        if right <= left or bottom <= top:
            continue
        regions.append([
            int(round(left)),
            int(round(top)),
            max(1, int(round(right - left))),
            max(1, int(round(bottom - top))),
        ])
    if not regions:
        raw_polygon = value.get("polygon_px") or value.get("polygon_source_px")
        if isinstance(raw_polygon, Sequence) and not isinstance(raw_polygon, (str, bytes)):
            points: list[tuple[float, float]] = []
            for point in list(raw_polygon)[:32]:
                if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) < 2:
                    continue
                try:
                    x, y = float(point[0]), float(point[1])
                except (TypeError, ValueError):
                    continue
                if x == x and y == y and x not in {float("inf"), float("-inf")} and y not in {float("inf"), float("-inf")}:
                    points.append((x, y))
            if len(points) >= 3:
                left = max(0, min(int(round(x)) for x, _ in points))
                top = max(0, min(int(round(y)) for _, y in points))
                right = min(width, max(int(round(x)) for x, _ in points))
                bottom = min(height, max(int(round(y)) for _, y in points))
                if right > left and bottom > top:
                    regions.append([left, top, max(1, right - left), max(1, bottom - top)])
    return regions


def measurement_focus_context(
    value: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
    base_region: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Describe an explicit include/exclude focus without widening it silently."""
    requested = isinstance(value, Mapping)
    mode = str(value.get("mode") or "include").strip().lower() if requested else "include"
    if mode not in {"include", "exclude"}:
        mode = "include"
    regions = measurement_target_regions(value, width=width, height=height) if requested else []
    base = list(base_region[:4]) if isinstance(base_region, Sequence) and len(base_region) >= 4 else [0, 0, width, height]
    base = [max(0, int(base[0])), max(0, int(base[1])), max(1, int(base[2])), max(1, int(base[3]))]
    target_refs: list[str] = []
    polygons: list[list[list[float]]] = []
    if requested:
        from ....measurement import normalize_evidence_refs

        target_refs = list(normalize_evidence_refs(value.get("resolved_refs") or value.get("refs")))
        raw_polygon = value.get("polygon_px") or value.get("polygon_source_px")
        if isinstance(raw_polygon, Sequence) and not isinstance(raw_polygon, (str, bytes)):
            points = []
            for point in list(raw_polygon)[:32]:
                if isinstance(point, Sequence) and not isinstance(point, (str, bytes)) and len(point) >= 2:
                    try:
                        x, y = float(point[0]), float(point[1])
                    except (TypeError, ValueError):
                        continue
                    if x == x and y == y and x not in {float("inf"), float("-inf")} and y not in {float("inf"), float("-inf")}:
                        points.append([round(x, 3), round(y, 3)])
            if len(points) >= 3:
                polygons.append(points)
    if not requested:
        return {
            "requested": False,
            "applied": False,
            "status": "none",
            "mode": None,
            "target_refs": [],
            "regions_px": [],
            "polygons_px": [],
            "region_px": None,
            "search_area": base,
            "search_scope": "panel_or_chart",
        }
    if not regions:
        return {
            "requested": True,
            "applied": False,
            "status": "focus_empty",
            "mode": mode,
            "target_refs": target_refs,
            "regions_px": [],
            "polygons_px": polygons,
            "region_px": None,
            "search_area": None,
            "search_scope": "target_region",
        }
    left = min(item[0] for item in regions)
    top = min(item[1] for item in regions)
    right = max(item[0] + item[2] for item in regions)
    bottom = max(item[1] + item[3] for item in regions)
    union = [left, top, max(1, right - left), max(1, bottom - top)]
    return {
        "requested": True,
        "applied": True,
        "status": "applied",
        "mode": mode,
        "target_refs": target_refs,
        "regions_px": regions,
        "polygons_px": polygons,
        "region_px": union,
        "search_area": union if mode == "include" else base,
        "search_scope": "target_region" if mode == "include" else "panel_excluding_target",
    }


def observation_scope_focus_context(
    value: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
    base_region: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Project an authorized observation scope into the sensor focus contract."""
    if not isinstance(value, Mapping):
        return {
            "requested": False,
            "applied": False,
            "status": "none",
            "mode": None,
            "target_refs": [],
            "regions_px": [],
            "polygons_px": [],
            "region_px": None,
            "search_area": list(base_region[:4]) if isinstance(base_region, Sequence) and len(base_region) >= 4 else [0, 0, width, height],
            "search_scope": "panel_or_chart",
        }
    if value.get("applied") is False or value.get("status") in {"focus_empty", "rejected", "invalid"}:
        return {
            "requested": True,
            "applied": False,
            "status": value.get("status") or "focus_empty",
            "mode": "include" if value.get("include") else "exclude",
            "target_refs": [],
            "regions_px": [],
            "polygons_px": [],
            "region_px": None,
            "search_area": None,
            "search_scope": "observation_scope",
        }
    base = list(base_region[:4]) if isinstance(base_region, Sequence) and len(base_region) >= 4 else [0, 0, width, height]
    base = [max(0, int(base[0])), max(0, int(base[1])), max(1, int(base[2])), max(1, int(base[3]))]
    include_regions = value.get("include_regions_px") or value.get("regions_px") or []
    exclude_regions = value.get("exclude_regions_px") or []
    include_polygons = value.get("include_polygons_px") or value.get("polygons_px") or []
    exclude_polygons = value.get("exclude_polygons_px") or []
    # Direct sensor callers may provide the model-facing scope without going
    # through the attachment adapter. Treat that form as local panel space;
    # the authorized adapter remains the only path that can turn source_px
    # into an actual attachment/panel authorization.
    if not include_regions and not exclude_regions and not include_polygons and not exclude_polygons:
        from ....measurement import ObservationScope

        requested = ObservationScope.from_mapping(value)
        if requested is not None:
            coordinate_space = requested.coordinate_space

            def local_bbox(region: Mapping[str, Any]) -> list[float] | None:
                raw = region.get("bbox")
                if not isinstance(raw, Sequence) or len(raw) < 4:
                    return None
                values = [float(item) for item in raw[:4]]
                if coordinate_space == "panel_norm":
                    values = [values[0] * base[2], values[1] * base[3], values[2] * base[2], values[3] * base[3]]
                return values

            def local_polygon(region: Mapping[str, Any]) -> list[list[float]] | None:
                raw = region.get("polygon")
                if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                    return None
                points = [[float(point[0]), float(point[1])] for point in raw if isinstance(point, Sequence) and len(point) >= 2]
                if coordinate_space == "panel_norm":
                    points = [[point[0] * base[2], point[1] * base[3]] for point in points]
                return points if len(points) >= 3 else None

            for source_regions, destination_regions, destination_polygons in (
                (requested.include, include_regions, include_polygons),
                (requested.exclude, exclude_regions, exclude_polygons),
            ):
                for region in source_regions:
                    bbox = local_bbox(region)
                    polygon = local_polygon(region)
                    if bbox is not None:
                        destination_regions.append(bbox)
                    if polygon is not None:
                        destination_polygons.append(polygon)
    include_regions = [list(item[:4]) for item in include_regions[:32] if isinstance(item, Sequence) and len(item) >= 4]
    exclude_regions = [list(item[:4]) for item in exclude_regions[:32] if isinstance(item, Sequence) and len(item) >= 4]
    include_polygons = [list(item) for item in include_polygons[:8] if isinstance(item, Sequence) and len(item) >= 3]
    exclude_polygons = [list(item) for item in exclude_polygons[:8] if isinstance(item, Sequence) and len(item) >= 3]
    if not include_regions and not include_polygons and not exclude_regions and not exclude_polygons:
        return {
            "requested": True,
            "applied": False,
            "status": "focus_empty",
            "mode": "include",
            "target_refs": [],
            "regions_px": [],
            "polygons_px": [],
            "region_px": None,
            "search_area": None,
            "search_scope": "observation_scope",
        }
    all_include = include_regions
    left = min((float(item[0]) for item in all_include), default=0.0)
    top = min((float(item[1]) for item in all_include), default=0.0)
    right = max((float(item[0]) + float(item[2]) for item in all_include), default=float(base[0] + base[2]))
    bottom = max((float(item[1]) + float(item[3]) for item in all_include), default=float(base[1] + base[3]))
    region = [max(0, int(round(left))), max(0, int(round(top))), max(1, int(round(right - left))), max(1, int(round(bottom - top)))]
    return {
        "requested": True,
        "applied": True,
        "status": "applied",
        "mode": "include" if include_regions or include_polygons else "exclude",
        "target_refs": [],
        "regions_px": include_regions,
        "polygons_px": include_polygons,
        "include_regions_px": include_regions,
        "exclude_regions_px": exclude_regions,
        "include_polygons_px": include_polygons,
        "exclude_polygons_px": exclude_polygons,
        "region_px": region if include_regions else None,
        "search_area": region if include_regions else base,
        "search_scope": "observation_include" if include_regions else "panel_excluding_observation",
        "scope": dict(value),
    }


def apply_measurement_focus(rgb: Any, focus: Mapping[str, Any]) -> Any:
    """Mask pixels outside/inside a focus so downstream sensors cannot rescan it."""
    if not isinstance(focus, Mapping) or not focus.get("requested") or not focus.get("applied"):
        return rgb
    regions = focus.get("regions_px")
    polygons = focus.get("polygons_px")
    include_regions = focus.get("include_regions_px") or regions
    exclude_regions = focus.get("exclude_regions_px") or []
    include_polygons = focus.get("include_polygons_px") or polygons
    exclude_polygons = focus.get("exclude_polygons_px") or []
    if (not isinstance(include_regions, list) or not include_regions) and (not isinstance(include_polygons, list) or not include_polygons) and (not exclude_regions) and (not exclude_polygons):
        return rgb
    import numpy as np
    from PIL import ImageDraw

    result = np.asarray(rgb).copy()
    height, width = result.shape[:2]
    allowed = np.zeros((height, width), dtype=bool)
    if isinstance(include_regions, list):
        for raw in include_regions[:32]:
            if not isinstance(raw, Sequence) or len(raw) < 4:
                continue
            left, top, box_width, box_height = (int(item) for item in raw[:4])
            right = min(width, max(0, left) + max(0, box_width))
            bottom = min(height, max(0, top) + max(0, box_height))
            if right > max(0, left) and bottom > max(0, top):
                allowed[max(0, top):bottom, max(0, left):right] = True
    if isinstance(include_polygons, list):
        mask = Image.new("1", (width, height), 0)
        drawer = ImageDraw.Draw(mask)
        for raw in include_polygons[:8]:
            if isinstance(raw, Sequence) and len(raw) >= 3:
                points = [
                    (max(0, min(width - 1, int(round(point[0])))), max(0, min(height - 1, int(round(point[1])))))
                    for point in raw
                    if isinstance(point, Sequence) and len(point) >= 2
                ]
                if len(points) >= 3:
                    drawer.polygon(points, fill=1)
        allowed |= np.asarray(mask, dtype=bool)
    if not include_regions and not include_polygons and (exclude_regions or exclude_polygons):
        # An exclude-only observation scope keeps the whole authorized panel
        # searchable and masks only the explicitly excluded shapes.
        allowed[:] = True
    excluded = np.zeros((height, width), dtype=bool)
    if isinstance(exclude_regions, list):
        for raw in exclude_regions[:32]:
            if not isinstance(raw, Sequence) or len(raw) < 4:
                continue
            left, top, box_width, box_height = (int(item) for item in raw[:4])
            right = min(width, max(0, left) + max(0, box_width))
            bottom = min(height, max(0, top) + max(0, box_height))
            if right > max(0, left) and bottom > max(0, top):
                excluded[max(0, top):bottom, max(0, left):right] = True
    if isinstance(exclude_polygons, list):
        mask = Image.new("1", (width, height), 0)
        drawer = ImageDraw.Draw(mask)
        for raw in exclude_polygons[:8]:
            if isinstance(raw, Sequence) and len(raw) >= 3:
                points = [
                    (max(0, min(width - 1, int(round(point[0])))), max(0, min(height - 1, int(round(point[1])))))
                    for point in raw
                    if isinstance(point, Sequence) and len(point) >= 2
                ]
                if len(points) >= 3:
                    drawer.polygon(points, fill=1)
        excluded |= np.asarray(mask, dtype=bool)
    has_include = bool(include_regions or include_polygons)
    if focus.get("mode") == "include" or has_include:
        result[~allowed | excluded] = 255
    else:
        result[excluded] = 255
    return result


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
    "apply_measurement_focus",
    "localize_layout_context",
    "measurement_focus_context",
    "observation_scope_focus_context",
    "measurement_target_region",
    "measurement_target_regions",
    "resolve_measurement_target",
    "resolve_observation_scope",
    "resolve_panel_scope",
    "scoped_image_path",
]
