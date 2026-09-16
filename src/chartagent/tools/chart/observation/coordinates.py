"""Coordinate-model helpers shared by chart-specific observation sensors."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from .foundation import bounded_source_point, color_mask, numeric_text
from .layout import context_frame

_DARK_PIXEL = 112
_MAX_AXIS_SLOPE = 0.18
_AXIS_SLOPE_STEPS = 49


def axis_scalar(point: Sequence[float], axis_points: Sequence[Sequence[float]] | None) -> float:
    """Project a source-image point onto an axis direction."""
    if not axis_points or len(axis_points) < 2:
        return float(point[0])
    origin = np.asarray(axis_points[0], dtype=float)
    direction = np.asarray(axis_points[1], dtype=float) - origin
    length = float(np.linalg.norm(direction))
    if length <= 1e-6:
        return float(point[0])
    return float(np.dot(np.asarray(point, dtype=float) - origin, direction / length))


def fit_axis_transform(
    ticks: list[dict[str, Any]],
    axis_points: Sequence[Sequence[float]] | None,
) -> dict[str, Any] | None:
    """Fit an evidence-bearing pixel-axis transform with a calibration gate."""
    if len(ticks) < 2:
        return None
    pixels = np.asarray(
        [axis_scalar(tick.get("point_px", [tick["pixel"], 0]), axis_points) for tick in ticks],
        dtype=float,
    )
    values = np.asarray([tick["value"] for tick in ticks], dtype=float)
    if len(np.unique(pixels)) < 2:
        return None
    slope, intercept = np.polyfit(pixels, values, 1)
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None
    residual = float(np.sqrt(np.mean((slope * pixels + intercept - values) ** 2)))
    value_span = max(1.0, float(np.ptp(values)))
    residual_limit = max(1.5, value_span * 0.08)
    support_span = float(np.ptp(pixels))
    confidence = (
        min(1.0, len(ticks) / 4.0)
        * min(1.0, support_span / 120.0)
        * max(0.0, min(1.0, 1.0 - residual / max(residual_limit, 1e-6)))
    )
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "residual": round(residual, 4),
        "support": len(ticks),
        "support_span_px": round(support_span, 3),
        "confidence": round(confidence, 4),
        "calibrated": bool(
            len(ticks) >= 2
            and support_span >= 40.0
            and residual <= residual_limit
            and confidence >= 0.35
        ),
        "axis_points": [list(map(float, point[:2])) for point in axis_points]
        if axis_points
        else None,
    }


def apply_axis_transform(model: dict[str, Any] | None, point: Sequence[float]) -> float | None:
    if not model or not model.get("calibrated"):
        return None
    scalar = axis_scalar(point, model.get("axis_points"))
    return round(float(model["slope"] * scalar + model["intercept"]), 6)


def _neutral_axis_line(
    rgb: np.ndarray,
    *,
    axis: str,
    search_area: Sequence[int] | None = None,
) -> dict[str, Any] | None:
    """Find a long low-saturation gray axis, including light renderer spines."""
    height, width = rgb.shape[:2]
    channels = rgb.astype(np.int16)
    brightness = channels.mean(axis=2)
    spread = channels.max(axis=2) - channels.min(axis=2)
    neutral = (spread <= 8) & (brightness >= 120) & (brightness <= 248)
    if axis == "x":
        row_start = max(0, int(height * 0.58))
        row_end = min(height, int(height * 0.97))
        col_start = max(0, int(width * 0.04))
        col_end = min(width, int(width * 0.98))
        candidates = []
        for row in range(row_start, row_end):
            indices = np.flatnonzero(neutral[row, col_start:col_end]) + col_start
            if len(indices) < width * 0.35:
                continue
            span = float(np.ptp(indices))
            if span >= width * 0.45:
                candidates.append((row, indices, span))
        if not candidates:
            return None
        row, indices, span = max(candidates, key=lambda item: (item[0], item[2]))
        fit_slope, intercept = np.polyfit(indices.astype(float), np.full(len(indices), float(row)), 1)
        residual_values = float(row) - (fit_slope * indices + intercept)
        return {
            "points_px": [[round(float(indices.min()), 2), round(float(fit_slope * indices.min() + intercept), 2)], [round(float(indices.max()), 2), round(float(fit_slope * indices.max() + intercept), 2)]],
            "slope": float(fit_slope),
            "intercept": float(intercept),
            "residual_px": round(float(np.sqrt(np.mean(residual_values**2))), 4),
            "support": int(len(indices)),
            "span_px": span,
            "source": "neutral_axis_pixels",
        }

    col_start = max(0, int(width * 0.04))
    col_end = min(width, int(width * 0.48))
    row_start = max(0, int(height * 0.05))
    row_end = min(height, int(height * 0.96))
    candidates = []
    for column in range(col_start, col_end):
        indices = np.flatnonzero(neutral[row_start:row_end, column]) + row_start
        if len(indices) < height * 0.25:
            continue
        span = float(np.ptp(indices))
        if span >= height * 0.45:
            candidates.append((column, indices, span))
    if not candidates:
        return None
    column, indices, span = min(candidates, key=lambda item: (item[0], -item[2]))
    fit_slope, intercept = np.polyfit(indices.astype(float), np.full(len(indices), float(column)), 1)
    residual_values = float(column) - (fit_slope * indices + intercept)
    return {
        "points_px": [[round(float(fit_slope * indices.min() + intercept), 2), round(float(indices.min()), 2)], [round(float(fit_slope * indices.max() + intercept), 2), round(float(indices.max()), 2)]],
        "slope": float(fit_slope),
        "intercept": float(intercept),
        "residual_px": round(float(np.sqrt(np.mean(residual_values**2))), 4),
        "support": int(len(indices)),
        "span_px": span,
        "source": "neutral_axis_pixels",
    }


def fit_dominant_axis_line(
    rgb: np.ndarray,
    *,
    axis: str,
    search_area: Sequence[int] | None = None,
) -> dict[str, Any] | None:
    """Find a long dark x or y axis and retain its source-image geometry."""
    if axis not in {"x", "y"}:
        raise ValueError("axis must be x or y")
    neutral = _neutral_axis_line(rgb, axis=axis, search_area=search_area)
    if neutral is not None:
        return neutral
    dark = np.max(rgb, axis=2) <= _DARK_PIXEL
    height, width = dark.shape
    yy, xx = np.nonzero(dark)
    if axis == "x":
        keep = (
            (xx >= int(width * 0.08))
            & (xx <= int(width * 0.97))
            & (yy >= int(height * 0.52))
            & (yy <= int(height * 0.96))
        )
    else:
        keep = (
            (xx >= int(width * 0.04))
            & (xx <= int(width * 0.46))
            & (yy >= int(height * 0.06))
            & (yy <= int(height * 0.94))
        )
    xx, yy = xx[keep].astype(float), yy[keep].astype(float)
    if len(xx) < 20:
        return None

    best: dict[str, Any] | None = None
    for slope in np.linspace(-_MAX_AXIS_SLOPE, _MAX_AXIS_SLOPE, _AXIS_SLOPE_STEPS):
        coordinate = yy - slope * xx if axis == "x" else xx - slope * yy
        rounded = np.rint(coordinate).astype(int)
        minimum = int(rounded.min())
        counts = np.bincount(rounded - minimum)
        if not len(counts):
            continue
        for candidate_bin in np.argsort(counts)[-8:]:
            support_line = minimum + int(candidate_bin)
            inliers = np.abs(coordinate - support_line) <= 1.6
            support = int(inliers.sum())
            if support < 12:
                continue
            projected = xx[inliers] if axis == "x" else yy[inliers]
            span = float(np.ptp(projected)) if len(projected) else 0.0
            minimum_span = width * 0.38 if axis == "x" else height * 0.38
            if span < minimum_span:
                continue
            expected = (
                float(search_area[1] + search_area[3])
                if axis == "x" and search_area and len(search_area) >= 4
                else float(search_area[0])
                if axis == "y" and search_area and len(search_area) >= 4
                else float(height * 0.88 if axis == "x" else width * 0.11)
            )
            distance = abs(float(np.median(projected)) - expected)
            score = span + support * 0.35 - distance * 0.65
            if best is not None and score <= best["score"]:
                continue
            if axis == "x":
                fit_slope, intercept = np.polyfit(xx[inliers], yy[inliers], 1)
                first, last = float(projected.min()), float(projected.max())
                endpoints = [
                    [round(first, 2), round(fit_slope * first + intercept, 2)],
                    [round(last, 2), round(fit_slope * last + intercept, 2)],
                ]
                residual_values = yy[inliers] - (fit_slope * xx[inliers] + intercept)
            else:
                fit_slope, intercept = np.polyfit(yy[inliers], xx[inliers], 1)
                first, last = float(projected.min()), float(projected.max())
                endpoints = [
                    [round(fit_slope * first + intercept, 2), round(first, 2)],
                    [round(fit_slope * last + intercept, 2), round(last, 2)],
                ]
                residual_values = xx[inliers] - (fit_slope * yy[inliers] + intercept)
            residual = float(np.sqrt(np.mean(residual_values**2)))
            best = {
                "points_px": endpoints,
                "slope": float(fit_slope),
                "intercept": float(intercept),
                "residual_px": round(residual, 4),
                "support": support,
                "span_px": round(span, 3),
                "score": score,
            }
    if best is not None:
        best.pop("score", None)
    return best


def axis_geometry(axis: dict[str, Any] | None) -> dict[str, Any] | None:
    if not axis:
        return None
    points = axis.get("points_px") or []
    if len(points) < 2:
        return None
    first, second = points[:2]
    dx = float(second[0]) - float(first[0])
    dy = float(second[1]) - float(first[1])
    length = max(1e-6, float(np.hypot(dx, dy)))
    return {
        "points_px": [list(map(float, point[:2])) for point in points[:2]],
        "direction": [round(dx / length, 6), round(dy / length, 6)],
        "slope": round(float(axis.get("slope", 0.0)), 8),
        "residual_px": float(axis.get("residual_px", 0.0)),
        "support": int(axis.get("support", 0)),
        "span_px": float(axis.get("span_px", 0.0)),
    }


def cartesian_frame(
    *,
    bbox: Sequence[int] | None,
    polygon: Sequence[Sequence[float]] | None = None,
    x_axis: dict[str, Any] | None = None,
    y_axis: dict[str, Any] | None = None,
    orientation: str = "unknown",
    confidence: float = 0.0,
    evidence: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Serialize a coordinate-aware Cartesian frame without mark semantics."""
    return {
        "coordinate_system": "cartesian_2d",
        "bbox_px": list(map(int, bbox[:4])) if bbox else None,
        "polygon_px": [list(map(float, point[:2])) for point in polygon or []],
        "x_axis": axis_geometry(x_axis),
        "y_axis": axis_geometry(y_axis),
        "orientation": orientation,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "evidence": list(evidence or []),
    }


