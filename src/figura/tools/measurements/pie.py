"""Polar geometry observations for ordinary circular pie charts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import hypot
from typing import Any

import numpy as np

from .ocr import OCRSnippet, recognize_text

_ANGLE_SAMPLES = 720
_RADII = (0.58, 0.70, 0.82, 0.91, 0.97)
_COLOR_TOLERANCE = 52
_MIN_RATIO_COVERAGE = 0.80
_MIN_RATIO_SUPPORT = 0.56


def measure_pie_pixels(rgb: np.ndarray, observation_mask: np.ndarray | None = None) -> dict[str, Any]:
    """Measure an already decoded, scope-masked RGB source without shifting its coordinates."""
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, observation_mask) if observation_mask is not None else recognize_text(rgb)
    palette = _palette(rgb)
    region = _find_region(rgb, palette, observation_mask)
    warnings: list[str] = []
    if ocr.truncated:
        warnings.append("OCR output was truncated; some sector labels may be missing")
    if not ocr.available:
        warnings.append("OCR is unavailable; sector labels could not be associated")
    if region is None:
        warnings.append("no reliable circular pie geometry was detected")
        return _result(width, height, "no_evidence", None, [], (0.0, 0.0, 0.0, 0.0), warnings)
    if region["shape"] == "unsupported":
        warnings.append(region["warning"])
        return _result(
            width,
            height,
            "unsupported",
            {"center_px": region["center_px"], "radius_px": region["radius_px"]},
            [],
            (region["confidence"], 0.0, 0.0, 0.0),
            warnings,
        )

    labels, support, coverage, radial_support = _sample_sectors(
        rgb,
        palette,
        region,
        observation_mask,
    )
    labels = _fill_small_gaps(labels)
    sector_data = _sector_runs(labels, support, palette)
    _associate_labels(sector_data, region, ocr.snippets)
    total_sweep = sum(item["sweep_angle_deg"] for item in sector_data)
    if any(item["confidence"] < _MIN_RATIO_SUPPORT for item in sector_data):
        warnings.append("one or more sector boundaries have insufficient radial support")
    if coverage < _MIN_RATIO_COVERAGE:
        warnings.append("observed angular coverage is incomplete; sector ratios are partial")
    if abs(total_sweep - 360.0) > 12.0:
        warnings.append("detected sectors do not cover approximately 360 degrees")

    ratios = [item["ratio"] for item in sector_data if item["ratio"] is not None]
    measured = (
        bool(sector_data)
        and all(item["ratio"] is not None for item in sector_data)
        and abs(total_sweep - 360.0) <= 12.0
        and bool(ratios)
        and abs(sum(ratios) - 1.0) <= 0.035
    )
    status = "measured" if measured else "partial" if sector_data else "no_evidence"
    if not sector_data:
        warnings.append("pie sectors could not be separated from the observed pixels")
    association = [
        item["label_confidence"]
        for item in sector_data
        if item["label_confidence"] is not None
    ]
    association_confidence = float(np.mean(association)) if association else 0.0
    segmentation_confidence = min(1.0, coverage * radial_support)
    geometry_confidence = region["confidence"]
    overall = 0.45 * geometry_confidence + 0.4 * segmentation_confidence + 0.15 * association_confidence
    return _result(
        width,
        height,
        status,
        {"center_px": region["center_px"], "radius_px": region["radius_px"]},
        sector_data,
        (overall, geometry_confidence, segmentation_confidence, association_confidence),
        warnings,
    )


def _palette(rgb: np.ndarray, max_colors: int = 12) -> list[tuple[int, int, int]]:
    pixels = rgb.reshape(-1, 3).astype(np.int16)
    spread = pixels.max(axis=1) - pixels.min(axis=1)
    colored = pixels[(spread >= 48) & (pixels.min(axis=1) < 245)]
    if len(colored) < 20:
        return []
    quantized = ((colored // 16) * 16 + 8).astype(np.uint8)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    minimum = max(20, int(counts[order[0]] * 0.012))
    palette: list[tuple[int, int, int]] = []
    for index in order:
        if int(counts[index]) < minimum:
            break
        color = tuple(int(value) for value in colors[index])
        if any(max(abs(a - b) for a, b in zip(color, known, strict=True)) <= 42 for known in palette):
            continue
        palette.append(color)
        if len(palette) == max_colors:
            break
    return palette


def _find_region(
    rgb: np.ndarray,
    palette: Sequence[Sequence[int]],
    observation_mask: np.ndarray | None,
) -> dict[str, Any] | None:
    if not palette:
        return None
    height, width = rgb.shape[:2]
    min_area = max(24, int(height * width * 0.0008))
    components: list[dict[str, Any]] = []
    for palette_index, color in enumerate(palette):
        mask = _color_mask(rgb, color)
        if observation_mask is not None:
            mask &= observation_mask
        components.extend(
            {**item, "palette_index": palette_index}
            for item in _components(mask, min_area)
        )
    candidates: list[dict[str, Any]] = []
    min_dimension = min(height, width)
    for anchor in sorted(components, key=lambda item: item["area"], reverse=True)[:12]:
        left, top, box_width, box_height = anchor["bbox"]
        anchor_size = max(box_width, box_height)
        anchor_x, anchor_y = anchor["center"]
        nearby = [
            item
            for item in components
            if item["area"] >= anchor["area"] * 0.12
            and hypot(item["center"][0] - anchor_x, item["center"][1] - anchor_y)
            <= max(anchor_size * 1.65, min_dimension * 0.12)
        ]
        if not nearby:
            continue
        left = min(item["bbox"][0] for item in nearby)
        top = min(item["bbox"][1] for item in nearby)
        right = max(item["bbox"][0] + item["bbox"][2] for item in nearby)
        bottom = max(item["bbox"][1] + item["bbox"][3] for item in nearby)
        box_width, box_height = right - left, bottom - top
        if min(box_width, box_height) < max(36, int(min_dimension * 0.08)):
            continue
        center_x, center_y = (left + right) / 2.0, (top + bottom) / 2.0
        radius = min(box_width, box_height) / 2.0
        aspect_ratio = max(box_width, box_height) / max(1.0, min(box_width, box_height))
        yy, xx = np.ogrid[:height, :width]
        disk = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius**2
        scope_clipped = observation_mask is not None and not bool(np.all(observation_mask[disk]))
        if observation_mask is not None:
            disk &= observation_mask
        color_union = np.zeros((height, width), dtype=bool)
        for item in nearby:
            color_union |= _color_mask(rgb, palette[item["palette_index"]])
        colored_coverage = float(np.mean(color_union[disk])) if np.any(disk) else 0.0
        center_radius = max(1, int(round(radius * 0.035)))
        cx, cy = int(round(center_x)), int(round(center_y))
        center = rgb[
            max(0, cy - center_radius) : min(height, cy + center_radius + 1),
            max(0, cx - center_radius) : min(width, cx + center_radius + 1),
        ]
        center_observed = observation_mask is None or bool(
            np.all(
                observation_mask[
                    max(0, cy - center_radius) : min(height, cy + center_radius + 1),
                    max(0, cx - center_radius) : min(width, cx + center_radius + 1),
                ]
            )
        )
        center_support = float(np.mean(_is_palette_pixel(center, palette))) if center.size else 0.0
        aspect_score = max(0.0, 1.0 - abs(aspect_ratio - 1.0) / 0.45)
        coverage_score = min(1.0, colored_coverage / 0.55)
        center_score = min(1.0, center_support / 0.35)
        confidence = max(0.0, min(0.98, 0.4 * aspect_score + 0.4 * coverage_score + 0.2 * center_score))
        shape, warning = "circle", ""
        if aspect_ratio > 1.18 and not scope_clipped:
            shape, warning = "unsupported", "elliptical or perspective pie geometry is unsupported"
        elif center_observed and center_support < 0.12 and colored_coverage >= 0.20 and not scope_clipped:
            inner_radius = _estimate_inner_radius_px(
                rgb,
                (center_x, center_y),
                radius,
                observation_mask,
                palette=palette,
            )
            if inner_radius is None:
                shape, warning = "unsupported", "exploded pie geometry is unsupported"
            else:
                shape, warning = "donut", ""
        candidates.append({
            "shape": shape,
            "warning": warning,
            "center_px": [round(center_x, 3), round(center_y, 3)],
            "radius_px": round(radius, 3),
            "confidence": round(confidence, 4),
            "area": sum(item["area"] for item in nearby),
        })
    return max(candidates, key=lambda item: (item["confidence"], item["area"])) if candidates else None


def _estimate_inner_radius_px(
    rgb: np.ndarray,
    center_px: Sequence[float],
    outer_radius_px: float,
    observation_mask: np.ndarray | None,
    *,
    palette: Sequence[Sequence[int]] | None = None,
) -> float | None:
    """Estimate a visible central hole only when several rings support a donut annulus."""
    colors = list(palette) if palette is not None else _palette(rgb)
    if not colors or outer_radius_px <= 0:
        return None
    center_x, center_y = float(center_px[0]), float(center_px[1])
    fractions = np.arange(0.04, 0.66, 0.025)
    angles = np.arange(0, 360, 4, dtype=float) * (np.pi / 180.0)
    scores: list[float] = []
    for fraction in fractions:
        xs = np.clip(np.rint(center_x + outer_radius_px * fraction * np.cos(angles)).astype(int), 0, rgb.shape[1] - 1)
        ys = np.clip(np.rint(center_y + outer_radius_px * fraction * np.sin(angles)).astype(int), 0, rgb.shape[0] - 1)
        visible = np.ones(len(xs), dtype=bool) if observation_mask is None else observation_mask[ys, xs]
        if int(np.count_nonzero(visible)) < len(xs) * 0.35:
            scores.append(0.0)
            continue
        selected = rgb[ys[visible], xs[visible]]
        scores.append(float(np.mean(_is_palette_pixel(selected[:, None, :], colors))))

    first_supported: int | None = None
    for index in range(1, len(scores) - 2):
        if scores[index] >= 0.58 and scores[index + 1] >= 0.58 and scores[index + 2] >= 0.58:
            first_supported = index
            break
    if first_supported is None or fractions[first_supported] < 0.16:
        return None
    preceding = scores[:first_supported]
    if preceding and max(preceding) >= 0.45:
        return None
    return round(float(fractions[first_supported - 1] * outer_radius_px), 3)


def _components(mask: np.ndarray, min_area: int) -> list[dict[str, Any]]:
    """Find 8-connected component bounds from row runs."""
    parents: list[int] = []
    runs: list[tuple[int, int, int, int]] = []
    previous: list[tuple[int, int, int]] = []
    for y, row in enumerate(mask):
        xs = np.flatnonzero(row)
        if not len(xs):
            previous = []
            continue
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts, ends = np.r_[0, breaks + 1], np.r_[breaks, len(xs) - 1]
        current: list[tuple[int, int, int]] = []
        previous_index = 0
        for first, last in zip(starts, ends, strict=True):
            left, right = int(xs[first]), int(xs[last])
            run_id = len(parents)
            parents.append(run_id)
            while previous_index < len(previous) and previous[previous_index][1] < left - 1:
                previous_index += 1
            scan = previous_index
            while scan < len(previous) and previous[scan][0] <= right + 1:
                prior_left, prior_right, prior_id = previous[scan]
                if prior_right >= left - 1:
                    _union(parents, run_id, prior_id)
                scan += 1
            current.append((left, right, run_id))
            runs.append((y, left, right, run_id))
        previous = current
    groups: dict[int, list[int]] = {}
    for y, left, right, run_id in runs:
        root = _find(parents, run_id)
        item = groups.setdefault(root, [0, left, y, right, y])
        item[0] += right - left + 1
        item[1] = min(item[1], left)
        item[2] = min(item[2], y)
        item[3] = max(item[3], right)
        item[4] = max(item[4], y)
    result = []
    for area, left, top, right, bottom in groups.values():
        if area < min_area:
            continue
        result.append({
            "area": area,
            "bbox": [left, top, right - left + 1, bottom - top + 1],
            "center": [(left + right) / 2.0, (top + bottom) / 2.0],
        })
    return result


def _find(parents: list[int], item: int) -> int:
    while parents[item] != item:
        parents[item] = parents[parents[item]]
        item = parents[item]
    return item


def _union(parents: list[int], left: int, right: int) -> None:
    first, second = _find(parents, left), _find(parents, right)
    if first != second:
        parents[second] = first


def _color_mask(rgb: np.ndarray, color: Sequence[int]) -> np.ndarray:
    return (
        np.max(np.abs(rgb.astype(np.int16) - np.asarray(color, dtype=np.int16)), axis=2)
        <= _COLOR_TOLERANCE
    )


def _is_palette_pixel(rgb: np.ndarray, palette: Sequence[Sequence[int]]) -> np.ndarray:
    if not palette:
        return np.zeros(rgb.shape[:2], dtype=bool)
    distances = np.stack(
        [
            np.max(np.abs(rgb.astype(np.int16) - np.asarray(color, dtype=np.int16)), axis=2)
            for color in palette
        ],
        axis=0,
    )
    return np.min(distances, axis=0) <= _COLOR_TOLERANCE


def _sample_sectors(
    rgb: np.ndarray,
    palette: Sequence[Sequence[int]],
    region: Mapping[str, Any],
    observation_mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    center_x, center_y = region["center_px"]
    radius = float(region["radius_px"])
    angles = np.arange(_ANGLE_SAMPLES, dtype=float) * (2.0 * np.pi / _ANGLE_SAMPLES)
    sampled = np.full((len(_RADII), _ANGLE_SAMPLES), -1, dtype=int)
    for radial_index, fraction in enumerate(_RADII):
        xs = np.clip(
            np.rint(center_x + radius * fraction * np.sin(angles)).astype(int),
            0,
            rgb.shape[1] - 1,
        )
        ys = np.clip(
            np.rint(center_y - radius * fraction * np.cos(angles)).astype(int),
            0,
            rgb.shape[0] - 1,
        )
        pixels = rgb[ys, xs].astype(np.int16)
        distances = np.stack(
            [np.max(np.abs(pixels - np.asarray(color, dtype=np.int16)), axis=1) for color in palette],
            axis=1,
        )
        nearest = np.argmin(distances, axis=1)
        nearest[distances[np.arange(_ANGLE_SAMPLES), nearest] > _COLOR_TOLERANCE] = -1
        if observation_mask is not None:
            nearest[~observation_mask[ys, xs]] = -1
        sampled[radial_index] = nearest
    labels = np.full(_ANGLE_SAMPLES, -1, dtype=int)
    support = np.zeros(_ANGLE_SAMPLES, dtype=float)
    for index in range(_ANGLE_SAMPLES):
        valid = sampled[:, index][sampled[:, index] >= 0]
        if not len(valid):
            continue
        counts = np.bincount(valid, minlength=len(palette))
        label = int(np.argmax(counts))
        support[index] = float(counts[label]) / len(_RADII)
        if counts[label] >= 2:
            labels[index] = label
    coverage = float(np.mean(labels >= 0))
    radial_support = float(np.mean(support[labels >= 0])) if np.any(labels >= 0) else 0.0
    return labels, support, coverage, radial_support


def _fill_small_gaps(labels: np.ndarray, max_gap: int = 10) -> np.ndarray:
    result = labels.copy()
    for _ in range(2):
        for index in range(len(result)):
            if result[index] >= 0:
                continue
            gap = 1
            while gap <= max_gap and result[(index + gap) % len(result)] < 0:
                gap += 1
            if gap > max_gap:
                continue
            before, after = result[index - 1], result[(index + gap) % len(result)]
            if before >= 0 and before == after:
                result[index : min(len(result), index + gap)] = before
                if index + gap > len(result):
                    result[: (index + gap) % len(result)] = before
    return result


def _sector_runs(
    labels: np.ndarray,
    support: np.ndarray,
    palette: Sequence[Sequence[int]],
) -> list[dict[str, Any]]:
    valid = labels >= 0
    if not np.any(valid):
        return []
    if np.all(valid) and np.all(labels == labels[0]):
        runs = [(int(labels[0]), 0, len(labels))]
    else:
        starts = [
            index
            for index, label in enumerate(labels)
            if label >= 0 and labels[index - 1] != label
        ]
        runs: list[tuple[int, int, int]] = []
        for start in starts:
            label = int(labels[start])
            length = 0
            while length < len(labels) and labels[(start + length) % len(labels)] == label:
                length += 1
            if length >= 4:
                runs.append((label, start, length))
    result = []
    ordered_runs = sorted(runs, key=lambda item: item[1])
    for sector_id, (palette_index, start, length) in enumerate(ordered_runs, start=1):
        sweep = length * 360.0 / _ANGLE_SAMPLES
        mean_support = float(np.mean(support[(start + np.arange(length)) % len(labels)]))
        result.append({
            "id": sector_id,
            "start_angle_deg": round(start * 360.0 / _ANGLE_SAMPLES, 3),
            "sweep_angle_deg": round(sweep, 3),
            "ratio": round(sweep / 360.0, 6) if mean_support >= _MIN_RATIO_SUPPORT else None,
            "color": _hex(palette[palette_index]),
            "label_text": None,
            "label_confidence": None,
            "confidence": round(mean_support, 4),
        })
    total_coverage = float(np.mean(valid))
    if total_coverage < _MIN_RATIO_COVERAGE:
        for item in result:
            item["ratio"] = None
    return result


def _associate_labels(
    sectors: list[dict[str, Any]],
    region: Mapping[str, Any],
    snippets: Sequence[OCRSnippet],
) -> None:
    center_x, center_y = region["center_px"]
    radius = float(region["radius_px"])
    candidates: dict[int, list[tuple[float, float, str]]] = {item["id"]: [] for item in sectors}
    for snippet in snippets:
        from .cartesian import parse_numeric_text
        if parse_numeric_text(snippet.text) is not None:
            continue
        left, top, width, height = snippet.bbox_px
        x, y = left + width / 2.0, top + height / 2.0
        distance = hypot(x - center_x, y - center_y)
        if distance > radius * 1.65 or distance < radius * 0.15:
            continue
        angle = float(np.degrees(np.arctan2(x - center_x, center_y - y)) % 360.0)
        for sector in sectors:
            offset = (angle - sector["start_angle_deg"]) % 360.0
            if offset <= sector["sweep_angle_deg"]:
                midpoint_distance = abs(offset - sector["sweep_angle_deg"] / 2.0)
                candidates[sector["id"]].append((midpoint_distance, -snippet.confidence, snippet.text[:128]))
                break
    for sector in sectors:
        matches = candidates[sector["id"]]
        if matches:
            _distance, negative_confidence, text = min(matches)
            sector["label_text"] = text
            sector["label_confidence"] = round(-negative_confidence, 4)


def _result(
    width: int,
    height: int,
    status: str,
    plot_region: Mapping[str, Any] | None,
    sectors: Sequence[Mapping[str, Any]],
    confidence: tuple[float, float, float, float],
    warnings: Sequence[str],
) -> dict[str, Any]:
    overall, geometry, segmentation, association = confidence
    return {
        "image_size": {"width": width, "height": height},
        "status": status,
        "plot_region": dict(plot_region) if plot_region is not None else None,
        "sectors": [dict(item) for item in sectors],
        "confidence": {
            "overall": _clamp(overall),
            "geometry": _clamp(geometry),
            "segmentation": _clamp(segmentation),
            "association": _clamp(association),
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def _hex(color: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(channel))):02x}" for channel in color[:3])


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
