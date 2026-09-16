"""Neutral evidence primitives shared by all chart observation sensors."""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Sequence

import numpy as np


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
    return f"{prefix}_{max(1, int(index))}"


def bbox_from_boxes(boxes: Iterable[Sequence[int]]) -> list[int] | None:
    normalized = [list(map(int, box[:4])) for box in boxes]
    if not normalized:
        return None
    left = min(box[0] for box in normalized)
    top = min(box[1] for box in normalized)
    right = max(box[0] + max(0, box[2]) for box in normalized)
    bottom = max(box[1] + max(0, box[3]) for box in normalized)
    return [left, top, max(1, right - left), max(1, bottom - top)]


def default_plot_area(rgb: np.ndarray) -> list[int]:
    """Estimate a renderer-like search area without treating it as truth."""
    height, width = rgb.shape[:2]
    left = max(0, int(round(width * 0.11)))
    top = max(0, int(round(height * 0.10)))
    right = min(width - 1, int(round(width * 0.93)))
    bottom = min(height - 1, int(round(height * 0.88)))
    return [left, top, max(1, right - left), max(1, bottom - top)]


def detect_color_palette(
    rgb: np.ndarray,
    *,
    region: Sequence[int] | None = None,
    max_colors: int = 8,
) -> list[np.ndarray]:
    """Find dominant saturated colors using coarse quantization."""
    pixels = rgb
    if region is not None:
        x, y, width, height = map(int, region)
        pixels = rgb[max(0, y) : y + height, max(0, x) : x + width]
    flat = pixels.reshape(-1, 3).astype(np.int16)
    if not len(flat):
        return []
    spread = flat.max(axis=1) - flat.min(axis=1)
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
    """Classify numeric OCR snippets near a Cartesian search area."""
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


def series_entry(index: int, color: Sequence[int], label: str | None = None) -> dict[str, Any]:
    return {"id": f"series_{index}", "label": label, "color": rgb_to_hex(color)}


def associate_series_labels(
    entries: list[dict[str, Any]],
    text_evidence: Iterable[dict[str, Any]],
    *,
    max_gap_px: float = 140.0,
    max_vertical_distance_px: float = 24.0,
) -> list[dict[str, Any]]:
    """Associate already-detected swatches with supplied OCR/text evidence.

    The function is deliberately image- and OCR-engine agnostic: callers pass
    serialized text evidence, and unresolved associations remain explicit.
    """
    snippets = [item for item in text_evidence if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else item
        bbox = geometry.get("bbox_px") or geometry.get("bbox")
        association: dict[str, Any] = {
            "label": item.get("label"),
            "source": "existing" if item.get("label") else None,
            "status": "resolved" if item.get("label") else "unresolved",
            "confidence": 0.8 if item.get("label") else None,
        }
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            left, top, width, height = map(float, bbox)
            right = left + width
            center_y = top + height / 2.0
            candidates: list[tuple[float, float, str]] = []
            for snippet in snippets:
                text = str(snippet.get("text", "")).strip()
                snippet_bbox = snippet.get("bbox")
                if not text or not isinstance(snippet_bbox, (list, tuple)) or len(snippet_bbox) != 4:
                    continue
                text_left, text_top, text_width, text_height = map(float, snippet_bbox)
                gap = text_left - right
                distance = abs(text_top + text_height / 2.0 - center_y)
                if -4.0 <= gap <= max_gap_px and distance <= max_vertical_distance_px:
                    candidates.append((distance, max(0.0, gap), text))
            if candidates and not item.get("label"):
                _, _, label = min(candidates)
                association.update(
                    label=label,
                    source="text_evidence",
                    status="candidate",
                    confidence=0.55,
                )
        item["association"] = association
        if association.get("label") and not item.get("label"):
            item["label"] = association["label"]
        result.append(item)
    return result


def evidence_envelope(
    rgb: np.ndarray,
    *,
    plot_area: Sequence[int] | None,
    axes: dict[str, Any] | None = None,
    legend: list[dict[str, Any]] | None = None,
    series: list[dict[str, Any]] | None = None,
    confidence: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build the historical common Cartesian-compatible fields."""
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


def build_common_evidence(
    rgb: np.ndarray,
    *,
    coordinate_system: str,
    frame: dict[str, Any] | None,
    legend: list[dict[str, Any]] | None = None,
    series: list[dict[str, Any]] | None = None,
    confidence: dict[str, float] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Compose the neutral evidence envelope used by all chart sensors."""
    return {
        "image_size": image_size(rgb),
        "coordinate_system": coordinate_system,
        "frame": frame,
        "legend": legend or [],
        "series": series or [],
        "confidence": confidence or confidence_map(overall=0.0),
        "warnings": list(warnings or []),
    }


__all__ = [
    "bbox_from_boxes",
    "bounded_source_point",
    "build_common_evidence",
    "associate_series_labels",
    "cluster_centers",
    "color_mask",
    "confidence_map",
    "crop_mask",
    "default_plot_area",
    "detect_color_palette",
    "evidence_envelope",
    "fit_ticks",
    "image_size",
    "numeric_text",
    "numeric_ticks",
    "rgb_to_hex",
    "series_entry",
    "stable_evidence_id",
]
