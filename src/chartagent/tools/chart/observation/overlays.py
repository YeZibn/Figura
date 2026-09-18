"""Deterministic, high-contrast overlays for chart tool observations."""

from __future__ import annotations

from io import BytesIO
import math

from PIL import Image, ImageDraw


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _tag(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    image_size: tuple[int, int],
) -> None:
    """Draw a readable label while keeping its background inside the image."""
    left, top, right, bottom = draw.textbbox((0, 0), text)
    width = right - left + 6
    height = bottom - top + 4
    x = max(0, min(xy[0], image_size[0] - width))
    y = max(0, min(xy[1], image_size[1] - height))
    draw.rectangle((x, y, x + width, y + height), fill="#fff176", outline="#111111")
    draw.text((x + 3, y + 2), text, fill="#111111")


def _draw_common_frame(
    draw: ImageDraw.ImageDraw,
    overlay: Image.Image,
    frame: dict | None,
    *,
    label: str,
    draw_axes: bool = True,
) -> None:
    """Draw coordinate evidence shared by every chart overlay."""
    if not isinstance(frame, dict):
        return
    polygon = frame.get("polygon_px")
    if isinstance(polygon, list) and len(polygon) >= 3:
        points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in polygon
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) >= 3:
            draw.line([*points, points[0]], fill="#0066ff", width=2, joint="curve")
            _tag(draw, points[0], label, image_size=overlay.size)
    elif isinstance(frame.get("bbox_px"), (list, tuple)) and len(frame["bbox_px"]) == 4:
        x, y, width, height = map(int, frame["bbox_px"])
        draw.rectangle(
            (x, y, min(overlay.width - 1, x + width - 1), min(overlay.height - 1, y + height - 1)),
            outline="#0066ff",
            width=2,
        )

    coordinate_system = frame.get("coordinate_system")
    if coordinate_system == "polar_2d":
        center = frame.get("center_px")
        radius = frame.get("radius_px")
        if isinstance(center, (list, tuple)) and len(center) >= 2 and radius:
            cx, cy = (int(round(value)) for value in center[:2])
            r = int(round(float(radius)))
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline="#0066ff", width=2)
            _tag(draw, (cx - r, max(0, cy - r - 18)), label, image_size=overlay.size)
        return

    if not draw_axes:
        return
    for axis_name, color in (("x_axis", "#0066ff"), ("y_axis", "#00a6a6")):
        axis = frame.get(axis_name)
        points = axis.get("points_px") if isinstance(axis, dict) else None
        if not isinstance(points, list) or len(points) < 2:
            continue
        axis_points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in points[:2]
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(axis_points) == 2:
            draw.line(axis_points, fill=color, width=3)
            _tag(draw, axis_points[0], axis_name.replace("_", " ").upper(), image_size=overlay.size)


def render_common_frame_overlay(
    image: Image.Image,
    frame: dict | None,
    *,
    label: str = "CHART FRAME",
) -> bytes:
    """Render only the neutral coordinate evidence layer."""
    overlay = image.convert("RGB").copy()
    _draw_common_frame(ImageDraw.Draw(overlay), overlay, frame, label=label)
    return _png_bytes(overlay)


def render_ocr_overlay(image: Image.Image, snippets: list[dict]) -> bytes:
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    if not snippets:
        _tag(draw, (8, 8), "NO TEXT DETECTED", image_size=overlay.size)
        return _png_bytes(overlay)

    for snippet in snippets:
        x, y, width, height = snippet["bbox"]
        right = min(overlay.width - 1, x + max(1, width))
        bottom = min(overlay.height - 1, y + max(1, height))
        draw.rectangle((x, y, right, bottom), outline="#e60000", width=3)
        label = f'{snippet["id"]} {snippet["confidence"]:.2f}'
        _tag(draw, (x, max(0, y - 16)), label, image_size=overlay.size)
    return _png_bytes(overlay)


