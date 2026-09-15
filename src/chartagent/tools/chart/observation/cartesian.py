"""Small shared helpers for Cartesian chart sensor observations."""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Sequence

import numpy as np

_DARK_PIXEL = 112
_MAX_AXIS_SLOPE = 0.18
_AXIS_SLOPE_STEPS = 49


def rgb_to_hex(color: Sequence[int]) -> str:
    """Return a stable lowercase hex color for a three-channel RGB value."""
    red, green, blue = (max(0, min(255, int(value))) for value in color[:3])
    return f"#{red:02x}{green:02x}{blue:02x}"


def image_size(rgb: np.ndarray) -> list[int]:
    return [int(rgb.shape[1]), int(rgb.shape[0])]


def bounded_source_point(
    point: Sequence[float],
    *,
    width: int,
    height: int,
) -> list[float] | None:
    """Validate and clamp a point to source-image pixel bounds."""
    if len(point) < 2:
        return None
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y) or width < 1 or height < 1:
        return None
    return [
        round(max(0.0, min(float(width - 1), x)), 3),
        round(max(0.0, min(float(height - 1), y)), 3),
    ]


def stable_evidence_id(prefix: str, index: int) -> str:
    """Build a deterministic bounded identifier for image evidence."""
    return f"{prefix}_{max(1, int(index))}"


def default_plot_area(rgb: np.ndarray) -> list[int]:
    """Estimate a Matplotlib-like plot area without depending on a CV package."""
    height, width = rgb.shape[:2]
    left = max(0, int(round(width * 0.11)))
    top = max(0, int(round(height * 0.10)))
    right = min(width - 1, int(round(width * 0.93)))
    bottom = min(height - 1, int(round(height * 0.88)))
    return [left, top, max(1, right - left), max(1, bottom - top)]


def bbox_from_boxes(boxes: Iterable[Sequence[int]]) -> list[int] | None:
    normalized = [list(map(int, box[:4])) for box in boxes]
    if not normalized:
        return None
    left = min(box[0] for box in normalized)
    top = min(box[1] for box in normalized)
    right = max(box[0] + max(0, box[2]) for box in normalized)
    bottom = max(box[1] + max(0, box[3]) for box in normalized)
    return [left, top, max(1, right - left), max(1, bottom - top)]


