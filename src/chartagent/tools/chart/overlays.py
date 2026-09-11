"""Deterministic, high-contrast overlays for chart tool observations."""

from __future__ import annotations

from io import BytesIO

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


def render_bar_overlay(
    image: Image.Image,
    bars: list[dict],
    baseline_y: int | None,
) -> bytes:
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    series_ids = {bar.get("series") for bar in bars if bar.get("series")}
    if baseline_y is not None:
        y = max(0, min(baseline_y, overlay.height - 1))
        draw.line((0, y, overlay.width - 1, y), fill="#0066ff", width=3)
        _tag(draw, (8, max(0, y - 18)), "BASELINE", image_size=overlay.size)

    for bar in bars:
        x, y, width, height = bar["bbox"]
        right = min(overlay.width - 1, x + max(1, width))
        bottom = min(overlay.height - 1, y + max(1, height))
        draw.rectangle((x, y, right, bottom), outline="#ff00aa", width=3)
        draw.line((x, y, right, y), fill="#00a050", width=4)
        label = str(bar["id"])
        if len(series_ids) > 1 and bar.get("series"):
            label = f'{label} {bar["series"]}'
        _tag(draw, (x, max(0, y - 16)), label, image_size=overlay.size)

    if not bars:
        _tag(draw, (8, 8), "NO BARS DETECTED", image_size=overlay.size)
    return _png_bytes(overlay)


def render_line_overlay(
    image: Image.Image,
    *,
    plot_area: list[int] | None,
    series: list[dict],
) -> bytes:
    """Draw bounded line/point evidence while retaining the source image."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    if plot_area:
        x, y, width, height = plot_area
        draw.rectangle(
            (x, y, min(overlay.width - 1, x + width), min(overlay.height - 1, y + height)),
            outline="#0066ff",
            width=2,
        )

    colors = ["#e60000", "#008f5a", "#7a00cc", "#d66b00", "#0066cc"]
    for index, entry in enumerate(series):
        color = colors[index % len(colors)]
        points = [
            point
            for point in entry.get("points", [])
            if point.get("x_px") is not None and point.get("y_px") is not None
        ]
        points.sort(key=lambda point: point["x_px"])
        if len(points) >= 2:
            draw.line(
                [(int(point["x_px"]), int(point["y_px"])) for point in points],
                fill=color,
                width=3,
            )
        for point in points:
            x = int(point["x_px"])
            y = int(point["y_px"])
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), outline=color, width=2)
        if points:
            _tag(
                draw,
                (int(points[0]["x_px"]), max(0, int(points[0]["y_px"]) - 18)),
                str(entry.get("id", f"series_{index + 1}")),
                image_size=overlay.size,
            )
    if not any(entry.get("points") for entry in series):
        _tag(draw, (8, 8), "NO LINE SERIES DETECTED", image_size=overlay.size)
    return _png_bytes(overlay)
