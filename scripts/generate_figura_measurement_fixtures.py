"""Generate reproducible chart PNGs and reference geometry, never detector inputs.

Run with: conda run -n agent python scripts/generate_figura_measurement_fixtures.py
Use --update-photo to explicitly refresh the presentation copies.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import matplotlib
import numpy as np
from matplotlib.colors import to_hex
from figura.charts.chartfigure import parse_chart_figure
import figura.charts.chartfigure.rendering as rendering

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/figura_measurement"


def pixel_point(axis, height: int, x: float, y: float) -> list[float]:
    px, py = axis.transData.transform((x, y))
    return [round(float(px), 4), round(height - float(py), 4)]


def pixel_bounds(axis, height: int, x: float, y: float, w: float, h: float) -> list[float]:
    a = pixel_point(axis, height, x, y)
    b = pixel_point(axis, height, x + w, y + h)
    return [min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]), abs(b[1] - a[1])]


def reference_chart(axis, spec: dict, width: int, height: int) -> dict:
    """Read rendering artists after final layout, not a measurement prediction."""
    kind = spec["metadata"]["chart_type"]
    data = spec["dataset"]
    targets = []
    bbox = axis.bbox
    plot = [float(bbox.x0), height - float(bbox.y1), float(bbox.width), float(bbox.height)]
    # Tolerance is fixed from reference transform before detector tuning.
    scales = {}
    if spec["coordinate_system"]["kind"] == "cartesian":
        a = axis.transData.inverted().transform((bbox.x0, bbox.y0))
        b = axis.transData.inverted().transform((bbox.x0 + 2, bbox.y0 + 2))
        scales = {"x": abs(float(b[0] - a[0])), "y": abs(float(b[1] - a[1]))}

    def add(identity, *, point=None, bounds=None, series=None, label=None, values=None, **extra):
        target = {"id": identity, "series_label": series, "label": label,
                  "position_px": point, "bounds_px": bounds, "values": values or {},
                  "visibility": "visible", **extra}
        if bounds is not None and point is None:
            target["position_px"] = [bounds[0] + bounds[2] / 2, bounds[1] + bounds[3] / 2]
        targets.append(target)

    if kind == "bar":
        n = len(data["categories"])
        for s, series in enumerate(data["series"]):
            for i, value in enumerate(series["values"]):
                artist = axis.patches[s * n + i]
                bounds = pixel_bounds(axis, height, artist.get_x(), artist.get_y(), artist.get_width(), artist.get_height())
                add(f'{series["id"]}:{i}', bounds=bounds, series=series["label"],
                    label=data["categories"][i]["label"], values={"value": value},
                    color=to_hex(artist.get_facecolor()))
    elif kind in {"line", "scatter", "area"}:
        cumulative = defaultdict(float)
        for s, series in enumerate(data["series"]):
            if kind == "scatter":
                locations = axis.collections[s].get_offsets()
            else:
                locations = np.column_stack(axis.lines[s].get_data())
            for i, source in enumerate(series["points"]):
                x, upper = map(float, locations[i])
                if source["y"] is None:
                    continue
                lower = cumulative[i] if kind == "area" and data["stacking"] == "stacked" else 0.0
                values = {"y_value": source["y"]} if kind != "area" else {"series_value": source["y"], "upper_value": upper, "lower_value": lower}
                if isinstance(source["x"], (int, float)):
                    values["x_value"] = source["x"]
                add(f'{series["id"]}:{i}', point=pixel_point(axis, height, x, upper),
                    series=series["label"], label=str(source["x"]) if isinstance(source["x"], str) else None, values=values,
                    point_source="marker" if kind == "line" else "boundary" if kind == "area" else "visible_marker",
                    lower_position_px=pixel_point(axis, height, x, lower) if kind == "area" else None)
                cumulative[i] = upper
    elif kind == "histogram":
        for i, source in enumerate(data["bins"]):
            artist = axis.patches[i]
            add(str(i), bounds=pixel_bounds(axis, height, artist.get_x(), artist.get_y(), artist.get_width(), artist.get_height()),
                values={"interval_start": source["start"], "interval_end": source["end"], "value": source["value"]})
    elif kind == "box_plot":
        for i, group in enumerate(data["groups"]):
            x = i + 1
            add(group["id"], point=pixel_point(axis, height, x, group["median"]), label=group["label"],
                values={k: group[k] for k in ("lower_whisker", "q1", "median", "q3", "upper_whisker")},
                outliers=group["outliers"], statistic_positions={k: pixel_point(axis, height, x, group[k]) for k in ("lower_whisker", "q1", "median", "q3", "upper_whisker")})
    elif kind == "radar":
        for s, series in enumerate(data["series"]):
            angles, radii = axis.lines[s].get_data()
            for i, value in enumerate(series["values"]):
                add(f'{series["id"]}:{i}', point=pixel_point(axis, height, angles[i], radii[i]),
                    series=series["label"], label=data["dimensions"][i]["label"], values={"value": value})
        outer = spec["coordinate_system"]["value_range"]["max"]
        center = pixel_point(axis, height, 0, 0)
        edge = pixel_point(axis, height, 0, outer)
        scales["radial"] = 2 * outer / np.linalg.norm(np.asarray(edge) - center)
    elif kind == "heatmap":
        for r, row in enumerate(data["values"]):
            for c, value in enumerate(row):
                add(f'{r}:{c}', bounds=pixel_bounds(axis, height, c - .5, r - .5, 1, 1),
                    label=data["x_categories"][c]["label"], row_label=data["y_categories"][r]["label"], values={"value": value})
        color_axis = axis.images[0].colorbar.ax
        low, high = axis.images[0].get_clim()
        scales["color"] = 2 * (high - low) / color_axis.bbox.height
    elif kind == "pie":
        total = sum(item["value"] for item in data["slices"])
        for i, source in enumerate(data["slices"]):
            artist = axis.patches[i]
            angle = np.radians((artist.theta1 + artist.theta2) / 2)
            point = pixel_point(axis, height, artist.center[0] + .7 * artist.r * np.cos(angle), artist.center[1] + .7 * artist.r * np.sin(angle))
            add(source["id"], point=point, label=source["label"], values={"ratio": source["value"] / total},
                start_angle_deg=artist.theta1, sweep_angle_deg=artist.theta2 - artist.theta1)
        scales["ratio"] = 2 / 360  # two reference degrees, not a fitted prediction error
    elif kind == "treemap":
        nodes = {n["id"]: n for n in data["nodes"]}
        children = {n["parent_id"] for n in data["nodes"]}
        for label in axis.texts:
            node = next((n for n in nodes.values() if n["label"] == label.get_text()), None)
            if node is None:
                continue
            pos = label.get_position()
            containing = [p for p in axis.patches if p.get_x() <= pos[0] <= p.get_x() + p.get_width() and p.get_y() <= pos[1] <= p.get_y() + p.get_height()]
            rect = min(containing, key=lambda p: p.get_width() * p.get_height()) if containing else None
            bounds = pixel_bounds(axis, height, rect.get_x(), rect.get_y(), rect.get_width(), rect.get_height()) if rect else None
            add(node["id"], point=pixel_point(axis, height, *pos), bounds=bounds, label=node["label"],
                role="group" if node["id"] in children else "leaf", parent_label=nodes[node["parent_id"]]["label"] if node["parent_id"] else None,
                # Source values are not printed, so they are NOT numeric targets.
                values={}, source_value_visible=False)
    return {"chart_type": kind, "plot_area_px": plot, "numeric_tolerance": scales,
            "geometry_tolerance_px": 2.0, "targets": targets}


def generate(*, update_photo: bool = False) -> dict:
    records = []
    original_fit = rendering._fit_plot
    for path in sorted((FIXTURES / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        axes = []
        def capture(axis, region, canvas):
            original_fit(axis, region, canvas)
            axes.append(axis)
        with patch.object(rendering, "_fit_plot", capture):
            png, width, height = rendering.render_chart_figure_image(parse_chart_figure(case["figure"]))
        destination = FIXTURES / "images" / case["image"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(png)
        if update_photo:
            photo = ROOT / "photo" / case["image"]
            photo.parent.mkdir(parents=True, exist_ok=True)
            photo.write_bytes(png)
        panels = []
        columns = case["figure"]["layout"]["columns"]
        rows = int(np.ceil(len(axes) / columns))
        title_height = 42 if case["figure"]["title"] else 0
        for i, (axis, chart) in enumerate(zip(axes, case["figure"]["charts"], strict=True)):
            reference = reference_chart(axis, chart["chart_spec"], width, height)
            top = title_height + (height - title_height) * (i // columns) / rows
            bottom = title_height + (height - title_height) * (i // columns + 1) / rows
            left, right = width * (i % columns) / columns, width * (i % columns + 1) / columns
            reference["panel_polygon"] = [[round(left/width*1000),round(top/height*1000)], [round(right/width*1000),round(top/height*1000)], [round(right/width*1000),round(bottom/height*1000)], [round(left/width*1000),round(bottom/height*1000)]]
            reference["chart_id"] = chart["chart_id"]
            panels.append(reference)
        records.append({"case_id":case["case_id"], "image":case["image"], "source":path.relative_to(FIXTURES).as_posix(),
                        "sha256":sha256(png).hexdigest(), "image_size":[width,height], "provenance":"recovered_original_generator", "charts":panels})
    manifest = {"schema_version":1, "measurement_targets":"visible image evidence; no hidden data",
                "renderer":"figura ChartFigure", "matplotlib_version":matplotlib.__version__,
                "fonts":["PingFang SC","Arial Unicode MS","Noto Sans CJK SC","DejaVu Sans"], "cases":records}
    (FIXTURES / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-photo", action="store_true")
    args = parser.parse_args()
    print(f"Generated {len(generate(update_photo=args.update_photo)['cases'])} cases")