def render_dashboard_overlay(
    image: Image.Image,
    panels: list[dict],
    snippets: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> bytes:
    """Draw semantic panel boundaries, names, crop status, and warnings."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    colors = [
        "#0066ff",
        "#008f5a",
        "#b000b5",
        "#d66b00",
        "#00a6a6",
        "#e60000",
    ]
    for index, panel in enumerate(panels):
        color = colors[index % len(colors)]
        polygon = panel.get("polygon_px") if isinstance(panel, dict) else None
        points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in polygon or []
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        bbox = panel.get("bbox_px") if isinstance(panel, dict) else None
        if len(points) >= 3:
            draw.line([*points, points[0]], fill=color, width=3, joint="curve")
            label_point = points[0]
        elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x, y, width, height = map(int, bbox)
            draw.rectangle(
                (x, y, min(overlay.width - 1, x + width - 1), min(overlay.height - 1, y + height - 1)),
                outline=color,
                width=3,
            )
            label_point = (x, y)
        else:
            continue
        status = str(panel.get("status", "partial"))
        role = str(panel.get("role", "unknown"))
        chart_type = str(panel.get("chart_type", "unknown"))
        name = " ".join(str(panel.get("name", "")).split())[:36]
        crop = panel.get("crop") if isinstance(panel.get("crop"), dict) else {}
        crop_status = str(crop.get("status", "unknown"))
        _tag(
            draw,
            label_point,
            f'{panel.get("id", "panel")} {name} {role}/{chart_type} {status} crop:{crop_status}',
            image_size=overlay.size,
        )

    if warnings:
        _tag(draw, (8, 8), "DASHBOARD PARTIAL" if panels else "NO PANELS", image_size=overlay.size)
    elif not panels:
        _tag(draw, (8, 8), "NO PANELS", image_size=overlay.size)
    return _png_bytes(overlay)


def render_bar_overlay(
    image: Image.Image,
    bars: list[dict],
    baseline: dict | None,
    *,
    frame: dict | None = None,
) -> bytes:
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    _draw_common_frame(draw, overlay, frame, label="BAR FRAME", draw_axes=False)
    series_ids = {bar.get("series_id") for bar in bars if bar.get("series_id")}
    baseline_points = baseline.get("points_px") if isinstance(baseline, dict) else None
    if isinstance(baseline_points, list) and len(baseline_points) >= 2:
        points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in baseline_points[:2]
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) == 2:
            draw.line(points, fill="#0066ff", width=3)
            _tag(draw, (points[0][0], max(0, points[0][1] - 18)), "BASELINE", image_size=overlay.size)

    for bar in bars:
        geometry = bar.get("geometry") if isinstance(bar, dict) else None
        polygon = geometry.get("polygon_px") if isinstance(geometry, dict) else None
        if not isinstance(polygon, list) or len(polygon) < 3:
            continue
        bbox = geometry.get("bbox_px") if isinstance(geometry, dict) else None
        right_edge = bottom_edge = None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            right_edge = int(bbox[0]) + int(bbox[2])
            bottom_edge = int(bbox[1]) + int(bbox[3])
        points = [
            (
                max(
                    0,
                    min(
                        overlay.width - 1,
                        int(round(point[0])) - (1 if right_edge is not None and int(round(point[0])) == right_edge else 0),
                    ),
                ),
                max(
                    0,
                    min(
                        overlay.height - 1,
                        int(round(point[1])) - (1 if bottom_edge is not None and int(round(point[1])) == bottom_edge else 0),
                    ),
                ),
            )
            for point in polygon
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) < 3:
            continue
        draw.line([*points, points[0]], fill="#ff00aa", width=3, joint="curve")
        label = str(bar["id"])
        if len(series_ids) > 1 and bar.get("series_id"):
            label = f'{label} {bar["series_id"]}'
        label_x, label_y = points[0]
        _tag(draw, (label_x, max(0, label_y - 16)), label, image_size=overlay.size)

    if not bars:
        _tag(draw, (8, 8), "NO BARS DETECTED", image_size=overlay.size)
    return _png_bytes(overlay)


def render_line_overlay(
    image: Image.Image,
    *,
    plot_area: list[int] | None = None,
    series: list[dict],
    plot_frame: dict | None = None,
    axes: dict | None = None,
    warnings: list[str] | None = None,
) -> bytes:
    """Draw source-image line traces, frame, points, and uncertainty."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    frame = plot_frame or {}
    _draw_common_frame(draw, overlay, frame, label="LINE FRAME")
    polygon = frame.get("polygon_px") if isinstance(frame, dict) else None
    if isinstance(polygon, list) and len(polygon) >= 3:
        frame_points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in polygon
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(frame_points) >= 3:
            draw.line([*frame_points, frame_points[0]], fill="#0066ff", width=2, joint="curve")
    elif plot_area:
        x, y, width, height = plot_area
        draw.rectangle(
            (x, y, min(overlay.width - 1, x + width - 1), min(overlay.height - 1, y + height - 1)),
            outline="#0066ff",
            width=2,
        )

    for axis_name, color in (("x_axis", "#0066ff"), ("y_axis", "#00a6a6")):
        axis = frame.get(axis_name) if isinstance(frame, dict) else None
        points = axis.get("points_px") if isinstance(axis, dict) else None
        if not isinstance(points, list) or len(points) < 2:
            continue
        axis_points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in points[:2]
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(axis_points) == 2:
            draw.line(axis_points, fill=color, width=3)
            _tag(draw, axis_points[0], axis_name.replace("_", " ").upper(), image_size=overlay.size)

    fallback_colors = ["#e60000", "#008f5a", "#7a00cc", "#d66b00", "#0066cc"]
    has_trace = False
    for index, entry in enumerate(series):
        color = entry.get("color") or fallback_colors[index % len(fallback_colors)]
        trace = entry.get("trace") if isinstance(entry, dict) else None
        fragments = trace.get("fragments") if isinstance(trace, dict) else None
        if not isinstance(fragments, list) or not fragments:
            polyline = trace.get("polyline_px") if isinstance(trace, dict) else None
            fragments = [{"polyline_px": polyline}] if isinstance(polyline, list) else []
        for fragment in fragments:
            polyline = fragment.get("polyline_px") if isinstance(fragment, dict) else None
            if not isinstance(polyline, list):
                continue
            points = [
                (int(round(point[0])), int(round(point[1])))
                for point in polyline
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if len(points) >= 2:
                has_trace = True
                draw.line(points, fill=color, width=3, joint="curve")
        points = [
            point
            for point in entry.get("points", [])
            if point.get("x_px") is not None and point.get("y_px") is not None
        ]
        points.sort(key=lambda point: point["x_px"])
        for point in points:
            x = int(point["x_px"])
            y = int(point["y_px"])
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), outline=color, width=2)
            source = str(point.get("source", "point"))
            label = f'{point.get("id", "point")} {source}'
            _tag(draw, (x + 5, y - 16), label, image_size=overlay.size)
        if points:
            _tag(
                draw,
                (int(points[0]["x_px"]), max(0, int(points[0]["y_px"]) - 18)),
                str(entry.get("id", f"series_{index + 1}")),
                image_size=overlay.size,
            )
    if warnings:
        _tag(draw, (8, 8), "LINE UNCERTAINTY", image_size=overlay.size)
    if not has_trace and not any(entry.get("points") for entry in series):
        _tag(draw, (8, 8), "NO LINE SERIES DETECTED", image_size=overlay.size)
    return _png_bytes(overlay)


