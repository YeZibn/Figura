"""Polar spoke, grid, and series-vertex observations for radar charts."""

from __future__ import annotations

from collections.abc import Mapping
import numpy as np

from .cartesian import associate_legend_labels
from .colors import color_mask, hex_color, series_palette
from .contracts import MAX_MEASUREMENT_OBSERVATIONS, MeasurementSensorResult, PreparedMeasurementImage
from .ocr import recognize_text
from .pie import _components


def measure_radar(image: PreparedMeasurementImage) -> MeasurementSensorResult:
    rgb = image.rgb
    height, width = rgb.shape[:2]
    ocr = recognize_text(rgb, image.observation_mask) if image.observation_mask is not None else recognize_text(rgb)
    palette = [c for c in series_palette(rgb) if max(c)-min(c) >= 50]
    if image.observation_mask is not None:
        palette_mask = image.observation_mask
    else:
        palette_mask = np.ones((height, width), dtype=bool)
    components = []
    for color in palette:
        components.extend(_components(color_mask(rgb, color) & palette_mask, max(4, int(width * height * 0.00002))))
    if not components:
        empty = {"center_px": None, "spokes": [], "radial_grid": [], "series": []}
        return MeasurementSensorResult(
            status="no_evidence",
            observations=empty,  # type: ignore[arg-type]
            confidence={"overall": 0.0, "geometry": 0.0, "calibration": 0.0, "association": 0.0},  # type: ignore[arg-type]
            warnings=("no colored radar series geometry was detected",),
        )

    main = max(components, key=lambda item: item["area"])
    x, y, box_width, box_height = main["bbox"]
    initial_center_x = float(x + box_width / 2)
    initial_center_y = float(y + box_height / 2)
    search_radius = max(12.0, min(width, height) * 0.48)
    gray = np.mean(rgb.astype(np.float32), axis=2)
    spread = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    dark = (gray <= 125) & (spread <= 72)
    if image.observation_mask is not None:
        dark &= image.observation_mask

    center_x, center_y = _refine_center(dark, initial_center_x, initial_center_y, search_radius)
    angles, radial_scores, _sampled_radii = _spoke_scores(dark, center_x, center_y, search_radius)
    spoke_groups = _angular_groups(np.flatnonzero(radial_scores >= 0.10), len(angles))
    spoke_angles = [
        _circular_mean(angles[group])
        for group in spoke_groups
        if len(group) <= 10 and float(np.max(radial_scores[group])) >= 0.12
    ]
    circle = None
    if len(spoke_angles) < 3:
        circle = _visible_outer_circle(rgb, image.observation_mask)
        if circle is not None:
            center_x, center_y, search_radius = circle
            # Neutral grid strokes can be light. Filled series colors must not
            # become axis support merely because their luminance is similar.
            grid = (gray <= 245) & (spread <= 4)
            if image.observation_mask is not None:
                grid &= image.observation_mask
            from scipy.ndimage import maximum_filter
            grid = maximum_filter(grid, size=3)
            if image.observation_mask is not None:
                grid &= image.observation_mask
            angles, radial_scores, _ = _spoke_scores(grid, center_x, center_y, search_radius,
                inner_fraction=.65)
            groups = _angular_groups(np.flatnonzero(radial_scores >= .28), len(angles))
            spoke_angles = [float(angles[g[np.argmax(radial_scores[g])]]) for g in groups if len(g) <= 12]
            label_angles = []
            from .cartesian import parse_numeric_text
            for snippet in ocr.snippets:
                sx,sy,sw,sh = snippet.bbox_px
                dx,dy = sx+sw/2-center_x, sy+sh/2-center_y
                if parse_numeric_text(snippet.text) is not None or not (.95*search_radius <= np.hypot(dx,dy) <= 1.3*search_radius):
                    continue
                guess = float(np.degrees(np.arctan2(dx,-dy))%360)
                choices = [int(round(guess+d))%360 for d in range(-7,8)]
                angle = max(choices,key=lambda a: radial_scores[a])
                if radial_scores[angle] >= .12 and not any(abs((angle-a+180)%360-180)<10 for a in label_angles):
                    label_angles.append(float(angle))
            if len(label_angles)>=3:
                spoke_angles = label_angles
            dark = grid
    outer_radius = circle[2] if circle is not None else _estimate_outer_radius(dark, center_x, center_y, search_radius, spoke_angles)
    spokes = []
    radius_by_angle: dict[float, float] = {}
    for index, angle in enumerate(sorted(spoke_angles), start=1):
        ray_radius = outer_radius if circle is not None else _last_dark_radius(dark, center_x, center_y, angle, outer_radius)
        if ray_radius < outer_radius * 0.55:
            continue
        radius_by_angle[angle] = ray_radius
        endpoint = _point(center_x, center_y, angle, ray_radius)
        label = _nearest_label(ocr.snippets, endpoint, outer_radius)
        spokes.append(
            {
                "dimension_id": f"dimension_{index}",
                "label": label,
                "angle_deg": round(angle % 360.0, 3),
                "endpoint_px": [round(endpoint[0], 2), round(endpoint[1], 2)],
            }
        )
    spokes = spokes[:MAX_MEASUREMENT_OBSERVATIONS]

    radial_grid = _radial_grid(dark, center_x, center_y, outer_radius, [item["angle_deg"] for item in spokes])
    from .scales import fit_scalar_support, text_evidence
    from .cartesian import parse_numeric_text
    from .ocr import recognize_region
    x0,y0 = int(center_x),max(0,int(center_y-outer_radius-8))
    x1,y1 = min(width,int(center_x+outer_radius*.6)),min(height,int(center_y+8))
    extra = recognize_region(rgb,(x0,y0,x1-x0,y1-y0),image.observation_mask,scale=3)
    pairs = []
    for snippet in (*ocr.snippets,*extra):
        value = parse_numeric_text(snippet.text)
        sx,sy,sw,sh = snippet.bbox_px
        dx,dy = sx+sw*.1-center_x, sy+sh*.85-center_y
        radius = float(np.hypot(dx,dy))
        if value is None or not (0 <= dx <= outer_radius*.55 and -outer_radius*1.1 <= dy <= 0):
            continue
        if any(v==value for _,_,v in pairs):
            continue
        if radial_grid:
            ring = min(radial_grid,key=lambda g: abs(g["radius_px"]-radius))
            if abs(ring["radius_px"]-radius) < 10:
                radius = ring["radius_px"]
        if circle is not None and abs(radius - outer_radius) < 10:
            radius = outer_radius
        pairs.append((snippet,radius,value))
    radial_fit = fit_scalar_support(pairs)
    evidence = [text_evidence(snippet,f"radial_tick_{i}") for i,(snippet,_,_) in enumerate(pairs)] if radial_fit else []
    calibration = {"id":"radial_scale","kind":"radial","axis_role":"radial","supported":True,
        "support_evidence_ids":[e["id"] for e in evidence],"parameters":{"slope":radial_fit["slope"],"intercept":radial_fit["intercept"],"center_px":[center_x,center_y]},
        "residual_value":radial_fit["residual_value"],"support_domain":[min(p[1] for p in pairs),max(p[1] for p in pairs)]} if radial_fit else None
    provenance = []
    from .layout import legend_regions
    regions = legend_regions(rgb,ocr.snippets,palette)
    legend_snippets = [s for s in ocr.snippets if any(0 <= s.bbox_px[0]-(x+w) <= 22 and s.bbox_px[1] <= y+h/2 <= s.bbox_px[1]+s.bbox_px[3] for x,y,w,h in regions)]
    labels = associate_legend_labels(rgb, legend_snippets, palette)
    series = []
    for series_index, color in enumerate(palette, start=1):
        mask = color_mask(rgb, color) & palette_mask
        color_hex = hex_color(color)
        label, label_confidence = labels.get(color_hex, (None, None))
        vertices = []
        for index, spoke in enumerate(spokes, start=1):
            vertex = _series_vertex(mask, center_x, center_y, float(spoke["angle_deg"]), outer_radius)
            if vertex is None:
                vertices.append({"dimension_id": f"dimension_{index}", "position_px": None, "value": None})
            else:
                vertices.append({"dimension_id": f"dimension_{index}", "position_px": vertex, "value": float(radial_fit["slope"]*np.hypot(vertex[0]-center_x,vertex[1]-center_y)+radial_fit["intercept"]) if radial_fit else None})
        for vertex_index, vertex in enumerate(vertices):
            if vertex["value"] is None:
                continue
            identity = f"radar_vertex_{len(series)}_{vertex_index}"
            evidence.append({"id":identity,"kind":"geometry","bounds_px":None,"points_px":[vertex["position_px"]],"ratio_denominator":None})
            provenance.append({"field_path":f"/observations/series/{len(series)}/vertices/{vertex_index}/value",
                "method":"radial_calibration","evidence_ids":[identity],"calibration_ids":["radial_scale"],"input_paths":[],
                "error_bound":2*abs(radial_fit["slope"])+radial_fit["residual_value"]})
        if any(mask.ravel()):
            series.append(
                {
                    "id": f"series_{series_index}",
                    "color": color_hex,
                    "label": label,
                    "label_confidence": label_confidence,
                    "vertices": vertices[:MAX_MEASUREMENT_OBSERVATIONS],
                }
            )
    if len(palette) >= 8:
        truncated = True
    else:
        truncated = False
    if len(radial_grid) > MAX_MEASUREMENT_OBSERVATIONS:
        radial_grid = radial_grid[:MAX_MEASUREMENT_OBSERVATIONS]
        truncated = True

    warnings = []
    if ocr.truncated:
        warnings.append("OCR candidate limit reached; radar dimension and legend labels may be incomplete")
    if len(spokes) < 3:
        warnings.append("fewer than three radial spokes were reliably observed")
    if not radial_grid:
        warnings.append("radial grid rings were not reliably separated")
    if radial_fit is None:
        warnings.append("radial values remain null because a readable numeric radial calibration was not established")
    if truncated:
        warnings.append("radar observation limit reached")
    status = "partial" if series else "unsupported"
    if truncated:
        status = "partial"
    geometry_confidence = min(0.95, 0.45 + min(len(spokes), 8) * 0.05 + min(len(series), 4) * 0.04)
    association_confidence = 0.7 if any(item["label"] for item in spokes) or any(item["label"] for item in series) else 0.45
    calibration_confidence = radial_fit["confidence"] if radial_fit else 0.0
    observations = {
        "center_px": [round(center_x, 2), round(center_y, 2)],
        "spokes": spokes,
        "radial_grid": radial_grid,
        "series": series,
    }
    return MeasurementSensorResult(
        status=status,
        observations=observations,  # type: ignore[arg-type]
        confidence={
            "overall": _clamp(0.7 * geometry_confidence + 0.3 * association_confidence),
            "geometry": _clamp(geometry_confidence),
            "calibration": calibration_confidence,
            "association": _clamp(association_confidence),
        },  # type: ignore[arg-type]
        plot_area_px=_bounded_plot_area(center_x, center_y, outer_radius, width, height),
        warnings=tuple(warnings),
        truncated=truncated,
        evidence=tuple(evidence), calibrations=(calibration,) if calibration else (),
        value_provenance=tuple(provenance),
    )


