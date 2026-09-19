"""Scoped OCR sensor exposed through the chart tool protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from ...core.result import GeneratedImage, ToolResult
from ...core.definition import Tool
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
        "对授权图像或指定 panel scope 执行 OCR，返回带稳定 ID、像素框、置信度和标注叠加图的文字片段。"
        "当需要标题、坐标标签、图例、注释或打印数值时使用；不要用它替代几何测量，也不要把风格化、旋转、遮挡或过小文字当成绝对真值。"
        "OCR 结果属于可能为空或有识别错误的视觉证据，应结合置信度、叠加图和其他证据判断。"
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


__all__ = ["EXTRACT_TEXT", "extract_text"]
