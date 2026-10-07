"""Local numeric support for observed radial rings and color scales."""
import numpy as np

from .cartesian import fit_axis_calibration, parse_numeric_text
from .colors import hex_color


def text_evidence(snippet, identity):
    x,y,w,h = snippet.bbox_px
    return {"id":identity,"kind":"ocr","bounds_px":{"x":x,"y":y,"width":w,"height":h},
            "text":snippet.text,"confidence":snippet.confidence}


def fit_scalar_support(pairs):
    """Fit only distinct observed labels over a non-degenerate physical span."""
    ticks = [{"value":v,"point_px":[p,0]} for _,p,v in pairs]
    fit = fit_axis_calibration(ticks, [[0,0],[1,0]])
    if fit is None or not fit["calibrated"]:
        return None
    return fit


def color_scale_support(rgb, snippets, plot):
    """Find a narrow continuous colored bar outside the observed cell grid."""
    left = plot["x"] + plot["width"]
    top, bottom = plot["y"], plot["y"] + plot["height"]
    colors = np.ptp(rgb[top:bottom,left:].astype(np.int16),axis=2) >= 18
    if not colors.size:
        return [], None
    fractions = colors.mean(axis=0)
    indices = np.flatnonzero(fractions >= .65)
    if not len(indices):
        return [], None
    groups = np.split(indices, np.flatnonzero(np.diff(indices)>1)+1)
    candidates = [g for g in groups if 3 <= len(g) <= max(30,plot["width"]*.1)]
    if len(candidates) != 1:
        return [], None  # Multiple scales cannot be assigned silently.
    group = candidates[0]
    x = left + int(round(group.mean()))
    scale_top, scale_bottom, x = _colorbar_vertical_extent(
        rgb, left + group, x, top, bottom
    )
    pairs = []
    for snippet in snippets:
        sx,sy,sw,sh = snippet.bbox_px
        value = parse_numeric_text(snippet.text)
        y = sy + sh/2
        if value is not None and 0 <= sx-(left+group[-1]) <= 42 and top-5 <= y <= bottom+5:
            axis_x = left+int(group[-1])+1
            lo,hi = max(0,int(round(y))-5),min(rgb.shape[0],int(round(y))+6)
            patch = rgb[lo:hi,axis_x+1:min(rgb.shape[1],axis_x+7)]
            scores = np.all(patch<180,axis=2).sum(axis=1)
            if scores.size and scores.max()>=2:
                hits = np.flatnonzero(scores==scores.max())
                if np.ptp(hits)<=3:
                    y = lo+float(hits.mean())
            pairs.append((snippet,float(y),value))
    fit = fit_scalar_support(pairs)
    if fit is None:
        return [], None
    evidence = [text_evidence(s,f"color_tick_{i}") for i,(s,_,_) in enumerate(pairs)]
    # Sample only actual scale pixels, with a shared closed collection bound.
    span = scale_bottom - scale_top + 1
    ys = (np.arange(scale_top,scale_bottom+1,dtype=int) if span <= 512 else
          np.linspace(scale_top,scale_bottom,512).round().astype(int))
    calibration = {"id":"color_scale","kind":"color_scale","axis_role":"color","supported":True,
        "support_evidence_ids":[e["id"] for e in evidence],
        "parameters":{"slope":fit["slope"],"intercept":fit["intercept"],
            "start_px":[x + 0.5,scale_top],"end_px":[x + 0.5,scale_bottom + 1.0],
            "samples":[{"position_px":[x + 0.5,float(y) + 0.5],"color":hex_color(rgb[y,x])} for y in ys]},
        "residual_value":fit["residual_value"],"support_domain":[min(p[1] for p in pairs),max(p[1] for p in pairs)]}
    return evidence, calibration


def _colorbar_vertical_extent(rgb, columns, preferred_x, top, bottom):
    """Locate the full rendered gradient, including pixels beyond the cell grid."""
    columns = np.asarray(columns, dtype=int)
    sampled = rgb[:, columns].astype(np.int16)
    chromatic = np.ptp(sampled, axis=2) >= 18
    row_fraction = chromatic.mean(axis=1)
    indices = np.flatnonzero(row_fraction >= 0.4)
    if not len(indices):
        return top, bottom - 1, preferred_x
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    minimum_span = max(12, int((bottom - top) * 0.6))
    candidates = [
        group for group in groups
        if len(group) >= minimum_span and group[0] <= top + 8 and group[-1] >= bottom - 8
    ]
    if not candidates:
        return top, bottom - 1, preferred_x
    selected = max(candidates, key=len)
    start, end = int(selected[0]), int(selected[-1])
    coverage = chromatic[start : end + 1].sum(axis=0)
    best_coverage = int(coverage.max())
    best_columns = columns[coverage == best_coverage]
    sample_x = int(min(best_columns, key=lambda candidate: abs(int(candidate) - preferred_x)))
    return start, end, sample_x


def color_reading(color, calibration):
    samples = calibration["parameters"]["samples"]
    target = np.asarray([int(color[i:i+2],16) for i in (1,3,5)])
    palette = np.asarray([[int(s["color"][i:i+2],16) for i in (1,3,5)] for s in samples])
    positions = np.asarray([float(s["position_px"][1]) for s in samples])
    candidates = []
    for index, (first, second) in enumerate(zip(palette, palette[1:])):
        direction = second-first
        length2 = float(np.dot(direction,direction))
        fraction = 0.0 if length2 <= 1e-9 else float(np.clip(np.dot(target-first,direction)/length2,0.0,1.0))
        projected = first + fraction*direction
        distance = float(np.linalg.norm(target-projected))
        position = float(positions[index] + fraction*(positions[index+1]-positions[index]))
        candidates.append((distance,position))
    if not candidates:
        return None
    nearest = min(distance for distance,_ in candidates)
    if nearest > 8:
        return None
    hits = [position for distance,position in candidates if distance <= nearest + 1e-6]
    if max(hits)-min(hits) > 3:
        return None  # Repeated colors in distant scale positions are ambiguous.
    position = float(np.mean(hits))
    params = calibration["parameters"]
    sample_step = (positions[-1] - positions[0]) / max(1, len(positions) - 1)
    start = params.get("start_px")
    end = params.get("end_px")
    if isinstance(start, (tuple, list)) and len(start) == 2 and position - positions[0] <= sample_step:
        position = float(start[1])
    elif isinstance(end, (tuple, list)) and len(end) == 2 and positions[-1] - position <= sample_step:
        position = float(end[1])
    return float(params["slope"] * position + params["intercept"])
