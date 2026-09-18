"""Deterministic geometry sensor for two-dimensional bar charts.

The sensor deliberately keeps its serialized geometry in source-image pixels.
Internally all bounding boxes use half-open intervals: ``[left, top, right,
bottom)``. The overlay is the only place that converts those coordinates to
Pillow's inclusive drawing endpoints.
"""

from __future__ import annotations

from math import exp, isfinite, sqrt
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image

from ...core.definition import Tool
from ...core.result import GeneratedImage, ToolResult
from .foundation import (
    build_common_evidence,
    cluster_centers,
    color_mask,
    confidence_map,
    detect_color_palette,
    image_size,
    rgb_to_hex,
)
from .coordinates import axis_geometry, cartesian_frame, fit_dominant_axis_line
from .layout import context_for_evidence, context_frame, context_scope
from .overlays import render_bar_overlay

Orientation = Literal["vertical", "horizontal"]


def _empty_result(
    chart_image: Image.Image,
    warnings: list[str] | None = None,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult:
    warning_list = warnings or ["no bar geometry or baseline detected"]
    rgb = np.asarray(chart_image)
    confidence = confidence_map(
        overall=0.0,
        geometry=0.0,
        calibration=0.0,
        association=0.0,
    )
    data = {
        "image_size": image_size(rgb),
        "evidence": build_common_evidence(
            rgb,
            coordinate_system="cartesian_2d",
            frame=None,
            confidence=confidence,
            warnings=warning_list,
            layout_context=context_for_evidence(layout_context),
        ),
        "orientation": "unknown",
        "bar_mode": "unknown",
        "plot_area": None,
        "baseline": None,
        "series": [],
        "bars": [],
        "confidence": confidence,
        "warnings": warning_list,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_bar_overlay(chart_image, [], None),
                "image/png",
                "No bars or baseline detected",
            ),
        ),
        tuple(warning_list),
    )


def _dominant_chart_color(rgb: np.ndarray) -> np.ndarray | None:
    """Keep the old helper available for callers that imported it directly."""
    palette = detect_color_palette(rgb, max_colors=1)
    return palette[0] if palette else None


def _contiguous_groups(indices: np.ndarray) -> list[tuple[int, int]]:
    if len(indices) == 0:
        return []
    breaks = np.where(np.diff(indices) > 1)[0]
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(indices) - 1]
    return [(int(indices[start]), int(indices[end])) for start, end in zip(starts, ends)]


def _candidate_from_region(
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    series_index: int,
    orientation: Orientation,
    density: float,
    shape_variation: float,
) -> dict[str, Any]:
    width = max(1, right - left)
    height = max(1, bottom - top)
    return {
        "_left": int(left),
        "_top": int(top),
        "_right": int(right),
        "_bottom": int(bottom),
        "_width": width,
        "_height": height,
        "_center_x": (left + right) / 2.0,
        "_center_y": (top + bottom) / 2.0,
        "_series_index": int(series_index),
        "_orientation": orientation,
        "_density": float(density),
        "_shape_variation": float(shape_variation),
    }


