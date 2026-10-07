"""Shared color sampling for visible Cartesian chart series."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def series_palette(rgb: np.ndarray, *, limit: int = 8) -> list[tuple[int, int, int]]:
    # A color must have a spatial body. Antialias fringes rarely have a full
    # same-color neighbourhood; true small objects and translucent fills do.
    # No RGB-distance suppression between distinct body colors is performed.
    from scipy.ndimage import convolve
    pixels = rgb.reshape(-1, 3).astype(np.int16)
    chroma = pixels.max(axis=1) - pixels.min(axis=1)
    selected = (chroma >= 18) & (pixels.min(axis=1) < 248)
    if not np.any(selected):
        return []
    colors, counts = np.unique(pixels[selected], axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    result = []
    for index in order:
        if counts[index] < 4:
            break
        color = tuple(int(v) for v in colors[index])
        mask = np.all(rgb == colors[index], axis=2)
        neighbours = convolve(mask.astype(np.uint8), np.ones((3, 3), dtype=np.uint8), mode="constant")
        if np.count_nonzero(mask & (neighbours >= 4)) < 4:
            continue
        result.append(color)
        if len(result) >= limit:
            break
    return result


def color_mask(rgb: np.ndarray, color: Sequence[int], tolerance: int = 34, *, palette=None) -> np.ndarray:
    pixels = rgb.astype(np.int16)
    distance = np.max(np.abs(pixels - np.asarray(color,dtype=np.int16)),axis=2)
    mask = distance <= tolerance
    if palette is not None:
        for other in palette:
            if tuple(other) == tuple(color):
                continue
            competing = np.max(np.abs(pixels-np.asarray(other,dtype=np.int16)),axis=2)
            mask &= distance < competing if tuple(other)<tuple(color) else distance <= competing
    return mask


def hex_color(color: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(value))):02x}" for value in color[:3])
