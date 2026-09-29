"""Scoped OCR observations used by Figura chart measurement sensors."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from threading import Lock
from typing import Any

import numpy as np


_MAX_OCR_SNIPPETS = 512
_MAX_OCR_TEXT_LENGTH = 128


@dataclass(frozen=True)
class OCRSnippet:
    snippet_id: str
    text: str
    bbox_px: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class OCRObservation:
    snippets: tuple[OCRSnippet, ...]
    available: bool
    truncated: bool = False


_engine: Any = None
_engine_lock = Lock()


def recognize_text(image_rgb: np.ndarray) -> OCRObservation:
    """Return bounded OCR snippets without exposing provider-facing images."""
    if (
        not isinstance(image_rgb, np.ndarray)
        or image_rgb.ndim != 3
        or image_rgb.shape[2] != 3
        or image_rgb.size == 0
    ):
        return OCRObservation((), False)

    try:
        with _engine_lock:
            result = _get_engine()(image_rgb)
    except Exception:  # OCR is optional evidence; geometric measurement can proceed.
        return OCRObservation((), False)

    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return OCRObservation((), True)

    snippets: list[OCRSnippet] = []
    truncated = False
    try:
        for index, (box, text, score) in enumerate(zip(boxes, texts, scores, strict=False), start=1):
            if index > _MAX_OCR_SNIPPETS:
                truncated = True
                break
            normalized_text = str(text).strip()
            bbox = _bbox(box)
            confidence = float(score)
            if not normalized_text or bbox is None or not isfinite(confidence):
                continue
            snippets.append(
                OCRSnippet(
                    f"text_{index}",
                    normalized_text[:_MAX_OCR_TEXT_LENGTH],
                    bbox,
                    _clamp(confidence),
                )
            )
    except (TypeError, ValueError, OverflowError):
        return OCRObservation((), True)
    return OCRObservation(tuple(snippets), True, truncated)


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR

        _engine = RapidOCR()
    return _engine


def _bbox(points: Any) -> tuple[int, int, int, int] | None:
    try:
        coordinates = [(float(point[0]), float(point[1])) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    if not coordinates or any(not isfinite(value) for point in coordinates for value in point):
        return None
    left = int(round(min(point[0] for point in coordinates)))
    top = int(round(min(point[1] for point in coordinates)))
    right = int(round(max(point[0] for point in coordinates)))
    bottom = int(round(max(point[1] for point in coordinates)))
    return left, top, max(1, right - left), max(1, bottom - top)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
