"""Deterministic, transient image annotations for committed observations."""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from math import cos, radians, sin

from PIL import Image, ImageDraw


def render_measurement_overlay(
    image_bytes: bytes,
    result: Mapping[str, object],
    tool_name: str,
) -> bytes:
    """Draw committed geometry and status labels without changing the source."""
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            source.load()
            rgba = source.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            image = Image.alpha_composite(background, rgba).convert("RGB")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError("measurement source cannot be decoded") from None
    expected_size = result.get("image_size")
    if (
        not isinstance(expected_size, Mapping)
        or expected_size.get("width") != image.width
        or expected_size.get("height") != image.height
    ):
        raise ValueError("measurement image size does not match its authorized source")

    draw = ImageDraw.Draw(image)
    status = result.get("status", "unknown")
    warnings = result.get("warnings", [])
    warning = warnings[0] if isinstance(warnings, (list, tuple)) and warnings and isinstance(warnings[0], str) else ""
    if tool_name == "measure_chart":
        chart_type = result.get("chart_type")
        banner = f"measure_chart | {chart_type or 'unknown'} | {status}"
    elif tool_name == "extract_text":
        banner = f"{tool_name} | {status}"
    else:
        raise ValueError("unsupported observation tool")
    if warning:
        banner = f"{banner} | {warning[:96]}"
    draw.rectangle((0, 0, image.width, 22), fill="#17202a")
    draw.text((6, 5), banner, fill="#ffffff")

    if tool_name == "measure_chart":
        observations = result.get("observations")
        chart_type = result.get("chart_type")
        if not isinstance(observations, Mapping) or not isinstance(chart_type, str):
            raise ValueError("measurement observation family is invalid")
        _draw_family(draw, chart_type, observations)
        _draw_evidence(draw, result)
    else:
        _draw_text(draw, result)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_family(draw: ImageDraw.ImageDraw, chart_type: str, observations: Mapping[str, object]) -> None:
    if chart_type == "bar":
        _draw_bars(draw, observations)
    elif chart_type == "line":
        for series in _records(observations.get("series")):
            color = _color(series.get("color"))
            for segment in _records_or_points(series.get("segments_px")):
                _draw_polyline(draw, segment, color, 3)
            for point in _records(series.get("points")):
                _draw_point(draw, point.get("position_px"), color, 5)
    elif chart_type == "scatter":
        for series in _records(observations.get("series")):
            color = _color(series.get("color"))
            for point in _records(series.get("points")):
                _draw_point(draw, point.get("center_px"), color, max(4, round(_number(point.get("radius_px")) or 0)))
    elif chart_type == "pie":
        _draw_pie(draw, observations)
    elif chart_type == "area":
        for series in _records(observations.get("series")):
            color = _color(series.get("color"))
            for segment in _records(series.get("segments")):
                upper = segment.get("upper_boundary_px")
                lower = segment.get("lower_boundary_px")
                if isinstance(upper, (tuple, list)):
                    _draw_polyline(draw, upper, color, 3)
                if isinstance(lower, (tuple, list)):
                    _draw_polyline(draw, lower, color, 3)
                    _draw_joined_outline(draw, upper, lower, color)
    elif chart_type == "histogram":
        for item in _records(observations.get("bins")):
            _draw_rect(draw, item.get("bounds_px"), "#00a6fb", label=None)
    elif chart_type == "box_plot":
        _draw_box_plots(draw, observations)
    elif chart_type == "radar":
        for series in _records(observations.get("series")):
            vertices = [item.get("position_px") for item in _records(series.get("vertices"))]
            _draw_polyline(draw, vertices, _color(series.get("color")), 3, close=True)
    elif chart_type == "heatmap":
        for cell in _records(observations.get("cells")):
            _draw_rect(draw, cell.get("bounds_px"), _color(cell.get("color"), "#00a6fb"), fill=True)
    elif chart_type == "treemap":
        for node in _records(observations.get("nodes")):
            _draw_rect(draw, node.get("bounds_px"), "#00a6fb", label=node.get("label") or node.get("id"))
    else:
        raise ValueError("unsupported measurement chart family")


def _draw_evidence(draw: ImageDraw.ImageDraw, result: Mapping[str, object]) -> None:
    """Mark the exact OCR and geometry supports retained in the committed result."""
    color = "#ff8c00"
    for evidence in _records(result.get("evidence")):
        kind = evidence.get("kind")
        if kind == "ocr":
            _draw_rect(draw, evidence.get("bounds_px"), color)
        elif kind == "geometry":
            bounds = evidence.get("bounds_px")
            if bounds is not None:
                _draw_rect(draw, bounds, color)
            for point in evidence.get("points_px", []) if isinstance(evidence.get("points_px"), (tuple, list)) else []:
                if _valid_point(point):
                    x, y = _xy(point)
                    draw.ellipse((round(x - 3), round(y - 3), round(x + 3), round(y + 3)), outline=color, width=2)


def _draw_bars(draw: ImageDraw.ImageDraw, observations: Mapping[str, object]) -> None:
    _draw_polyline(draw, observations.get("baseline_px"), "#f5a623", 2)
    for item in _records(observations.get("bars")):
        polygon = item.get("polygon_px")
        _draw_polyline(draw, polygon, "#00a6fb", 3, close=True)
        bounds = item.get("bounds_px")
        if isinstance(bounds, Mapping):
            x, y = bounds.get("x"), bounds.get("y")
            if _number(x) is not None and _number(y) is not None:
                draw.text((int(x), max(23, int(y) - 13)), str(item.get("id", "bar")), fill="#063970")