def _refine_center(dark: np.ndarray, center_x: float, center_y: float, radius: float) -> tuple[float, float]:
    """Refine the colored-series bounding-box center against radial grid support."""
    search = max(3, int(round(min(dark.shape) * 0.06)))
    image_height, image_width = dark.shape
    candidates = [
        (
            float(np.clip(round(center_x + dx), 0, image_width - 1)),
            float(np.clip(round(center_y + dy), 0, image_height - 1)),
        )
        for dy in range(-search, search + 1, 2)
        for dx in range(-search, search + 1, 2)
    ]
    best = max(candidates, key=lambda candidate: _radial_support_score(dark, *candidate, radius))
    refined = [
        (
            float(np.clip(best[0] + dx, 0, image_width - 1)),
            float(np.clip(best[1] + dy, 0, image_height - 1)),
        )
        for dy in (-1.0, 0.0, 1.0)
        for dx in (-1.0, 0.0, 1.0)
    ]
    return max(refined, key=lambda candidate: _radial_support_score(dark, *candidate, radius))


def _radial_support_score(dark: np.ndarray, center_x: float, center_y: float, radius: float) -> float:
    angles, scores, _ = _spoke_scores(dark, center_x, center_y, radius)
    groups = _angular_groups(np.flatnonzero(scores >= 0.10), len(angles))
    peaks = sorted(
        (float(np.max(scores[group])) for group in groups if len(group) <= 10),
        reverse=True,
    )
    selected = peaks[:12]
    score = sum(selected) + len(selected) * 0.015
    if len(groups) >= 3:
        spoke_angles = [
            _circular_mean(group)
            for group in groups
            if len(group) <= 10 and float(np.max(scores[group])) >= 0.12
        ]
        outer_radius = _estimate_outer_radius(dark, center_x, center_y, radius, spoke_angles)
        score += len(_radial_grid(dark, center_x, center_y, outer_radius, spoke_angles)) * 0.1
    return score


