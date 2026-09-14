"""Whole-image OCR sensor exposed through the chart tool protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from ..result import GeneratedImage, ToolResult
from ..tool import Tool
from .overlays import render_ocr_overlay

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


def extract_text(image_path: str) -> ToolResult | dict:
    """Return OCR snippets plus a model-readable detection overlay."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": f"image not found: {image_path}"}

    try:
        with Image.open(path) as source:
            chart_image = source.convert("RGB")
        result = _get_engine()(path)
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or texts is None or scores is None:
            snippets: list[dict] = []
        else:
            snippets = [
                {
                    "id": index,
                    "text": str(text),
                    "bbox": _bbox(box),
                    "confidence": max(0.0, min(1.0, float(score))),
                }
                for index, (box, text, score) in enumerate(
                    zip(boxes, texts, scores), start=1
                )
            ]
        overlay = render_ocr_overlay(chart_image, snippets)
        return ToolResult(
            data=snippets,
            images=(
                GeneratedImage(
                    overlay,
                    "image/png",
                    "OCR detections with stable IDs, bounding boxes, and confidence labels",
                ),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"extract_text failed for {image_path}: {exc}"}


EXTRACT_TEXT = Tool(
    name="extract_text",
    description=(
        "Run OCR over the entire authorized chart image and return detected text "
        "snippets with stable IDs, pixel bounding boxes, confidence scores, and a "
        "labeled overlay. Use when labels, titles, annotations, or printed values "
        "are needed; do not use it as a substitute for measuring geometry or for "
        "reading stylized, rotated, obscured, or very small text as ground truth. "
        "OCR output is visual evidence and may be empty or contain recognition "
        "errors, so compare confidence and the overlay with other evidence."
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
    group="chart-observation",
)
