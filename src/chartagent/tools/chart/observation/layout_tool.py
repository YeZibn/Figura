"""Model-facing layout preflight tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...core.definition import Tool
from ...core.result import ToolResult
from .foundation import detect_color_palette
from .layout import fallback_layout_context, validate_layout_hint


def inspect_chart_layout(
    image_path: str,
    layout_hint: dict[str, Any] | None = None,
    chart_type: str | None = None,
    attachment_id: str | None = None,
) -> ToolResult | dict:
    """Validate a model's normalized layout hint against an authorized image."""
    path = Path(image_path)
    if not path.is_file():
        return {"error": "chart layout image could not be resolved"}
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"))
    except Exception as exc:  # noqa: BLE001 - tool boundary
        return {"error": f"inspect_chart_layout failed: {type(exc).__name__}"}

    palette = detect_color_palette(rgb, max_colors=8)
    if layout_hint is None:
        context = fallback_layout_context(
            rgb,
            chart_type=chart_type,
            attachment_id=attachment_id,
        )
    else:
        context = validate_layout_hint(
            rgb,
            layout_hint,
            attachment_id=attachment_id,
            palette=palette,
            chart_type=chart_type,
        )
    warnings = list(context.get("validation", {}).get("warnings", []))
    return ToolResult({"layout_context": context}, warnings=tuple(warnings))


INSPECT_CHART_LAYOUT = Tool(
    name="inspect_chart_layout",
    description=(
        "Use this tool after loading an authorized chart image to inspect and "
        "validate a model-proposed layout before geometry measurement. Call it "
        "once per attachment when the chart is rotated, horizontal, visually "
        "ambiguous, or contains dense labels. When supplying layout_hint, use "
        "canonical normalized fields: measurement_frame.bbox_norm, optional "
        "axes.x/y.points_norm=[[x1, y1], [x2, y2]], annotation_regions, "
        "orientation, coordinate_system, and polar_region; keep all region "
        "coordinates in 0..1 and supply chart_type when known. The hint is "
        "advisory evidence: do not include local paths, image bytes, chart "
        "values, or fabricated calibration, and omit an entire uncertain axis "
        "rather than giving one endpoint. The result returns a reusable "
        "layout_context with accepted, partial, or rejected validation status; "
        "only accepted_for_measurement=true may constrain a sensor, while "
        "rejected or fallback contexts must preserve independent pixel evidence "
        "and warnings. If uncertain, still call the tool with layout_hint "
        "omitted to obtain the bounded deterministic fallback."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Internal authorized image path used only by the callable.",
            },
            "layout_hint": {
                "type": "object",
                "description": (
                    "Optional canonical normalized layout hint. Use "
                    "measurement_frame.bbox_norm, axes.x/y.points_norm, "
                    "annotation_regions, orientation, coordinate_system, and "
                    "polar_region. Axis points must be two endpoints in "
                    "[[x1, y1], [x2, y2]] form; regions use [left, top, width, "
                    "height] in 0..1 coordinates. If an axis is uncertain, omit "
                    "the entire axis instead of supplying one endpoint."
                ),
                "additionalProperties": True,
            },
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "scatter", "pie"],
                "description": "Optional chart type used to select Cartesian or polar defaults.",
            },
        },
        "required": ["image_path"],
        "additionalProperties": False,
    },
    fn=inspect_chart_layout,
    group="chart-observation",
)


__all__ = ["INSPECT_CHART_LAYOUT", "inspect_chart_layout"]