def _spoke_scores(dark: np.ndarray, center_x: float, center_y: float, radius: float, inner_fraction=.1):
    angles = np.arange(360, dtype=float)
    radii = np.arange(max(4.0, radius * inner_fraction), radius * 0.96, 1.0)
    xs = np.rint(center_x + np.sin(np.deg2rad(angles))[:, None] * radii[None, :]).astype(int)
    ys = np.rint(center_y - np.cos(np.deg2rad(angles))[:, None] * radii[None, :]).astype(int)
    in_bounds = (xs >= 0) & (xs < dark.shape[1]) & (ys >= 0) & (ys < dark.shape[0])
    safe_x, safe_y = np.clip(xs, 0, dark.shape[1] - 1), np.clip(ys, 0, dark.shape[0] - 1)
    hits = dark[safe_y, safe_x] & in_bounds
    scores = np.mean(hits, axis=1) if len(radii) else np.zeros(360)
    return angles, scores, radii


def _angular_groups(indices: np.ndarray, size: int) -> list[list[int]]:
    if not len(indices):
        return []
    groups: list[list[int]] = [[int(indices[0])]]
    for value in indices[1:]:
        if int(value) - groups[-1][-1] <= 1:
            groups[-1].append(int(value))
        else:
            groups.append([int(value)])
    if len(groups) > 1 and groups[0][0] == 0 and groups[-1][-1] == size - 1:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    return groups