def polar_frame(region: dict[str, Any] | None, *, warnings: Sequence[str] | None = None) -> dict[str, Any]:
    """Serialize a coordinate-aware polar frame from pie region evidence."""
    region = region or {}
    center = region.get("center_px") or region.get("center")
    radius = region.get("radius_px", region.get("radius"))
    bbox = region.get("bbox_px") or region.get("bbox")
    frame: dict[str, Any] = {
        "coordinate_system": "polar_2d",
        "bbox_px": list(map(int, bbox[:4])) if isinstance(bbox, (list, tuple)) and len(bbox) >= 4 else None,
        "center_px": list(map(float, center[:2])) if isinstance(center, (list, tuple)) and len(center) >= 2 else None,
        "radius_px": round(float(radius), 3) if radius is not None else None,
        "orientation": region.get("orientation", "upright"),
        "confidence": max(0.0, min(1.0, float(region.get("confidence", 0.0)))),
        "evidence": list(region.get("evidence") or []),
    }
    if warnings:
        frame["warnings"] = list(warnings)
    return frame


def _bbox_from_points(points: Sequence[Sequence[float]]) -> list[int] | None:
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    left = max(0, int(np.floor(min(xs))))
    top = max(0, int(np.floor(min(ys))))
    right = int(np.ceil(max(xs))) + 1
    bottom = int(np.ceil(max(ys))) + 1
    return [left, top, max(1, right - left), max(1, bottom - top)]


