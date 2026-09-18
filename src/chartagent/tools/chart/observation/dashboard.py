"""VLM-guided semantic decomposition for multi-panel chart images."""

from __future__ import annotations

from io import BytesIO
import math
import re
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from ....panels import PanelHandoff, handoff_from_panel, normalize_bbox, stable_panel_id
from ...core.definition import Tool
from ...core.result import GeneratedImage, ToolResult
from .foundation import image_size
from .overlays import render_dashboard_overlay
from .segmentation import (
    PanelSegmenter,
    SegmentationResult,
    build_panel_segmenter,
)

_MAX_PANELS = 32
_MAX_CROPS = 12
_MIN_PANEL_WIDTH = 48
_MIN_PANEL_HEIGHT = 32
_MAX_NAME_LENGTH = 96
_MAX_SLUG_LENGTH = 64
_OVERLAP_THRESHOLD = 0.72
_ALLOWED_ROLES = frozenset({"text_block", "kpi_card", "chart", "legend", "unknown"})
_ALLOWED_CHART_TYPES = frozenset({"bar", "line", "pie", "scatter", "unknown"})


def _bbox_polygon(bbox: Sequence[int]) -> list[list[int]]:
    left, top, width, height = (int(value) for value in bbox[:4])
    right = left + max(1, width) - 1
    bottom = top + max(1, height) - 1
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def _box_area(bbox: Sequence[int]) -> float:
    if len(bbox) < 4:
        return 0.0
    return max(1.0, float(bbox[2]) * float(bbox[3]))


def _box_overlap(first: Sequence[int], second: Sequence[int]) -> float:
    if len(first) < 4 or len(second) < 4:
        return 0.0
    left = max(int(first[0]), int(second[0]))
    top = max(int(first[1]), int(second[1]))
    right = min(int(first[0] + first[2]), int(second[0] + second[2]))
    bottom = min(int(first[1] + first[3]), int(second[1] + second[3]))
    if right <= left or bottom <= top:
        return 0.0
    return float((right - left) * (bottom - top)) / min(_box_area(first), _box_area(second))


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bounded_confidence(value: object, default: float) -> float:
    parsed = _finite(value)
    return max(0.0, min(1.0, parsed if parsed is not None else default))


def _safe_name(value: object, index: int) -> str:
    text = " ".join(str(value or "").split())[:_MAX_NAME_LENGTH].strip()
    return text or f"区域 {index}"


def _safe_slug(value: str, index: int) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", normalized)
    normalized = normalized.strip("_")[:_MAX_SLUG_LENGTH]
    return normalized or f"region_{index}"