def render_scatter_overlay(
    image: Image.Image,
    plot_area: list[int] | None = None,
    series: list[dict] | None = None,
    *,
    plot_frame: dict | None = None,
    axes: dict | None = None,
    warnings: list[str] | None = None,
) -> bytes:
    """Draw source-sized scatter frame, axes, points, and uncertainty evidence."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    series = series or []
    frame = plot_frame or {}
    _draw_common_frame(draw, overlay, frame, label="SCATTER FRAME")
    polygon = frame.get("polygon_px") if isinstance(frame, dict) else None
    if isinstance(polygon, list) and len(polygon) >= 3:
        frame_points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in polygon
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(frame_points) >= 3:
            draw.line([*frame_points, frame_points[0]], fill="#0066ff", width=2, joint="curve")
            _tag(draw, frame_points[0], "SCATTER FRAME", image_size=overlay.size)
    elif plot_area:
        x, y, width, height = plot_area
        draw.rectangle(
            (
                x,
                y,
                min(overlay.width - 1, x + width - 1),
                min(overlay.height - 1, y + height - 1),
            ),
            outline="#0066ff",
            width=2,
        )
    else:
        _tag(draw, (8, 8), "SCATTER FRAME UNRESOLVED", image_size=overlay.size)

    for axis_name, color in (("x_axis", "#0066ff"), ("y_axis", "#00a6a6")):
        axis = frame.get(axis_name) if isinstance(frame, dict) else None
        axis_points = axis.get("points_px") if isinstance(axis, dict) else None
        if not isinstance(axis_points, list) or len(axis_points) < 2:
            continue
        points = [
            (
                max(0, min(overlay.width - 1, int(round(point[0])))),
                max(0, min(overlay.height - 1, int(round(point[1])))),
            )
            for point in axis_points[:2]
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) == 2:
            draw.line(points, fill=color, width=3)
            _tag(draw, points[0], axis_name.replace("_", " ").upper(), image_size=overlay.size)

    if axes:
        for axis_name, color in (("x", "#0066ff"), ("y", "#00a6a6")):
            for tick in (axes.get(axis_name) or {}).get("ticks", []):
                point = tick.get("point_px") if isinstance(tick, dict) else None
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                x, y = int(round(point[0])), int(round(point[1]))
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
        x_status = "X CALIBRATED" if (axes.get("x") or {}).get("calibrated") else "X PIXEL ONLY"
        y_status = "Y CALIBRATED" if (axes.get("y") or {}).get("calibrated") else "Y PIXEL ONLY"
        _tag(draw, (8, 30), f"{x_status} / {y_status}", image_size=overlay.size)

    fallback_colors = ["#e60000", "#008f5a", "#7a00cc", "#d66b00", "#0066cc"]
    has_points = False
    for series_index, entry in enumerate(series):
        color = entry.get("color") or fallback_colors[series_index % len(fallback_colors)]
        for point in entry.get("points", []):
            if point.get("x_px") is None or point.get("y_px") is None:
                continue
            has_points = True
            x = int(point["x_px"])
            y = int(point["y_px"])
            appearance = point.get("appearance") or {}
            radius = max(4, int(round(float(appearance.get("radius_px", 4)))))
            outline = "#111111" if point.get("outlier_candidate") else color
            width = 4 if point.get("merged_candidate") else 2
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                outline=outline,
                width=width,
            )
            if point.get("overlap_candidate"):
                draw.line((x - radius, y - radius, x + radius, y + radius), fill="#111111", width=2)
            if point.get("dense_candidate") or point.get("occluded_candidate"):
                draw.rectangle(
                    (x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2),
                    outline="#d66b00",
                    width=2,
                )
            _tag(
                draw,
                (x + radius + 2, y - radius - 2),
                str(point.get("id", "point")),
                image_size=overlay.size,
            )
    if warnings:
        _tag(draw, (8, 8), "SCATTER UNCERTAINTY", image_size=overlay.size)
    if not has_points:
        _tag(draw, (8, 8), "NO SCATTER POINTS DETECTED", image_size=overlay.size)
    return _png_bytes(overlay)


def render_pie_overlay(
    image: Image.Image,
    plot_region: dict | None,
    sectors: list[dict],
    legend: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> bytes:
    """Draw source-image pie geometry, associations, and uncertainty."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    if plot_region is None:
        _tag(draw, (8, 8), "NO PIE REGION DETECTED", image_size=overlay.size)
        return _png_bytes(overlay)

    center = plot_region.get("center_px") or plot_region.get("center")
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        _tag(draw, (8, 8), "PIE REGION UNRESOLVED", image_size=overlay.size)
        return _png_bytes(overlay)
    center_x, center_y = float(center[0]), float(center[1])
    radius = float(plot_region.get("radius_px", plot_region.get("radius", 0.0)))
    if radius <= 0:
        _tag(draw, (8, 8), "PIE REGION UNRESOLVED", image_size=overlay.size)
        return _png_bytes(overlay)
    _draw_common_frame(
        draw,
        overlay,
        {
            "coordinate_system": "polar_2d",
            "bbox_px": plot_region.get("bbox_px") or plot_region.get("bbox"),
            "center_px": center,
            "radius_px": radius,
        },
        label="PIE FRAME",
    )
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        outline="#0066ff",
        width=3,
    )

    def point(angle: float, distance: float) -> tuple[int, int]:
        radians = math.radians(angle)
        return (
            int(round(center_x + distance * math.sin(radians))),
            int(round(center_y - distance * math.cos(radians))),
        )

    colors = ["#e60000", "#008f5a", "#7a00cc", "#d66b00", "#0066cc"]
    for index, item in enumerate(sectors):
        geometry = item.get("geometry") if isinstance(item, dict) else None
        measure = item.get("measure") if isinstance(item, dict) else None
        if not isinstance(geometry, dict):
            continue
        start = float(geometry.get("start_angle_deg", 0.0))
        span = float((measure or {}).get("angle_deg", 0.0))
        color = colors[index % len(colors)]
        start_point = point(start, radius)
        end_point = point(start + span, radius)
        draw.line((center_x, center_y, start_point[0], start_point[1]), fill=color, width=3)
        draw.line((center_x, center_y, end_point[0], end_point[1]), fill=color, width=3)
        label_point = point(start + span / 2.0, radius * 0.68)
        ratio = (measure or {}).get("ratio")
        ratio_label = f"{float(ratio):.0%}" if isinstance(ratio, (int, float)) else "?"
        association = item.get("association") if isinstance(item, dict) else None
        status = association.get("status") if isinstance(association, dict) else None
        label = f'{item.get("id", index + 1)} {ratio_label}'
        if status in {"ambiguous", "candidate"}:
            label += " ?"
        _tag(draw, label_point, label, image_size=overlay.size)
        if status == "resolved" and association.get("label"):
            _tag(draw, point(start + span / 2.0, radius * 0.86), str(association["label"]), image_size=overlay.size)

    for entry in legend or []:
        geometry = entry.get("geometry") if isinstance(entry, dict) else None
        if not isinstance(geometry, dict):
            continue
        bbox = geometry.get("bbox_px")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        left, top, width, height = map(int, bbox)
        draw.rectangle((left, top, left + width, top + height), outline="#ff7f00", width=2)
        label = entry.get("label") or entry.get("id", "legend")
        if (entry.get("association") or {}).get("status") == "ambiguous":
            label = f"{label} ?"
        _tag(draw, (left + width + 2, top), str(label), image_size=overlay.size)

    if warnings:
        _tag(draw, (8, 8), "PIE UNCERTAINTY", image_size=overlay.size)
    if not sectors:
        _tag(draw, (8, 8), "NO PIE SECTORS DETECTED", image_size=overlay.size)
    return _png_bytes(overlay)


__all__ = [
    "render_ocr_overlay",
    "render_common_frame_overlay",
    "render_bar_overlay",
    "render_line_overlay",
    "render_scatter_overlay",
    "render_pie_overlay",
]