def _projection_candidates(
    mask: np.ndarray,
    series_index: int,
    orientation: Orientation,
) -> list[dict[str, Any]]:
    """Extract filled bar-like regions from one palette color."""
    height, width = mask.shape
    minimum_area = max(80, int(height * width * 0.0001))
    minimum_span = max(5, int(round(min(height, width) * 0.008)))
    candidates: list[dict[str, Any]] = []

    if orientation == "vertical":
        minimum_active = max(3, int(round(height * 0.01)))
        active_primary = np.flatnonzero(mask.sum(axis=0) >= minimum_active)
        primary_groups = _contiguous_groups(active_primary)
        for primary_start, primary_end in primary_groups:
            left = primary_start
            right = primary_end + 1
            width_px = right - left
            if width_px < minimum_span:
                continue
            region = mask[:, left:right]
            active_secondary = np.flatnonzero(
                region.sum(axis=1) >= max(2, int(round(width_px * 0.45)))
            )
            for secondary_start, secondary_end in _contiguous_groups(active_secondary):
                top = secondary_start
                bottom = secondary_end + 1
                height_px = bottom - top
                area = int(mask[top:bottom, left:right].sum())
                if height_px < minimum_span or width_px * height_px < minimum_area:
                    continue
                density = area / float(width_px * height_px)
                if density < 0.35:
                    continue
                row_spans = region[secondary_start : secondary_end + 1].sum(axis=1)
                shape_variation = (
                    float(np.percentile(row_spans, 95) - np.percentile(row_spans, 5))
                    / max(1.0, float(width_px))
                )
                candidates.append(
                    _candidate_from_region(
                        left=left,
                        top=top,
                        right=right,
                        bottom=bottom,
                        series_index=series_index,
                        orientation=orientation,
                        density=density,
                        shape_variation=shape_variation,
                    )
                )
    else:
        minimum_active = max(3, int(round(width * 0.01)))
        active_primary = np.flatnonzero(mask.sum(axis=1) >= minimum_active)
        primary_groups = _contiguous_groups(active_primary)
        for primary_start, primary_end in primary_groups:
            top = primary_start
            bottom = primary_end + 1
            height_px = bottom - top
            if height_px < minimum_span:
                continue
            region = mask[top:bottom, :]
            active_secondary = np.flatnonzero(
                region.sum(axis=0) >= max(2, int(round(height_px * 0.45)))
            )
            for secondary_start, secondary_end in _contiguous_groups(active_secondary):
                left = secondary_start
                right = secondary_end + 1
                width_px = right - left
                area = int(mask[top:bottom, left:right].sum())
                if width_px < minimum_span or width_px * height_px < minimum_area:
                    continue
                density = area / float(width_px * height_px)
                if density < 0.35:
                    continue
                column_spans = region[:, secondary_start : secondary_end + 1].sum(axis=0)
                shape_variation = (
                    float(np.percentile(column_spans, 95) - np.percentile(column_spans, 5))
                    / max(1.0, float(height_px))
                )
                candidates.append(
                    _candidate_from_region(
                        left=left,
                        top=top,
                        right=right,
                        bottom=bottom,
                        series_index=series_index,
                        orientation=orientation,
                        density=density,
                        shape_variation=shape_variation,
                    )
                )
    return candidates


def _bar_candidates(
    rgb: np.ndarray,
    color: np.ndarray,
    series_index: int,
    plot_area: list[int] | None = None,
    *,
    orientation: Orientation = "vertical",
) -> list[dict[str, Any]]:
    """Return bar candidates scoped to the supplied measurement frame."""
    mask = color_mask(rgb, color, tolerance=28)
    if plot_area is not None:
        left, top, width, height = map(int, plot_area)
        scoped = np.zeros_like(mask)
        right = min(mask.shape[1], left + width)
        bottom = min(mask.shape[0], top + height)
        if right > left and bottom > top:
            scoped[max(0, top) : bottom, max(0, left) : right] = mask[max(0, top) : bottom, max(0, left) : right]
        mask = scoped
    return _projection_candidates(
        mask, series_index, orientation
    )


def _orientation_score(candidates: list[dict[str, Any]], orientation: Orientation) -> float:
    if not candidates:
        return float("-inf")
    scores = []
    for candidate in candidates:
        width = candidate["_width"]
        height = candidate["_height"]
        if orientation == "vertical":
            scores.append(np.log((height + 1.0) / (width + 1.0)))
        else:
            scores.append(np.log((width + 1.0) / (height + 1.0)))
    return float(np.median(scores)) + min(0.1, len(candidates) * 0.01)


def _has_category_overlap(
    first: dict[str, Any],
    second: dict[str, Any],
    orientation: Orientation,
) -> bool:
    if orientation == "vertical":
        overlap = min(first["_right"], second["_right"]) - max(
            first["_left"], second["_left"]
        )
        return overlap >= 0.5 * min(first["_width"], second["_width"])
    overlap = min(first["_bottom"], second["_bottom"]) - max(
        first["_top"], second["_top"]
    )
    return overlap >= 0.5 * min(first["_height"], second["_height"])


def _assign_categories(
    candidates: list[dict[str, Any]],
    orientation: Orientation,
    stacked: bool,
) -> None:
    centers = [
        candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"]
        for candidate in candidates
    ]
    if not centers:
        return
    if stacked:
        category_centers = cluster_centers(centers, gap=12.0)
    elif len({candidate["_series_index"] for candidate in candidates}) > 1:
        category_centers = cluster_centers(centers)
    else:
        category_centers = sorted(centers)
    for candidate in candidates:
        center = candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"]
        candidate["_category_index"] = min(
            range(len(category_centers)),
            key=lambda index: abs(category_centers[index] - center),
        ) + 1