def _normalized_bbox(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    values = [_finite(item) for item in value[:4]]
    if any(item is None for item in values):
        return None
    left, top, width, height = (float(item) for item in values if item is not None)
    if width <= 0 or height <= 0 or left < 0 or top < 0 or left + width > 1 or top + height > 1:
        return None
    return [round(left, 6), round(top, 6), round(width, 6), round(height, 6)]


def _pixel_bbox(bbox_norm: Sequence[float], width: int, height: int) -> list[int]:
    left, top, box_width, box_height = bbox_norm[:4]
    pixel_left = max(0, min(width - 1, int(round(left * width))))
    pixel_top = max(0, min(height - 1, int(round(top * height))))
    pixel_right = max(pixel_left + 1, min(width, int(round((left + box_width) * width))))
    pixel_bottom = max(pixel_top + 1, min(height, int(round((top + box_height) * height))))
    return [pixel_left, pixel_top, pixel_right - pixel_left, pixel_bottom - pixel_top]


def _padded_bbox(bbox: Sequence[int], width: int, height: int, padding: float) -> list[int]:
    left, top, box_width, box_height = (int(value) for value in bbox[:4])
    pad_x = max(2, int(round(width * padding)))
    pad_y = max(2, int(round(height * padding)))
    padded_left = max(0, left - pad_x)
    padded_top = max(0, top - pad_y)
    padded_right = min(width, left + box_width + pad_x)
    padded_bottom = min(height, top + box_height + pad_y)
    return [padded_left, padded_top, max(1, padded_right - padded_left), max(1, padded_bottom - padded_top)]


def _normalize_proposals(
    regions: object,
    *,
    width: int,
    height: int,
    max_panels: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if regions is None:
        return []
    if not isinstance(regions, list):
        warnings.append("VLM region proposals must be a list")
        return []
    proposals: list[dict[str, Any]] = []
    used_slugs: set[str] = set()
    for index, raw in enumerate(regions[:max_panels], start=1):
        if not isinstance(raw, dict):
            warnings.append(f"proposal {index} is not an object")
            continue
        bbox_norm = _normalized_bbox(raw.get("bbox_norm", raw.get("bbox")))
        if bbox_norm is None:
            warnings.append(f"proposal {index} has an invalid normalized bbox")
            continue
        bbox_px = _pixel_bbox(bbox_norm, width, height)
        if bbox_px[2] < _MIN_PANEL_WIDTH or bbox_px[3] < _MIN_PANEL_HEIGHT:
            warnings.append(f"proposal {index} is below the minimum panel size")
            continue
        name = _safe_name(raw.get("name"), index)
        role = str(raw.get("role", "unknown")).strip().lower()
        chart_type = str(raw.get("chart_type", "unknown")).strip().lower()
        if role not in _ALLOWED_ROLES:
            warnings.append(f"proposal {index} has an unsupported role; using unknown")
            role = "unknown"
        if chart_type not in _ALLOWED_CHART_TYPES:
            warnings.append(f"proposal {index} has an unsupported chart type; using unknown")
            chart_type = "unknown"
        proposal_id = str(raw.get("proposal_id", f"proposal_{index}")).strip()[:80]
        slug = _safe_slug(name, index)
        if slug in used_slugs:
            suffix = f"_{index}"
            slug = f"{slug[: max(1, _MAX_SLUG_LENGTH - len(suffix))]}{suffix}"
            warnings.append(f"proposal {index} reused a display name; assigned a unique slug")
        used_slugs.add(slug)
        proposals.append(
            {
                "proposal_id": proposal_id or f"proposal_{index}",
                "name": name,
                "slug": slug,
                "role": role,
                "chart_type": chart_type,
                "bbox_norm": bbox_norm,
                "bbox_px": bbox_px,
                "confidence": _bounded_confidence(raw.get("confidence"), 0.72),
                "evidence": [
                    "vlm_region_proposal",
                    *[
                        str(item)[:96]
                        for item in raw.get("evidence", [])
                        if isinstance(item, str)
                    ][:4],
                ],
            }
        )
    if len(regions) > max_panels:
        warnings.append(f"region proposal count capped at {max_panels}")
    for index, proposal in enumerate(proposals):
        for previous in proposals[:index]:
            overlap = _box_overlap(proposal["bbox_px"], previous["bbox_px"])
            if overlap > _OVERLAP_THRESHOLD:
                proposal.setdefault("warnings", []).append(
                    f"proposal overlaps {previous['proposal_id']} by {overlap:.2f}"
                )
                warnings.append(
                    f"{proposal['proposal_id']} overlaps {previous['proposal_id']} materially"
                )
                break
    return proposals


def _whole_image_proposal(width: int, height: int) -> dict[str, Any]:
    return {
        "proposal_id": "whole_image",
        "name": "整张图片",
        "slug": "whole_image",
        "role": "unknown",
        "chart_type": "unknown",
        "bbox_norm": [0.0, 0.0, 1.0, 1.0],
        "bbox_px": [0, 0, width, height],
        "confidence": 0.18,
        "evidence": ["bounded_whole_image_fallback"],
        "warnings": ["VLM region proposals were missing or unusable"],
        "fallback": True,
    }


def _panel_layout_context(
    panel: dict[str, Any],
    *,
    image_dimensions: Sequence[int],
    attachment_id: str | None,
) -> dict[str, Any]:
    width, height = (int(value) for value in image_dimensions[:2])
    left, top, box_width, box_height = (int(value) for value in panel["bbox_px"])
    status = str(panel.get("status", "partial"))
    confidence = float(panel.get("confidence", 0.0))
    chart_type = str(panel.get("chart_type") or "unknown").lower()
    role = str(panel.get("role") or "unknown").lower()
    if chart_type == "pie":
        coordinate_system = "polar_2d"
    elif role == "chart" or chart_type in {"bar", "line", "scatter"}:
        coordinate_system = "cartesian_2d"
    else:
        coordinate_system = "unknown"
    scope = {
        "role": "panel_scope",
        "bbox_px": [left, top, box_width, box_height],
        "source_origin_px": [left, top],
        "local_to_source": "x_source = x_local + source_origin_px[0]; y_source = y_local + source_origin_px[1]",
        "confidence": max(0.0, min(1.0, confidence)),
        "evidence": list(panel.get("evidence", []))[:8],
    }
    return {
        "version": 1,
        "context_id": f"{panel['id']}_layout",
        "source_attachment_id": attachment_id,
        "image_size": [width, height],
        "coordinate_system": coordinate_system,
        "orientation": "unknown",
        "analysis_scope": scope,
        "measurement_frame": None,
        "annotation_regions": {},
        "axes": {"x": None, "y": None},
        "panel": {
            "id": panel["id"],
            "name": panel.get("name"),
            "source_bbox_px": [left, top, box_width, box_height],
            "scope_bbox_px": [left, top, box_width, box_height],
            "crop_ref": panel.get("crop", {}).get("resource_ref"),
        },
        "validation": {
            "status": "accepted" if status == "accepted" else "partial",
            "accepted_for_measurement": False,
            "accepted_for_analysis": status == "accepted",
            "confidence": max(0.0, min(1.0, confidence)),
            "warnings": list(panel.get("warnings", []))[:12],
        },
        "evidence": ["dashboard_panel", "vlm_region_proposal", "deterministic_scope", "source_coordinates"],
    }


def _fallback_result(
    candidate: dict[str, Any],
    *,
    warnings: Sequence[str],
    source: str = "deterministic_fallback",
) -> SegmentationResult:
    bbox = list(candidate["bbox_px"])
    return SegmentationResult(
        status="partial",
        source=source,
        bbox_px=bbox,
        polygon_px=_bbox_polygon(bbox),
        confidence=min(0.45, float(candidate.get("confidence", 0.25))),
        warnings=tuple(warnings),
    )


def _validate_segmentation(
    result: SegmentationResult,
    candidate: dict[str, Any],
    *,
    image_dimensions: Sequence[int],
    accepted_panels: list[dict[str, Any]],
) -> SegmentationResult:
    width, height = (int(value) for value in image_dimensions[:2])
    proposal_bbox = candidate["bbox_px"]
    bbox = result.bbox_px
    warnings = list(result.warnings)
    if bbox is None or len(bbox) != 4:
        return _fallback_result(
            candidate,
            warnings=[*warnings, "segmentation boundary was invalid; using VLM proposal bounds"],
        )
    left, top, box_width, box_height = (int(value) for value in bbox)
    in_bounds = (
        left >= 0
        and top >= 0
        and box_width >= _MIN_PANEL_WIDTH
        and box_height >= _MIN_PANEL_HEIGHT
        and left + box_width <= width
        and top + box_height <= height
    )
    if not in_bounds:
        return _fallback_result(
            candidate,
            warnings=[*warnings, "segmentation boundary is outside source bounds or too small"],
        )
    overlap = _box_overlap(bbox, proposal_bbox)
    area_ratio = _box_area(bbox) / _box_area(proposal_bbox)
    if overlap < 0.20 or area_ratio > 2.5:
        return _fallback_result(
            candidate,
            warnings=[*warnings, "segmentation boundary conflicts with VLM proposal"],
        )
    if result.mask is not None:
        mask = np.asarray(result.mask, dtype=bool)
        mask_area = int(mask.sum())
        if mask_area <= 0 or mask_area / _box_area(bbox) < 0.01:
            return _fallback_result(
                candidate,
                warnings=[*warnings, "segmentation mask is empty or too fragmented"],
            )
    if len(result.polygon_px) < 3:
        warnings.append("segmentation polygon is unavailable; retaining bbox evidence")
    for panel in accepted_panels:
        panel_bbox = panel.get("segmentation", {}).get("boundary_bbox_px") or panel.get("bbox_px")
        if _box_overlap(bbox, panel_bbox) > _OVERLAP_THRESHOLD:
            return _fallback_result(
                candidate,
                warnings=[*warnings, f"segmentation overlaps accepted panel {panel['id']}"],
            )
    return SegmentationResult(
        status=result.status if result.status in {"accepted", "partial", "rejected"} else "partial",
        source=result.source if result.source in {"deterministic", "sam", "deterministic_fallback", "none"} else "none",
        bbox_px=list(bbox),
        polygon_px=[
            list(map(int, point[:2]))
            for point in result.polygon_px
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ],
        confidence=max(0.0, min(1.0, float(result.confidence))),
        warnings=tuple(warnings),
        mask=result.mask,
    )


def _normalize_segmenter_result(result: object) -> SegmentationResult:
    if isinstance(result, SegmentationResult):
        return result
    if isinstance(result, dict):
        return SegmentationResult(
            status=str(result.get("status", "partial")),
            source=str(result.get("source", "none")),
            bbox_px=list(result["bbox_px"]) if isinstance(result.get("bbox_px"), (list, tuple)) else None,
            polygon_px=[
                list(point[:2])
                for point in result.get("polygon_px", [])
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ],
            confidence=float(result.get("confidence", 0.0)),
            warnings=tuple(str(item) for item in result.get("warnings", []) if isinstance(item, str)),
        )
    return SegmentationResult(
        status="rejected",
        source="none",
        bbox_px=None,
        polygon_px=[],
        confidence=0.0,
        warnings=("segmenter returned an invalid result",),
    )


def _encode_crop(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _make_crop(
    image: Image.Image,
    bbox: Sequence[int],
) -> tuple[bytes, list[int], list[int]]:
    left, top, width, height = (int(value) for value in bbox[:4])
    crop = image.crop((left, top, left + width, top + height))
    return _encode_crop(crop), [left, top], [crop.width, crop.height]


def decompose_chart_image(
    image_path: str,
    regions: list[dict[str, Any]] | None = None,
    segmentation_mode: str = "auto",
    max_panels: int = _MAX_PANELS,
    crop_padding: float = 0.015,
    attachment_id: str | None = None,
    *,
    segmenter: PanelSegmenter | None = None,
) -> ToolResult | dict:
    """Validate VLM-proposed regions and return reusable named panel crops."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": "dashboard image could not be resolved"}
    try:
        with Image.open(path) as source:
            chart_image = source.convert("RGB")
        rgb = np.asarray(chart_image)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"decompose_chart_image failed: {type(exc).__name__}"}

    width, height = chart_image.width, chart_image.height
    warnings: list[str] = []
    try:
        bounded_max = max(1, min(_MAX_PANELS, int(max_panels)))
    except (TypeError, ValueError):
        bounded_max = _MAX_PANELS
        warnings.append("max_panels was invalid; using the bounded default")
    try:
        bounded_padding = max(0.0, min(0.08, float(crop_padding)))
    except (TypeError, ValueError):
        bounded_padding = 0.015
        warnings.append("crop_padding was invalid; using the bounded default")

    proposals = _normalize_proposals(
        regions,
        width=width,
        height=height,
        max_panels=bounded_max,
        warnings=warnings,
    )
    if not proposals:
        proposals = [_whole_image_proposal(width, height)]
        warnings.append("VLM region proposals were missing or unusable; using one advisory whole-image region")
    active_segmenter = segmenter or build_panel_segmenter(segmentation_mode)
    image_dimensions = image_size(rgb)
    panels: list[dict[str, Any]] = []
    for index, proposal in enumerate(proposals, start=1):
        candidate = dict(proposal)
        candidate["bbox_px"] = list(proposal["bbox_px"])
        candidate["confidence"] = proposal["confidence"]
        try:
            raw_result = active_segmenter.segment(chart_image, candidate)
            result = _normalize_segmenter_result(raw_result)
        except Exception as exc:  # noqa: BLE001 - backend boundary
            result = _fallback_result(
                candidate,
                warnings=[f"panel segmentation failed: {type(exc).__name__}"],
            )
        result = _validate_segmentation(
            result,
            candidate,
            image_dimensions=image_dimensions,
            accepted_panels=panels,
        )
        if proposal.get("fallback") and result.status == "accepted":
            result = SegmentationResult(
                status="partial",
                source="deterministic_fallback",
                bbox_px=result.bbox_px,
                polygon_px=result.polygon_px,
                confidence=min(0.45, result.confidence),
                warnings=tuple(result.warnings) + ("whole-image region is advisory, not a VLM semantic proposal",),
                mask=result.mask,
            )
        panel_id = f"panel_{index}"
        crop_bbox = _padded_bbox(proposal["bbox_px"], width, height, bounded_padding)
        panel_warnings = list(proposal.get("warnings", [])) + list(result.warnings)
        if proposal.get("fallback"):
            panel_warnings.append("using advisory whole-image fallback because no usable VLM region was supplied")
        panel = {
            "id": panel_id,
            "name": proposal["name"],
            "slug": proposal["slug"],
            "role": proposal["role"],
            "chart_type": proposal["chart_type"],
            "proposal": {
                "proposal_id": proposal["proposal_id"],
                "bbox_norm": proposal["bbox_norm"],
                "bbox_px": proposal["bbox_px"],
                "confidence": proposal["confidence"],
            },
            "bbox_px": crop_bbox,
            "polygon_px": result.polygon_px or _bbox_polygon(crop_bbox),
            "status": result.status,
            "segmentation": {
                "source": result.source,
                "confidence": result.confidence,
                "proposal_confidence": proposal["confidence"],
                "boundary_bbox_px": result.bbox_px,
            },
            "confidence": round(
                max(0.0, min(1.0, result.confidence * 0.75 + proposal["confidence"] * 0.25)),
                4,
            ),
            "warnings": panel_warnings,
            "evidence": list(dict.fromkeys(proposal.get("evidence", []) + ["source_coordinates"])),
            "crop": {
                "name": f"{panel_id}_{proposal['slug']}.png",
                "slug": proposal["slug"],
                "bbox_px": crop_bbox,
                "source_origin_px": [crop_bbox[0], crop_bbox[1]],
                "size_px": [crop_bbox[2], crop_bbox[3]],
                "resource_key": f"{panel_id}_crop",
                "resource_ref": None,
                "status": "pending",
            },
        }
        panel["layout_context"] = _panel_layout_context(
            panel,
            image_dimensions=image_dimensions,
            attachment_id=attachment_id,
        )
        panel["analysis_transform"] = {
            "source_origin_px": [crop_bbox[0], crop_bbox[1]],
            "scale": [1.0, 1.0],
            "local_to_source": "x_source = x_local + source_origin_px[0]; y_source = y_local + source_origin_px[1]",
        }
        panels.append(panel)
        warnings.extend(panel_warnings)

    accepted_count = sum(panel["status"] == "accepted" for panel in panels)
    images: list[GeneratedImage] = [
        GeneratedImage(
            render_dashboard_overlay(chart_image, panels, warnings=warnings),
            "image/png",
        "Dashboard semantic regions, panel scopes, optional boundaries, crop names, and warnings",
            metadata={
                "kind": "dashboard_decomposition_overlay",
                "image_role": "overlay",
                "panel_count": len(panels),
            },
        )
    ]
    crop_count = 0
    for panel in panels:
        if crop_count >= _MAX_CROPS:
            panel["crop"]["status"] = "omitted"
            panel["warnings"].append(f"crop count capped at {_MAX_CROPS}")
            warnings.append(f"crop count capped at {_MAX_CROPS}")
            continue
        try:
            content, origin, dimensions = _make_crop(chart_image, panel["crop"]["bbox_px"])
            crop_count += 1
            panel["crop"]["image_index"] = len(images)
            panel["crop"]["size_px"] = dimensions
            images.append(
                GeneratedImage(
                    content,
                    "image/png",
                    f"局部区域 {panel['id']}：{panel['name']}",
                    metadata={
                        "kind": "dashboard_panel_crop",
                        "image_role": "crop",
                        "resource_key": panel["crop"]["resource_key"],
                        "panel_id": panel["id"],
                        "crop_name": panel["crop"]["name"],
                        "source_origin_x": origin[0],
                        "source_origin_y": origin[1],
                        "width": dimensions[0],
                        "height": dimensions[1],
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-crop resource boundary
            panel["crop"]["status"] = "failed"
            panel["warnings"].append(f"crop persistence preparation failed: {type(exc).__name__}")
            warnings.append(f"{panel['id']} crop could not be prepared")

    for panel in panels:
        if panel["crop"]["status"] == "pending" and "image_index" in panel["crop"]:
            panel["crop"]["status"] = "available"
        panel["layout_context"]["panel"]["crop_ref"] = panel["crop"].get("resource_ref")
        panel["layout_context"]["validation"]["warnings"] = list(panel["warnings"])[:12]

    status = "rejected" if not panels else "accepted" if accepted_count == len(panels) and not warnings else "partial"
    confidence = float(np.mean([panel["confidence"] for panel in panels])) if panels else 0.0
    data = {
        "kind": "chart_image_decomposition",
        "image_size": image_dimensions,
        "status": status,
        "proposals": [panel["proposal"] for panel in panels],
        "panels": panels,
        "segmentation": {
            "mode": str(segmentation_mode or "auto"),
            "panel_count": len(panels),
            "accepted_count": accepted_count,
            "crop_count": crop_count,
            "crop_limit": _MAX_CROPS,
        },
        "confidence": {"overall": max(0.0, min(1.0, confidence))},
        "warnings": warnings,
    }
    return ToolResult(data, images=tuple(images), warnings=tuple(warnings))


def _panel_from_handoff(handoff: PanelHandoff, image_dimensions: Sequence[int]) -> dict[str, Any]:
    """Rebuild the bounded model-facing panel record without re-segmenting."""
    width, height = (int(value) for value in image_dimensions[:2])
    left, top, box_width, box_height = handoff.source_bbox
    scope = list(handoff.analysis_scope)
    panel = {
        "id": handoff.panel_id,
        "name": handoff.name,
        "slug": handoff.slug,
        "role": handoff.role,
        "chart_type": handoff.chart_type,
        "proposal": {
            "proposal_id": f"handoff_{handoff.panel_id}",
            "bbox_norm": [round(left / width, 6), round(top / height, 6), round(box_width / width, 6), round(box_height / height, 6)],
            "bbox_px": list(handoff.source_bbox),
            "confidence": handoff.confidence,
        },
        "bbox_px": list(handoff.source_bbox),
        "polygon_px": _bbox_polygon(handoff.source_bbox),
        "status": "accepted" if handoff.status == "active" else "partial",
        "segmentation": {
            "source": "persisted_handoff",
            "confidence": handoff.confidence,
            "proposal_confidence": handoff.confidence,
            "boundary_bbox_px": list(handoff.source_bbox),
        },
        "confidence": handoff.confidence,
        "warnings": list(handoff.warnings),
        "evidence": list(dict.fromkeys([*handoff.evidence, "persisted_panel_handoff"])),
        "crop": {
            "name": f"{handoff.panel_id}_{handoff.slug}.png",
            "slug": handoff.slug,
            "bbox_px": list(handoff.analysis_scope),
            "source_origin_px": list(handoff.source_origin),
            "size_px": [scope[2], scope[3]],
            "resource_key": f"{handoff.panel_id}_crop",
            "resource_ref": None,
            "status": "pending",
        },
    }
    panel["layout_context"] = _panel_layout_context(
        panel,
        image_dimensions=image_dimensions,
        attachment_id=handoff.attachment_id,
    )
    panel["layout_context"]["analysis_scope"]["bbox_px"] = scope
    panel["layout_context"]["analysis_scope"]["source_origin_px"] = list(handoff.source_origin)
    panel["layout_context"]["panel"]["source_bbox_px"] = list(handoff.source_bbox)
    panel["layout_context"]["panel"]["scope_bbox_px"] = scope
    panel["analysis_transform"] = {
        "source_origin_px": list(handoff.source_origin),
        "scale": [1.0, 1.0],
        "local_to_source": "x_source = x_local + source_origin_px[0]; y_source = y_local + source_origin_px[1]",
    }
    return panel


def reuse_decomposition(
    image_path: str,
    handoffs: Sequence[PanelHandoff],
    *,
    attachment_id: str | None = None,
) -> ToolResult | dict:
    """Return previously accepted panels and fresh bounded crops.

    This path intentionally does not call the segmenter or re-run proposal
    validation.  The attachment hash and panel authorization are checked by
    the caller before this function is reached.
    """
    path = Path(image_path)
    if not path.is_file():
        return {"error": "dashboard image could not be resolved"}
    try:
        with Image.open(path) as source:
            chart_image = source.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"decompose_chart_image reuse failed: {type(exc).__name__}"}
    image_dimensions = image_size(np.asarray(chart_image))
    panels = [_panel_from_handoff(item, image_dimensions) for item in handoffs[:_MAX_PANELS]]
    warnings = ["reused persisted panel handoffs; dashboard decomposition was not repeated"]
    images: list[GeneratedImage] = [GeneratedImage(
        render_dashboard_overlay(chart_image, panels, warnings=warnings),
        "image/png",
        "复用的 dashboard 面板范围和局部 crop",
        metadata={"kind": "dashboard_decomposition_overlay", "image_role": "overlay", "panel_count": len(panels), "reuse": True},
    )]
    for panel in panels:
        content, origin, dimensions = _make_crop(chart_image, panel["crop"]["bbox_px"])
        panel["crop"]["status"] = "available"
        panel["crop"]["image_index"] = len(images)
        panel["crop"]["size_px"] = dimensions
        images.append(GeneratedImage(
            content,
            "image/png",
            f"复用局部区域 {panel['id']}：{panel['name']}",
            metadata={
                "kind": "dashboard_panel_crop",
                "image_role": "crop",
                "resource_key": panel["crop"]["resource_key"],
                "panel_id": panel["id"],
                "crop_name": panel["crop"]["name"],
                "source_origin_x": origin[0],
                "source_origin_y": origin[1],
                "width": dimensions[0],
                "height": dimensions[1],
                "reuse": True,
            },
        ))
        panel["layout_context"]["panel"]["crop_ref"] = panel["crop"].get("resource_ref")
    status = "accepted" if panels and all(panel["status"] == "accepted" for panel in panels) else "partial"
    data = {
        "kind": "chart_image_decomposition",
        "image_size": image_dimensions,
        "status": status,
        "reuse": True,
        "proposals": [panel["proposal"] for panel in panels],
        "panels": panels,
        "segmentation": {"mode": "persisted_handoff", "panel_count": len(panels), "accepted_count": len(panels), "crop_count": len(panels), "crop_limit": _MAX_CROPS},
        "confidence": {"overall": float(np.mean([panel["confidence"] for panel in panels])) if panels else 0.0},
        "warnings": warnings,
    }
    return ToolResult(data, images=tuple(images), warnings=tuple(warnings))


def stabilize_decomposition_result(
    result: ToolResult | dict,
    *,
    session_id: str,
    attachment_id: str,
    attachment_sha256: str,
    origin_run_id: str | None,
    panel_store: Any,
) -> ToolResult | dict:
    """Replace run-local panel ordinals and persist the accepted handoffs."""
    if not isinstance(result, ToolResult) or not isinstance(result.data, dict):
        return result
    data = dict(result.data)
    panels = data.get("panels")
    if not isinstance(panels, list):
        return result
    changed_ids: dict[str, str] = {}
    stable_panels: list[PanelHandoff] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        source_bbox = normalize_bbox(panel.get("bbox_px"))
        if source_bbox is None:
            continue
        name = str(panel.get("name") or "Panel")
        chart_type = str(panel.get("chart_type") or "unknown")
        existing = panel_store.match_panel_handoff(
            attachment_id,
            attachment_sha256,
            name=name,
            chart_type=chart_type,
            source_bbox=source_bbox,
            minimum_iou=0.55,
        )
        stable_id = existing.panel_id if existing is not None else stable_panel_id(attachment_sha256, name, chart_type, source_bbox)
        old_id = str(panel.get("id") or "")
        if old_id and old_id != stable_id:
            changed_ids[old_id] = stable_id
        panel["id"] = stable_id
        crop = panel.get("crop") if isinstance(panel.get("crop"), dict) else {}
        crop["name"] = f"{stable_id}_{panel.get('slug', 'panel')}.png"
        crop["resource_key"] = f"{stable_id}_crop"
        panel["crop"] = crop
        layout = panel.get("layout_context")
        if isinstance(layout, dict):
            layout["context_id"] = f"{stable_id}_layout"
            panel_info = dict(layout.get("panel") or {})
            panel_info["id"] = stable_id
            layout["panel"] = panel_info
        handoff = handoff_from_panel(
            session_id=session_id,
            attachment_id=attachment_id,
            attachment_sha256=attachment_sha256,
            panel=panel,
            origin_run_id=origin_run_id,
            panel_id=stable_id,
            revision=existing.revision if existing is not None else 1,
            supersedes_panel_id=None,
        )
        stable_panels.append(panel_store.save_panel_handoff(handoff))
    images = list(result.images)
    if changed_ids:
        for index, image in enumerate(images):
            metadata = dict(image.metadata) if isinstance(image.metadata, dict) else {}
            if isinstance(metadata.get("panel_id"), str) and metadata["panel_id"] in changed_ids:
                metadata["panel_id"] = changed_ids[metadata["panel_id"]]
            metadata["panel_registry"] = "persisted"
            images[index] = GeneratedImage(image.content, image.media_type, image.caption, metadata)
    data["panels"] = panels
    data["panel_registry"] = {"status": "persisted", "panel_ids": [item.panel_id for item in stable_panels]}
    return ToolResult(data, images=tuple(images), warnings=result.warnings, evidence=result.evidence)


DECOMPOSE_CHART_IMAGE = Tool(
    name="decompose_chart_image",
    description=(
        "Use when需要对授权的复杂图表图片执行 VLM 引导的语义分区；调用前先根据图片提出 "
        "regions，每个 region 提供 name、bbox_norm，以及可选 role/chart_type。"
        "工具随后使用确定性边界校验并 return 带稳定 ID 和名称的局部 crop、源图坐标、"
        "analysis scope、crop 引用、置信度、警告和预览；SAM 只在显式请求时作为可选边界证据。"
        "do not 用它提取图表数值，也不要依赖 OCR 来发现区域。"
        "必要时后续再按需调用 extract_text、柱状图、折线图、饼图或散点图传感器。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Internal authorized image path used only by the callable.",
            },
            "regions": {
                "type": "array",
                "description": "VLM-proposed semantic regions in normalized source-image coordinates.",
                "maxItems": _MAX_PANELS,
                "items": {
                    "type": "object",
                    "properties": {
                        "proposal_id": {"type": "string", "description": "Optional bounded proposal identity."},
                        "name": {"type": "string", "description": "Human-readable region name."},
                        "role": {
                            "type": "string",
                            "enum": sorted(_ALLOWED_ROLES),
                            "description": "Advisory region role.",
                        },
                        "chart_type": {
                            "type": "string",
                            "enum": sorted(_ALLOWED_CHART_TYPES),
                            "description": "Advisory chart type when the region is a chart.",
                        },
                        "bbox_norm": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 4,
                            "items": {"type": "number", "minimum": 0, "maximum": 1},
                            "description": "Normalized [x, y, width, height] source-image region.",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "Optional VLM proposal confidence.",
                        },
                    },
                    "required": ["name", "bbox_norm"],
                    "additionalProperties": False,
                },
            },
            "segmentation_mode": {
                "type": "string",
                "enum": ["auto", "deterministic", "sam"],
                "description": "Bounded segmentation policy; auto uses deterministic VLM-bbox scopes, while sam is explicit opt-in.",
                "default": "auto",
            },
            "max_panels": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_PANELS,
                "description": "Maximum number of semantic panel records returned for one image.",
                "default": _MAX_PANELS,
            },
            "crop_padding": {
                "type": "number",
                "minimum": 0,
                "maximum": 0.08,
                "description": "Bounded normalized padding around each VLM crop frame.",
                "default": 0.015,
            },
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=decompose_chart_image,
    group="chart-observation",
)


__all__ = ["DECOMPOSE_CHART_IMAGE", "decompose_chart_image", "reuse_decomposition", "stabilize_decomposition_result"]
