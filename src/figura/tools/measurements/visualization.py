"""Deterministic, transient image annotations for committed measurements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO

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
            image = source.convert("RGB")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError("measurement source cannot be decoded") from None
    expected_size = result.get("image_size")
    if not isinstance(expected_size, Mapping) or expected_size.get("width") != image.width or expected_size.get("height") != image.height:
        raise ValueError("measurement image size does not match its authorized source")

    draw = ImageDraw.Draw(image)
    status = result.get("status", "unknown")
    warnings = result.get("warnings", [])
    warning = warnings[0] if isinstance(warnings, (list, tuple)) and warnings and isinstance(warnings[0], str) else ""
    banner = f"{tool_name} | {status}"
    if warning:
        banner = f"{banner} | {warning[:96]}"
    draw.rectangle((0, 0, image.width, 22), fill="#17202a")
    draw.text((6, 5), banner, fill="#ffffff")

    if tool_name == "measure_bars":
        _draw_bars(draw, result)
    elif tool_name == "measure_lines":
        _draw_lines(draw, result)
    elif tool_name == "measure_scatter":
        _draw_scatter(draw, result)
    else:
        raise ValueError("unsupported measurement tool")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_bars(draw: ImageDraw.ImageDraw, result: Mapping[str, object]) -> None:
    baseline = result.get("baseline")
    if isinstance(baseline, Mapping):
        _draw_polyline(draw, baseline.get("points_px"), "#f5b041", 2)
    bars = result.get("bars", [])
    if not isinstance(bars, (list, tuple)):
        return
    for item in bars:
        if not isinstance(item, Mapping):
            continue
        geometry = item.get("geometry")
        if not isinstance(geometry, Mapping):
            continue
        polygon = geometry.get("polygon_px")
        _draw_polyline(draw, polygon, "#00a6fb", 3, close=True)
        bbox = geometry.get("bbox_px")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x, y, width, height = (int(value) for value in bbox)
            draw.text((x, max(23, y - 13)), f"bar {item.get('id')}", fill="#063970")


def _draw_lines(draw: ImageDraw.ImageDraw, result: Mapping[str, object]) -> None:
    for series in _series(result):
        color = _color(series.get("color"))
        traces = series.get("trace", [])
        if isinstance(traces, (list, tuple)):
            for trace in traces:
                _draw_polyline(draw, trace, color, 3)
        points = series.get("points", [])
        if isinstance(points, (list, tuple)):
            for point in points:
                if isinstance(point, Mapping):
                    _draw_point(draw, point.get("position_px"), color, 5)


def _draw_scatter(draw: ImageDraw.ImageDraw, result: Mapping[str, object]) -> None:
    for series in _series(result):
        color = _color(series.get("color"))
        points = series.get("points", [])
        if not isinstance(points, (list, tuple)):
            continue
        for point in points:
            if not isinstance(point, Mapping):
                continue
            position = point.get("position_px")
            radius = point.get("radius_px")
            _draw_point(draw, position, color, max(4, round(float(radius or 0))))


def _series(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = result.get("series", [])
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, (list, tuple)) else []


def _draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: object,
    color: str,
    width: int,
    *,
    close: bool = False,
) -> None:
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        return
    coordinates = [tuple(int(round(float(value))) for value in point[:2]) for point in points if isinstance(point, (list, tuple)) and len(point) >= 2]
    if len(coordinates) >= 2:
        if close:
            coordinates.append(coordinates[0])
        draw.line(coordinates, fill=color, width=width, joint="curve")


def _draw_point(draw: ImageDraw.ImageDraw, position: object, color: str, radius: int) -> None:
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return
    x, y = (int(round(float(value))) for value in position)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=3)


def _color(value: object) -> str:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        return value
    return "#00a6fb"
