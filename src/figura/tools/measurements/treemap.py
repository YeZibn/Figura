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
    groups = _visible_groups(image, ocr.snippets, regions)
    regions = [*regions,*groups]
    plot_area = enclosing_plot_area(regions, width, height)
    root_label = None
    if plot_area is not None and len(groups)>=2:
        center_x = plot_area["x"]+plot_area["width"]/2
        candidates = [s for s in ocr.snippets if
            abs(s.bbox_px[0]+s.bbox_px[2]/2-center_x) <= plot_area["width"]*.15 and
            0 < plot_area["y"]-(s.bbox_px[1]+s.bbox_px[3]/2) <= 35]
        if len(candidates)==1:
            root_label = candidates[0]
            regions.append(ColorRegion(plot_area["x"],plot_area["y"],plot_area["width"],plot_area["height"],
                plot_area["width"]*plot_area["height"],"#ffffff",1.0))
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
    if root_label is not None:
        labels[-1] = (root_label.text,root_label.confidence)
        # The root spans the observed grouped plot, including equal-size groups.
        parent_indices = [len(regions)-1 if p is None and i!=len(regions)-1 else p for i,p in enumerate(parent_indices)]
    for index, region in enumerate(regions):
        if index in parent_indices and index!=len(regions)-1:
            header = [s for s in ocr.snippets if region.left <= s.bbox_px[0]+s.bbox_px[2]/2 <= region.right and
                region.top <= s.bbox_px[1]+s.bbox_px[3]/2 <= region.top+region.height*.18]
            if len(header)==1:
                labels[index] = (header[0].text,header[0].confidence)
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
                "role": "group" if index in parent_indices else "leaf",
                "area_ratio_basis": "parent_plot" if parent_index is not None else "root_plot",
                "area_ratio_parent_id": f"node_{parent_index + 1}" if parent_index is not None else None,
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


def _visible_groups(image, snippets, leaves):
    """Recover sparse enclosing contours with filled title bands and children."""
    from .colors import series_palette, color_mask, hex_color
    from .pie import _components
    groups = []
    for color in series_palette(image.rgb,limit=512):
        mask = color_mask(image.rgb,color,tolerance=3)
        if image.observation_mask is not None:
            mask &= image.observation_mask
        for component in _components(mask,20):
            x,y,w,h = component["bbox"]
            if w<30 or h<30 or component["area"]/(w*h) >= .42:
                continue
            inside = [leaf for leaf in leaves if x<=leaf.left and y<=leaf.top and x+w>=leaf.right and y+h>=leaf.bottom]
            if len(inside)<2:
                continue
            upper = mask[y:y+max(3,int(h*.18)),x:x+w]
            if np.count_nonzero(upper.sum(axis=1)>=w*.7)<4:
                continue
            header = [s for s in snippets if x<=s.bbox_px[0]+s.bbox_px[2]/2<=x+w and y<=s.bbox_px[1]+s.bbox_px[3]/2<=y+h*.18]
            if len(header)!=1:
                continue
            if any(abs(x-r.left)<=2 and abs(y-r.top)<=2 and abs(w-r.width)<=2 and abs(h-r.height)<=2 for r in groups):
                continue
            groups.append(ColorRegion(x,y,w,h,component["area"],hex_color(color),1.0))
    return groups
