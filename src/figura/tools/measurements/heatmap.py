"""Cell geometry and color observations for ordinary heatmaps."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .contracts import MeasurementSensorResult, PreparedMeasurementImage
from .ocr import recognize_text
from .rectangular_regions import ColorRegion, enclosing_plot_area, visible_color_regions


def measure_heatmap(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    rgb = image.rgb
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, image.observation_mask) if image.observation_mask is not None else recognize_text(rgb)
    regions, truncated = visible_color_regions(image)
    plot_area = enclosing_plot_area(regions, width, height)
    if not regions or plot_area is None:
        return MeasurementSensorResult(
            status="no_evidence",
            observations={"row_labels": [], "column_labels": [], "cells": []},  # type: ignore[arg-type]
            confidence={"overall": 0.0, "geometry": 0.0, "calibration": 0.0, "association": 0.0},  # type: ignore[arg-type]
            warnings=("no rectangular heatmap color cells were reliably detected",),
        )

    typical_width = float(np.median([item.width for item in regions]))
    typical_height = float(np.median([item.height for item in regions]))
    columns = _cluster_regions(regions, "center_x", typical_width)
    rows = _cluster_regions(regions, "center_y", typical_height)
    row_for_region = _nearest_cluster_map(regions, rows, "center_y")
    column_for_region = _nearest_cluster_map(regions, columns, "center_x")
    buckets: dict[tuple[int, int], list[ColorRegion]] = defaultdict(list)
    for index, region in enumerate(regions):
        buckets[(row_for_region[index], column_for_region[index])].append(region)

    cells = []
    cell_bounds: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for row_index, column_index in sorted(buckets):
        candidates = buckets[(row_index, column_index)]
        left = min(item.left for item in candidates)
        top = min(item.top for item in candidates)
        right = max(item.right for item in candidates)
        bottom = max(item.bottom for item in candidates)
        weights = np.asarray([item.pixels for item in candidates], dtype=np.float64)
        colors = np.asarray([_rgb_tuple(item.color) for item in candidates], dtype=np.float64)
        color = tuple(int(round(value)) for value in np.average(colors, axis=0, weights=weights))
        row_id, column_id = f"row_{row_index + 1}", f"column_{column_index + 1}"
        cells.append(
            {
                "row_id": row_id,
                "column_id": column_id,
                "bounds_px": {"x": left, "y": top, "width": right - left, "height": bottom - top},
                "color": "#" + "".join(f"{channel:02x}" for channel in color),
                "value": None,
            }
        )
        cell_bounds[(row_index, column_index)] = (left, top, right, bottom)

    row_labels, labeled_rows = _row_labels(ocr.snippets, rows, plot_area, typical_height)
    column_labels, labeled_columns = _column_labels(ocr.snippets, columns, plot_area, typical_width)
    occupied_rows = {row_index for row_index, _ in buckets}
    occupied_columns = {column_index for _, column_index in buckets}
    row_labels = [row_labels[index] if index in occupied_rows else None for index in range(len(rows))]
    column_labels = [column_labels[index] if index in occupied_columns else None for index in range(len(columns))]

    widths = [bounds[2] - bounds[0] for bounds in cell_bounds.values()]
    heights = [bounds[3] - bounds[1] for bounds in cell_bounds.values()]
    size_consistency = min(_consistency(widths), _consistency(heights))
    regularity = 0.55 * size_consistency + 0.45 * min(1.0, len(occupied_rows) / 2, len(occupied_columns) / 2)
    status = "measured" if len(cells) >= 4 and len(occupied_rows) >= 2 and len(occupied_columns) >= 2 and regularity >= 0.55 else "partial"
    warnings = []
    if not any(cell["value"] is not None for cell in cells):
        warnings.append("cell colors were observed, but a readable calibrated color scale was not established; numeric values remain null")
    if not ocr.available:
        warnings.append("OCR is unavailable; row and column labels could not be associated")
    elif not labeled_rows and not labeled_columns:
        warnings.append("row or column labels were not reliably associated with the detected grid")
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; some heatmap labels may be missing")
    if truncated:
        warnings.append("heatmap color-region observation limit reached")
        status = "partial"
    geometry_confidence = min(0.95, 0.45 + 0.08 * min(len(cells), 6) + 0.15 * regularity)
    association_confidence = float(np.mean(labeled_rows + labeled_columns)) if labeled_rows or labeled_columns else 0.45
    observations = {"row_labels": row_labels, "column_labels": column_labels, "cells": cells}
    return MeasurementSensorResult(
        status=status,
        observations=observations,  # type: ignore[arg-type]
        confidence={
            "overall": _clamp(0.72 * geometry_confidence + 0.28 * association_confidence),
            "geometry": _clamp(geometry_confidence),
            "calibration": 0.0,
            "association": _clamp(association_confidence),
        },  # type: ignore[arg-type]
        plot_area_px=plot_area,
        warnings=tuple(warnings),
        truncated=truncated,
    )


def _cluster_regions(regions: list[ColorRegion], coordinate: str, typical_size: float) -> list[float]:
    centers = sorted(float(getattr(item, coordinate)) for item in regions)
    if not centers:
        return []
    tolerance = max(3.0, typical_size * 0.42)
    clusters: list[list[float]] = [[centers[0]]]
    for center in centers[1:]:
        if center - float(np.mean(clusters[-1])) <= tolerance:
            clusters[-1].append(center)
        else:
            clusters.append([center])
    return [float(np.mean(cluster)) for cluster in clusters]


def _nearest_cluster_map(regions: list[ColorRegion], clusters: list[float], coordinate: str) -> dict[int, int]:
    result = {}
    for index, region in enumerate(regions):
        value = float(getattr(region, coordinate))
        nearest = min(range(len(clusters)), key=lambda item: abs(clusters[item] - value))
        result[index] = nearest
    return result


def _row_labels(snippets, centers: list[float], plot_area: dict[str, int], cell_height: float):
    labels: list[str | None] = [None] * len(centers)
    confidences: list[float] = []
    left, right = plot_area["x"], plot_area["x"] + plot_area["width"]
    candidates = []
    for snippet in snippets:
        x, y, width, height = snippet.bbox_px
        center_x, center_y = x + width / 2, y + height / 2
        if left <= center_x <= right:
            continue
        nearest = min(range(len(centers)), key=lambda index: abs(centers[index] - center_y)) if centers else None
        if nearest is None or abs(centers[nearest] - center_y) > max(14, cell_height * 0.8):
            continue
        candidates.append((abs(centers[nearest] - center_y), -snippet.confidence, nearest, snippet.text[:160]))
    for _, negative_confidence, index, text in sorted(candidates):
        if labels[index] is None:
            labels[index] = text
            confidences.append(-negative_confidence)
    return labels, confidences


def _column_labels(snippets, centers: list[float], plot_area: dict[str, int], cell_width: float):
    labels: list[str | None] = [None] * len(centers)
    confidences: list[float] = []
    top, bottom = plot_area["y"], plot_area["y"] + plot_area["height"]
    candidates = []
    for snippet in snippets:
        x, y, width, height = snippet.bbox_px
        center_x, center_y = x + width / 2, y + height / 2
        if top <= center_y <= bottom:
            continue
        nearest = min(range(len(centers)), key=lambda index: abs(centers[index] - center_x)) if centers else None
        if nearest is None or abs(centers[nearest] - center_x) > max(18, cell_width * 0.8):
            continue
        candidates.append((abs(centers[nearest] - center_x), -snippet.confidence, nearest, snippet.text[:160]))
    for _, negative_confidence, index, text in sorted(candidates):
        if labels[index] is None:
            labels[index] = text
            confidences.append(-negative_confidence)
    return labels, confidences


def _rgb_tuple(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def _consistency(values: list[int]) -> float:
    if not values:
        return 0.0
    average = float(np.mean(values))
    if average <= 0:
        return 0.0
    return max(0.0, 1.0 - float(np.std(values)) / average)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
