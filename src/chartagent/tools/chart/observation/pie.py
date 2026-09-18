"""Evidence-driven measurement for ordinary two-dimensional pie charts."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...core.definition import Tool
from ...core.result import GeneratedImage, ToolResult
from .foundation import (
    build_common_evidence,
    color_mask,
    confidence_map,
    image_size,
    numeric_text,
    rgb_to_hex,
)
from .coordinates import polar_frame
from .ocr import extract_text
from .overlays import render_pie_overlay
from .layout import context_for_evidence, context_frame, context_scope

_ANGLE_SAMPLES = 720
_RADII = (0.58, 0.70, 0.82, 0.91, 0.97)
_COLOR_TOLERANCE = 52
_MIN_RUN_SAMPLES = 4
_MIN_REGION_SIZE = 36
_MAX_SUPPORTED_ASPECT = 1.18
_MIN_SECTOR_COVERAGE = 0.80
_MIN_RATIO_SUPPORT = 0.56


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
                (y - 1, x),
                (y + 1, x),
                (y, x - 1),
                (y, x + 1),
            ):
                if (
                    0 <= next_y < height
                    and 0 <= next_x < width
                    and mask[next_y, next_x]
                    and not visited[next_y, next_x]
                ):
                    visited[next_y, next_x] = True
                    stack.append((next_y, next_x))
        if area >= min_area:
            components.append(
                {
                    "area": area,
                    "bbox": [left, top, right - left + 1, bottom - top + 1],
                    "center": [(left + right) / 2.0, (top + bottom) / 2.0],
                }
            )
    return components


def _nearest_palette(rgb: np.ndarray, palette: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return nearest palette index and distance for each RGB pixel."""
    if not palette:
        return np.full(rgb.shape[:2], -1, dtype=int), np.full(rgb.shape[:2], np.inf, dtype=float)
    pixels = rgb.astype(np.int16)
    distances = np.stack(
        [np.max(np.abs(pixels - color.reshape(1, 1, 3)), axis=2) for color in palette],
        axis=2,
    )
    labels = np.argmin(distances, axis=2)
    nearest = distances[np.arange(rgb.shape[0])[:, None], np.arange(rgb.shape[1])[None, :], labels]
    labels[nearest > _COLOR_TOLERANCE] = -1
    return labels, nearest


