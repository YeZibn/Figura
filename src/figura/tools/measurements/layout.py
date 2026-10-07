"""Observed legend samples, kept separate from chart data and calibration."""
from collections.abc import Sequence
import numpy as np
from scipy.ndimage import label, find_objects

from .colors import color_mask
from .cartesian import parse_numeric_text


def legend_regions(rgb, snippets, palette):
    """Require compact samples paired with text and an aligned legend group.

    A solitary color mark next to text is ambiguous and is not removed. Bounds
    remain in the source frame and are inferred only from already masked pixels.
    """
    height, width = rgb.shape[:2]
    candidates = []
    for color in palette:
        components, count = label(color_mask(rgb, color))
        for slices in find_objects(components):
            if slices is None:
                continue
            yy, xx = slices
            x, y, w, h = xx.start, yy.start, xx.stop - xx.start, yy.stop - yy.start
            if not (2 <= w <= max(48, width * .08) and 2 <= h <= max(22, height * .04)):
                continue
            for snippet in snippets:
                if parse_numeric_text(snippet.text) is not None:
                    continue
                tx, ty, tw, th = snippet.bbox_px
                if 0 <= tx - (x + w) <= 20 and ty <= y + h / 2 <= ty + th:
                    candidates.append((x, y, w, h, snippet))
                    break
    retained = []
    for candidate in candidates:
        x, y, w, h, snippet = candidate
        aligned = any(other is not candidate and other[4].snippet_id != snippet.snippet_id and
            (abs(other[0] - x) <= 6 or abs(other[1] - y) <= 6)
            for other in candidates)
        if aligned:
            retained.append((x - 1, y - 1, w + 2, h + 2))
    return retained


def exclude_legend(mask, regions, offset=(0, 0)):
    mask = mask.copy()
    ox, oy = offset
    for x, y, w, h in regions:
        left, top = max(0, x - ox), max(0, y - oy)
        right, bottom = min(mask.shape[1], x + w - ox), min(mask.shape[0], y + h - oy)
        if right > left and bottom > top:
            mask[top:bottom, left:right] = False
    return mask
