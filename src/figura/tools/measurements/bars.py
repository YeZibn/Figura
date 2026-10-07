"""Pixel geometry sensor for two-dimensional bar charts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from math import exp, isfinite, sqrt
from typing import Any, Literal

import numpy as np

from .cartesian import (
    associate_legend_labels,
    axis_scalar,
    calibrated_axis_value,
    observe_cartesian_axes,
)
from .ocr import recognize_text


Orientation = Literal["vertical", "horizontal"]


def measure_bar_pixels(rgb: np.ndarray, observation_mask: np.ndarray | None = None) -> dict[str, Any]:
    """Measure an already decoded, scope-masked RGB source without shifting its coordinates."""
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, observation_mask) if observation_mask is not None else recognize_text(rgb)
    from .layout import legend_regions
    palette = _color_palette(rgb)
    regions = legend_regions(rgb, ocr.snippets, palette)
    data_rgb = rgb.copy()
    for x, y, w, h in regions:
        data_rgb[max(0,y):y+h, max(0,x):x+w] = 255
    candidates, orientation, palette, orientation_confidence = _find_candidates(data_rgb)
    if not candidates:
        axes = observe_cartesian_axes(rgb, ocr.snippets, None)
        return _empty_result(width, height, axes, ocr.truncated)

    stacked = _has_stacked_bars(candidates, orientation)
    _assign_categories(candidates, orientation, stacked)
    candidates.sort(
        key=lambda item: (
            item["_center_x"] if orientation == "vertical" else item["_center_y"],
            item["_top"] if orientation == "vertical" else item["_left"],
            item["_series_index"],
        )
    )
    for index, item in enumerate(candidates):
        item["_order"] = index

    axis_hint = _axis_hint(rgb, candidates, orientation)
    baseline = _fit_baseline(candidates, orientation, axis_hint, stacked)
    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; axis and legend associations may be incomplete")
    if orientation_confidence < 0.56:
        warnings.append("bar orientation is ambiguous")
    if len({item["_series_index"] for item in candidates}) > 1:
        warnings.append("series are identified by color; semantic labels are unavailable")

    unsupported = any(
        item["_density"] < 0.45 or item["_shape_variation"] > 0.48
        for item in candidates
    )
    if unsupported:
        warnings.append("irregular bar geometry may indicate perspective or three-dimensional styling")
        baseline = None
    elif baseline is None or baseline["confidence"] < 0.6:
        warnings.append("zero baseline is ambiguous; pixel lengths are omitted")
        baseline = None

    stacked_groups = _stack_groups(candidates, orientation) if stacked else {}
    values = [
        _bar_length(item, baseline, orientation, stacked)
        if baseline is not None else None
        for item in candidates
    ]
    measurements_partial = baseline is not None and any(value is None for value in values)
    if measurements_partial:
        warnings.append("some bars do not align with the fitted baseline")
    valid_lengths = [abs(value) for value in values if value is not None and abs(value) > 0]
    shortest = min(valid_lengths) if valid_lengths else None
    series_colors = {
        f"series_{index}": _hex(palette[index - 1])
        for index in sorted({item["_series_index"] for item in candidates})
    }
    axes = observe_cartesian_axes(rgb, ocr.snippets, None)
    labels = associate_legend_labels(rgb, ocr.snippets, palette)
    series = [
        {
            "id": series_id,
            "color": color,
            "label": labels.get(color, (None, None))[0],
            "label_confidence": labels.get(color, (None, None))[1],
        }
        for series_id, color in series_colors.items()
    ]
    category_axis_name = "x" if orientation == "vertical" else "y"
    category_associations = _category_associations(candidates, orientation, axes[category_axis_name])
    value_axis_name = "y" if orientation == "vertical" else "x"
    bars: list[dict[str, Any]] = []
    for bar_id, (candidate, value) in enumerate(zip(candidates, values, strict=True), start=1):
        category_label, category_tick_id = category_associations.get(candidate["_category_index"], (None, None))
        measure = {
            "value_length_px": value,
            "ratio_to_shortest": round(abs(value) / shortest, 6) if value is not None and shortest else None,
            "value": _bar_chart_value(candidate, baseline, orientation, axes[value_axis_name]) if baseline is not None else None,
        }
        bar: dict[str, Any] = {
            "id": bar_id,
            "category_index": candidate["_category_index"],
            "category_label": category_label,
            "category_tick_id": category_tick_id,
            "series_id": f"series_{candidate['_series_index']}",
            "geometry": _geometry(candidate),
            "measure": measure,
        }
        stack = stacked_groups.get(candidate["_category_index"])
        if stack is not None:
            members = stack["members"]
            bar["stack"] = {
                "segment_index": members.index(candidate) + 1,
                "total_length_px": stack["total_length_px"] if baseline is not None else None,
                "total_geometry": stack["total_geometry"],
                "total_value": _bar_chart_value(
                    {
                        "_left": stack["total_geometry"]["bbox_px"][0],
                        "_top": stack["total_geometry"]["bbox_px"][1],
                        "_right": stack["total_geometry"]["bbox_px"][0] + stack["total_geometry"]["bbox_px"][2],
                        "_bottom": stack["total_geometry"]["bbox_px"][1] + stack["total_geometry"]["bbox_px"][3],
                    },
                    baseline,
                    orientation,
                    axes[value_axis_name],
                ) if baseline is not None else None,
            }
        bars.append(bar)

    if baseline is None:
        status = "unsupported" if unsupported else "partial"
        orientation_name = "unknown" if len(candidates) == 1 and axis_hint is None else orientation
        public_baseline = None
        baseline_confidence = 0.0
    else:
        status = "partial" if measurements_partial else "measured"
        orientation_name = "oblique" if abs(baseline["slope"]) > 0.025 else orientation
        public_baseline = {key: baseline[key] for key in (
            "points_px", "axis", "slope", "intercept", "residual_px", "confidence"
        )}
        baseline_confidence = baseline["confidence"]

    value_calibration = axes[value_axis_name].get("calibration")
    calibration_confidence = (
        float(value_calibration["confidence"])
        if isinstance(value_calibration, dict) and value_calibration.get("calibrated") is True
        else 0.0
    )
    if not calibration_confidence:
        warnings.append("numeric value-axis calibration is unavailable; chart-unit values are null")
        if status == "measured":
            status = "partial"
    geometry_confidence = _clamp(float(np.mean([item["_density"] for item in candidates])))
    association_confidence = 0.78 if len(series) == 1 else 0.62
    overall = _clamp(0.4 * geometry_confidence + 0.25 * baseline_confidence + 0.2 * calibration_confidence + 0.15 * association_confidence)
    plot_area = _plot_area(candidates)
    return {
        "image_size": {"width": width, "height": height},
        "status": status,
        "orientation": orientation_name,
        "bar_mode": "stacked" if stacked else "grouped" if len(series) > 1 else "single",
        "plot_area_px": plot_area,
        "baseline": public_baseline,
        "axes": axes,
        "series": series,
        "bars": bars,
        "confidence": {
            "overall": overall,
            "geometry": geometry_confidence,
            "calibration": calibration_confidence,
            "association": association_confidence,
        },
        "warnings": warnings,
    }


def _empty_result(
    width: int,
    height: int,
    axes: dict[str, dict[str, object]],
    ocr_truncated: bool,
) -> dict[str, Any]:
    return {
        "image_size": {"width": width, "height": height},
        "status": "no_evidence",
        "orientation": "unknown",
        "bar_mode": "unknown",
        "plot_area_px": None,
        "baseline": None,
        "axes": axes,
        "series": [],
        "bars": [],
        "confidence": {"overall": 0.0, "geometry": 0.0, "calibration": 0.0, "association": 0.0},
        "warnings": [
            "no bar geometry was detected",
            *(["OCR candidate limit reached; axis and legend associations may be incomplete"] if ocr_truncated else []),
        ],
    }


def _category_associations(
    candidates: Sequence[dict[str, Any]],
    orientation: Orientation,
    axis: dict[str, object],
) -> dict[int, tuple[str | None, str | None]]:
    points, ticks = axis.get("points_px"), axis.get("ticks")
    if not isinstance(points, list) or len(points) != 2 or not isinstance(ticks, list) or not ticks:
        return {}
    center_key = "_center_x" if orientation == "vertical" else "_center_y"
    groups: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault(candidate["_category_index"], []).append(candidate)
    axis_length = float(np.linalg.norm(np.asarray(points[1], dtype=float) - np.asarray(points[0], dtype=float)))
    max_distance = max(20.0, axis_length / max(2.0, len(ticks) * 1.5))
    result: dict[int, tuple[str | None, str | None]] = {}
    for category_index, members in groups.items():
        coordinate = float(np.mean([item[center_key] for item in members]))
        if orientation == "vertical":
            y = float(np.interp(coordinate, [points[0][0], points[1][0]], [points[0][1], points[1][1]]))
            center = [coordinate, y]
        else:
            y0, y1 = float(points[0][1]), float(points[1][1])
            x = float(points[0][0]) + (coordinate - y0) * (float(points[1][0]) - float(points[0][0])) / (y1 - y0)
            center = [x, coordinate]
        projection = axis_scalar(center, points)
        candidates_by_distance = [
            (abs(axis_scalar(tick["point_px"], points) - projection), tick)
            for tick in ticks
            if isinstance(tick, dict) and isinstance(tick.get("point_px"), list)
        ]
        if not candidates_by_distance:
            continue
        distance, tick = min(candidates_by_distance, key=lambda item: item[0])
        if distance > max_distance:
            continue
        category_text = tick.get("text") if axis.get("kind") == "categorical" else None
        result[category_index] = (
            category_text if isinstance(category_text, str) else None,
            tick.get("id") if isinstance(tick.get("id"), str) else None,
        )
    return result


def _bar_chart_value(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    orientation: Orientation,
    axis: dict[str, object],
) -> float | None:
    if orientation == "vertical":
        coordinate = (candidate["_left"] + candidate["_right"]) / 2.0
        baseline_point = [coordinate, baseline["slope"] * coordinate + baseline["intercept"]]
        edge_points = [[coordinate, candidate["_top"]], [coordinate, candidate["_bottom"]]]
    else:
        coordinate = (candidate["_top"] + candidate["_bottom"]) / 2.0
        baseline_point = [baseline["slope"] * coordinate + baseline["intercept"], coordinate]
        edge_points = [[candidate["_left"], coordinate], [candidate["_right"], coordinate]]
    near_index = min(range(2), key=lambda index: abs(edge_points[index][0 if orientation == "horizontal" else 1] - baseline_point[0 if orientation == "horizontal" else 1]))
    far_point = edge_points[1 - near_index]
    near_value = calibrated_axis_value(baseline_point, axis)
    far_value = calibrated_axis_value(far_point, axis)
    return round(far_value - near_value, 6) if near_value is not None and far_value is not None else None


def _find_candidates(
    rgb: np.ndarray,
) -> tuple[list[dict[str, Any]], Orientation, list[tuple[int, int, int]], float]:
    palette = _color_palette(rgb)
    vertical = _candidates_for(rgb, palette, "vertical")
    horizontal = _candidates_for(rgb, palette, "horizontal")
    vertical_score = _orientation_score(vertical, "vertical")
    horizontal_score = _orientation_score(horizontal, "horizontal")
    orientation: Orientation = "vertical" if vertical_score >= horizontal_score else "horizontal"
    selected = vertical if orientation == "vertical" else horizontal
    unique: dict[tuple[int, int, int, int, int], dict[str, Any]] = {}
    for candidate in selected:
        key = (
            candidate["_left"], candidate["_top"], candidate["_right"],
            candidate["_bottom"], candidate["_series_index"],
        )
        unique.setdefault(key, candidate)
    confidence = _clamp(0.5 + abs(vertical_score - horizontal_score) / 2.0)
    return list(unique.values()), orientation, palette, confidence


def _color_palette(rgb: np.ndarray) -> list[tuple[int, int, int]]:
    from .colors import series_palette
    return sorted(series_palette(rgb))


def _color_mask(rgb: np.ndarray, color: Sequence[int]) -> np.ndarray:
    return np.max(np.abs(rgb.astype(np.int16) - np.asarray(color, dtype=np.int16)), axis=2) <= 28


def _candidates_for(
    rgb: np.ndarray,
    palette: Sequence[Sequence[int]],
    orientation: Orientation,
) -> list[dict[str, Any]]:
    candidates = []
    height, width = rgb.shape[:2]
    minimum_span = max(5, int(round(min(height, width) * 0.008)))
    minimum_area = max(40, int(height * width * 0.0001))
    for series_index, color in enumerate(palette, start=1):
        from .colors import color_mask
        mask = color_mask(rgb, color, tolerance=28, palette=palette)
        if orientation == "vertical":
            primary = np.flatnonzero(mask.sum(axis=0) >= max(3, int(height * 0.01)))
        else:
            primary = np.flatnonzero(mask.sum(axis=1) >= max(3, int(width * 0.01)))
        for first, last in _groups(primary):
            start, end = first, last + 1
            span = end - start
            if span < minimum_span:
                continue
            region = mask[:, start:end] if orientation == "vertical" else mask[start:end, :]
            cross_axis = 1 if orientation == "vertical" else 0
            cross = np.flatnonzero(region.sum(axis=cross_axis) >= max(2, int(span * 0.45)))
            for cross_first, cross_last in _groups(cross):
                other_start, other_end = cross_first, cross_last + 1
                area_region = (
                    region[cross_first : cross_last + 1, :]
                    if orientation == "vertical"
                    else region[:, cross_first : cross_last + 1]
                )
                area = int(area_region.sum())
                if other_end - other_start < minimum_span or span * (other_end - other_start) < minimum_area:
                    continue
                density = area / float(span * (other_end - other_start))
                if density < 0.35:
                    continue
                if orientation == "vertical":
                    left, top, right, bottom = start, other_start, end, other_end
                    spans = region[cross_first:cross_last + 1, :].sum(axis=1)
                else:
                    left, top, right, bottom = other_start, start, other_end, end
                    spans = region[:, cross_first:cross_last + 1].sum(axis=0)
                shape_variation = float(np.percentile(spans, 95) - np.percentile(spans, 5)) / max(1.0, float(span))
                candidates.append(_candidate(left, top, right, bottom, series_index, density, shape_variation))
    return candidates


def _groups(indices: np.ndarray) -> list[tuple[int, int]]:
    if not len(indices):
        return []
    breaks = np.where(np.diff(indices) > 1)[0]
    starts, ends = np.r_[0, breaks + 1], np.r_[breaks, len(indices) - 1]
    return [(int(indices[first]), int(indices[last])) for first, last in zip(starts, ends, strict=True)]


def _candidate(
    left: int,
    top: int,
    right: int,
    bottom: int,
    series_index: int,
    density: float,
    variation: float,
) -> dict[str, Any]:
    return {
        "_left": left, "_top": top, "_right": right, "_bottom": bottom,
        "_width": right - left, "_height": bottom - top,
        "_center_x": (left + right) / 2.0, "_center_y": (top + bottom) / 2.0,
        "_series_index": series_index, "_density": density, "_shape_variation": variation,
    }


def _orientation_score(candidates: Sequence[dict[str, Any]], orientation: Orientation) -> float:
    if not candidates:
        return float("-inf")
    ratios = [
        np.log(
            (item["_height"] + 1.0) / (item["_width"] + 1.0)
            if orientation == "vertical"
            else (item["_width"] + 1.0) / (item["_height"] + 1.0)
        )
        for item in candidates
    ]
    return float(np.median(ratios)) + min(0.1, len(candidates) * 0.01)


def _has_stacked_bars(candidates: Sequence[dict[str, Any]], orientation: Orientation) -> bool:
    for first, second in combinations(candidates, 2):
        if first["_series_index"] == second["_series_index"]:
            continue
        start, end = ("_left", "_right") if orientation == "vertical" else ("_top", "_bottom")
        overlap = min(first[end], second[end]) - max(first[start], second[start])
        span = min(first[end] - first[start], second[end] - second[start])
        if overlap >= 0.5 * span:
            return True
    return False


def _assign_categories(candidates: list[dict[str, Any]], orientation: Orientation, stacked: bool) -> None:
    axis_start, axis_end = ("_left", "_right") if orientation == "vertical" else ("_top", "_bottom")
    center_key = "_center_x" if orientation == "vertical" else "_center_y"
    if stacked:
        threshold = max(4.0, float(np.median([item[axis_end] - item[axis_start] for item in candidates]) * 0.65))
    elif len({item["_series_index"] for item in candidates}) > 1:
        threshold = max(8.0, float(np.median([item[axis_end] - item[axis_start] for item in candidates]) * 1.25))
    else:
        threshold = -1.0
    ordered = sorted(candidates, key=lambda item: item[center_key])
    groups: list[list[dict[str, Any]]] = []
    for item in ordered:
        if threshold >= 0 and groups and item[center_key] - groups[-1][-1][center_key] <= threshold:
            groups[-1].append(item)
        else:
            groups.append([item])
    for category_index, group in enumerate(groups, start=1):
        for item in group:
            item["_category_index"] = category_index


def _axis_hint(rgb: np.ndarray, candidates: Sequence[dict[str, Any]], orientation: Orientation) -> float | None:
    height, width = rgb.shape[:2]
    left = max(0, min(item["_left"] for item in candidates) - 24)
    right = min(width, max(item["_right"] for item in candidates) + 24)
    top = max(0, min(item["_top"] for item in candidates) - 24)
    bottom = min(height, max(item["_bottom"] for item in candidates) + 24)
    dark = np.all(rgb < 90, axis=2)
    support = dark[top:bottom, left:right].sum(axis=1 if orientation == "vertical" else 0)
    minimum = max(12, int((right - left if orientation == "vertical" else bottom - top) * 0.35))
    if not len(support) or int(support.max()) < minimum:
        return None
    offset = top if orientation == "vertical" else left
    edge_keys = ("_top", "_bottom") if orientation == "vertical" else ("_left", "_right")
    positions = np.flatnonzero(support >= minimum)
    axis_index = max(positions, key=lambda i: (
        sum(min(abs(item[key] - (offset+i)) for key in edge_keys) <= 3 for item in candidates),
        int(support[i])))
    if not any(min(abs(item[key] - (offset+axis_index)) for key in edge_keys) <= 3 for item in candidates):
        return None
    return float(offset + axis_index)


def _fit_baseline(
    candidates: Sequence[dict[str, Any]],
    orientation: Orientation,
    axis_hint: float | None,
    stacked: bool,
) -> dict[str, Any] | None:
    center_key = "_center_x" if orientation == "vertical" else "_center_y"
    edges = [
        [(item[center_key], float(item["_top"] if orientation == "vertical" else item["_left"]), "start"),
         (item[center_key], float(item["_bottom"] if orientation == "vertical" else item["_right"]), "end")]
        for item in candidates
    ]
    tolerance = max(2.5, float(np.median([min(item["_width"], item["_height"]) * 0.04 for item in candidates])))
    points = [point for pair in edges for point in pair]
    lines: list[tuple[float, float]] = []
    if axis_hint is not None:
        lines.append((0.0, axis_hint))
    elif len(candidates) == 1:
        return None
    else:
        for first, second in combinations(points, 2):
            if abs(first[0] - second[0]) < 1e-6:
                continue
            slope = (second[1] - first[1]) / (second[0] - first[0])
            lines.append((slope, first[1] - slope * first[0]))
    if not lines:
        return None

    def evaluate(line: tuple[float, float]) -> tuple[tuple[float, ...], list[float], list[str]]:
        slope, intercept = line
        distances = [[abs(edge[1] - (slope * edge[0] + intercept)) for edge in pair] for pair in edges]
        selected = [int(np.argmin(pair)) for pair in distances]
        residuals = [pair[index] for pair, index in zip(distances, selected, strict=True)]
        inliers = [value for value in residuals if value <= tolerance]
        mean_value = float(np.mean([slope * item[center_key] + intercept for item in candidates]))
        hint_score = -abs(mean_value - axis_hint) if axis_hint is not None else 0.0
        outer_score = mean_value if orientation == "vertical" else -mean_value
        inlier_error = -float(np.mean(inliers)) if inliers else -float("inf")
        score = (
            (hint_score, len(inliers), inlier_error, -abs(slope), outer_score)
            if axis_hint is not None
            else (len(inliers), inlier_error, outer_score, -abs(slope))
        )
        return score, residuals, [pair[index][2] for pair, index in zip(edges, selected, strict=True)]

    slope, intercept = max(lines, key=lambda line: evaluate(line)[0])
    selected_points: list[tuple[float, float]] = []
    selected_edges: list[str] = []
    residuals: list[float] = []
    for pair in edges:
        selected = min(pair, key=lambda edge: abs(edge[1] - (slope * edge[0] + intercept)))
        residual = abs(selected[1] - (slope * selected[0] + intercept))
        residuals.append(residual)
        selected_edges.append(selected[2])
        if residual <= tolerance:
            selected_points.append((selected[0], selected[1]))
    if len(selected_points) >= 2:
        values = np.asarray(selected_points, dtype=float)
        design = np.column_stack((values[:, 0], np.ones(len(values))))
        slope, intercept = np.linalg.lstsq(design, values[:, 1], rcond=None)[0]
        residuals = [min(abs(edge[1] - (slope * edge[0] + intercept)) for edge in pair) for pair in edges]
        selected_edges = [
            min(pair, key=lambda edge: abs(edge[1] - (slope * edge[0] + intercept)))[2]
            for pair in edges
        ]
    inliers = [value for value in residuals if value <= tolerance]
    if not inliers:
        return None
    residual = sqrt(float(np.mean(np.square(inliers))))
    confidence = _clamp((len(inliers) / len(candidates)) * exp(-min(4.0, residual) / 4.0))
    if len(candidates) == 1:
        confidence = min(confidence, 0.68)
    if orientation == "vertical":
        first_x, last_x = min(item["_left"] for item in candidates), max(item["_right"] for item in candidates)
        points_px = [
            [int(first_x), int(round(slope * first_x + intercept))],
            [int(last_x), int(round(slope * last_x + intercept))],
        ]
        axis = "y"
    else:
        first_y, last_y = min(item["_top"] for item in candidates), max(item["_bottom"] for item in candidates)
        points_px = [
            [int(round(slope * first_y + intercept)), int(first_y)],
            [int(round(slope * last_y + intercept)), int(last_y)],
        ]
        axis = "x"
    return {
        "points_px": points_px, "axis": axis, "slope": float(slope), "intercept": float(intercept),
        "residual_px": round(residual, 3), "confidence": confidence, "selected_edges": selected_edges,
    }


def _bar_length(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    orientation: Orientation,
    stacked: bool,
) -> float | None:
    coordinate = candidate["_center_x"] if orientation == "vertical" else candidate["_center_y"]
    base = baseline["slope"] * coordinate + baseline["intercept"]
    residual_limit = max(4.0, baseline["residual_px"] + 3.0)
    start = float(candidate["_top"] if orientation == "vertical" else candidate["_left"])
    end = float(candidate["_bottom"] if orientation == "vertical" else candidate["_right"])
    selected_edge = baseline["selected_edges"][candidate["_order"]]
    scale = sqrt(1.0 + baseline["slope"] ** 2)
    if stacked:
        center = (start + end) / 2.0
        sign = (1.0 if center < base else -1.0) if orientation == "vertical" else (1.0 if center > base else -1.0)
        return round(sign * (end - start) / scale, 3)
    if orientation == "vertical" and selected_edge == "end":
        return round((base - start) / scale, 3) if abs(end - base) <= residual_limit else None
    if orientation == "vertical" and selected_edge == "start":
        return round(-(end - base) / scale, 3) if abs(start - base) <= residual_limit else None
    if orientation == "horizontal" and selected_edge == "start":
        return round((end - base) / scale, 3) if abs(start - base) <= residual_limit else None
    if orientation == "horizontal" and selected_edge == "end":
        return round(-(base - start) / scale, 3) if abs(end - base) <= residual_limit else None
    return None


def _stack_groups(candidates: Sequence[dict[str, Any]], orientation: Orientation) -> dict[int, dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for item in candidates:
        groups.setdefault(item["_category_index"], []).append(item)
    result: dict[int, dict[str, Any]] = {}
    for category_index, members in groups.items():
        left, top = min(item["_left"] for item in members), min(item["_top"] for item in members)
        right, bottom = max(item["_right"] for item in members), max(item["_bottom"] for item in members)
        members.sort(key=lambda item: item["_top"] if orientation == "vertical" else item["_left"])
        result[category_index] = {
            "members": members,
            "total_length_px": round(float(bottom - top if orientation == "vertical" else right - left), 3),
            "total_geometry": _box_geometry(left, top, right, bottom),
        }
    return result


def _geometry(candidate: dict[str, Any]) -> dict[str, list[Any]]:
    return _box_geometry(candidate["_left"], candidate["_top"], candidate["_right"], candidate["_bottom"])


def _box_geometry(left: int, top: int, right: int, bottom: int) -> dict[str, list[Any]]:
    return {
        "bbox_px": [left, top, right - left, bottom - top],
        "polygon_px": [[left, top], [right, top], [right, bottom], [left, bottom]],
    }


def _plot_area(candidates: Sequence[dict[str, Any]]) -> dict[str, int]:
    left, top = min(item["_left"] for item in candidates), min(item["_top"] for item in candidates)
    right, bottom = max(item["_right"] for item in candidates), max(item["_bottom"] for item in candidates)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _hex(color: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(value))):02x}" for value in color[:3])


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value)) if isfinite(value) else 0.0
