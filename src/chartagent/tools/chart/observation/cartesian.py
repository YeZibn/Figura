"""Compatibility facade for the chart observation foundation.

New code should import generic evidence helpers from ``foundation`` and
coordinate helpers from ``coordinates``. This module remains importable for
existing callers while the migration is completed.
"""

from .coordinates import (
    apply_axis_transform,
    axis_geometry,
    axis_output,
    axis_scalar,
    cartesian_frame,
    fit_axis_transform,
    fit_dominant_axis_line,
    inside_polygon,
    polar_frame,
)
from .foundation import (
    associate_series_labels,
    bbox_from_boxes,
    bounded_source_point,
    build_common_evidence,
    cluster_centers,
    color_mask,
    confidence_map,
    crop_mask,
    default_plot_area,
    detect_color_palette,
    evidence_envelope,
    fit_ticks,
    image_size,
    numeric_text,
    numeric_ticks,
    rgb_to_hex,
    series_entry,
    stable_evidence_id,
)

__all__ = [
    "apply_axis_transform",
    "associate_series_labels",
    "axis_geometry",
    "axis_output",
    "axis_scalar",
    "bbox_from_boxes",
    "bounded_source_point",
    "build_common_evidence",
    "cartesian_frame",
    "cluster_centers",
    "color_mask",
    "confidence_map",
    "crop_mask",
    "default_plot_area",
    "detect_color_palette",
    "evidence_envelope",
    "fit_axis_transform",
    "fit_dominant_axis_line",
    "fit_ticks",
    "image_size",
    "inside_polygon",
    "numeric_text",
    "numeric_ticks",
    "polar_frame",
    "rgb_to_hex",
    "series_entry",
    "stable_evidence_id",
]
