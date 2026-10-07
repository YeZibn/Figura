"""Shared axis, tick, and linear calibration evidence for Cartesian sensors."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from math import hypot, isfinite
from typing import Any

import numpy as np

from .ocr import OCRSnippet


_AXIS_SLOPE_LIMIT = 0.18
_AXIS_SLOPE_STEPS = 49
_MIN_CALIBRATION_SPAN_PX = 40.0
_NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?$")


def observe_cartesian_axes(
    image_rgb: np.ndarray,
    snippets: Sequence[OCRSnippet],
    plot_area_px: Mapping[str, int] | None,
) -> dict[str, dict[str, object]]:
    """Build x/y axis observations and gated calibration candidates."""
    height, width = image_rgb.shape[:2]
    area = _bounded_plot_area(plot_area_px, width, height)
    axes: dict[str, dict[str, object]] = {}
    for name in ("x", "y"):
        points = _detect_axis_points(image_rgb, area, name)
        local_snippets = snippets
        if name == "x" and points is not None:
            preliminary = _axis_ticks(snippets, points, area, name)
            if len(preliminary) < 3:
                from .ocr import recognize_region
                from .context import observation_context
                context = observation_context()
                y = max(0, min(height - 1, int(max(p[1] for p in points)) + 4))
                local = recognize_region(image_rgb, (0, y, width, min(36, height-y)),
                    context.mask if context is not None else None)
                local_snippets = list(snippets)
                for snippet in local:
                    cx = snippet.bbox_px[0] + snippet.bbox_px[2] / 2
                    cy = snippet.bbox_px[1] + snippet.bbox_px[3] / 2
                    if not any(abs(s.bbox_px[0] + s.bbox_px[2]/2-cx) < 6 and
                               abs(s.bbox_px[1] + s.bbox_px[3]/2-cy) < 6 for s in snippets):
                        local_snippets.append(snippet)
        ticks = _axis_ticks(local_snippets, points, area, name)
        _snap_tick_marks(image_rgb, ticks, points, name)
        numeric_count = sum(tick["value"] is not None for tick in ticks)
        kind = "numeric" if numeric_count else "categorical" if ticks else "unknown"
        label, label_confidence = _axis_label(local_snippets, ticks, area, name)
        calibration = fit_axis_calibration(ticks, points) if points else None
        axes[name] = {
            "kind": kind,
            "label_text": label,
            "label_confidence": label_confidence,
            "points_px": points,
            "ticks": ticks,
            "calibration": calibration,
        }
    return axes


def fit_axis_calibration(
    ticks: Sequence[Mapping[str, object]],
    axis_points_px: Sequence[Sequence[float]],
) -> dict[str, object] | None:
    numeric_ticks = [
        tick for tick in ticks
        if isinstance(tick.get("value"), int | float)
        and isinstance(tick.get("point_px"), (list, tuple))
        and len(tick["point_px"]) == 2  # type: ignore[arg-type]
    ]
    if len(numeric_ticks) < 2 or len(axis_points_px) != 2:
        return None
    pixels = np.asarray(
        [axis_scalar(tick["point_px"], axis_points_px) for tick in numeric_ticks],  # type: ignore[arg-type]
        dtype=float,
    )
    values = np.asarray([float(tick["value"]) for tick in numeric_ticks], dtype=float)
    if len(np.unique(pixels)) < 2 or len(np.unique(values)) < 2:
        return None
    # Two-point consensus avoids letting one mistaken OCR tick tilt the axis.
    # At least three agreeing observations are needed to reject an outlier.
    if len(values)>=4:
        from itertools import combinations
        tolerance = max(.15,float(np.ptp(values))*.015)
        hypotheses = []
        for i,j in combinations(range(len(values)),2):
            if abs(pixels[j]-pixels[i]) < 1e-6:
                continue
            candidate_slope = (values[j]-values[i])/(pixels[j]-pixels[i])
            candidate_intercept = values[i]-candidate_slope*pixels[i]
            errors = np.abs(candidate_slope*pixels+candidate_intercept-values)
            inliers = errors<=tolerance
            hypotheses.append((int(inliers.sum()),-float(errors[inliers].mean()),inliers))
        if hypotheses:
            count,_,inliers = max(hypotheses,key=lambda h:(h[0],h[1]))
            if count>=3 and count>=len(values)*.7:
                numeric_ticks = [t for t,keep in zip(numeric_ticks,inliers) if keep]
                pixels,values = pixels[inliers],values[inliers]
    slope, intercept = np.polyfit(pixels, values, 1)
    if not isfinite(float(slope)) or not isfinite(float(intercept)):
        return None
    residual = float(np.sqrt(np.mean((slope * pixels + intercept - values) ** 2)))
    value_span = float(np.ptp(values))
    support_span = float(np.ptp(pixels))
    residual_limit = max(1.5, value_span * 0.08)
    confidence = _clamp(
        min(1.0, len(numeric_ticks) / 4.0)
        * min(1.0, support_span / 120.0)
        * max(0.0, 1.0 - residual / max(residual_limit, 1e-9))
    )
    calibrated = (
        support_span >= _MIN_CALIBRATION_SPAN_PX
        and residual <= residual_limit
        and confidence >= 0.35
    )
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "residual_value": residual,
        "support_count": len(numeric_ticks),
        "support_tick_ids": [t["id"] for t in numeric_ticks if "id" in t],
        "support_span_px": support_span,
        "confidence": confidence,
        "calibrated": calibrated,
    }


def axis_scalar(point_px: Sequence[float], axis_points_px: Sequence[Sequence[float]]) -> float:
    origin = np.asarray(axis_points_px[0], dtype=float)
    direction = np.asarray(axis_points_px[1], dtype=float) - origin
    length = float(np.linalg.norm(direction))
    if length <= 1e-9:
        return 0.0
    return float(np.dot(np.asarray(point_px, dtype=float) - origin, direction / length))


def calibrated_axis_value(
    point_px: Sequence[float],
    axis: Mapping[str, object],
) -> float | None:
    points = axis.get("points_px")
    calibration = axis.get("calibration")
    if (
        not isinstance(points, (list, tuple))
        or len(points) != 2
        or not isinstance(calibration, Mapping)
        or calibration.get("calibrated") is not True
    ):
        return None
    try:
        result = float(calibration["slope"]) * axis_scalar(point_px, points) + float(calibration["intercept"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return round(result, 6) if isfinite(result) else None


def parse_numeric_text(text: str) -> float | None:
    cleaned = text.strip().replace(",", "").replace("−", "-")
    if cleaned.startswith(("$", "€", "£", "¥")):
        cleaned = cleaned[1:]
    if not _NUMERIC_TEXT.fullmatch(cleaned):
        return None
    try:
        value = float(cleaned.rstrip("%"))
    except ValueError:
        return None
    return value if isfinite(value) else None


def associate_legend_labels(
    image_rgb: np.ndarray,
    snippets: Sequence[OCRSnippet],
    colors: Sequence[Sequence[int]],
) -> dict[str, tuple[str, float]]:
    """Associate OCR text with a nearby matching color swatch or line sample."""
    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3 or not colors:
        return {}
    height, width = image_rgb.shape[:2]
    labels: dict[str, tuple[str, float]] = {}
    for snippet in snippets:
        x, y, box_width, box_height = snippet.bbox_px
        regions = (
            (max(0, x - 28), max(0, y - 4), min(width, x), min(height, y + box_height + 4)),
            (min(width, x + box_width), max(0, y - 4), min(width, x + box_width + 28), min(height, y + box_height + 4)),
        )
        best: tuple[int, int] | None = None
        for color_index, color in enumerate(colors):
            target = np.asarray(color, dtype=np.int16)
            count = 0
            for left, top, right, bottom in regions:
                patch = image_rgb[top:bottom, left:right].astype(np.int16)
                if patch.size:
                    count += int(np.count_nonzero(np.max(np.abs(patch - target), axis=2) <= 36))
            candidate = (count, color_index)
            if best is None or candidate > best:
                best = candidate
        if best is None or best[0] < 4:
            continue
        color = "#" + "".join(f"{int(channel):02x}" for channel in colors[best[1]][:3])
        confidence = _clamp(snippet.confidence * min(1.0, best[0] / 12.0))
        if color not in labels or confidence > labels[color][1]:
            labels[color] = (snippet.text, confidence)
    return labels


def _bounded_plot_area(
    plot_area_px: Mapping[str, int] | None,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    if plot_area_px is None:
        left, top = round(image_width * 0.1), round(image_height * 0.1)
        right, bottom = round(image_width * 0.92), round(image_height * 0.88)
    else:
        left = int(plot_area_px.get("x", 0))
        top = int(plot_area_px.get("y", 0))
        right = left + int(plot_area_px.get("width", image_width))
        bottom = top + int(plot_area_px.get("height", image_height))
    left = max(0, min(image_width - 1, left))
    top = max(0, min(image_height - 1, top))
    right = max(left + 1, min(image_width, right))
    bottom = max(top + 1, min(image_height, bottom))
    return left, top, right - left, bottom - top


def _detect_axis_points(
    image_rgb: np.ndarray,
    area: tuple[int, int, int, int],
    axis: str,
) -> list[list[float]] | None:
    left, top, width, height = area
    if axis == "x":
        search_top = top + int(height * 0.58)
        search_bottom = min(image_rgb.shape[0], top + int(height * 1.08))
        search_left, search_right = left, left + width
    else:
        search_left = left
        search_right = min(image_rgb.shape[1], left + int(width * 0.42))
        search_top, search_bottom = top, top + height
    region = image_rgb[search_top:search_bottom, search_left:search_right].astype(np.int16)
    if region.size == 0:
        return None
    brightness = region.mean(axis=2)
    spread = region.max(axis=2) - region.min(axis=2)
    ys, xs = np.nonzero((brightness <= 180) & (spread <= 48))
    if len(xs) < 12:
        return None
    xs = xs.astype(float) + search_left
    ys = ys.astype(float) + search_top
    origin_x = float(left)
    origin_y = float(top + height)
    extent = width if axis == "x" else height
    candidates: list[tuple[float, float, float, float, float]] = []
    for slope in np.linspace(-_AXIS_SLOPE_LIMIT, _AXIS_SLOPE_LIMIT, _AXIS_SLOPE_STEPS):
        if axis == "x":
            offsets = np.rint(ys - origin_y - slope * (xs - origin_x)).astype(int)
        else:
            offsets = np.rint(xs - origin_x - slope * (ys - origin_y)).astype(int)
        minimum, maximum = int(offsets.min()), int(offsets.max())
        counts = np.bincount(offsets - minimum, minlength=maximum - minimum + 1)
        peak_indices = np.argpartition(counts, -min(6, len(counts)))[-min(6, len(counts)):]
        for peak_index in peak_indices:
            intercept = float(peak_index + minimum)
            selected = np.abs(offsets - intercept) <= 1
            if not np.any(selected):
                continue
            selected_x, selected_y = xs[selected], ys[selected]
            along = selected_x if axis == "x" else selected_y
            span = float(np.ptp(along))
            if span < extent * 0.45:
                continue
            if axis == "x":
                location = float(np.mean(selected_y))
                location_weight = 0.75 + 0.25 * (location - search_top) / max(1.0, search_bottom - search_top)
            else:
                location = float(np.mean(selected_x))
                location_weight = 0.75 + 0.25 * (search_right - location) / max(1.0, search_right - search_left)
            score = span * float(np.count_nonzero(selected)) * location_weight
            candidates.append((score, float(slope), intercept, span, float(np.count_nonzero(selected))))
    if not candidates:
        return None
    _score, _slope, intercept, _span, _support = max(candidates)
    if axis == "x":
        selected = np.abs((ys - origin_y) - _slope * (xs - origin_x) - intercept) <= 2.0
        if np.count_nonzero(selected) < 8:
            return None
        fit_slope, fit_intercept = np.polyfit(xs[selected], ys[selected], 1)
        x1, x2 = float(left), float(left + width - 1)
        return [[x1, float(fit_slope * x1 + fit_intercept)], [x2, float(fit_slope * x2 + fit_intercept)]]
    selected = np.abs((xs - origin_x) - _slope * (ys - origin_y) - intercept) <= 2.0
    if np.count_nonzero(selected) < 8:
        return None
    fit_slope, fit_intercept = np.polyfit(ys[selected], xs[selected], 1)
    y1, y2 = float(top + height - 1), float(top)
    return [[float(fit_slope * y1 + fit_intercept), y1], [float(fit_slope * y2 + fit_intercept), y2]]


def _axis_ticks(
    snippets: Sequence[OCRSnippet],
    axis_points: list[list[float]] | None,
    area: tuple[int, int, int, int],
    axis: str,
) -> list[dict[str, object]]:
    if axis_points is None:
        return []
    left, top, width, height = area
    ticks: list[dict[str, object]] = []
    for snippet in snippets:
        x, y, box_width, box_height = snippet.bbox_px
        center = [x + box_width / 2.0, y + box_height / 2.0]
        projection = axis_scalar(center, axis_points)
        axis_length = hypot(axis_points[1][0] - axis_points[0][0], axis_points[1][1] - axis_points[0][1])
        if projection < -4 or projection > axis_length + 4:
            continue
        if axis == "x":
            axis_y = np.interp(center[0], [axis_points[0][0], axis_points[1][0]], [axis_points[0][1], axis_points[1][1]])
            near = left - 12 <= center[0] <= left + width + 12 and axis_y - 4 <= center[1] <= axis_y + max(28, height * 0.16)
        else:
            y0, y1 = axis_points[0][1], axis_points[1][1]
            axis_x = axis_points[0][0] + (center[1] - y0) * (axis_points[1][0] - axis_points[0][0]) / (y1 - y0)
            near = axis_x - max(54, width * 0.28) <= center[0] <= axis_x + 4
        if not near:
            continue
        ticks.append({
            "id": f"{axis}_{snippet.snippet_id}",
            "text": snippet.text,
            "value": parse_numeric_text(snippet.text),
            "bbox_px": [x, y, box_width, box_height],
            "point_px": [round(center[0], 3), round(center[1], 3)],
            "confidence": snippet.confidence,
            "_projection": projection,
        })
    if ticks and axis == "x":
        axis_y = float(axis_points[0][1])
        nearest_row = min(float(t["point_px"][1]) - axis_y for t in ticks)
        ticks = [t for t in ticks if float(t["point_px"][1]) - axis_y <= nearest_row + 8]
    if axis == "y":
        ticks = [t for t in ticks if t["value"] is not None or t["bbox_px"][3] <= t["bbox_px"][2] * 1.4]
    ticks.sort(key=lambda tick: float(tick["_projection"]))
    for tick in ticks:
        tick.pop("_projection")
    return ticks


def _axis_label(
    snippets: Sequence[OCRSnippet],
    ticks: Sequence[Mapping[str, object]],
    area: tuple[int, int, int, int],
    axis: str,
) -> tuple[str | None, float | None]:
    used = {str(tick.get("id", "")).removeprefix(f"{axis}_") for tick in ticks}
    left, top, width, height = area
    candidates: list[OCRSnippet] = []
    for snippet in snippets:
        if snippet.snippet_id in used or parse_numeric_text(snippet.text) is not None:
            continue
        x, y, box_width, box_height = snippet.bbox_px
        center_x, center_y = x + box_width / 2, y + box_height / 2
        if axis == "x":
            is_label = center_x >= left + width * 0.25 and center_x <= left + width * 0.75 and center_y > top + height * 0.92
        else:
            is_label = center_x < left and top + height * 0.2 <= center_y <= top + height * 0.8
        if is_label:
            candidates.append(snippet)
    if not candidates:
        return None, None
    selected = max(candidates, key=lambda item: (item.confidence, len(item.text)))
    return selected.text, selected.confidence


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _snap_tick_marks(rgb, ticks, points, role):
    """Align OCR text with physical tick marks, leaving absent marks unchanged."""
    if points is None:
        return
    dark = (rgb.mean(axis=2) < 180) & (np.ptp(rgb.astype(np.int16), axis=2) < 30)
    for tick in ticks:
        x, y = tick["point_px"]
        if role == "y":
            axis_x = int(round(points[0][0]))
            lo, hi = max(0, int(round(y))-5), min(rgb.shape[0], int(round(y))+6)
            patch = dark[lo:hi, max(0,axis_x-6):max(0,axis_x-1)]
            scores = patch.sum(axis=1)
            if scores.size and scores.max() >= 3:
                positions = np.flatnonzero(scores == scores.max())
                if np.ptp(positions) <= 3:
                    tick["point_px"] = [x, float(lo + positions.mean())]
        else:
            axis_y = int(round(points[0][1]))
            lo, hi = max(0, int(round(x))-5), min(rgb.shape[1], int(round(x))+6)
            scores = dark[min(rgb.shape[0],axis_y+1):min(rgb.shape[0],axis_y+7),lo:hi].sum(axis=0)
            if scores.size and scores.max() >= 3:
                positions = np.flatnonzero(scores == scores.max())
                if np.ptp(positions) <= 3:
                    tick["point_px"] = [float(lo + positions.mean()), y]