def _pie_palette(
    rgb: np.ndarray,
    *,
    region: Sequence[int] | None = None,
    max_colors: int = 12,
) -> list[np.ndarray]:
    """Find pie colors without dropping small but real sectors."""
    if region is not None and len(region) >= 4:
        left, top, width, height = map(int, region[:4])
        flat = rgb[max(0, top) : min(rgb.shape[0], top + height), max(0, left) : min(rgb.shape[1], left + width)].reshape(-1, 3).astype(np.int16)
    else:
        flat = rgb.reshape(-1, 3).astype(np.int16)
    if not len(flat):
        return []
    spread = flat.max(axis=1) - flat.min(axis=1)
    colored = flat[(spread >= 48) & (flat.min(axis=1) < 245)]
    if len(colored) < 20:
        return []
    quantized = ((colored // 16) * 16 + 8).astype(np.uint8)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    minimum = max(20, int(counts[order[0]] * 0.012))
    selected: list[np.ndarray] = []
    for index in order:
        if int(counts[index]) < minimum:
            break
        candidate = colors[index].astype(np.int16)
        if any(np.max(np.abs(candidate - existing)) <= 42 for existing in selected):
            continue
        selected.append(candidate)
        if len(selected) >= max_colors:
            break
    return selected


def _bbox_intersects_region(
    bbox: Sequence[int],
    region: Sequence[int] | None,
) -> bool:
    if region is None or len(region) < 4:
        return True
    left, top, width, height = map(int, bbox[:4])
    region_left, region_top, region_width, region_height = map(int, region[:4])
    return (
        left < region_left + region_width
        and left + width > region_left
        and top < region_top + region_height
        and top + height > region_top
    )


def _circle_candidate(
    rgb: np.ndarray,
    palette: list[np.ndarray],
    *,
    region: Sequence[int] | None = None,
) -> dict[str, Any] | None:
    """Find and score a source-image pie-region hypothesis."""
    if not palette:
        return None
    components: list[dict[str, Any]] = []
    min_area = max(80, int(rgb.shape[0] * rgb.shape[1] * 0.001))
    for palette_index, color in enumerate(palette):
        for component in _connected_components(
            color_mask(rgb, color, tolerance=_COLOR_TOLERANCE),
            min_area=min_area,
        ):
            if not _bbox_intersects_region(component["bbox"], region):
                continue
            components.append({**component, "palette_index": palette_index})
    if not components:
        return None

    candidates: list[dict[str, Any]] = []
    for anchor in sorted(components, key=lambda item: item["area"], reverse=True)[:12]:
        anchor_x, anchor_y = anchor["center"]
        anchor_size = float(max(anchor["bbox"][2:]))
        nearby = [
            item
            for item in components
            if item["area"] >= anchor["area"] * 0.12
            and math.hypot(item["center"][0] - anchor_x, item["center"][1] - anchor_y)
            <= max(anchor_size * 1.65, min(rgb.shape[:2]) * 0.12)
        ]
        if not nearby:
            continue
        left = min(item["bbox"][0] for item in nearby)
        top = min(item["bbox"][1] for item in nearby)
        right = max(item["bbox"][0] + item["bbox"][2] for item in nearby)
        bottom = max(item["bbox"][1] + item["bbox"][3] for item in nearby)
        width, height = right - left, bottom - top
        if min(width, height) < max(_MIN_REGION_SIZE, int(min(rgb.shape[:2]) * 0.08)):
            continue
        diameter = float(min(width, height))
        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        radius = diameter / 2.0
        aspect_ratio = max(width, height) / max(1.0, min(width, height))

        yy, xx = np.ogrid[: rgb.shape[0], : rgb.shape[1]]
        disk = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius**2
        union_mask = np.zeros(disk.shape, dtype=bool)
        for item in nearby:
            union_mask |= color_mask(rgb, palette[item["palette_index"]], tolerance=_COLOR_TOLERANCE)
        colored_fraction = float(np.mean(union_mask[disk])) if np.any(disk) else 0.0
        center_window = rgb[
            max(0, int(round(center_y)) - 2) : min(rgb.shape[0], int(round(center_y)) + 3),
            max(0, int(round(center_x)) - 2) : min(rgb.shape[1], int(round(center_x)) + 3),
        ]
        center_labels, _ = _nearest_palette(center_window, palette)
        center_support = float(np.mean(center_labels >= 0)) if center_labels.size else 0.0
        fit_residual = abs(float(width - height)) / 2.0
        aspect_score = max(0.0, 1.0 - abs(aspect_ratio - 1.0) / 0.45)
        coverage_score = min(1.0, colored_fraction / 0.55)
        center_score = min(1.0, center_support / 0.35)
        confidence = max(0.0, min(0.98, aspect_score * 0.4 + coverage_score * 0.4 + center_score * 0.2))
        if center_support < 0.12 and colored_fraction >= 0.20:
            shape = "donut_or_exploded"
            status = "unsupported"
        elif aspect_ratio > _MAX_SUPPORTED_ASPECT:
            shape = "elliptical_or_perspective"
            status = "unsupported"
        else:
            shape = "circle"
            status = "supported" if confidence >= 0.50 else "uncertain"
        candidates.append(
            {
                "shape": shape,
                "status": status,
                "center_px": [round(center_x, 3), round(center_y, 3)],
                "radius_px": round(radius, 3),
                "bbox_px": [int(left), int(top), int(width), int(height)],
                "aspect_ratio": round(aspect_ratio, 4),
                "fit_residual_px": round(fit_residual, 3),
                "coverage": round(colored_fraction, 4),
                "center_support": round(center_support, 4),
                "confidence": round(confidence, 4),
                "_area": sum(int(item["area"]) for item in nearby),
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["confidence"], item["_area"]))


def _region_center(region: dict[str, Any]) -> tuple[float, float]:
    center = region.get("center_px") or region.get("center") or [0.0, 0.0]
    return float(center[0]), float(center[1])


def _region_radius(region: dict[str, Any]) -> float:
    return float(region.get("radius_px", region.get("radius", 0.0)))


def _sample_labels(
    rgb: np.ndarray,
    region: dict[str, Any],
    palette: list[np.ndarray],
) -> tuple[np.ndarray, float, np.ndarray, float]:
    """Sample angular labels at several radii and retain support per angle."""
    center_x, center_y = _region_center(region)
    radius = _region_radius(region)
    angles = np.arange(_ANGLE_SAMPLES, dtype=float) * 360.0 / _ANGLE_SAMPLES
    radians = np.deg2rad(angles)
    sampled = np.full((len(_RADII), _ANGLE_SAMPLES), -1, dtype=int)
    for radius_index, fraction in enumerate(_RADII):
        xs = np.clip(
            np.rint(center_x + radius * fraction * np.sin(radians)).astype(int),
            0,
            rgb.shape[1] - 1,
        )
        ys = np.clip(
            np.rint(center_y - radius * fraction * np.cos(radians)).astype(int),
            0,
            rgb.shape[0] - 1,
        )
        pixels = rgb[ys, xs].astype(np.int16)
        distances = np.stack(
            [np.max(np.abs(pixels - color.reshape(1, 3)), axis=1) for color in palette],
            axis=1,
        )
        nearest = np.argmin(distances, axis=1)
        nearest_distance = distances[np.arange(len(nearest)), nearest]
        nearest[nearest_distance > _COLOR_TOLERANCE] = -1
        sampled[radius_index] = nearest

    labels = np.full(_ANGLE_SAMPLES, -1, dtype=int)
    support = np.zeros(_ANGLE_SAMPLES, dtype=float)
    for index in range(_ANGLE_SAMPLES):
        valid = sampled[:, index][sampled[:, index] >= 0]
        if not len(valid):
            continue
        counts = np.bincount(valid, minlength=len(palette))
        label = int(np.argmax(counts))
        support[index] = float(np.mean(valid == label)) * len(valid) / len(_RADII)
        if counts[label] >= max(2, int(math.ceil(len(_RADII) * 0.4))):
            labels[index] = label
    coverage = float(np.mean(labels >= 0))
    radial_consistency = float(np.mean(support[labels >= 0])) if np.any(labels >= 0) else 0.0
    return labels, coverage, support, radial_consistency


def _fill_gaps(labels: np.ndarray, max_gap: int = 10) -> np.ndarray:
    result = labels.copy()
    for _ in range(2):
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
    """Return circular same-color runs as (palette index, start, end)."""
    if not len(labels) or not np.any(labels >= 0):
        return []
    runs: list[tuple[int, int, int]] = []
    starts = [
        index
        for index, label in enumerate(labels)
        if label >= 0 and labels[index - 1] != label
    ]
    for start in starts:
        label = int(labels[start])
        end = start
        while end - start < len(labels) and labels[end % len(labels)] == label:
            end += 1
        if end - start >= _MIN_RUN_SAMPLES:
            runs.append((label, start, end - 1))
    return sorted(runs, key=lambda item: item[1] % len(labels))


def _angle_point(region: dict[str, Any], angle: float, distance: float | None = None) -> list[float]:
    center_x, center_y = _region_center(region)
    radius = _region_radius(region) if distance is None else distance
    radians = math.radians(float(angle))
    return [
        round(center_x + radius * math.sin(radians), 3),
        round(center_y - radius * math.cos(radians), 3),
    ]


def _sector_geometry(region: dict[str, Any], start: int, end: int, angle: float) -> dict[str, Any]:
    start_angle = (start % _ANGLE_SAMPLES) * 360.0 / _ANGLE_SAMPLES
    end_angle = ((end + 1) % _ANGLE_SAMPLES) * 360.0 / _ANGLE_SAMPLES
    midpoint = start_angle + angle / 2.0
    center = _angle_point(region, 0.0, 0.0)
    start_point = _angle_point(region, start_angle)
    end_point = _angle_point(region, end_angle)
    centroid = _angle_point(region, midpoint, _region_radius(region) * 0.60)
    points = [center, start_point, end_point]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "start_angle_deg": round(start_angle % 360.0, 3),
        "end_angle_deg": round(end_angle % 360.0, 3),
        "boundary_points_px": [start_point, end_point],
        "polygon_px": points,
        "centroid_px": centroid,
        "bbox_px": [
            round(min(xs), 3),
            round(min(ys), 3),
            round(max(xs) - min(xs), 3),
            round(max(ys) - min(ys), 3),
        ],
    }


def _angle_for_point(x: float, y: float, region: dict[str, Any]) -> float:
    center_x, center_y = _region_center(region)
    return float(np.degrees(np.arctan2(x - center_x, center_y - y)) % 360.0)


def _slice_at(sectors: list[dict[str, Any]], angle: float) -> dict[str, Any] | None:
    for item in sectors:
        geometry = item.get("geometry") or {}
        start = float(geometry.get("start_angle_deg", 0.0))
        span = float((item.get("measure") or {}).get("angle_deg", 0.0))
        if (angle - start) % 360.0 <= span + 1.0:
            return item
    return None


def _ocr_snippets(
    path: Path,
    scope: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    try:
        result = extract_text(str(path))
    except Exception:  # noqa: BLE001 - OCR is optional evidence at this boundary.
        return []
    if isinstance(result, ToolResult) and isinstance(result.data, list):
        snippets = [item for item in result.data if isinstance(item, dict)]
        if scope is None or len(scope) < 4:
            return snippets
        return [
            item
            for item in snippets
            if isinstance(item.get("bbox"), (list, tuple))
            and len(item["bbox"]) == 4
            and _bbox_intersects_region(item["bbox"], scope)
        ]
    return []


def _snippet_center(snippet: dict[str, Any]) -> tuple[float, float] | None:
    bbox = snippet.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        left, top, width, height = map(float, bbox)
    except (TypeError, ValueError):
        return None
    return left + width / 2.0, top + height / 2.0


def _attach_ocr(
    sectors: list[dict[str, Any]],
    region: dict[str, Any],
    snippets: list[dict[str, Any]],
) -> tuple[list[str], set[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    used_text: set[str] = set()
    conflicts: list[dict[str, Any]] = []
    center_x, center_y = _region_center(region)
    radius = _region_radius(region)
    for snippet in snippets:
        text = str(snippet.get("text", "")).strip()
        center = _snippet_center(snippet)
        if not text or center is None:
            continue
        x, y = center
        distance = math.hypot(x - center_x, y - center_y)
        if distance > radius * 1.15:
            continue
        sector = _slice_at(sectors, _angle_for_point(x, y, region))
        if sector is None:
            warnings.append("OCR text inside the pie could not be assigned to a sector")
            continue
        confidence = snippet.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            confidence = None
        numeric_value = numeric_text(text)
        if numeric_value is not None:
            sector["printed"] = {
                "text": text,
                "value": numeric_value,
                "confidence": confidence,
                "source": "ocr",
            }
            geometry_ratio = (sector.get("measure") or {}).get("ratio")
            if ("%" in text or 0.0 <= numeric_value <= 1.0) and geometry_ratio is not None:
                printed_ratio = numeric_value / 100.0 if "%" in text else numeric_value
                if abs(float(geometry_ratio) - printed_ratio) > max(0.06, abs(float(geometry_ratio)) * 0.22):
                    conflicts.append(
                        {
                            "field": f"{sector['id']}_ratio",
                            "sources": ["ocr", "pixel_geometry"],
                            "message": "printed OCR ratio disagrees with the independently measured sector angle",
                        }
                    )
                    warnings.append(f"OCR printed ratio conflicts with geometry for {sector['id']}")
            used_text.add(text)
            continue
        association = sector.setdefault("association", {})
        if association.get("label") and association["label"] != text:
            warnings.append(f"conflicting labels for {sector['id']}")
            association["status"] = "ambiguous"
            continue
        association.update(
            {
                "label": text,
                "source": "ocr",
                "status": "resolved",
                "confidence": confidence,
                "support": "angular_position",
            }
        )
        used_text.add(text)
    return warnings, used_text, conflicts


def _legend(
    rgb: np.ndarray,
    region: dict[str, Any],
    palette: list[np.ndarray],
    snippets: list[dict[str, Any]],
    search_region: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    entries: list[dict[str, Any]] = []
    used_text: set[str] = set()
    center_x, center_y = _region_center(region)
    radius = _region_radius(region)
    for palette_index, color in enumerate(palette):
        mask = color_mask(rgb, color, tolerance=_COLOR_TOLERANCE)
        components = _connected_components(mask, min_area=12)
        candidates = []
        for component in components:
            if not _bbox_intersects_region(component["bbox"], search_region):
                continue
            component_x, component_y = component["center"]
            distance = math.hypot(component_x - center_x, component_y - center_y)
            if (
                distance > radius * 1.08
                and component["area"] <= 5000
                and max(component["bbox"][2:]) <= 90
            ):
                candidates.append((distance, component))
        if not candidates:
            continue
        _, component = min(candidates, key=lambda item: item[0])
        left, top, width, height = component["bbox"]
        component_x, component_y = component["center"]
        label_candidates: list[tuple[float, str, float | None]] = []
        for snippet in snippets:
            text = str(snippet.get("text", "")).strip()
            snippet_center = _snippet_center(snippet)
            if not text or snippet_center is None:
                continue
            snippet_x, snippet_y = snippet_center
            distance = math.hypot(snippet_x - component_x, snippet_y - component_y)
            if (
                distance <= max(140.0, radius * 0.85)
                and math.hypot(snippet_x - center_x, snippet_y - center_y) > radius * 1.02
                and (
                    abs(snippet_y - component_y) <= max(28.0, float(height) * 2.0)
                    or abs(snippet_x - component_x) <= max(60.0, float(width) * 2.0)
                )
            ):
                confidence = snippet.get("confidence")
                confidence = confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
                label_candidates.append((distance, text, confidence))
        label = None
        label_confidence = None
        if label_candidates:
            _, label, label_confidence = min(label_candidates, key=lambda item: item[0])
            used_text.add(label)
        entries.append(
            {
                "id": f"legend_{len(entries) + 1}",
                "color": rgb_to_hex(color),
                "geometry": {
                    "bbox_px": [int(left), int(top), int(width), int(height)],
                    "center_px": [round(component_x, 3), round(component_y, 3)],
                },
                "label": label,
                "label_source": "ocr" if label else None,
                "confidence": round(float(label_confidence), 4) if label_confidence is not None else None,
                "palette_index": palette_index,
                "association": {
                    "sector_id": None,
                    "status": "unresolved",
                    "source": None,
                    "confidence": None,
                },
            }
        )
    return entries, used_text


def _attach_external_labels(
    sectors: list[dict[str, Any]],
    region: dict[str, Any],
    snippets: list[dict[str, Any]],
    used_text: set[str],
) -> list[str]:
    warnings: list[str] = []
    center_x, center_y = _region_center(region)
    radius = _region_radius(region)
    for snippet in snippets:
        text = str(snippet.get("text", "")).strip()
        center = _snippet_center(snippet)
        if not text or text in used_text or numeric_text(text) is not None or center is None:
            continue
        x, y = center
        distance = math.hypot(x - center_x, y - center_y)
        if not radius * 1.12 < distance <= radius * 1.85:
            continue
        sector = _slice_at(sectors, _angle_for_point(x, y, region))
        if sector is None:
            continue
        association = sector.setdefault("association", {})
        if association.get("label") and association["label"] != text:
            association["status"] = "ambiguous"
            warnings.append(f"external label {text!r} has an ambiguous sector association")
            continue
        association.update(
            {
                "label": text,
                "source": "ocr_external",
                "status": "candidate",
                "confidence": 0.55,
                "support": "angular_position",
            }
        )
        used_text.add(text)
    return warnings


def _empty_result(
    image: Image.Image,
    warning: str,
    plot_region: dict[str, Any] | None = None,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult:
    safe_region = (
        {key: value for key, value in plot_region.items() if not key.startswith("_")}
        if isinstance(plot_region, dict)
        else None
    )
    rgb = np.asarray(image.convert("RGB"))
    confidence = confidence_map(overall=0.0, geometry=0.0, calibration=0.0, association=0.0)
    data = {
        "image_size": [image.width, image.height],
        "evidence": build_common_evidence(
            rgb,
            coordinate_system="polar_2d",
            frame=polar_frame(safe_region, warnings=[warning]) if safe_region else None,
            confidence=confidence,
            warnings=[warning],
            layout_context=context_for_evidence(layout_context),
        ),
        "orientation": "unknown",
        "transform": {"kind": "unresolved", "rotation_deg": None},
        "plot_region": safe_region,
        "sectors": [],
        "legend": [],
        "ocr": [],
        "totals": {
            "angle_deg": 0.0,
            "ratio": 0.0,
            "angle_consistent": False,
            "ratio_consistent": False,
            "consistent": False,
        },
        "confidence": confidence,
        "warnings": [warning],
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_pie_overlay(image, plot_region, [], [], [warning]),
                "image/png",
                "No reliable pie evidence detected",
            ),
        ),
        (warning,),
    )


def _error(reason: str) -> dict[str, str]:
    return {"error": f"extract_pie_slices: {reason}"}


def extract_pie_slices(
    image_path: str,
    layout_context: dict[str, Any] | None = None,
) -> ToolResult | dict:
    """Extract source-image sector evidence and gated pie ratios."""
    path = Path(image_path)
    if not path.is_file():
        return _error("image could not be resolved")
    try:
        with Image.open(path) as image:
            chart_image = image.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return _error(f"input is not a readable image ({type(exc).__name__})")

    scope = context_scope(layout_context)
    layout = context_frame(layout_context) if isinstance(layout_context, dict) and layout_context.get("coordinate_system") == "polar_2d" else None
    search_region = layout.get("bbox_px") if layout else (scope.get("bbox_px") if scope else None)
    palette = _pie_palette(rgb, region=search_region)
    plot_region = _circle_candidate(rgb, palette, region=search_region)
    if plot_region is None:
        return _empty_result(chart_image, "no reliable pie region detected", layout_context=layout_context)
    if plot_region.get("status") != "supported" or plot_region.get("shape") != "circle":
        reason = "unsupported pie geometry detected"
        if plot_region.get("shape") == "donut_or_exploded":
            reason = "donut or exploded pie geometry is unsupported"
        elif plot_region.get("shape") == "elliptical_or_perspective":
            reason = "elliptical or perspective pie geometry is unsupported"
        return _empty_result(chart_image, reason, plot_region, layout_context)

    polar_hint = layout_context.get("polar_region") if isinstance(layout_context, dict) else None
    conflicts: list[dict[str, Any]] = []
    if isinstance(polar_hint, dict):
        detected_center = np.asarray(_region_center(plot_region), dtype=float)
        hinted_center = np.asarray(polar_hint.get("center_px", []), dtype=float)
        detected_radius = float(_region_radius(plot_region))
        hinted_radius = float(polar_hint.get("radius_px", 0.0) or 0.0)
        if len(hinted_center) >= 2 and hinted_radius > 0:
            center_error = float(np.linalg.norm(detected_center - hinted_center[:2]))
            radius_error = abs(detected_radius - hinted_radius)
            if center_error > max(12.0, detected_radius * 0.18) or radius_error > max(12.0, detected_radius * 0.18):
                warnings = ["polar layout hint conflicts with detected circle geometry"]
                conflicts.append(
                    {
                        "field": "polar_geometry",
                        "sources": ["layout_hint", "pixel_geometry"],
                        "message": "polar center or radius disagrees with independently detected circle",
                    }
                )
            else:
                warnings = ["polar layout hint agrees with detected circle geometry"]
        else:
            warnings = ["polar layout region has no usable center/radius evidence"]
    else:
        warnings = []

    labels, coverage, support, radial_consistency = _sample_labels(rgb, plot_region, palette)
    labels = _fill_gaps(labels)
    sectors: list[dict[str, Any]] = []
    for index, (palette_index, start, end) in enumerate(_runs(labels), start=1):
        angle = (end - start + 1) * 360.0 / _ANGLE_SAMPLES
        support_values = support[np.arange(start, end + 1) % _ANGLE_SAMPLES]
        mean_support = float(np.mean(support_values)) if len(support_values) else 0.0
        geometry = _sector_geometry(plot_region, start, end, angle)
        ratio_eligible = coverage >= _MIN_SECTOR_COVERAGE and mean_support >= _MIN_RATIO_SUPPORT
        sectors.append(
            {
                "id": f"sector_{index}",
                "geometry": geometry,
                "measure": {
                    "angle_deg": round(angle, 3),
                    "ratio": round(angle / 360.0, 6) if ratio_eligible else None,
                    "support": round(mean_support, 4),
                    "residual_deg": round(max(0.0, (1.0 - mean_support) * 8.0), 3),
                },
                "appearance": {
                    "color": rgb_to_hex(palette[palette_index]),
                    "palette_index": palette_index,
                    "confidence": round(mean_support, 4),
                },
                "association": {
                    "label": None,
                    "source": None,
                    "status": "unresolved",
                    "confidence": None,
                    "support": None,
                },
            }
        )

    if isinstance(layout_context, dict):
        validation = layout_context.get("validation") if isinstance(layout_context.get("validation"), dict) else {}
        if validation.get("status") == "rejected":
            warnings.append("layout context rejected; using pie pixel evidence fallback")
        elif validation.get("status") == "partial":
            warnings.append("layout context partially validated; pie geometry remains partial")
    if coverage < _MIN_SECTOR_COVERAGE:
        warnings.append("sector color coverage is incomplete; semantic ratios are partial")
    if radial_consistency < 0.70:
        warnings.append("sector colors are not consistent across sampled radii")
    if any(item["measure"]["support"] < _MIN_RATIO_SUPPORT for item in sectors):
        warnings.append("one or more sector boundaries have insufficient support")

    snippets = _ocr_snippets(path, scope.get("bbox_px") if scope else None)
    legend, legend_text = _legend(rgb, plot_region, palette, snippets, search_region)
    ocr_warnings, ocr_text, ocr_conflicts = _attach_ocr(sectors, plot_region, snippets)
    warnings.extend(ocr_warnings)
    conflicts.extend(ocr_conflicts)
    warnings.extend(_attach_external_labels(sectors, plot_region, snippets, legend_text | ocr_text))

    for entry in legend:
        matches = [
            item
            for item in sectors
            if item["appearance"].get("color") == entry.get("color")
        ]
        if len(matches) == 1:
            sector = matches[0]
            entry["association"] = {
                "sector_id": sector["id"],
                "status": "resolved" if entry.get("label") else "color_matched",
                "source": "legend_color",
                "confidence": entry.get("confidence") or 0.78,
            }
            if entry.get("label") and not sector["association"].get("label"):
                sector["association"] = {
                    "label": entry["label"],
                    "source": "legend",
                    "status": "resolved",
                    "confidence": entry.get("confidence"),
                    "support": "legend_color",
                }
        elif entry.get("label"):
            entry["association"]["status"] = "ambiguous"
            warnings.append(f"legend label {entry['label']!r} has ambiguous sector association")

    angle_total = sum(float((item.get("measure") or {}).get("angle_deg") or 0.0) for item in sectors)
    ratio_values = [
        float(item["measure"]["ratio"])
        for item in sectors
        if isinstance(item.get("measure"), dict) and item["measure"].get("ratio") is not None
    ]
    ratio_total = sum(ratio_values)
    angle_consistent = abs(angle_total - 360.0) <= 12.0
    ratio_consistent = bool(ratio_values) and abs(ratio_total - 1.0) <= 0.035
    consistent = bool(sectors and coverage >= _MIN_SECTOR_COVERAGE and angle_consistent and ratio_consistent)
    if not consistent:
        warnings.append("detected sector totals do not cover approximately 360 degrees or 100 percent")

    plot_region = {key: value for key, value in plot_region.items() if not key.startswith("_")}
    plot_region["sector_coverage"] = round(coverage, 4)
    plot_region["radial_consistency"] = round(radial_consistency, 4)
    geometry_confidence = min(0.98, float(plot_region.get("confidence", 0.0)) * 0.7 + coverage * 0.3)
    calibration_confidence = 0.96 if consistent else min(0.8, max(0.0, coverage))
    resolved_associations = [
        item for item in sectors if (item.get("association") or {}).get("status") == "resolved"
    ]
    association_confidence = (
        float(np.mean([float((item["association"] or {}).get("confidence") or 0.0) for item in resolved_associations]))
        if resolved_associations
        else 0.45
    )
    confidence = confidence_map(
        overall=geometry_confidence * 0.45 + calibration_confidence * 0.35 + association_confidence * 0.20,
        geometry=geometry_confidence,
        calibration=calibration_confidence,
        association=association_confidence,
    )
    layout_evidence = context_for_evidence(layout_context)
    data = {
        "image_size": image_size(rgb),
        "evidence": build_common_evidence(
            rgb,
            coordinate_system="polar_2d",
            frame=polar_frame(plot_region, warnings=warnings),
            legend=legend,
            series=[],
            confidence=confidence,
            warnings=warnings,
            layout_context=layout_evidence,
            conflicts=conflicts,
        ),
        "orientation": "upright",
        "transform": {"kind": "circular_invariant", "rotation_deg": None},
        "plot_region": plot_region,
        "layout_context": layout_evidence,
        "sectors": sectors,
        "legend": legend,
        "ocr": snippets,
        "totals": {
            "angle_deg": round(angle_total, 3),
            "ratio": round(ratio_total, 6),
            "angle_consistent": angle_consistent,
            "ratio_consistent": ratio_consistent,
            "consistent": consistent,
        },
        "confidence": confidence,
        "warnings": warnings,
    }
    return ToolResult(
        data,
        (
            GeneratedImage(
                render_pie_overlay(chart_image, plot_region, sectors, legend, warnings),
                "image/png",
                "Detected pie region, sectors, associations, and uncertainty",
            ),
        ),
        tuple(warnings),
    )


EXTRACT_PIE_SLICES = Tool(
    name="extract_pie_slices",
    description=(
        "Measure an ordinary authorized two-dimensional pie chart and return "
        "source-image plot geometry, stable sector evidence, gated angles and "
        "ratios, legend/OCR associations, confidence, warnings, and a "
        "source-sized overlay. Use it for recognizable circular pies; do not "
        "treat donut, exploded, nested, 3D, perspective, or ambiguous circular "
        "graphics as complete flat-pie data. Check evidence and warnings before "
        "using ratios for ChartSpec restoration."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Internal image path used only by the callable; authorized registrations replace this with attachment_id.",
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
    fn=extract_pie_slices,
    group="chart-observation",
)


__all__ = ["EXTRACT_PIE_SLICES", "extract_pie_slices"]