def _circular_mean(angles: list[int]) -> float:
    radians = np.deg2rad(np.asarray(angles, dtype=float))
    return float(np.degrees(np.arctan2(np.mean(np.sin(radians)), np.mean(np.cos(radians)))) % 360.0)


def _estimate_outer_radius(
    dark: np.ndarray,
    center_x: float,
    center_y: float,
    search_radius: float,
    angles: list[float],
) -> float:
    radii = [_last_dark_radius(dark, center_x, center_y, angle, search_radius) for angle in angles]
    usable = [radius for radius in radii if radius >= search_radius * 0.5]
    if usable:
        return float(np.median(usable))
    return float(search_radius * 0.82)


def _last_dark_radius(dark: np.ndarray, center_x: float, center_y: float, angle: float, maximum: float) -> float:
    radians = np.deg2rad(angle)
    radii = np.arange(maximum * 0.1, maximum * 0.98, 1.0)
    xs = np.rint(center_x + np.sin(radians) * radii).astype(int)
    ys = np.rint(center_y - np.cos(radians) * radii).astype(int)
    valid = (xs >= 0) & (xs < dark.shape[1]) & (ys >= 0) & (ys < dark.shape[0])
    if not np.any(valid):
        return 0.0
    selected = radii[valid][dark[ys[valid], xs[valid]]]
    return float(selected[-1]) if len(selected) else 0.0


def _point(center_x: float, center_y: float, angle: float, radius: float) -> tuple[float, float]:
    radians = np.deg2rad(angle)
    return float(center_x + np.sin(radians) * radius), float(center_y - np.cos(radians) * radius)


def _nearest_label(snippets, endpoint: tuple[float, float], radius: float) -> str | None:
    candidates = []
    for snippet in snippets:
        x, y, width, height = snippet.bbox_px
        center = (x + width / 2, y + height / 2)
        distance = float(np.hypot(center[0] - endpoint[0], center[1] - endpoint[1]))
        if distance <= max(18, radius * 0.35):
            candidates.append((distance, -snippet.confidence, snippet.text[:160]))
    return min(candidates)[2] if candidates else None