def _draw_pie(draw: ImageDraw.ImageDraw, observations: Mapping[str, object]) -> None:
    center = observations.get("center_px")
    radius = _number(observations.get("outer_radius_px"))
    if not _valid_point(center) or radius is None:
        return
    cx, cy = _xy(center)
    outer = float(radius)
    inner = _number(observations.get("inner_radius_px")) or 0.0
    draw.ellipse((round(cx - outer), round(cy - outer), round(cx + outer), round(cy + outer)), outline="#ff8c00", width=3)
    if inner > 0:
        draw.ellipse((round(cx - inner), round(cy - inner), round(cx + inner), round(cy + inner)), outline="#ff8c00", width=3)
    for sector in _records(observations.get("sectors")):
        start = _number(sector.get("start_angle_deg"))
        sweep = _number(sector.get("sweep_angle_deg"))
        if start is None or sweep is None:
            continue
        for angle in (start, start + sweep):
            theta = radians(angle)
            inner_point = (round(cx + inner * sin(theta)), round(cy - inner * cos(theta)))
            outer_point = (round(cx + outer * sin(theta)), round(cy - outer * cos(theta)))
            draw.line((*inner_point, *outer_point), fill="#ff8c00", width=3)


def _draw_box_plots(draw: ImageDraw.ImageDraw, observations: Mapping[str, object]) -> None:
    orientation = observations.get("orientation")
    horizontal = orientation == "horizontal"
    for group in _records(observations.get("groups")):
        _draw_rect(draw, group.get("bounds_px"), "#00a6fb", label=None)
        sequence = [
            group.get("lower_whisker_px"),
            group.get("q1_px"),
            group.get("median_px"),
            group.get("q3_px"),
            group.get("upper_whisker_px"),
        ]
        usable = [point for point in sequence if _valid_point(point)]
        _draw_polyline(draw, usable, "#b041ff", 3)
        bounds = group.get("bounds_px")
        cap = min(8.0, max(3.0, (_number(bounds.get("width" if horizontal else "height")) or 8.0) * 0.2)) if isinstance(bounds, Mapping) else 6.0
        for point in (group.get("lower_whisker_px"), group.get("upper_whisker_px")):
            if not _valid_point(point):
                continue
            x, y = _xy(point)
            endpoints = ((x, y - cap), (x, y + cap)) if not horizontal else ((x - cap, y), (x + cap, y))
            draw.line((*endpoints[0], *endpoints[1]), fill="#b041ff", width=3)
        for outlier in _records(group.get("outliers")):
            _draw_point(draw, outlier.get("position_px"), "#ff595e", 4)


def _draw_text(draw: ImageDraw.ImageDraw, result: Mapping[str, object]) -> None:
    for snippet in _records(result.get("snippets")):
        bbox = snippet.get("bbox_px")
        rect = _rect(bbox)
        if rect is None:
            continue
        x, y, width, height = rect
        draw.rectangle((x, y, x + width, y + height), outline="#ff8c00", width=2)
        text = snippet.get("text")
        if isinstance(text, str):
            draw.text((x, max(23, y - 13)), f"{snippet.get('snippet_id')}: {text[:32]}", fill="#17202a")


def _draw_rect(
    draw: ImageDraw.ImageDraw,
    value: object,
    color: str,
    *,
    label: object = None,
    fill: bool = False,
) -> None:
    rect = _rect(value)
    if rect is None:
        return
    x, y, width, height = rect
    box = (x, y, x + width, y + height)
    draw.rectangle(box, outline=color, width=3, fill=color if fill else None)
    if isinstance(label, str) and label:
        draw.text((x + 3, y + 3), label[:32], fill="#17202a")


def _rect(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    parts = tuple(_number(value.get(key)) for key in ("x", "y", "width", "height"))
    if any(part is None for part in parts):
        return None
    return tuple(int(round(part)) for part in parts if part is not None)  # type: ignore[return-value]


def _draw_joined_outline(draw: ImageDraw.ImageDraw, upper: object, lower: object, color: str) -> None:
    if not isinstance(upper, (tuple, list)) or not isinstance(lower, (tuple, list)):
        return
    points = [*upper, *reversed(lower)]
    _draw_polyline(draw, points, color, 2, close=True)


def _draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: object,
    color: str,
    width: int,
    *,
    close: bool = False,
) -> None:
    if not isinstance(points, (tuple, list)) or len(points) < 2:
        return
    if any(not _valid_point(point) for point in points):
        segment = []
        for point in points:
            if _valid_point(point):
                segment.append(point)
            else:
                _draw_polyline(draw, segment, color, width)
                segment = []
        _draw_polyline(draw, segment, color, width)
        return
    coordinates = [
        tuple(int(round(value)) for value in _xy(point))
        for point in points
        if _valid_point(point)
    ]
    if len(coordinates) >= 2:
        if close:
            coordinates.append(coordinates[0])
        draw.line(coordinates, fill=color, width=width, joint="curve")


def _draw_point(draw: ImageDraw.ImageDraw, position: object, color: str, radius: int) -> None:
    if not _valid_point(position):
        return
    x, y = (int(round(value)) for value in _xy(position))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=3)


def _records(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, (tuple, list)) else []


def _records_or_points(value: object) -> list[object]:
    return list(value) if isinstance(value, (tuple, list)) else []


def _valid_point(value: object) -> bool:
    return isinstance(value, (tuple, list)) and len(value) == 2 and all(_number(part) is not None for part in value)


def _xy(value: object) -> tuple[float, float]:
    if not _valid_point(value):
        raise ValueError("invalid pixel point")
    return float(value[0]), float(value[1])  # type: ignore[index]


def _number(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    return float(value)


def _color(value: object, default: str = "#00a6fb") -> str:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        return value
    return default