def inside_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]] | None) -> bool:
    if not polygon or len(polygon) < 3:
        return True
    values = []
    for first, second in zip(polygon, [*polygon[1:], polygon[0]]):
        values.append(
            (float(second[0]) - float(first[0])) * (float(point[1]) - float(first[1]))
            - (float(second[1]) - float(first[1])) * (float(point[0]) - float(first[0]))
        )
    return all(value >= -1.5 for value in values) or all(value <= 1.5 for value in values)


def _nearest_axis_origin(
    x_axis: dict[str, Any],
    y_axis: dict[str, Any],
) -> tuple[list[float], int, int]:
    candidates = [
        (
            float(np.hypot(x_point[0] - y_point[0], x_point[1] - y_point[1])),
            x_index,
            y_index,
            x_point,
            y_point,
        )
        for x_index, x_point in enumerate(x_axis["points_px"][:2])
        for y_index, y_point in enumerate(y_axis["points_px"][:2])
    ]
    _, x_index, y_index, x_point, y_point = min(candidates, key=lambda item: item[0])
    return [
        (float(x_point[0]) + float(y_point[0])) / 2.0,
        (float(x_point[1]) + float(y_point[1])) / 2.0,
    ], x_index, y_index


def _colored_extent(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    region: Sequence[int],
    polygon: Sequence[Sequence[float]] | None = None,
) -> list[int] | None:
    x, y, width, height = map(int, region)
    left = max(0, x)
    top = max(0, y)
    right = min(rgb.shape[1], x + width)
    bottom = min(rgb.shape[0], y + height)
    points: list[list[float]] = []
    for color in palette:
        mask = color_mask(rgb, color, tolerance=34)
        for local_y, local_x in np.argwhere(mask[top:bottom, left:right]):
            point = [float(local_x + left), float(local_y + top)]
            if inside_polygon(point, polygon):
                points.append(point)
    return _bbox_from_points(points)


