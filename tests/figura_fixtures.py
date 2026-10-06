"""Reusable v2 contracts for Figura execution and resource tests."""

from __future__ import annotations

def measurement_result(
    chart_type: str = "bar",
    *,
    source_kind: str = "attachment",
    source_id: str = "attachment-1",
    status: str = "no_evidence",
) -> dict[str, object]:
    axes = {
        "x": _axis(),
        "y": _axis(),
    }
    observations: dict[str, object] = {
        "bar": {
            "orientation": "vertical", "mode": "single", "axes": axes,
            "baseline_px": None, "baseline_value": None, "series": [], "bars": [],
        },
        "line": {"axes": axes, "series": []},
        "scatter": {"axes": axes, "series": []},
        "pie": {"center_px": [10, 10], "outer_radius_px": 5, "inner_radius_px": None, "sectors": []},
        "area": {"axes": axes, "stacking": "none", "series": []},
        "histogram": {"axes": axes, "y_measure": "unknown", "bins": []},
        "box_plot": {"axes": axes, "orientation": "vertical", "groups": []},
        "radar": {"center_px": [10, 10], "spokes": [], "radial_grid": [], "series": []},
        "heatmap": {"row_labels": [], "column_labels": [], "cells": []},
        "treemap": {"nodes": []},
    }
    return {
        "schema_version": 2,
        "chart_type": chart_type,
        "source_kind": source_kind,
        "source_id": source_id,
        "image_size": {"width": 20, "height": 20},
        "coordinate_system": f"{source_kind}_px",
        "status": status,
        "plot_area_px": None,
        "observations": observations[chart_type],
        "confidence": {"overall": 0, "geometry": 0, "calibration": 0, "association": 0},
        "warnings": [],
        "truncated": False,
    }


def bar_chart_figure(*, measurement_ref: dict[str, str] | None = None) -> dict[str, object]:
    references = [measurement_ref] if measurement_ref is not None else []
    return {
        "schema_version": 2,
        "title": "Figure",
        "layout": {"columns": 1},
        "charts": [
            {
                "chart_id": "sales",
                "chart_spec": {
                    "schema_version": 2,
                    "metadata": {"chart_type": "bar", "title": "Sales"},
                    "coordinate_system": {
                        "kind": "cartesian",
                        "x_axis": {"kind": "categorical"},
                        "y_axis": {"kind": "numeric"},
                    },
                    "dataset": {
                        "orientation": "vertical",
                        "mode": "grouped",
                        "categories": [{"id": "q1", "label": "Q1"}],
                        "series": [{"id": "revenue", "label": "Revenue", "values": [1]}],
                    },
                },
                "measurement_refs": references,
            }
        ],
    }


def _axis() -> dict[str, object]:
    return {
        "kind": "unknown",
        "label_text": None,
        "label_confidence": None,
        "points_px": None,
        "ticks": [],
        "calibration": None,
    }
