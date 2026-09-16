"""Model-guided chart layout hints with deterministic validation.

The layout object is deliberately a small, JSON-compatible evidence envelope.
Models provide normalized regions and semantic roles; this module converts them
to source-image coordinates and decides whether they are safe to use for
measurement.  It never turns a layout hint into chart values by itself.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

LAYOUT_CONTEXT_VERSION = 1
LAYOUT_STATUSES = frozenset({"accepted", "partial", "rejected"})
COORDINATE_SYSTEMS = frozenset({"cartesian_2d", "polar_2d", "unknown"})
ORIENTATIONS = frozenset({"upright", "horizontal", "oblique", "unknown"})
ANNOTATION_ROLES = (
    "title",
    "legend",
    "x_ticks",
    "y_ticks",
    "x_label",
    "y_label",
    "data_labels",
)


def _finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _confidence(value: object, default: float = 0.0) -> float:
    parsed = _finite(value)
    return max(0.0, min(1.0, parsed if parsed is not None else default))


def _normalized_bbox(value: object) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 4:
        return None
    values = [_finite(item) for item in value[:4]]
    if any(item is None for item in values):
        return None
    left, top, width, height = (float(item) for item in values if item is not None)
    if width <= 0 or height <= 0 or left < 0 or top < 0 or left + width > 1 or top + height > 1:
        return None
    return [round(left, 6), round(top, 6), round(width, 6), round(height, 6)]


def _pixel_bbox(bbox: Sequence[float], width: int, height: int) -> list[int]:
    left, top, box_width, box_height = bbox
    pixel_left = max(0, min(width - 1, int(round(left * width))))
    pixel_top = max(0, min(height - 1, int(round(top * height))))
    pixel_right = max(pixel_left + 1, min(width, int(round((left + box_width) * width))))
    pixel_bottom = max(pixel_top + 1, min(height, int(round((top + box_height) * height))))
    return [pixel_left, pixel_top, pixel_right - pixel_left, pixel_bottom - pixel_top]


def _normalized_points(value: object) -> list[list[float]] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    points: list[list[float]] = []
    for point in value:
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) < 2:
            return None
        x, y = _finite(point[0]), _finite(point[1])
        if x is None or y is None or not (0 <= x <= 1 and 0 <= y <= 1):
            return None
        points.append([round(x, 6), round(y, 6)])
    return points if len(points) >= 2 else None


def _pixel_points(points: Sequence[Sequence[float]], width: int, height: int) -> list[list[float]]:
    return [
        [round(max(0.0, min(width - 1.0, point[0] * width)), 3), round(max(0.0, min(height - 1.0, point[1] * height)), 3)]
        for point in points
    ]


def _axis_points(value: object) -> list[list[float]] | None:
    """Normalize nested or flat model axis endpoints into two points."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if len(value) == 4 and all(not isinstance(item, Sequence) for item in value):
        values = [_finite(item) for item in value]
        if any(item is None for item in values):
            return None
        value = [[values[0], values[1]], [values[2], values[3]]]
    return _normalized_points(value)


