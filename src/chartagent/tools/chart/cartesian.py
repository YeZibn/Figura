"""Small shared helpers for Cartesian chart sensor observations."""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np


def rgb_to_hex(color: Sequence[int]) -> str:
    """Return a stable lowercase hex color for a three-channel RGB value."""
    red, green, blue = (max(0, min(255, int(value))) for value in color[:3])
    return f"#{red:02x}{green:02x}{blue:02x}"


def image_size(rgb: np.ndarray) -> list[int]:
    return [int(rgb.shape[1]), int(rgb.shape[0])]


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
    colored = flat[(spread >= 64) & (flat.max(axis=1) <= 250) & (flat.min(axis=1) < 235)]
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


def series_entry(index: int, color: Sequence[int], label: str | None = None) -> dict[str, Any]:
    series_id = f"series_{index}"
    return {
        "id": series_id,
        "label": label,
        "color": rgb_to_hex(color),
    }