def _plot_bbox(candidates: list[dict[str, Any]]) -> list[int] | None:
    if not candidates:
        return None
    left = min(candidate["_left"] for candidate in candidates)
    top = min(candidate["_top"] for candidate in candidates)
    right = max(candidate["_right"] for candidate in candidates)
    bottom = max(candidate["_bottom"] for candidate in candidates)
    return [left, top, max(1, right - left), max(1, bottom - top)]


def _axis_hint(
    rgb: np.ndarray,
    candidates: list[dict[str, Any]],
    orientation: Orientation,
) -> float | None:
    """Find a strong dark axis line near the candidate plot region."""
    if not candidates:
        return None
    height, width = rgb.shape[:2]
    left = max(0, min(candidate["_left"] for candidate in candidates) - 28)
    right = min(width, max(candidate["_right"] for candidate in candidates) + 28)
    top = max(0, min(candidate["_top"] for candidate in candidates) - 28)
    bottom = min(height, max(candidate["_bottom"] for candidate in candidates) + 28)
    dark = np.all(rgb < 80, axis=2)
    if orientation == "vertical":
        support = dark[top:bottom, left:right].sum(axis=1)
        minimum = max(12, int((right - left) * 0.35))
        if len(support) and int(support.max()) >= minimum:
            return float(top + int(np.argmax(support)))
    else:
        support = dark[top:bottom, left:right].sum(axis=0)
        minimum = max(12, int((bottom - top) * 0.35))
        if len(support) and int(support.max()) >= minimum:
            return float(left + int(np.argmax(support)))
    return None


def _visible_axis_reference(
    rgb: np.ndarray,
    candidates: list[dict[str, Any]],
    orientation: Orientation,
    search_area: list[int] | None = None,
    strict_search_area: bool = False,
) -> dict[str, Any] | None:
    """Return visible zero-axis evidence in the same scalar space as bars."""
    if not candidates:
        return None
    axis = fit_dominant_axis_line(
        rgb,
        axis="x" if orientation == "vertical" else "y",
        search_area=search_area,
        strict_search_area=strict_search_area,
    )
    if axis is None:
        return None
    return {
        "points_px": axis["points_px"],
        "slope": float(axis["slope"]),
        "intercept": float(axis["intercept"]),
        "residual_px": float(axis["residual_px"]),
        "support": int(axis["support"]),
        "span_px": float(axis["span_px"]),
        "source": "visible_axis",
    }


def _line_fit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    coordinates = np.asarray(points, dtype=float)
    if float(np.ptp(coordinates[:, 0])) < 1e-6:
        return None
    design = np.column_stack((coordinates[:, 0], np.ones(len(coordinates))))
    slope, intercept = np.linalg.lstsq(design, coordinates[:, 1], rcond=None)[0]
    return float(slope), float(intercept)


def _edge_points(
    candidates: list[dict[str, Any]], orientation: Orientation
) -> list[list[tuple[float, float, str]]]:
    edges: list[list[tuple[float, float, str]]] = []
    for candidate in candidates:
        if orientation == "vertical":
            coordinate = candidate["_center_x"]
            edges.append(
                [
                    (coordinate, float(candidate["_top"]), "start"),
                    (coordinate, float(candidate["_bottom"]), "end"),
                ]
            )
        else:
            coordinate = candidate["_center_y"]
            edges.append(
                [
                    (coordinate, float(candidate["_left"]), "start"),
                    (coordinate, float(candidate["_right"]), "end"),
                ]
            )
    return edges


