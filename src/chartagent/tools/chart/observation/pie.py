"""Deterministic pie-sector sensor for clean, non-donut charts."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...core.result import GeneratedImage, ToolResult
from ...core.definition import Tool
from .cartesian import color_mask, confidence_map, detect_color_palette, numeric_text, rgb_to_hex
from .ocr import extract_text
from .overlays import render_pie_overlay

_ANGLE_SAMPLES = 720
_RADII = (0.76, 0.84, 0.90, 0.96)
_COLOR_TOLERANCE = 52


def _connected_components(mask: np.ndarray, *, min_area: int) -> list[dict[str, Any]]:
    """Summarize colored regions using a bounded pure-NumPy flood fill."""
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, Any]] = []
    for start_y, start_x in np.argwhere(mask):
        start_y, start_x = int(start_y), int(start_x)
        if visited[start_y, start_x]:
            continue
        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        area = 0
        left = right = start_x
        top = bottom = start_y
        while stack:
            y, x = stack.pop()
            area += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for next_y, next_x in (
                (y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1),
            ):
                if (
                    0 <= next_y < height and 0 <= next_x < width
                    and mask[next_y, next_x] and not visited[next_y, next_x]
                ):
                    visited[next_y, next_x] = True
                    stack.append((next_y, next_x))
        if area >= min_area:
            components.append({
                "area": area,
                "bbox": [left, top, right - left + 1, bottom - top + 1],
                "center": [(left + right) / 2.0, (top + bottom) / 2.0],
            })
    return components


def _circle_candidate(rgb: np.ndarray, palette: list[np.ndarray]) -> dict[str, Any] | None:
    """Fit a near-square region around adjacent saturated sector components."""
    if not palette:
        return None
    components: list[dict[str, Any]] = []
    for color in palette:
        components.extend(
            _connected_components(
                color_mask(rgb, color, tolerance=_COLOR_TOLERANCE),
                min_area=max(80, int(rgb.shape[0] * rgb.shape[1] * 0.001)),
            )
        )
    if not components:
        return None
    anchor = max(components, key=lambda item: item["area"])
    anchor_x, anchor_y = anchor["center"]
    anchor_size = max(anchor["bbox"][2:])
    nearby = [
        item for item in components
        if item["area"] >= anchor["area"] * 0.30
        and math.hypot(item["center"][0] - anchor_x, item["center"][1] - anchor_y)
        <= anchor_size * 1.45
    ]
    left = min(item["bbox"][0] for item in nearby)
    top = min(item["bbox"][1] for item in nearby)
    right = max(item["bbox"][0] + item["bbox"][2] for item in nearby)
    bottom = max(item["bbox"][1] + item["bbox"][3] for item in nearby)
    width, height = right - left, bottom - top
    if min(width, height) < max(36, int(min(rgb.shape[:2]) * 0.08)):
        return None
    if max(width, height) / max(1, min(width, height)) > 1.65:
        return None
    diameter = min(width, height)
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    return {
        "bbox": [int(round(center_x - diameter / 2)), int(round(center_y - diameter / 2)), diameter, diameter],
        "center": [round(center_x, 2), round(center_y, 2)],
        "radius": round(diameter / 2.0, 2),
    }


def _sample_labels(rgb: np.ndarray, circle: dict[str, Any], palette: list[np.ndarray]) -> tuple[np.ndarray, float]:
    center_x, center_y = circle["center"]
    radius = float(circle["radius"])
    angles = np.arange(_ANGLE_SAMPLES, dtype=float) * 360.0 / _ANGLE_SAMPLES
    radians = np.deg2rad(angles)
    labels_by_radius: list[np.ndarray] = []
    for fraction in _RADII:
        xs = np.clip(np.rint(center_x + radius * fraction * np.sin(radians)).astype(int), 0, rgb.shape[1] - 1)
        ys = np.clip(np.rint(center_y - radius * fraction * np.cos(radians)).astype(int), 0, rgb.shape[0] - 1)
        pixels = rgb[ys, xs].astype(np.int16)
        distances = np.stack(
            [np.max(np.abs(pixels - color.reshape(1, 3)), axis=1) for color in palette],
            axis=1,
        )
        nearest = np.argmin(distances, axis=1)
        nearest_distance = distances[np.arange(len(nearest)), nearest]
        nearest[nearest_distance > _COLOR_TOLERANCE] = -1
        labels_by_radius.append(nearest)
    sampled = np.stack(labels_by_radius, axis=0)
    labels = np.full(_ANGLE_SAMPLES, -1, dtype=int)
    for index in range(_ANGLE_SAMPLES):
        valid = sampled[:, index][sampled[:, index] >= 0]
        if len(valid):
            labels[index] = int(np.bincount(valid, minlength=len(palette)).argmax())
    return labels, float(np.mean(labels >= 0))


def _fill_gaps(labels: np.ndarray, max_gap: int = 8) -> np.ndarray:
    result = labels.copy()
    index = 0
    while index < len(result):
        if result[index] >= 0:
            index += 1
            continue
        start = index
        while index < len(result) and result[index] < 0:
            index += 1
        end = index
        if end - start <= max_gap:
            before = result[start - 1] if start else result[-1]
            after = result[end] if end < len(result) else result[0]
            if before >= 0 and before == after:
                result[start:end] = before
    return result


def _runs(labels: np.ndarray) -> list[tuple[int, int, int]]:
    runs: list[tuple[int, int, int]] = []
    index = 0
    while index < len(labels):
        if labels[index] < 0:
            index += 1
            continue
        start = index
        label = int(labels[index])
        index += 1
        while index < len(labels) and labels[index] == label:
            index += 1
        if index - start >= 4:
            runs.append((label, start, index - 1))
    if len(runs) > 1 and runs[0][0] == runs[-1][0] and runs[0][1] == 0:
        first = runs.pop(0)
        last = runs.pop()
        runs.append((first[0], last[1], first[2] + len(labels)))
    return sorted(runs, key=lambda item: item[1] % len(labels))


def _ocr_snippets(path: Path) -> list[dict[str, Any]]:
    result = extract_text(str(path))
    return [item for item in result.data if isinstance(item, dict)] if isinstance(result, ToolResult) and isinstance(result.data, list) else []


def _angle_for_point(x: float, y: float, circle: dict[str, Any]) -> float:
    center_x, center_y = circle["center"]
    return float(np.degrees(np.arctan2(x - center_x, center_y - y)) % 360.0)


def _slice_at(slices: list[dict[str, Any]], angle: float) -> dict[str, Any] | None:
    for item in slices:
        if (angle - item["start_angle_deg"]) % 360.0 <= item["angle_deg"] + 1.0:
            return item
    return None


def _attach_ocr(slices: list[dict[str, Any]], circle: dict[str, Any], snippets: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for snippet in snippets:
        bbox = snippet.get("bbox")
        text = str(snippet.get("text", "")).strip()
        if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        left, top, width, height = map(float, bbox)
        x, y = left + width / 2.0, top + height / 2.0
        if math.hypot(x - circle["center"][0], y - circle["center"][1]) > circle["radius"] * 1.12:
            continue
        item = _slice_at(slices, _angle_for_point(x, y, circle))
        if item is None:
            warnings.append("OCR text inside the pie could not be assigned to a sector")
            continue
        confidence = snippet.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            confidence = None
        value = numeric_text(text)
        if value is not None:
            item["printed_text"] = text
            item["printed_value"] = value
            item["printed_value_confidence"] = confidence
        elif item.get("label") and item["label"] != text:
            warnings.append(f"conflicting labels for {item['id']}")
        else:
            item["label"] = text
            item["label_source"] = "ocr"
            item["label_confidence"] = confidence
    return warnings


def _legend(rgb: np.ndarray, circle: dict[str, Any], palette: list[np.ndarray], snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    center_x, center_y = circle["center"]
    for palette_index, color in enumerate(palette):
        mask = color_mask(rgb, color, tolerance=_COLOR_TOLERANCE)
        components = _connected_components(mask, min_area=12)
        candidates = [
            component for component in components
            if component["center"][0] > center_x + circle["radius"] * 0.95
            and component["area"] <= 5000
            and max(component["bbox"][2:]) <= 90
        ]
        if not candidates:
            continue
        component = max(candidates, key=lambda item: item["area"])
        left, top, width, height = component["bbox"]
        x, y = left, component["center"][1]
        label = None
        label_candidates: list[tuple[float, str]] = []
        for snippet in snippets:
            bbox = snippet.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            snippet_left, snippet_top, snippet_width, snippet_height = map(float, bbox)
            if snippet_left >= left + width - 2 and abs(snippet_top + snippet_height / 2 - y) <= 24:
                text = str(snippet.get("text", "")).strip()
                if text:
                    label_candidates.append((abs(snippet_top + snippet_height / 2 - y), text))
        if label_candidates:
            label = min(label_candidates, key=lambda item: item[0])[1]
        entries.append({
            "id": f"legend_{len(entries) + 1}",
            "color": rgb_to_hex(color),
            "bbox": [int(left), int(top), int(width), int(height)],
            "label": label,
            "palette_index": palette_index,
        })
    return entries


def _empty_result(image: Image.Image, warning: str) -> ToolResult:
    data = {
        "image_size": [image.width, image.height],
        "circle": None,
        "slices": [],
        "legend": [],
        "ocr": [],
        "totals": {"angle_deg": 0.0, "ratio": 0.0, "angle_consistent": False, "ratio_consistent": False, "consistent": False},
        "confidence": confidence_map(overall=0.0, geometry=0.0, association=0.0, calibration=0.0),
        "warnings": [warning],
    }
    return ToolResult(data, (GeneratedImage(render_pie_overlay(image, None, []), "image/png", "No reliable pie region detected"),), (warning,))


def extract_pie_slices(image_path: str) -> ToolResult | dict:
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}
    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"extract_pie_slices failed for {image_path}: {exc}"}

    palette = detect_color_palette(rgb, max_colors=8)
    circle = _circle_candidate(rgb, palette)
    if circle is None:
        return _empty_result(chart_image, "no reliable pie region detected")
    labels, coverage = _sample_labels(rgb, circle, palette)
    labels = _fill_gaps(labels)
    slices: list[dict[str, Any]] = []
    for index, (palette_index, start, end) in enumerate(_runs(labels), start=1):
        angle = (end - start + 1) * 360.0 / _ANGLE_SAMPLES
        slices.append({
            "id": f"slice_{index}",
            "color": rgb_to_hex(palette[palette_index]),
            "start_angle_deg": round((start % _ANGLE_SAMPLES) * 360.0 / _ANGLE_SAMPLES, 3),
            "end_angle_deg": round((end + 1) * 360.0 / _ANGLE_SAMPLES % 360.0, 3),
            "angle_deg": round(angle, 3),
            "ratio": round(angle / 360.0, 6),
            "palette_index": palette_index,
        })
    warnings: list[str] = []
    if coverage < 0.92:
        warnings.append("some pie angles were not assigned to a reliable sector color")
    snippets = _ocr_snippets(path)
    legend = _legend(rgb, circle, palette, snippets)
    warnings.extend(_attach_ocr(slices, circle, snippets))
    for entry in legend:
        matches = [item for item in slices if item["color"] == entry["color"]]
        if len(matches) == 1:
            entry["slice_id"] = matches[0]["id"]
            if entry.get("label") and not matches[0].get("label"):
                matches[0]["label"] = entry["label"]
                matches[0]["label_source"] = "legend"
        elif entry.get("label"):
            warnings.append(f"legend label {entry['label']!r} has ambiguous sector association")
    angle_total = sum(item["angle_deg"] for item in slices)
    ratio_total = sum(item["ratio"] for item in slices)
    angle_consistent = abs(angle_total - 360.0) <= 12.0
    ratio_consistent = abs(ratio_total - 1.0) <= 0.035
    consistent = bool(slices and coverage >= 0.92 and angle_consistent and ratio_consistent)
    if not consistent:
        warnings.append("detected sector totals do not cover approximately 360 degrees or 100 percent")
    geometry_confidence = 0.9 if slices else 0.2
    association_confidence = 0.9 if slices and all(item.get("label") for item in slices) else 0.62
    consistency_confidence = 0.96 if consistent else min(0.8, coverage)
    data = {
        "image_size": [chart_image.width, chart_image.height],
        "circle": circle,
        "slices": slices,
        "legend": legend,
        "ocr": snippets,
        "totals": {"angle_deg": round(angle_total, 3), "ratio": round(ratio_total, 6), "angle_consistent": angle_consistent, "ratio_consistent": ratio_consistent, "consistent": consistent},
        "confidence": confidence_map(overall=geometry_confidence * 0.5 + association_confidence * 0.2 + consistency_confidence * 0.3, geometry=geometry_confidence, association=association_confidence, calibration=consistency_confidence),
        "warnings": warnings,
    }
    return ToolResult(data, (GeneratedImage(render_pie_overlay(chart_image, circle, slices), "image/png", "Detected pie sectors, boundaries, IDs, and ratios"),), tuple(warnings))


EXTRACT_PIE_SLICES = Tool(
    name="extract_pie_slices",
    description=(
        "Extract sectors from a clean authorized non-donut pie chart and return "
        "sector IDs, angles, ratios, colors, optional legend labels, totals, "
        "confidence, warnings, and an overlay. Use when the image contains a "
        "recognizable pie chart; do not use for donut, 3D, exploded, occluded, or "
        "ambiguous circular graphics, and do not treat inferred labels or ratios "
        "as exact source data when coverage is incomplete. Check consistency and "
        "warnings before using the result for a ChartSpec."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Internal image path used only by the callable; authorized registrations replace this with attachment_id.",
            }
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=extract_pie_slices,
    group="chart-observation",
)


__all__ = ["EXTRACT_PIE_SLICES", "extract_pie_slices"]
