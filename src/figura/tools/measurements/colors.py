"""Shared color sampling for visible Cartesian chart series."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def series_palette(rgb: np.ndarray) -> list[tuple[int, int, int]]:
    pixels = rgb.reshape(-1, 3).astype(np.int16)
    chroma = pixels.max(axis=1) - pixels.min(axis=1)
    selected = pixels[(chroma >= 55) & (pixels.min(axis=1) < 220) & (pixels.max(axis=1) > 72)]
    if not len(selected):
        return []
    quantized = ((selected // 16) * 16 + 8).astype(np.uint8)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    min_count = max(4, int(counts[order[0]] * 0.06))
    result: list[tuple[int, int, int]] = []
    for index in order:
        if int(counts[index]) < min_count:
            break
        color = tuple(int(channel) for channel in colors[index])
        if any(max(abs(a - b) for a, b in zip(color, existing, strict=True)) <= 42 for existing in result):
            continue
        result.append(color)
        if len(result) >= 8:
            break
    return result


def color_mask(rgb: np.ndarray, color: Sequence[int], tolerance: int = 34) -> np.ndarray:
    return np.max(np.abs(rgb.astype(np.int16) - np.asarray(color, dtype=np.int16)), axis=2) <= tolerance


def hex_color(color: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(value))):02x}" for value in color[:3])