def _fit_baseline(
    candidates: list[dict[str, Any]],
    orientation: Orientation,
    axis_hint: float | None,
    *,
    prefer_outer: bool = False,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    edges = _edge_points(candidates, orientation)
    tolerance = max(
        2.5,
        float(
            np.median(
                [
                    min(candidate["_width"], candidate["_height"]) * 0.04
                    for candidate in candidates
                ]
            )
        ),
    )
    lines: list[tuple[float, float]] = []
    family_lines: dict[str, tuple[tuple[float, float], float, float]] = {}
    flattened = [edge for candidate_edges in edges for edge in candidate_edges]
    if len(candidates) == 1:
        edge = flattened[1 if orientation == "vertical" else 0]
        lines.append((0.0, edge[1]))
    else:
        for first_index, first in enumerate(flattened):
            for second in flattened[first_index + 1 :]:
                if abs(first[0] - second[0]) < 1e-6:
                    continue
                fitted = _line_fit([(first[0], first[1]), (second[0], second[1])])
                if fitted is not None:
                    lines.append(fitted)
        for edge_name in ("start", "end"):
            family_points = [
                (
                    candidate_edges[0][0],
                    candidate_edges[0 if edge_name == "start" else 1][1],
                )
                for candidate_edges in edges
            ]
            fitted = _line_fit(family_points)
            if fitted is not None:
                lines.append(fitted)
                family_residual = float(
                    np.sqrt(
                        np.mean(
                            [
                                (value - (fitted[0] * coordinate + fitted[1])) ** 2
                                for coordinate, value in family_points
                            ]
                        )
                    )
                )
                family_mean = float(np.mean([value for _, value in family_points]))
                family_lines[edge_name] = (fitted, family_residual, family_mean)
    if not lines:
        return None

    preferred_family: str | None = None
    valid_families = {
        name: details
        for name, details in family_lines.items()
        if details[1] <= tolerance
    }
    if valid_families and axis_hint is None:
        preferred_family = max(
            valid_families,
            key=lambda name: (
                valid_families[name][2]
                if orientation == "vertical"
                else -valid_families[name][2]
            ),
        )

    def evaluate(line: tuple[float, float]) -> tuple[tuple[float, ...], float]:
        slope, intercept = line
        residuals: list[float] = []
        for candidate_edges in edges:
            distances = [
                abs(edge_value - (slope * coordinate + intercept))
                for coordinate, edge_value, _ in candidate_edges
            ]
            residuals.append(float(min(distances)))
        inliers = [residual for residual in residuals if residual <= tolerance]
        median_residual = float(np.median(inliers)) if inliers else float("inf")
        coordinates = [
            candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"]
            for candidate in candidates
        ]
        mean_value = float(np.mean([slope * coordinate + intercept for coordinate in coordinates]))
        hint_score = (
            -float(
                np.mean(
                    [
                        abs(slope * coordinate + intercept - axis_hint)
                        for coordinate in coordinates
                    ]
                )
            )
            if axis_hint is not None
            else 0.0
        )
        direction_score = mean_value if orientation == "vertical" else -mean_value
        if axis_hint is not None or prefer_outer:
            key = (
                hint_score if axis_hint is not None else direction_score,
                -abs(slope),
                float(len(inliers)),
                -median_residual,
                direction_score,
            )
        else:
            key = (
                float(len(inliers)),
                -median_residual,
                hint_score,
                direction_score,
            )
        return key, median_residual

    best_line: tuple[float, float] | None = (
        valid_families[preferred_family][0] if preferred_family else None
    )
    best_key: tuple[float, ...] | None = None
    if best_line is None:
        for line in lines:
            key, _ = evaluate(line)
            if best_key is None or key > best_key:
                best_key = key
                best_line = line
    if best_line is None:
        return None

    slope, intercept = best_line
    selected_points: list[tuple[float, float]] = []
    selected_edges: list[str] = []
    residuals: list[float] = []
    for candidate_edges in edges:
        distances = [
            abs(edge_value - (slope * coordinate + intercept))
            for coordinate, edge_value, _ in candidate_edges
        ]
        selected_index = int(np.argmin(distances))
        coordinate, edge_value, edge_name = candidate_edges[selected_index]
        if distances[selected_index] <= tolerance:
            selected_points.append((coordinate, edge_value))
        selected_edges.append(edge_name)
        residuals.append(float(distances[selected_index]))
    refit = _line_fit(selected_points)
    if refit is not None:
        slope, intercept = refit
        residuals = []
        selected_edges = []
        for candidate_edges in edges:
            distances = [
                abs(edge_value - (slope * coordinate + intercept))
                for coordinate, edge_value, _ in candidate_edges
            ]
            selected_index = int(np.argmin(distances))
            selected_edges.append(candidate_edges[selected_index][2])
            residuals.append(float(distances[selected_index]))

    inlier_count = sum(residual <= tolerance for residual in residuals)
    fit_residuals = [residual for residual in residuals if residual <= tolerance]
    residual = (
        float(np.sqrt(np.mean(np.square(fit_residuals))))
        if fit_residuals
        else float("inf")
    )
    if inlier_count == 0:
        return None
    if orientation == "vertical":
        first_coordinate = float(min(candidate["_left"] for candidate in candidates))
        last_coordinate = float(max(candidate["_right"] for candidate in candidates))
    else:
        first_coordinate = float(min(candidate["_top"] for candidate in candidates))
        last_coordinate = float(max(candidate["_bottom"] for candidate in candidates))
    first_value = slope * first_coordinate + intercept
    last_value = slope * last_coordinate + intercept
    if orientation == "vertical":
        points = [
            [int(round(first_coordinate)), int(round(first_value))],
            [int(round(last_coordinate)), int(round(last_value))],
        ]
        axis_name = "y"
    else:
        points = [
            [int(round(first_value)), int(round(first_coordinate))],
            [int(round(last_value)), int(round(last_coordinate))],
        ]
        axis_name = "x"
    coverage = inlier_count / max(1, len(candidates))
    if prefer_outer:
        coverage = max(coverage, 0.75)
    confidence = coverage * exp(-min(4.0, residual) / 4.0)
    if len(candidates) == 1:
        confidence = min(confidence, 0.68)
    return {
        "points_px": points,
        "axis": axis_name,
        "slope": slope,
        "intercept": intercept,
        "residual_px": round(residual, 3),
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "_selected_edges": selected_edges,
        "_tolerance": tolerance,
    }


def _baseline_value(baseline: dict[str, Any], candidate: dict[str, Any], orientation: Orientation) -> float:
    coordinate = candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"]
    return float(baseline["slope"] * coordinate + baseline["intercept"])


def _candidate_value_length(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    orientation: Orientation,
    stacked: bool,
) -> float | None:
    base = _baseline_value(baseline, candidate, orientation)
    selected_edge = candidate.get("_baseline_edge")
    residual_limit = max(4.0, float(baseline["residual_px"]) + 3.0)
    if orientation == "vertical":
        start = float(candidate["_top"])
        end = float(candidate["_bottom"])
        if stacked:
            length = (end - start) / sqrt(1.0 + float(baseline["slope"]) ** 2)
            center = (start + end) / 2.0
            sign = 1.0 if center < base else -1.0
            return round(sign * length, 3)
        if selected_edge == "end":
            if abs(end - base) > residual_limit:
                return None
            return round((base - start) / sqrt(1.0 + float(baseline["slope"]) ** 2), 3)
        if selected_edge == "start":
            if abs(start - base) > residual_limit:
                return None
            return round(-(end - base) / sqrt(1.0 + float(baseline["slope"]) ** 2), 3)
    else:
        start = float(candidate["_left"])
        end = float(candidate["_right"])
        if stacked:
            length = (end - start) / sqrt(1.0 + float(baseline["slope"]) ** 2)
            center = (start + end) / 2.0
            sign = 1.0 if center > base else -1.0
            return round(sign * length, 3)
        if selected_edge == "start":
            if abs(start - base) > residual_limit:
                return None
            return round((end - base) / sqrt(1.0 + float(baseline["slope"]) ** 2), 3)
        if selected_edge == "end":
            if abs(end - base) > residual_limit:
                return None
            return round(-(base - start) / sqrt(1.0 + float(baseline["slope"]) ** 2), 3)
    return None


def _geometry(candidate: dict[str, Any]) -> dict[str, Any]:
    left, top = candidate["_left"], candidate["_top"]
    right, bottom = candidate["_right"], candidate["_bottom"]
    return {
        "bbox_px": [left, top, right - left, bottom - top],
        "polygon_px": [[left, top], [right, top], [right, bottom], [left, bottom]],
    }


def _stack_evidence(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
    orientation: Orientation,
) -> dict[int, dict[str, Any]]:
    evidence: dict[int, dict[str, Any]] = {}
    for category_index in sorted({candidate["_category_index"] for candidate in candidates}):
        members = [
            candidate
            for candidate in candidates
            if candidate["_category_index"] == category_index
        ]
        left = min(candidate["_left"] for candidate in members)
        top = min(candidate["_top"] for candidate in members)
        right = max(candidate["_right"] for candidate in members)
        bottom = max(candidate["_bottom"] for candidate in members)
        base = _baseline_value(baseline, members[0], orientation)
        if orientation == "vertical":
            outer = (
                min(candidate["_top"] for candidate in members)
                if base >= top
                else max(candidate["_bottom"] for candidate in members)
            )
            total_length = abs(base - outer) / sqrt(1.0 + float(baseline["slope"]) ** 2)
            members.sort(key=lambda candidate: candidate["_top"])
        else:
            outer = (
                max(candidate["_right"] for candidate in members)
                if base <= right
                else min(candidate["_left"] for candidate in members)
            )
            total_length = abs(base - outer) / sqrt(1.0 + float(baseline["slope"]) ** 2)
            members.sort(key=lambda candidate: candidate["_left"])
        total_geometry = {
            "bbox_px": [left, top, right - left, bottom - top],
            "polygon_px": [[left, top], [right, top], [right, bottom], [left, bottom]],
        }
        evidence[category_index] = {
            "members": members,
            "total_length_px": round(total_length, 3),
            "total_geometry": total_geometry,
        }
    return evidence


def _measure_chart(
    rgb: np.ndarray,
    layout_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout = context_frame(layout_context)
    scope = context_scope(layout_context)
    measurement_area = layout.get("bbox_px") if layout else None
    search_area = measurement_area or (scope.get("bbox_px") if scope else None)
    palette = detect_color_palette(rgb, region=search_area, max_colors=8)
    vertical_candidates: list[dict[str, Any]] = []
    horizontal_candidates: list[dict[str, Any]] = []
    for series_index, color in enumerate(palette, start=1):
        vertical_candidates.extend(_bar_candidates(rgb, color, series_index, search_area, orientation="vertical"))
        horizontal_candidates.extend(_bar_candidates(rgb, color, series_index, search_area, orientation="horizontal"))
    vertical_score = _orientation_score(vertical_candidates, "vertical")
    horizontal_score = _orientation_score(horizontal_candidates, "horizontal")
    if not vertical_candidates and not horizontal_candidates:
        return {
            "candidates": [],
            "orientation": "unknown",
            "bar_mode": "unknown",
            "baseline": None,
            "plot_area": None,
            "palette": palette,
            "warnings": ["no bar geometry or baseline detected"],
            "layout_context": layout_context,
        }
    orientation: Orientation = "vertical" if vertical_score >= horizontal_score else "horizontal"
    candidates = vertical_candidates if orientation == "vertical" else horizontal_candidates
    stacked = any(
        first["_series_index"] != second["_series_index"]
        and _has_category_overlap(first, second, orientation)
        for position, first in enumerate(candidates)
        for second in candidates[position + 1 :]
    )
    _assign_categories(candidates, orientation, stacked)
    candidates.sort(
        key=lambda candidate: (
            candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"],
            candidate["_top"] if orientation == "vertical" else candidate["_left"],
            candidate["_series_index"],
        )
    )
    baseline = _fit_baseline(
        candidates,
        orientation,
        _axis_hint(rgb, candidates, orientation),
        prefer_outer=stacked,
    )
    warnings: list[str] = []
    visible_axis = _visible_axis_reference(
        rgb,
        candidates,
        orientation,
        search_area,
        strict_search_area=scope is not None,
    )
    baseline_cross_check: dict[str, Any] | None = None
    if baseline is not None and visible_axis is not None:
        residuals = []
        for candidate in candidates:
            coordinate = candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"]
            baseline_value = float(baseline["slope"] * coordinate + baseline["intercept"])
            visible_value = float(visible_axis["slope"] * coordinate + visible_axis["intercept"])
            residuals.append(abs(baseline_value - visible_value))
        cross_residual = float(np.sqrt(np.mean(np.square(residuals)))) if residuals else 0.0
        cross_limit = max(float(baseline["_tolerance"]), float(visible_axis["residual_px"]) + 3.0)
        baseline_cross_check = {
            "source": "visible_axis_cross_check",
            "visible_axis": visible_axis,
            "residual_px": round(cross_residual, 3),
            "tolerance_px": round(cross_limit, 3),
            "consistent": bool(cross_residual <= cross_limit),
        }
        if not baseline_cross_check["consistent"]:
            warnings.append("bar baseline disagrees with visible zero-axis evidence")
    if abs(vertical_score - horizontal_score) < 0.12:
        warnings.append("bar orientation is ambiguous; geometry confidence is reduced")
    if len({candidate["_series_index"] for candidate in candidates}) > 1:
        warnings.append("series labels unresolved; using stable color-based identities")
    if baseline is None:
        warnings.append("zero baseline is ambiguous; signed measurements omitted")
    elif baseline["confidence"] < 0.55 or baseline["residual_px"] > baseline["_tolerance"]:
        warnings.append("baseline fit is uncertain; measurements may be partial")
        if baseline["confidence"] < 0.45 or baseline["residual_px"] > baseline["_tolerance"] * 2:
            baseline = None
            warnings.append("unsupported perspective or 3D-like bar geometry detected")
    if any(candidate["_density"] < 0.72 for candidate in candidates):
        warnings.append("bar fill geometry is irregular; perspective or 3D styling may be unsupported")
    if any(candidate["_shape_variation"] > 0.35 for candidate in candidates):
        warnings.append("bar edge width changes materially; perspective or 3D styling may be unsupported")
    if any(candidate["_shape_variation"] > 0.48 for candidate in candidates):
        baseline = None
        warnings.append("unsupported perspective or 3D-like bar geometry detected")
    plot_area = measurement_area or _plot_bbox(candidates)
    slope = abs(float(baseline["slope"])) if baseline else 0.0
    resolved_orientation = "oblique" if slope > 0.025 else orientation
    if baseline is None and len(candidates) < 2:
        resolved_orientation = "unknown"
    bar_mode = "stacked" if stacked else (
        "grouped" if len({candidate["_series_index"] for candidate in candidates}) > 1 else "single"
    )
    return {
        "candidates": candidates,
        "orientation": resolved_orientation,
        "axis_orientation": orientation,
        "bar_mode": bar_mode,
        "baseline": baseline,
        "baseline_cross_check": baseline_cross_check,
        "plot_area": plot_area,
        "palette": palette,
        "warnings": warnings,
        "layout_context": layout_context,
    }


def measure_bars(
    image_path: str,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult | dict:
    """Measure two-dimensional bars with source-image geometry evidence."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}

    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"measure_bars failed for {image_path}: {exc}"}

    measured = _measure_chart(rgb, layout_context)
    candidates = measured["candidates"]
    baseline = measured["baseline"]
    if not candidates:
        return _empty_result(chart_image, measured["warnings"], layout_context)

    orientation: Orientation = measured.get("axis_orientation", "vertical")
    stacked = measured["bar_mode"] == "stacked"
    if baseline is not None:
        for candidate, selected_edge in zip(candidates, baseline["_selected_edges"]):
            candidate["_baseline_edge"] = selected_edge

    values = [
        _candidate_value_length(candidate, baseline, orientation, stacked)
        if baseline is not None
        else None
        for candidate in candidates
    ]
    finite_values = [
        abs(value)
        for value in values
        if value is not None and isfinite(value) and abs(value) > 0
    ]
    shortest = min(finite_values) if finite_values else None
    stack_evidence = _stack_evidence(candidates, baseline, orientation) if stacked and baseline else {}
    palette_map = {index: color for index, color in enumerate(measured["palette"], start=1)}
    series = [
        {
            "id": f"series_{index}",
            "label": None,
            "color": rgb_to_hex(palette_map[index]),
        }
        for index in sorted({candidate["_series_index"] for candidate in candidates})
        if index in palette_map
    ]
    bars: list[dict[str, Any]] = []
    for index, (candidate, value) in enumerate(zip(candidates, values), start=1):
        ratio = abs(value) / shortest if value is not None and shortest else None
        bar: dict[str, Any] = {
            "id": index,
            "category_index": candidate["_category_index"],
            "series_id": f"series_{candidate['_series_index']}",
            "geometry": _geometry(candidate),
            "measure": {
                "value_length_px": value,
                "ratio": round(ratio, 6) if ratio is not None else None,
            },
        }
        if stacked and candidate["_category_index"] in stack_evidence:
            stack = stack_evidence[candidate["_category_index"]]
            segment_index = stack["members"].index(candidate) + 1
            bar["stack"] = {
                "segment_index": segment_index,
                "total_length_px": stack["total_length_px"],
                "total_geometry": stack["total_geometry"],
            }
        bars.append(bar)

    warnings = list(measured["warnings"])
    if isinstance(layout_context, dict):
        validation = layout_context.get("validation") if isinstance(layout_context.get("validation"), dict) else {}
        if validation.get("status") == "rejected":
            warnings.append("layout context rejected; using bar pixel evidence fallback")
        elif validation.get("status") == "partial":
            warnings.append("layout context partially validated; bar geometry remains partial")
    if baseline is None:
        for bar in bars:
            bar["measure"]["value_length_px"] = None
            bar["measure"]["ratio"] = None
    confidence_overall = 0.0 if baseline is None else min(0.96, 0.72 + baseline["confidence"] * 0.24)
    if warnings:
        confidence_overall *= 0.9
    confidence = confidence_map(
        overall=confidence_overall,
        geometry=0.9 if candidates else 0.0,
        calibration=0.0,
        association=0.8 if len(series) == 1 else 0.62,
    )
    frame = (
        cartesian_frame(
            bbox=measured["plot_area"],
            x_axis=(measured["baseline_cross_check"] or {}).get("visible_axis")
            if orientation == "vertical" and measured.get("baseline_cross_check")
            else (baseline if orientation == "vertical" else None),
            y_axis=(measured["baseline_cross_check"] or {}).get("visible_axis")
            if orientation == "horizontal" and measured.get("baseline_cross_check")
            else (baseline if orientation == "horizontal" else None),
            orientation=measured["orientation"],
            confidence=confidence_overall,
            evidence=["bar_geometry", "baseline"] if baseline else ["bar_geometry"],
        )
        if measured["plot_area"]
        else None
    )
    independent_frame = frame
    layout_frame = context_frame(layout_context)
    if layout_frame is not None:
        frame = dict(layout_frame)
        frame["bbox"] = list(map(int, layout_frame["bbox_px"][:4]))
        frame["coordinate_system"] = "cartesian_2d"
        context_axes = ((layout_context.get("axes") or {}) if isinstance(layout_context, dict) else {})
        frame["x_axis"] = axis_geometry(context_axes.get("x")) if isinstance(context_axes, dict) else None
        frame["y_axis"] = axis_geometry(context_axes.get("y")) if isinstance(context_axes, dict) else None
        frame["orientation"] = str(layout_context.get("orientation", measured["orientation"]))
        frame["evidence"] = ["validated_layout_context"]
        frame["confidence"] = float((layout_context.get("validation") or {}).get("confidence", 0.0))
        frame["independent_geometry"] = independent_frame
    if frame is not None:
        frame["baseline"] = baseline is not None
    public_baseline = (
        {key: value for key, value in baseline.items() if not key.startswith("_")}
        if baseline
        else None
    )
    if public_baseline is not None and measured.get("baseline_cross_check") is not None:
        public_baseline["cross_check"] = measured["baseline_cross_check"]
    data = {
        "image_size": image_size(rgb),
        "evidence": build_common_evidence(
            rgb,
            coordinate_system="cartesian_2d",
            frame=frame,
            legend=series,
            series=series,
            confidence=confidence,
            warnings=warnings,
            layout_context=context_for_evidence(layout_context),
        ),
        "orientation": measured["orientation"],
        "bar_mode": measured["bar_mode"],
        "plot_area": {"bbox": measured["plot_area"]} if measured["plot_area"] else None,
        "baseline": public_baseline,
        "baseline_cross_check": measured.get("baseline_cross_check"),
        "series": series,
        "bars": bars,
        "confidence": confidence,
        "warnings": warnings,
        "layout_context": context_for_evidence(layout_context),
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_bar_overlay(chart_image, bars, data["baseline"], frame=frame),
                "image/png",
                "Detected bars with unified geometry, identities, and baseline",
            ),
        ),
        tuple(warnings),
    )


MEASURE_BARS = Tool(
    name="measure_bars",
    description=(
        "Measure two-dimensional vertical, horizontal, rotated, grouped, or "
        "stacked bars in an authorized chart image. return source-image polygon "
        "geometry, a fitted zero baseline, signed value-axis lengths, normalized "
        "ratios, stable category/series identities, confidence, warnings, and "
        "a source-sized overlay. Use it when bar geometry or relative magnitudes "
        "are required. do not use it for 3D, strongly perspective, or "
        "heavily occluded bars, or as proof of exact source values without axis "
        "calibration."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local chart image.",
            },
            "layout_context": {
                "type": "object",
                "description": "Optional validated chart layout context; model hints remain advisory.",
                "additionalProperties": True,
            },
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=measure_bars,
    group="chart-observation",
)


__all__ = ["MEASURE_BARS", "measure_bars"]