def _region(
    value: object,
    *,
    width: int,
    height: int,
    role: str,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    bbox = _normalized_bbox(value.get("bbox_norm", value.get("bbox")))
    if bbox is None:
        return None
    polygon = _normalized_points(value.get("polygon_norm", value.get("polygon")))
    result: dict[str, Any] = {
        "role": role,
        "bbox_norm": bbox,
        "bbox_px": _pixel_bbox(bbox, width, height),
        "confidence": _confidence(value.get("confidence"), 0.0),
        "evidence": [
            str(item)[:96]
            for item in value.get("evidence", [])
            if isinstance(item, str)
        ][:8],
    }
    if polygon:
        result["polygon_norm"] = polygon
        result["polygon_px"] = _pixel_points(polygon, width, height)
    if isinstance(value.get("text_orientation"), str):
        result["text_orientation"] = value["text_orientation"][:32]
    return result


def _axis(value: object, *, width: int, height: int, role: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    points = _axis_points(value.get("points_norm", value.get("points")))
    if not points or len(points) < 2:
        return None
    result: dict[str, Any] = {
        "role": role,
        "points_norm": points[:2],
        "points_px": _pixel_points(points[:2], width, height),
        "confidence": _confidence(value.get("confidence"), 0.0),
        "evidence": [str(item)[:96] for item in value.get("evidence", []) if isinstance(item, str)][:8],
    }
    label = value.get("label")
    if isinstance(label, str) and label.strip():
        result["label"] = label.strip()[:160]
    return result


def _axis_alias(value: object) -> dict[str, Any] | None:
    """Convert common model axis-region forms into the canonical axis shape."""
    if isinstance(value, Mapping):
        if "points_norm" in value or "points" in value:
            key = "points_norm" if "points_norm" in value else "points"
            points = _axis_points(value.get(key))
            if points is None:
                return dict(value)
            result = dict(value)
            result["points_norm"] = points
            result.pop("points", None)
            return result
        raw_bbox = value.get("bbox_norm", value.get("bbox"))
    else:
        raw_bbox = value
    if not isinstance(raw_bbox, Sequence) or isinstance(raw_bbox, (str, bytes)) or len(raw_bbox) < 4:
        return None
    values = [_finite(item) for item in raw_bbox[:4]]
    if any(item is None for item in values):
        return None
    left, top, box_width, box_height = (float(item) for item in values if item is not None)
    if box_width <= 0 or box_height <= 0:
        return None
    if box_width >= box_height:
        # An X-axis region normally sits immediately below the frame. Its
        # upper edge is the strongest positional evidence for the axis line.
        points = [[left, top], [left + box_width, top]]
    else:
        # A Y-axis region normally sits immediately left of the frame. Its
        # right edge is the strongest positional evidence for the axis line.
        points = [[left + box_width, top], [left + box_width, top + box_height]]
    return {"points_norm": points, "evidence": ["model_axis_region"]}


def _canonicalize_hint(hint: Mapping[str, Any]) -> dict[str, Any]:
    """Accept model-friendly aliases while keeping one public output schema."""
    canonical = dict(hint)

    if "measurement_frame" not in canonical and "plot_frame" not in canonical:
        plot_area = canonical.get("plot_area")
        if isinstance(plot_area, Mapping):
            canonical["measurement_frame"] = plot_area
        elif isinstance(plot_area, Sequence) and not isinstance(plot_area, (str, bytes)):
            canonical["measurement_frame"] = {"bbox_norm": list(plot_area)}

    axes = dict(canonical.get("axes")) if isinstance(canonical.get("axes"), Mapping) else {}
    for axis_name in ("x", "y"):
        existing = axes.get(axis_name)
        parsed = _axis_alias(existing) if existing is not None else None
        if parsed is None:
            alias = canonical.get(f"{axis_name}_axis")
            parsed = _axis_alias(alias)
        if parsed is not None:
            axes[axis_name] = parsed
    if axes:
        canonical["axes"] = axes

    annotation_regions = dict(canonical.get("annotation_regions")) if isinstance(canonical.get("annotation_regions"), Mapping) else {}
    for role in ANNOTATION_ROLES:
        if role not in annotation_regions and role in canonical:
            raw = canonical[role]
            if isinstance(raw, Mapping):
                annotation_regions[role] = raw
            elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                annotation_regions[role] = {"bbox_norm": list(raw)}
    if annotation_regions:
        canonical["annotation_regions"] = annotation_regions
    return canonical


def _trace_coverage(rgb: np.ndarray, bbox: Sequence[int], palette: Sequence[np.ndarray] | None) -> float | None:
    left, top, width, height = map(int, bbox)
    crop = rgb[max(0, top) : min(rgb.shape[0], top + height), max(0, left) : min(rgb.shape[1], left + width)]
    if crop.size == 0:
        return 0.0
    if palette:
        masks = []
        pixels = crop.astype(np.int16)
        for color in palette:
            target = np.asarray(color, dtype=np.int16).reshape(1, 1, 3)
            masks.append(np.max(np.abs(pixels - target), axis=2) <= 38)
        return float(np.mean(np.logical_or.reduce(masks))) if masks else 0.0
    spread = crop.max(axis=2).astype(np.int16) - crop.min(axis=2).astype(np.int16)
    return float(np.mean((spread >= 48) & (crop.min(axis=2) < 245)))


def _context_id(hint: Mapping[str, Any], image_size: Sequence[int], attachment_id: str | None) -> str:
    payload = json.dumps(
        {"hint": hint, "image_size": list(image_size), "attachment_id": attachment_id},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return f"layout_{hashlib.sha256(payload).hexdigest()[:16]}"


def _rejected_context(
    *,
    rgb: np.ndarray,
    hint: object,
    attachment_id: str | None,
    warnings: list[str],
    evidence: list[str],
) -> dict[str, Any]:
    image_dimensions = [int(rgb.shape[1]), int(rgb.shape[0])]
    normalized_hint = hint if isinstance(hint, Mapping) else {}
    return {
        "version": LAYOUT_CONTEXT_VERSION,
        "context_id": _context_id(normalized_hint, image_dimensions, attachment_id),
        "source_attachment_id": attachment_id,
        "image_size": image_dimensions,
        "coordinate_system": "unknown",
        "orientation": "unknown",
        "measurement_frame": None,
        "annotation_regions": {},
        "axes": {"x": None, "y": None},
        "polar_region": None,
        "validation": {
            "status": "rejected",
            "accepted_for_measurement": False,
            "confidence": 0.0,
            "checks": {},
            "warnings": warnings[:12],
        },
        "evidence": evidence[:12],
    }


def validate_layout_hint(
    rgb: np.ndarray,
    hint: object,
    *,
    attachment_id: str | None = None,
    palette: Sequence[np.ndarray] | None = None,
    chart_type: str | None = None,
) -> dict[str, Any]:
    """Validate a model-proposed normalized layout against source pixels."""
    image_dimensions = [int(rgb.shape[1]), int(rgb.shape[0])]
    if not isinstance(hint, Mapping):
        return _rejected_context(
            rgb=rgb,
            hint=hint,
            attachment_id=attachment_id,
            warnings=["layout hint must be a JSON object"],
            evidence=[],
        )

    hint = _canonicalize_hint(hint)
    coordinate_system = str(hint.get("coordinate_system", hint.get("coordinate_model", "unknown")))
    if coordinate_system not in COORDINATE_SYSTEMS:
        coordinate_system = "polar_2d" if chart_type == "pie" else "cartesian_2d" if chart_type in {"bar", "line", "scatter"} else "unknown"
    orientation = str(hint.get("orientation", "unknown"))
    if orientation not in ORIENTATIONS:
        orientation = "unknown"
    frame = _region(
        hint.get("measurement_frame", hint.get("plot_frame")),
        width=image_dimensions[0],
        height=image_dimensions[1],
        role="measurement_frame",
    )
    if frame is None:
        return _rejected_context(
            rgb=rgb,
            hint=hint,
            attachment_id=attachment_id,
            warnings=["measurement frame is missing or not normalized"],
            evidence=["model_layout_hint"],
        )

    warnings: list[str] = []
    evidence = ["model_layout_hint", "frame_bounds"]
    checks: dict[str, Any] = {"frame_bounds": True}
    frame_bbox = frame["bbox_px"]
    if frame_bbox[2] < max(16, image_dimensions[0] * 0.04) or frame_bbox[3] < max(16, image_dimensions[1] * 0.04):
        checks["frame_size"] = False
        warnings.append("measurement frame is too small for stable chart geometry")
    else:
        checks["frame_size"] = True

    axes_hint = hint.get("axes") if isinstance(hint.get("axes"), Mapping) else {}
    axes = {
        "x": _axis(axes_hint.get("x"), width=image_dimensions[0], height=image_dimensions[1], role="x_axis"),
        "y": _axis(axes_hint.get("y"), width=image_dimensions[0], height=image_dimensions[1], role="y_axis"),
    }
    if coordinate_system == "cartesian_2d" and axes["x"] and axes["y"]:
        x_first, x_last = axes["x"]["points_px"][:2]
        y_first, y_last = axes["y"]["points_px"][:2]
        x_vector = np.asarray(x_last, dtype=float) - np.asarray(x_first, dtype=float)
        y_vector = np.asarray(y_last, dtype=float) - np.asarray(y_first, dtype=float)
        x_length = float(np.linalg.norm(x_vector))
        y_length = float(np.linalg.norm(y_vector))
        perpendicularity = abs(float(np.dot(x_vector, y_vector))) / max(1e-6, x_length * y_length)
        checks["axis_relation"] = perpendicularity <= 0.45 and x_length >= frame_bbox[2] * 0.30 and y_length >= frame_bbox[3] * 0.30
        if checks["axis_relation"]:
            evidence.append("axis_relation")
        else:
            warnings.append("layout axes are too short or not sufficiently independent")
    elif coordinate_system == "cartesian_2d":
        checks["axis_relation"] = "partial"
        warnings.append("one or both Cartesian axes are missing from the layout hint")
    else:
        checks["axis_relation"] = "not_applicable"

    coverage = _trace_coverage(rgb, frame_bbox, palette)
    if coverage is None:
        checks["trace_coverage"] = "unavailable"
    else:
        checks["trace_coverage"] = round(coverage, 6)
        if coverage >= 0.0002:
            evidence.append("colored_trace_coverage")
        else:
            warnings.append("measurement frame has little colored trace evidence")

    annotation_values = hint.get("annotation_regions")
    if not isinstance(annotation_values, Mapping):
        annotation_values = {role: hint.get(role) for role in ANNOTATION_ROLES if hint.get(role) is not None}
    annotation_regions: dict[str, dict[str, Any]] = {}
    for role in ANNOTATION_ROLES:
        parsed = _region(annotation_values.get(role), width=image_dimensions[0], height=image_dimensions[1], role=role)
        if parsed is not None:
            annotation_regions[role] = parsed

    polar_region: dict[str, Any] | None = None
    if coordinate_system == "polar_2d":
        polar_hint = hint.get("polar_region")
        if isinstance(polar_hint, Mapping):
            raw_center = polar_hint.get("center_norm", polar_hint.get("center"))
            center_values = (
                [_finite(raw_center[0]), _finite(raw_center[1])]
                if isinstance(raw_center, Sequence) and not isinstance(raw_center, (str, bytes)) and len(raw_center) >= 2
                else [None, None]
            )
            radius = _finite(polar_hint.get("radius_norm", polar_hint.get("radius")))
            if all(value is not None and 0 <= value <= 1 for value in center_values) and radius is not None and 0 < radius <= 1:
                center = [[float(center_values[0]), float(center_values[1])]]
                polar_region = {
                    "center_norm": center[0],
                    "center_px": _pixel_points(center, image_dimensions[0], image_dimensions[1])[0],
                    "radius_norm": round(radius, 6),
                    "radius_px": round(radius * min(image_dimensions) / 2.0, 3),
                    "confidence": _confidence(polar_hint.get("confidence"), 0.0),
                }
            else:
                warnings.append("polar center or radius is missing or not normalized")

    model_confidence = _confidence(hint.get("confidence"), _confidence(frame.get("confidence"), 0.0))
    checks["model_confidence"] = round(model_confidence, 6)
    if model_confidence < 0.25:
        warnings.append("model layout confidence is below the measurement threshold")

    critical_failure = not checks["frame_bounds"] or not checks["frame_size"]
    if coordinate_system == "cartesian_2d" and checks["axis_relation"] is False and axes["x"] and axes["y"]:
        critical_failure = True
    if critical_failure:
        status = "rejected"
    elif model_confidence < 0.25 or (coverage is not None and coverage < 0.0002):
        status = "partial"
    elif warnings:
        status = "partial"
    else:
        status = "accepted"
    validation_confidence = model_confidence
    if status == "partial":
        validation_confidence *= 0.72
    elif status == "rejected":
        validation_confidence = 0.0
    context = {
        "version": LAYOUT_CONTEXT_VERSION,
        "context_id": _context_id(hint, image_dimensions, attachment_id),
        "source_attachment_id": attachment_id,
        "image_size": image_dimensions,
        "coordinate_system": coordinate_system,
        "orientation": orientation,
        "measurement_frame": frame,
        "annotation_regions": annotation_regions,
        "axes": axes,
        "polar_region": polar_region,
        "validation": {
            "status": status,
            "accepted_for_measurement": status == "accepted",
            "confidence": round(max(0.0, min(1.0, validation_confidence)), 6),
            "checks": checks,
            "warnings": warnings[:12],
        },
        "evidence": evidence[:12],
    }
    return context


def fallback_layout_context(
    rgb: np.ndarray,
    *,
    chart_type: str | None = None,
    attachment_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded non-authoritative context for sensor-only callers."""
    height, width = rgb.shape[:2]
    if chart_type == "pie":
        bbox = [0.12, 0.12, 0.76, 0.76]
        coordinate_system = "polar_2d"
    else:
        bbox = [0.11, 0.10, 0.82, 0.78]
        coordinate_system = "cartesian_2d"
    hint = {
        "coordinate_system": coordinate_system,
        "orientation": "unknown",
        "measurement_frame": {"bbox_norm": bbox, "confidence": 0.2, "evidence": ["deterministic_fallback"]},
        "confidence": 0.2,
    }
    context = validate_layout_hint(
        rgb,
        hint,
        attachment_id=attachment_id,
        chart_type=chart_type,
    )
    context["validation"]["status"] = "partial"
    context["validation"]["accepted_for_measurement"] = False
    context["validation"]["warnings"] = ["model layout hint not supplied; deterministic fallback is advisory"]
    context["validation"]["confidence"] = 0.14
    context["evidence"] = ["deterministic_fallback"]
    return context


def context_frame(context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return only a fully accepted frame for geometric measurement."""
    if not isinstance(context, Mapping):
        return None
    validation = context.get("validation")
    frame = context.get("measurement_frame")
    if (
        not isinstance(validation, Mapping)
        or validation.get("status") != "accepted"
        or not validation.get("accepted_for_measurement")
        or not isinstance(frame, Mapping)
    ):
        return None
    bbox = frame.get("bbox_px")
    if not isinstance(bbox, Sequence) or len(bbox) < 4:
        return None
    return dict(frame)


def context_region(context: Mapping[str, Any] | None, role: str) -> dict[str, Any] | None:
    if not isinstance(context, Mapping) or role not in ANNOTATION_ROLES:
        return None
    validation = context.get("validation")
    if isinstance(validation, Mapping) and validation.get("status") == "rejected":
        return None
    regions = context.get("annotation_regions")
    value = regions.get(role) if isinstance(regions, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else None


def context_for_evidence(context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Keep the public evidence context bounded and JSON-compatible."""
    if not isinstance(context, Mapping):
        return None
    validation = context.get("validation") if isinstance(context.get("validation"), Mapping) else {}
    return {
        "context_id": str(context.get("context_id", ""))[:80],
        "coordinate_system": str(context.get("coordinate_system", "unknown"))[:32],
        "orientation": str(context.get("orientation", "unknown"))[:32],
        "measurement_frame": context.get("measurement_frame"),
        "annotation_regions": context.get("annotation_regions", {}),
        "axes": context.get("axes", {"x": None, "y": None}),
        "polar_region": context.get("polar_region"),
        "validation": {
            "status": str(validation.get("status", "rejected")),
            "accepted_for_measurement": bool(validation.get("accepted_for_measurement")),
            "confidence": _confidence(validation.get("confidence")),
            "warnings": [str(item)[:160] for item in validation.get("warnings", []) if isinstance(item, str)][:12],
        },
        "evidence": [str(item)[:96] for item in context.get("evidence", []) if isinstance(item, str)][:12],
    }


__all__ = [
    "ANNOTATION_ROLES",
    "COORDINATE_SYSTEMS",
    "LAYOUT_CONTEXT_VERSION",
    "context_for_evidence",
    "context_frame",
    "context_region",
    "fallback_layout_context",
    "validate_layout_hint",
]