def _radial_grid(dark: np.ndarray, center_x: float, center_y: float, radius: float, spoke_angles: list[float]):
    if len(spoke_angles) < 3:
        return []
    sorted_angles = sorted(spoke_angles)
    off_angles = [
        (angle + ((sorted_angles[(index + 1) % len(sorted_angles)] - angle) % 360.0) / 2.0) % 360.0
        for index, angle in enumerate(sorted_angles)
    ]
    sample_radii = np.arange(max(4.0, radius * 0.08), radius * 0.94, 1.0)
    counts = np.zeros(len(sample_radii), dtype=float)
    for angle in off_angles:
        radians = np.deg2rad(angle)
        xs = np.rint(center_x + np.sin(radians) * sample_radii).astype(int)
        ys = np.rint(center_y - np.cos(radians) * sample_radii).astype(int)
        valid = (xs >= 0) & (xs < dark.shape[1]) & (ys >= 0) & (ys < dark.shape[0])
        indices = np.flatnonzero(valid)
        counts[indices] += dark[ys[valid], xs[valid]]
    threshold = max(2, int(np.ceil(len(off_angles) * 0.4)))
    candidates = np.flatnonzero(counts >= threshold)
    groups = _angular_groups(candidates, len(sample_radii))
    radii = []
    for group in groups:
        if len(group) >= 1:
            radius_px = float(np.mean(sample_radii[group]))
            if radius_px < radius * 0.95:
                radii.append({"value": None, "radius_px": round(radius_px, 2)})
    return radii[:MAX_MEASUREMENT_OBSERVATIONS]


def _bounded_plot_area(center_x: float, center_y: float, radius: float, width: int, height: int) -> dict[str, int]:
    left = max(0, int(round(center_x - radius)))
    top = max(0, int(round(center_y - radius)))
    right = min(width, int(round(center_x + radius)))
    bottom = min(height, int(round(center_y + radius)))
    return {"x": left, "y": top, "width": max(1, right - left), "height": max(1, bottom - top)}


def _series_vertex(mask: np.ndarray, center_x: float, center_y: float, angle: float, radius: float):
    radii = np.arange(max(3.0, radius * 0.08), radius * 1.02, 1.0)
    radians = np.deg2rad(angle)
    xs = np.rint(center_x + np.sin(radians) * radii).astype(int)
    ys = np.rint(center_y - np.cos(radians) * radii).astype(int)
    valid = (xs >= 0) & (xs < mask.shape[1]) & (ys >= 0) & (ys < mask.shape[0])
    if not np.any(valid):
        return None
    indices = np.flatnonzero(mask[ys[valid], xs[valid]])
    if not len(indices):
        return None
    # A stroke/marker has thickness; reading its far edge biases every radius.
    groups = np.split(indices, np.flatnonzero(np.diff(indices)>1)+1)
    selected = np.flatnonzero(valid)[groups[-1]]
    return [round(float(np.mean(xs[selected])), 2), round(float(np.mean(ys[selected])), 2)]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _visible_outer_circle(rgb, observation_mask):
    """Fit an observed closed neutral contour; reject non-circular candidates."""
    from scipy.ndimage import label, find_objects
    gray = rgb.mean(axis=2)
    dark = (gray < 150) & (np.ptp(rgb.astype(np.int16), axis=2) <= 8)
    if observation_mask is not None:
        dark &= observation_mask
    components, count = label(dark, structure=np.ones((3,3)))
    for slices in sorted((s for s in find_objects(components) if s is not None),
                         key=lambda s: (s[0].stop-s[0].start)*(s[1].stop-s[1].start), reverse=True):
        yy, xx = slices
        w,h = xx.stop-xx.start, yy.stop-yy.start
        if min(w,h) < min(rgb.shape[:2])*.25 or abs(w-h) > max(w,h)*.08:
            continue
        cx,cy = (xx.start+xx.stop-1)/2, (yy.start+yy.stop-1)/2
        ys,xs = np.nonzero(dark[yy,xx])
        xs,ys = xs+xx.start,ys+yy.start
        radius = (w+h)/4
        outer = np.abs(np.hypot(xs-cx,ys-cy)-radius) <= 3
        if np.count_nonzero(outer) < radius*2:
            continue
        matrix = np.column_stack((2*xs[outer],2*ys[outer],np.ones(np.count_nonzero(outer))))
        fit = np.linalg.lstsq(matrix,xs[outer]**2+ys[outer]**2,rcond=None)[0]
        cx,cy = fit[:2]
        radius = np.sqrt(fit[2]+cx*cx+cy*cy)
        residual = np.sqrt(np.mean((np.hypot(xs[outer]-cx,ys[outer]-cy)-radius)**2))
        if residual <= 2:
            return float(cx),float(cy),float(radius)
    return None