def detect_cartesian_frame(
    rgb: np.ndarray,
    search_area: Sequence[int],
    palette: list[np.ndarray] | None = None,
    snippets: list[dict[str, Any]] | None = None,
    layout_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str, list[int]]:
    """Infer a source-image Cartesian frame from axes and colored evidence.

    ``search_area`` is only a bounded search hint. The returned frame is a
    coordinate adapter result and intentionally contains no chart-mark data.
    """
    height, width = rgb.shape[:2]
    palette = palette or []
    snippets = snippets or []
    accepted_layout = context_frame(layout_context)
    x_axis = fit_dominant_axis_line(rgb, axis="x", search_area=search_area)
    y_axis = fit_dominant_axis_line(rgb, axis="y", search_area=search_area)
    layout_frame: dict[str, Any] | None = None
    layout_validation = layout_context.get("validation", {}) if isinstance(layout_context, dict) else {}
    layout_checks = layout_validation.get("checks", {}) if isinstance(layout_validation, dict) else {}
    context_axes = layout_context.get("axes", {}) if isinstance(layout_context, dict) else {}
    verified_layout_axes = bool(
        accepted_layout
        and isinstance(context_axes, dict)
        and context_axes.get("x")
        and context_axes.get("y")
        and layout_checks.get("axis_relation") is True
    )
    if accepted_layout and verified_layout_axes:
        context_x = context_axes.get("x") if isinstance(context_axes, dict) else None
        context_y = context_axes.get("y") if isinstance(context_axes, dict) else None
        context_bbox = accepted_layout.get("bbox_px")
        if isinstance(context_bbox, (list, tuple)) and len(context_bbox) >= 4:
            context_polygon = accepted_layout.get("polygon_px")
            layout_frame = cartesian_frame(
                bbox=context_bbox,
                polygon=context_polygon,
                x_axis=context_x,
                y_axis=context_y,
                orientation=str(layout_context.get("orientation", "unknown")),
                confidence=float((layout_context.get("validation") or {}).get("confidence", 0.0)),
                evidence=["validated_layout_context", *list(layout_context.get("evidence") or [])[:6]],
            )
            layout_frame["bbox"] = list(map(int, context_bbox[:4]))
            layout_frame["layout_context_id"] = str(layout_context.get("context_id", ""))[:80]
            layout_frame["marker_extent_px"] = _colored_extent(rgb, palette, layout_frame["bbox"], context_polygon)
            if layout_frame["marker_extent_px"] is not None:
                layout_frame["evidence"].append("colored_extents")
    x_geometry = axis_geometry(x_axis)
    y_geometry = axis_geometry(y_axis)
    evidence = [name for name, value in (("x_axis", x_axis), ("y_axis", y_axis)) if value]

    if x_axis and y_axis:
        origin, x_origin_index, y_origin_index = _nearest_axis_origin(x_axis, y_axis)
        x_far = x_axis["points_px"][1 - x_origin_index]
        y_far = y_axis["points_px"][1 - y_origin_index]
        delta_y = [float(y_far[0]) - origin[0], float(y_far[1]) - origin[1]]
        polygon = [
            origin,
            [float(x_far[0]), float(x_far[1])],
            [float(x_far[0]) + delta_y[0], float(x_far[1]) + delta_y[1]],
            [float(y_far[0]), float(y_far[1])],
        ]
        polygon = [
            bounded_source_point(point, width=width, height=height) or [0.0, 0.0]
            for point in polygon
        ]
        bbox = _bbox_from_points(polygon) or list(map(int, search_area))
        max_slope = max(abs(float(x_axis["slope"])), abs(float(y_axis["slope"])))
        orientation = "oblique" if max_slope > 0.025 else "upright"
        confidence = min(
            1.0,
            0.45
            + min(0.3, float(x_axis["support"]) / max(1.0, width) * 0.3)
            + min(0.3, float(y_axis["support"]) / max(1.0, height) * 0.3),
        )
        frame_evidence = [*evidence, "image_boundaries"]
        marker_extent = _colored_extent(rgb, palette, search_area, polygon)
        if marker_extent is not None:
            frame_evidence.append("colored_extents")
        if any(numeric_text(str(snippet.get("text", ""))) is not None for snippet in snippets):
            frame_evidence.append("numeric_tick_ocr")
        if max_slope > 0.16:
            confidence *= 0.35
            frame_evidence.append("excessive_axis_rotation")
            orientation = "unknown"
        frame = cartesian_frame(
            bbox=bbox,
            polygon=polygon,
            x_axis=x_axis,
            y_axis=y_axis,
            orientation=orientation,
            confidence=confidence,
            evidence=frame_evidence,
        )
        frame["bbox"] = bbox
        frame["marker_extent_px"] = marker_extent
        if layout_frame is not None:
            layout_frame["independent_geometry"] = frame
            return layout_frame, layout_frame["orientation"], list(map(int, layout_frame["bbox_px"][:4]))
        return frame, orientation, bbox

    axis = x_axis or y_axis
    if axis:
        points = axis.get("points_px") or []
        bbox = _bbox_from_points(points)
        if bbox is not None:
            marker_extent = _colored_extent(rgb, palette, search_area)
            if marker_extent is not None:
                bbox = _bbox_from_points(
                    [
                        [bbox[0], bbox[1]],
                        [bbox[0] + bbox[2], bbox[1] + bbox[3]],
                        [marker_extent[0], marker_extent[1]],
                        [marker_extent[0] + marker_extent[2], marker_extent[1] + marker_extent[3]],
                    ]
                ) or bbox
            polygon = [
                [bbox[0], bbox[1]],
                [bbox[0] + bbox[2] - 1, bbox[1]],
                [bbox[0] + bbox[2] - 1, bbox[1] + bbox[3] - 1],
                [bbox[0], bbox[1] + bbox[3] - 1],
            ]
            frame = cartesian_frame(
                bbox=bbox,
                polygon=polygon,
                x_axis=x_axis,
                y_axis=y_axis,
                confidence=0.35,
                evidence=[*evidence, "colored_extents"] if marker_extent is not None else evidence,
            )
            frame["bbox"] = bbox
            frame["marker_extent_px"] = marker_extent
            if layout_frame is not None:
                layout_frame["independent_geometry"] = frame
                return layout_frame, layout_frame["orientation"], list(map(int, layout_frame["bbox_px"][:4]))
            return frame, "unknown", bbox

    marker_extent = _colored_extent(rgb, palette, search_area)
    if marker_extent is not None:
        padding = 10
        left = max(0, marker_extent[0] - padding)
        top = max(0, marker_extent[1] - padding)
        right = min(width, marker_extent[0] + marker_extent[2] + padding)
        bottom = min(height, marker_extent[1] + marker_extent[3] + padding)
        bbox = [left, top, max(1, right - left), max(1, bottom - top)]
        polygon = [
            [bbox[0], bbox[1]],
            [bbox[0] + bbox[2] - 1, bbox[1]],
            [bbox[0] + bbox[2] - 1, bbox[1] + bbox[3] - 1],
            [bbox[0], bbox[1] + bbox[3] - 1],
        ]
        frame = cartesian_frame(
            bbox=bbox,
            polygon=polygon,
            orientation="unknown",
            confidence=0.2,
            evidence=["colored_extents"],
        )
        frame["bbox"] = bbox
        frame["marker_extent_px"] = marker_extent
        if layout_frame is not None:
            layout_frame["independent_geometry"] = frame
            return layout_frame, layout_frame["orientation"], list(map(int, layout_frame["bbox_px"][:4]))
        return frame, "unknown", bbox
    if layout_frame is not None:
        layout_frame["independent_geometry"] = None
        return layout_frame, layout_frame["orientation"], list(map(int, layout_frame["bbox_px"][:4]))
    return None, "unknown", list(map(int, search_area))


def axis_output(ticks: list[dict[str, Any]], model: dict[str, Any] | None) -> dict[str, Any]:
    """Serialize ticks and fit quality using one axis result shape."""
    output: dict[str, Any] = {
        "label": None,
        "ticks": [
            {
                "pixel": round(float(tick["pixel"]), 3),
                "value": round(float(tick["value"]), 6),
                "point_px": [
                    round(float(tick["point_px"][0]), 3),
                    round(float(tick["point_px"][1]), 3),
                ],
            }
            for tick in ticks
        ],
        "calibrated": bool(model and model.get("calibrated")),
    }
    if model:
        output["transform"] = {
            "slope": round(float(model["slope"]), 8),
            "intercept": round(float(model["intercept"]), 8),
            "residual": model["residual"],
            "support": model["support"],
            "support_span_px": model["support_span_px"],
            "confidence": model["confidence"],
        }
    return output


__all__ = [
    "apply_axis_transform",
    "axis_geometry",
    "axis_output",
    "axis_scalar",
    "cartesian_frame",
    "detect_cartesian_frame",
    "fit_axis_transform",
    "fit_dominant_axis_line",
    "inside_polygon",
    "polar_frame",
]
