"""Whole-image OCR sensor exposed through the chart tool protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tool import Tool

_engine: Any = None


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR

        _engine = RapidOCR()
    return _engine


def _bbox(points: Any) -> list[int]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    left, top = min(xs), min(ys)
    right, bottom = max(xs), max(ys)
    return [
        int(round(left)),
        int(round(top)),
        int(round(right - left)),
        int(round(bottom - top)),
    ]


def extract_text(image_path: str) -> list[dict] | dict:
    """Return all recognized snippets with bounding boxes and confidence."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}

    try:
        result = _get_engine()(path)
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or texts is None or scores is None:
            return []
        return [
            {
                "text": str(text),
                "bbox": _bbox(box),
                "confidence": max(0.0, min(1.0, float(score))),
            }
            for box, text, score in zip(boxes, texts, scores)
        ]
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"extract_text failed for {image_path}: {exc}"}


EXTRACT_TEXT = Tool(
    name="extract_text",
    description=(
        "Run OCR over an entire chart image and return text snippets with "
        "pixel bounding boxes and confidence scores."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the local chart image.",
            }
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=extract_text,
)