def detect_color_palette(
    rgb: np.ndarray,
    *,
    region: Sequence[int] | None = None,
    max_colors: int = 8,
) -> list[np.ndarray]:
    """Find dominant saturated colors using coarse quantization.

    Anti-aliased chart primitives produce many nearby RGB values. Quantizing
    first makes the sensor stable across PNG renderers while keeping the
    implementation limited to NumPy.
    """
    pixels = rgb
    if region is not None:
        x, y, width, height = map(int, region)
        pixels = rgb[max(0, y) : y + height, max(0, x) : x + width]
    flat = pixels.reshape(-1, 3).astype(np.int16)
    if not len(flat):
        return []
    spread = flat.max(axis=1) - flat.min(axis=1)
    # Keep fully saturated chart colors such as Matplotlib's tab10 orange
    # (#ff7f0e); white background pixels are still excluded by ``spread``.
    colored = flat[(spread >= 64) & (flat.max(axis=1) <= 255) & (flat.min(axis=1) < 235)]
    if len(colored) < 20:
        return []
    quantized = ((colored // 16) * 16 + 8).astype(np.uint8)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    minimum = max(20, int(counts[order[0]] * 0.08))
    selected: list[np.ndarray] = []
    for index in order:
        if int(counts[index]) < minimum:
            break
        candidate = colors[index].astype(np.int16)
        if any(np.max(np.abs(candidate - existing)) <= 48 for existing in selected):
            continue
        selected.append(candidate)
        if len(selected) >= max_colors:
            break
    return selected


def color_mask(rgb: np.ndarray, color: Sequence[int], tolerance: int = 28) -> np.ndarray:
    target = np.asarray(color, dtype=np.int16).reshape(1, 1, 3)
    distance = np.max(np.abs(rgb.astype(np.int16) - target), axis=2)
    return distance <= int(tolerance)


def crop_mask(mask: np.ndarray, region: Sequence[int]) -> tuple[np.ndarray, int, int]:
    x, y, width, height = map(int, region)
    left = max(0, x)
    top = max(0, y)
    right = min(mask.shape[1], x + width)
    bottom = min(mask.shape[0], y + height)
    return mask[top:bottom, left:right], left, top


def cluster_centers(values: Sequence[float], *, gap: float | None = None) -> list[float]:
    """Cluster ordered one-dimensional centers, preserving their order."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return []
    if len(ordered) == 1:
        return ordered
    gaps = np.diff(ordered)
    threshold = gap if gap is not None else max(8.0, float(np.median(gaps) * 1.5))
    groups: list[list[float]] = [[ordered[0]]]
    for value, distance in zip(ordered[1:], gaps):
        if float(distance) > threshold:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [float(sum(group) / len(group)) for group in groups]


def confidence_map(
    *,
    overall: float,
    geometry: float | None = None,
    calibration: float | None = None,
    association: float | None = None,
) -> dict[str, float]:
    values = {"overall": overall}
    if geometry is not None:
        values["geometry"] = geometry
    if calibration is not None:
        values["calibration"] = calibration
    if association is not None:
        values["association"] = association
    return {
        name: max(0.0, min(1.0, float(value)))
        for name, value in values.items()
        if math.isfinite(float(value))
    }


def evidence_envelope(
    rgb: np.ndarray,
    *,
    plot_area: Sequence[int] | None,
    axes: dict[str, Any] | None = None,
    legend: list[dict[str, Any]] | None = None,
    series: list[dict[str, Any]] | None = None,
    confidence: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build the common portion of a successful Cartesian observation."""
    return {
        "image_size": image_size(rgb),
        "plot_area": {"bbox": list(map(int, plot_area))} if plot_area else None,
        "axes": axes
        or {
            "x": {"label": None, "ticks": [], "calibrated": False},
            "y": {"label": None, "ticks": [], "calibrated": False},
        },
        "legend": legend or [],
        "series": series or [],
        "confidence": confidence or confidence_map(overall=0.0),
    }


def numeric_text(value: str) -> float | None:
    """Parse an OCR snippet when it is a complete numeric tick label."""
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        number = float(cleaned.rstrip("%"))
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def numeric_ticks(
    snippets: list[dict[str, Any]],
    plot_area: Sequence[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify numeric OCR snippets near a Cartesian search area.

    The search area is only a hint. Each tick retains its full source-image
    center so callers can project it onto a detected, possibly oblique axis.
    """
    x, y, width, height = map(float, plot_area)
    x_ticks: list[dict[str, Any]] = []
    y_ticks: list[dict[str, Any]] = []
    for snippet in snippets:
        value = numeric_text(str(snippet.get("text", "")))
        bbox = snippet.get("bbox")
        if value is None or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        left, top, box_width, box_height = map(float, bbox)
        center_x = left + box_width / 2.0
        center_y = top + box_height / 2.0
        item: dict[str, Any] = {
            "pixel": center_x,
            "value": value,
            "point_px": [center_x, center_y],
        }
        if center_x < x + 12 and y - 8 <= center_y <= y + height + 8:
            y_item = dict(item)
            y_item["pixel"] = center_y
            y_ticks.append(y_item)
        elif y + height - 12 <= center_y <= y + height + 20 and x - 8 <= center_x <= x + width + 8:
            x_ticks.append(item)

    def unique(ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: dict[tuple[int, float], dict[str, Any]] = {}
        for tick in ticks:
            result[(round(float(tick["pixel"])), float(tick["value"]))] = tick
        return sorted(result.values(), key=lambda tick: float(tick["pixel"]))

    return unique(x_ticks), unique(y_ticks)


def fit_ticks(ticks: list[dict[str, Any]]) -> Callable[[float], float] | None:
    """Fit the historical one-dimensional pixel-to-value transform."""
    if len(ticks) < 2:
        return None
    pixels = np.asarray([tick["pixel"] for tick in ticks], dtype=float)
    values = np.asarray([tick["value"] for tick in ticks], dtype=float)
    if len(np.unique(pixels)) < 2:
        return None
    slope, intercept = np.polyfit(pixels, values, 1)
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None
    return lambda pixel: float(slope * pixel + intercept)


def axis_scalar(point: Sequence[float], axis_points: Sequence[Sequence[float]] | None) -> float:
    """Project a source-image point onto an axis, using source pixels."""
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
    """Fit an evidence-bearing pixel-axis transform.

    A model can be returned with ``calibrated=False`` when OCR support is
    present but its residual is too large. Callers must honor that gate.
    """
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
    """Apply a calibrated transform, returning ``None`` for pixel-only data."""
    if not model or not model.get("calibrated"):
        return None
    scalar = axis_scalar(point, model.get("axis_points"))
    return round(float(model["slope"] * scalar + model["intercept"]), 6)


def fit_dominant_axis_line(rgb: np.ndarray, *, axis: str) -> dict[str, Any] | None:
    """Find a long dark x or y axis and retain its source-image geometry."""
    if axis not in {"x", "y"}:
        raise ValueError("axis must be x or y")
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
            score = span + support * 0.35
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


def axis_output(ticks: list[dict[str, Any]], model: dict[str, Any] | None) -> dict[str, Any]:
    """Serialize ticks and fit quality using one Cartesian field shape."""
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


def series_entry(index: int, color: Sequence[int], label: str | None = None) -> dict[str, Any]:
    series_id = f"series_{index}"
    return {
        "id": series_id,
        "label": label,
        "color": rgb_to_hex(color),
    }


__all__ = [
    "bbox_from_boxes",
    "apply_axis_transform",
    "axis_output",
    "axis_scalar",
    "bounded_source_point",
    "cluster_centers",
    "color_mask",
    "confidence_map",
    "crop_mask",
    "default_plot_area",
    "detect_color_palette",
    "evidence_envelope",
    "fit_axis_transform",
    "fit_dominant_axis_line",
    "fit_ticks",
    "image_size",
    "numeric_text",
    "numeric_ticks",
    "rgb_to_hex",
    "series_entry",
    "stable_evidence_id",
]
