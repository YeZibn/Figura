"""Panel segmentation backends for dashboard decomposition.

The public dashboard tool consumes a small, backend-neutral segmentation
record.  A deterministic rectangle backend is always available; a SAM-family
backend is loaded lazily and is only used when its optional runtime is
configured.  No backend exposes model paths or dense masks to the Agent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

import numpy as np
from PIL import Image


SEGMENTATION_STATUSES = frozenset({"accepted", "partial", "rejected"})
SEGMENTATION_SOURCES = frozenset(
    {"deterministic", "sam", "deterministic_fallback", "none"}
)


def _clamp_bbox(bbox: Sequence[float], width: int, height: int) -> list[int] | None:
    if len(bbox) < 4:
        return None
    try:
        left, top, box_width, box_height = (float(value) for value in bbox[:4])
    except (TypeError, ValueError):
        return None
    if not all(np.isfinite(value) for value in (left, top, box_width, box_height)):
        return None
    right = min(width, max(0, int(round(left + box_width))))
    bottom = min(height, max(0, int(round(top + box_height))))
    left_i = min(width - 1, max(0, int(round(left)))) if width else 0
    top_i = min(height - 1, max(0, int(round(top)))) if height else 0
    if right <= left_i or bottom <= top_i:
        return None
    return [left_i, top_i, right - left_i, bottom - top_i]


def _bbox_polygon(bbox: Sequence[int]) -> list[list[int]]:
    left, top, width, height = (int(value) for value in bbox[:4])
    right = left + max(1, width) - 1
    bottom = top + max(1, height) - 1
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def _convex_hull(points: Sequence[Sequence[float]]) -> list[list[int]]:
    """Return a compact integer hull without requiring a CV dependency."""
    normalized = sorted(
        {(int(round(point[0])), int(round(point[1]))) for point in points if len(point) >= 2}
    )
    if len(normalized) <= 2:
        return [[x, y] for x, y in normalized]

    def cross(origin: tuple[int, int], first: tuple[int, int], second: tuple[int, int]) -> int:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (first[1] - origin[1]) * (second[0] - origin[0])

    lower: list[tuple[int, int]] = []
    for point in normalized:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[int, int]] = []
    for point in reversed(normalized):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return [[x, y] for x, y in lower[:-1] + upper[:-1]]


def _mask_geometry(mask: np.ndarray) -> tuple[list[int], list[list[int]]] | None:
    coordinates = np.argwhere(mask)
    if coordinates.size == 0:
        return None
    rows = coordinates[:, 0]
    columns = coordinates[:, 1]
    bbox = [
        int(columns.min()),
        int(rows.min()),
        int(columns.max() - columns.min() + 1),
        int(rows.max() - rows.min() + 1),
    ]
    stride = max(1, len(coordinates) // 512)
    sampled = coordinates[::stride]
    polygon = _convex_hull([[column, row] for row, column in sampled])
    if len(polygon) < 3:
        polygon = _bbox_polygon(bbox)
    return bbox, polygon


@dataclass(frozen=True)
class SegmentationResult:
    """Backend-neutral panel boundary result."""

    status: str
    source: str
    bbox_px: list[int] | None
    polygon_px: list[list[int]]
    confidence: float
    warnings: tuple[str, ...] = ()
    mask: np.ndarray | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "bbox_px": self.bbox_px,
            "polygon_px": self.polygon_px,
            "confidence": max(0.0, min(1.0, float(self.confidence))),
            "warnings": list(self.warnings),
        }


class PanelSegmenter(Protocol):
    """Internal interface implemented by deterministic and SAM backends."""

    def segment(self, image: Image.Image, candidate: dict[str, Any]) -> SegmentationResult:
        ...


class DeterministicPanelSegmenter:
    """Always-available rectangular candidate backend."""

    def segment(self, image: Image.Image, candidate: dict[str, Any]) -> SegmentationResult:
        bbox = _clamp_bbox(candidate.get("bbox_px", []), image.width, image.height)
        if bbox is None:
            return SegmentationResult(
                status="rejected",
                source="none",
                bbox_px=None,
                polygon_px=[],
                confidence=0.0,
                warnings=("candidate panel bounds are invalid",),
            )
        confidence = float(candidate.get("confidence", 0.58))
        return SegmentationResult(
            status="accepted",
            source="deterministic",
            bbox_px=bbox,
            polygon_px=_bbox_polygon(bbox),
            confidence=max(0.25, min(0.86, confidence)),
        )


class SamPanelSegmenter:
    """Lazy adapter for the optional ``segment_anything`` package."""

    def __init__(
        self,
        *,
        checkpoint: str | None = None,
        model_type: str | None = None,
        device: str | None = None,
    ) -> None:
        self.checkpoint = checkpoint or os.getenv("FIGURA_SAM_CHECKPOINT")
        self.model_type = model_type or os.getenv("FIGURA_SAM_MODEL_TYPE", "vit_b")
        self.device = device or os.getenv("FIGURA_SAM_DEVICE", "cpu")
        self._predictor: Any = None
        self._load_error: str | None = None
        self._image_source: Image.Image | None = None

    def _load(self) -> Any:
        if self._predictor is not None:
            return self._predictor
        if self._load_error is not None:
            raise RuntimeError(self._load_error)
        if not self.checkpoint:
            self._load_error = "FIGURA_SAM_CHECKPOINT is not configured"
            raise RuntimeError(self._load_error)
        try:
            from segment_anything import SamPredictor, sam_model_registry

            model_factory = sam_model_registry.get(self.model_type)
            if model_factory is None:
                raise RuntimeError(f"unsupported SAM model type: {self.model_type}")
            model = model_factory(checkpoint=self.checkpoint)
            model.to(device=self.device)
            self._predictor = SamPredictor(model)
            return self._predictor
        except Exception as exc:  # noqa: BLE001 - optional runtime boundary
            self._load_error = f"SAM backend unavailable: {type(exc).__name__}"
            raise RuntimeError(self._load_error) from exc

    def segment(self, image: Image.Image, candidate: dict[str, Any]) -> SegmentationResult:
        try:
            predictor = self._load()
            rgb = np.asarray(image.convert("RGB"))
            # ``segment`` is called once per candidate, but all candidates in
            # one decomposition share the same PIL image object.  Cache the
            # predictor embedding for that object rather than re-encoding the
            # full dashboard for every panel.
            if self._image_source is not image:
                predictor.set_image(rgb)
                self._image_source = image
            bbox = _clamp_bbox(candidate.get("bbox_px", []), image.width, image.height)
            if bbox is None:
                raise ValueError("candidate panel bounds are invalid")
            left, top, width, height = bbox
            right = left + width - 1
            bottom = top + height - 1
            center = np.asarray([[left + width / 2.0, top + height / 2.0]], dtype=np.float32)
            labels = np.asarray([1], dtype=np.int32)
            masks, scores, _ = predictor.predict(
                point_coords=center,
                point_labels=labels,
                box=np.asarray([left, top, right, bottom], dtype=np.float32),
                multimask_output=True,
            )
            if masks is None or len(masks) == 0:
                raise ValueError("SAM returned no masks")
            index = int(np.argmax(np.asarray(scores, dtype=float))) if scores is not None else 0
            mask = np.asarray(masks[index], dtype=bool)
            geometry = _mask_geometry(mask)
            if geometry is None:
                raise ValueError("SAM returned an empty mask")
            mask_bbox, polygon = geometry
            score = float(np.asarray(scores, dtype=float)[index]) if scores is not None else 0.5
            return SegmentationResult(
                status="accepted",
                source="sam",
                bbox_px=mask_bbox,
                polygon_px=polygon,
                confidence=max(0.0, min(1.0, score)),
                mask=mask,
            )
        except Exception as exc:  # noqa: BLE001 - optional runtime boundary
            return SegmentationResult(
                status="partial",
                source="none",
                bbox_px=None,
                polygon_px=[],
                confidence=0.0,
                warnings=(f"SAM refinement unavailable: {type(exc).__name__}",),
            )


class FallbackPanelSegmenter:
    """Try an optional backend, retaining a bounded deterministic result."""

    def __init__(self, primary: PanelSegmenter, fallback: PanelSegmenter | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or DeterministicPanelSegmenter()

    def segment(self, image: Image.Image, candidate: dict[str, Any]) -> SegmentationResult:
        primary = self.primary.segment(image, candidate)
        if primary.status == "accepted" and primary.bbox_px and len(primary.polygon_px) >= 3:
            return primary
        fallback = self.fallback.segment(image, candidate)
        warnings = tuple(primary.warnings) + tuple(fallback.warnings)
        return SegmentationResult(
            status="partial" if fallback.bbox_px else "rejected",
            source="deterministic_fallback" if fallback.bbox_px else "none",
            bbox_px=fallback.bbox_px,
            polygon_px=fallback.polygon_px,
            confidence=min(0.45, fallback.confidence),
            warnings=warnings or ("advanced segmentation failed; using fallback bounds",),
        )


def build_panel_segmenter(mode: str = "auto") -> PanelSegmenter:
    """Build a bounded backend without loading optional models by default.

    Dashboard cards are rectangular semantic regions, so the default ``auto``
    path intentionally stays deterministic.  SAM remains an explicit opt-in
    experiment and is never activated merely because a checkpoint happens to
    be present in the environment.
    """
    normalized = str(mode or "auto").strip().lower()
    if normalized not in {"auto", "deterministic", "sam"}:
        normalized = "auto"
    if normalized in {"auto", "deterministic"}:
        return DeterministicPanelSegmenter()
    sam = SamPanelSegmenter()
    return FallbackPanelSegmenter(sam)


__all__ = [
    "DeterministicPanelSegmenter",
    "FallbackPanelSegmenter",
    "PanelSegmenter",
    "SEGMENTATION_SOURCES",
    "SEGMENTATION_STATUSES",
    "SamPanelSegmenter",
    "SegmentationResult",
    "build_panel_segmenter",
]
