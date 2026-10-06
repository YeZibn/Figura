"""Visible rectangle hierarchy and relative-area observations for treemaps."""

from __future__ import annotations

import numpy as np

from .contracts import MeasurementSensorResult, PreparedMeasurementImage
from .ocr import recognize_text
from .rectangular_regions import ColorRegion, enclosing_plot_area, matched_label, visible_color_regions


def measure_treemap(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    rgb = image.rgb
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, image.observation_mask) if image.observation_mask is not None else recognize_text(rgb)
    regions, truncated = visible_color_regions(image)
    plot_area = enclosing_plot_area(regions, width, height)
    if not regions or plot_area is None:
        return MeasurementSensorResult(
            status="no_evidence",
            observations={"nodes": []},  # type: ignore[arg-type]
            confidence={"overall": 0.0, "geometry": 0.0, "calibration": 0.0, "association": 0.0},  # type: ignore[arg-type]
            warnings=("no rectangular treemap regions were reliably detected",),
        )

    nodes = []
    labels: list[tuple[str | None, float | None]] = [matched_label(region, ocr.snippets) for region in regions]
    parent_indices = [_parent_index(regions, index) for index in range(len(regions))]
    for index, region in enumerate(regions):
        parent_index = parent_indices[index]
        denominator = (
            regions[parent_index].width * regions[parent_index].height
            if parent_index is not None
            else plot_area["width"] * plot_area["height"]
        )
        area_ratio = min(1.0, (region.width * region.height) / max(1, denominator))
        nodes.append(
            {
                "id": f"node_{index + 1}",
                "parent_id": f"node_{parent_index + 1}" if parent_index is not None else None,
                "label": labels[index][0],
                "bounds_px": region.bounds_px,
                "value": None,
                "area_ratio": round(area_ratio, 6),
            }
        )

    geometry_confidence = float(np.mean([region.rectangularity for region in regions]))
    geometry_confidence = min(0.95, max(0.35, geometry_confidence))
    associated = [confidence for _, confidence in labels if confidence is not None]
    association_confidence = float(np.mean(associated)) if associated else 0.4
    status = "measured" if len(regions) >= 2 and geometry_confidence >= 0.62 else "partial"
    warnings = []
    if not associated:
        warnings.append("treemap labels were not reliably recognized inside the detected rectangles")
    if not any(node["value"] is not None for node in nodes):
        warnings.append("rectangle areas are observed, but explicit source values were not legible; values remain null")
    if not any(parent is not None for parent in parent_indices):
        warnings.append("no visible enclosing rectangles established parent-child hierarchy")
    if not ocr.available:
        warnings.append("OCR is unavailable; rectangle labels could not be associated")
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; some treemap labels may be missing")
    if truncated:
        warnings.append("treemap color-region observation limit reached")
        status = "partial"

    return MeasurementSensorResult(
        status=status,
        observations={"nodes": nodes},  # type: ignore[arg-type]
        confidence={
            "overall": _clamp(0.76 * geometry_confidence + 0.24 * association_confidence),
            "geometry": _clamp(geometry_confidence),
            "calibration": 0.0,
            "association": _clamp(association_confidence),
        },  # type: ignore[arg-type]
        plot_area_px=plot_area,
        warnings=tuple(warnings),
        truncated=truncated,
    )


def _parent_index(regions: list[ColorRegion], child_index: int) -> int | None:
    child = regions[child_index]
    containers = []
    for index, candidate in enumerate(regions):
        if index == child_index or candidate.width * candidate.height <= child.width * child.height * 1.2:
            continue
        contains = (
            candidate.left <= child.left
            and candidate.top <= child.top
            and candidate.right >= child.right
            and candidate.bottom >= child.bottom
        )
        strict = candidate.left < child.left or candidate.top < child.top or candidate.right > child.right or candidate.bottom > child.bottom
        if contains and strict:
            containers.append(index)
    return min(containers, key=lambda index: regions[index].width * regions[index].height) if containers else None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
