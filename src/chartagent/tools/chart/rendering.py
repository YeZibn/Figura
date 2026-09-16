"""Deterministic ChartSpec-to-image generation for the Agent tool surface."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from matplotlib.collections import PathCollection
from matplotlib.patches import Rectangle, Wedge

from ...spec import chart_spec_digest
from ...spec import ChartSpec, ChartType, DataPoint
from ..core.result import GeneratedImage, ToolResult
from ..core.definition import Tool
from .specification import CHART_SPEC_SCHEMA
from .validation import (
    GenerationIssue,
    GenerationValidation,
    MAX_GENERATION_LABEL_LENGTH,
    validate_generation,
)

DEFAULT_CHART_WIDTH = 1200
DEFAULT_CHART_HEIGHT = 800
MAX_CHART_WIDTH = 2400
MAX_CHART_HEIGHT = 1600
MAX_CHART_BYTES = 10 * 1024 * 1024
MAX_CHART_POINTS = 512
MAX_TITLE_LENGTH = 240
MAX_LABEL_LENGTH = MAX_GENERATION_LABEL_LENGTH
MAX_FONT_NAME_LENGTH = 120
FONT_PATH_ENV = "CHARTAGENT_FONT_PATH"
_CJK_FAMILIES = (
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "WenQuanYi Zen Hei",
)
_CJK_PROBES = "中文图表数据"


@dataclass(frozen=True)
class _ResolvedFont:
    """Per-render font choice and bounded diagnostics."""

    properties: FontProperties | None
    family: str | None
    source: str
    status: str
    warning: str | None = None


def _font_supports_cjk(path: str | os.PathLike[str]) -> bool:
    """Return whether a font file contains representative CJK glyphs."""
    try:
        font = font_manager.get_font(path)
        charmap = font.get_charmap()
        return all(ord(character) in charmap for character in _CJK_PROBES)
    except (OSError, RuntimeError, ValueError):
        return False


def _font_name(properties: FontProperties, path: str | None = None) -> str | None:
    try:
        name = properties.get_name()
    except (OSError, RuntimeError, ValueError):
        name = None
    if not isinstance(name, str) or not name.strip():
        name = Path(path).stem if path else None
    return name.strip()[:MAX_FONT_NAME_LENGTH] if name else None


def _resolved_font_from_path(path: str, source: str) -> _ResolvedFont | None:
    candidate = Path(path).expanduser()
    if not candidate.is_file() or not os.access(candidate, os.R_OK):
        return None
    if not _font_supports_cjk(candidate):
        return None
    try:
        properties = FontProperties(fname=str(candidate))
        family = _font_name(properties, str(candidate))
    except (OSError, RuntimeError, ValueError):
        return None
    if not family:
        return None
    return _ResolvedFont(properties, family, source, "resolved")


def _resolve_font() -> _ResolvedFont:
    """Resolve one CJK font without changing process-wide Matplotlib settings."""
    configured = os.environ.get(FONT_PATH_ENV, "").strip()
    if configured:
        resolved = _resolved_font_from_path(configured, "configured")
        if resolved is not None:
            return resolved
        return _ResolvedFont(
            None,
            None,
            "fallback",
            "fallback",
            f"{FONT_PATH_ENV} does not point to a readable CJK font",
        )

    for family in _CJK_FAMILIES:
        try:
            path = font_manager.findfont(
                FontProperties(family=family),
                fallback_to_default=False,
            )
        except (OSError, RuntimeError, ValueError):
            continue
        resolved = _resolved_font_from_path(path, "system")
        if resolved is not None:
            return resolved

    return _ResolvedFont(
        None,
        None,
        "fallback",
        "fallback",
        "no compatible CJK font was found; Chinese text may be missing",
    )


def _set_font(text: Any, font: _ResolvedFont) -> None:
    if font.properties is not None:
        text.set_fontproperties(font.properties)


def _set_tick_fonts(axis: Any, font: _ResolvedFont) -> None:
    for label in (*axis.get_xticklabels(), *axis.get_yticklabels()):
        _set_font(label, font)


def _set_legend_fonts(legend: Any, font: _ResolvedFont) -> None:
    if legend is None:
        return
    for text in legend.get_texts():
        _set_font(text, font)
    title = legend.get_title()
    if title is not None:
        _set_font(title, font)


def _series_name(point: DataPoint) -> str:
    return point.series.strip() if isinstance(point.series, str) and point.series.strip() else "数据"


def _unique(values: Iterable[str]) -> list[str]:
    return list(OrderedDict.fromkeys(values))


def _group_points(points: list[DataPoint]) -> OrderedDict[str, list[DataPoint]]:
    groups: OrderedDict[str, list[DataPoint]] = OrderedDict()
    for point in points:
        groups.setdefault(_series_name(point), []).append(point)
    return groups


def _configure_axes(ax: Any, spec: ChartSpec, font: _ResolvedFont) -> None:
    if spec.metadata.title:
        _set_font(ax.set_title(spec.metadata.title[:MAX_TITLE_LENGTH]), font)
    if spec.axes is not None:
        _set_font(ax.set_xlabel(spec.axes.x.label[:MAX_LABEL_LENGTH]), font)
        _set_font(ax.set_ylabel(spec.axes.y.label[:MAX_LABEL_LENGTH]), font)
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)
    _set_tick_fonts(ax, font)


def _canonical_category(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bar_categories(spec: ChartSpec) -> list[str]:
    return _unique(
        [
            _canonical_category(category)
            for category in (spec.axes.x.categories if spec.axes and spec.axes.x.categories else [])
            if isinstance(category, str)
        ]
        + [_canonical_category(point.category) for point in spec.dataset]
    )


def _apply_axis_ranges(ax: Any, spec: ChartSpec) -> None:
    if spec.axes is None:
        return
    for name in ("x", "y"):
        axis = getattr(spec.axes, name)
        minimum = axis.min_value
        maximum = axis.max_value
        if minimum is None and maximum is None:
            continue
        current_min, current_max = getattr(ax, f"get_{name}lim")()
        getattr(ax, f"set_{name}lim")(
            current_min if minimum is None else float(minimum),
            current_max if maximum is None else float(maximum),
        )


def _render_bar(ax: Any, spec: ChartSpec, font: _ResolvedFont) -> None:
    categories = _bar_categories(spec)
    groups = _group_points(spec.dataset)
    explicit_series = any(point.series for point in spec.dataset)
    positions = np.arange(len(categories), dtype=float)
    width = 0.8 / max(1, len(groups))
    colors = plt.get_cmap("tab10")
    for group_index, (series, points) in enumerate(groups.items()):
        values = {_canonical_category(point.category): float(point.value) for point in points}
        offset = (group_index - (len(groups) - 1) / 2) * width
        bars = ax.bar(
            positions + offset,
            [values[category] for category in categories],
            width,
            label=series,
            color=colors(group_index % 10),
        )
        for bar in bars:
            value = bar.get_height()
            annotation = ax.annotate(
                f"{value:g}",
                (bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )
            _set_font(annotation, font)
    if spec.axes is None or (spec.axes.y.min_value is None and spec.axes.y.max_value is None):
        values = [float(point.value) for point in spec.dataset]
        lower = min(0.0, min(values))
        upper = max(0.0, max(values))
        margin = max((upper - lower) * 0.12, 1.0)
        ax.set_ylim(lower, upper + margin)
    ax.set_xticks(positions, categories)
    if explicit_series:
        _set_legend_fonts(ax.legend(), font)
    _set_tick_fonts(ax, font)


def _render_line(ax: Any, spec: ChartSpec, font: _ResolvedFont) -> None:
    groups = _group_points(spec.dataset)
    colors = plt.get_cmap("tab10")
    explicit_series = any(point.series for point in spec.dataset)
    for index, (series, points) in enumerate(groups.items()):
        ax.plot(
            [float(point.x) for point in points],
            [float(point.y) for point in points],
            marker="o",
            label=series,
            color=colors(index % 10),
        )
    if explicit_series:
        _set_legend_fonts(ax.legend(), font)


def _render_scatter(ax: Any, spec: ChartSpec, font: _ResolvedFont) -> None:
    groups = _group_points(spec.dataset)
    colors = plt.get_cmap("tab10")
    explicit_series = any(point.series for point in spec.dataset)
    for index, (series, points) in enumerate(groups.items()):
        ax.scatter(
            [float(point.x) for point in points],
            [float(point.y) for point in points],
            label=series,
            color=colors(index % 10),
            alpha=0.86,
        )
    if explicit_series:
        _set_legend_fonts(ax.legend(), font)


def _render_pie(ax: Any, spec: ChartSpec, font: _ResolvedFont) -> None:
    labels = [_canonical_category(point.category) for point in spec.dataset]
    values = [float(point.value) for point in spec.dataset]
    _, label_texts, percentage_texts = ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
    )
    for text in (*label_texts, *percentage_texts):
        _set_font(text, font)
    ax.axis("equal")


def _audit_issue(
    code: str,
    location: str,
    message: str,
    *,
    severity: str = "error",
) -> GenerationIssue:
    return GenerationIssue(code, location, message, severity)


def _close_enough(actual: Any, expected: Any, *, tolerance: float = 1e-7) -> bool:
    try:
        return bool(np.allclose(actual, expected, atol=tolerance, rtol=tolerance))
    except (TypeError, ValueError):
        return False


def _audit_artist_fidelity(ax: Any, spec: ChartSpec) -> list[GenerationIssue]:
    """Check that the figure artists still represent the validated dataset."""
    chart_type = spec.metadata.chart_type
    issues: list[GenerationIssue] = []
    groups = _group_points(spec.dataset)

    if chart_type is ChartType.BAR:
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        categories = _bar_categories(spec)
        expected: list[float] = []
        for points in groups.values():
            values = {_canonical_category(point.category): float(point.value) for point in points}
            expected.extend(values[category] for category in categories)
        actual = [float(bar.get_height()) for bar in bars]
        if len(actual) != len(expected):
            issues.append(_audit_issue("artist_count_mismatch", "figure.bars", "rendered bar count does not match the dataset"))
        elif not _close_enough(actual, expected):
            issues.append(_audit_issue("artist_value_mismatch", "figure.bars", "rendered bar heights do not match the dataset"))
        actual_categories = [
            label.get_text()
            for label in ax.get_xticklabels()
            if label.get_text()
        ]
        if actual_categories != categories:
            issues.append(_audit_issue("category_mismatch", "figure.x_ticks", "rendered categories do not match the dataset order"))

    elif chart_type is ChartType.LINE:
        lines = list(ax.lines)
        if len(lines) != len(groups):
            issues.append(_audit_issue("artist_count_mismatch", "figure.lines", "rendered line count does not match the series count"))
        else:
            for line, points in zip(lines, groups.values()):
                if not _close_enough(line.get_xdata(), [float(point.x) for point in points]) or not _close_enough(line.get_ydata(), [float(point.y) for point in points]):
                    issues.append(_audit_issue("artist_value_mismatch", "figure.lines", "rendered line points do not match the dataset"))
                    break

    elif chart_type is ChartType.SCATTER:
        collections = [collection for collection in ax.collections if isinstance(collection, PathCollection)]
        if len(collections) != len(groups):
            issues.append(_audit_issue("artist_count_mismatch", "figure.scatter", "rendered scatter series count does not match the dataset"))
        else:
            for collection, points in zip(collections, groups.values()):
                expected = [[float(point.x), float(point.y)] for point in points]
                if not _close_enough(collection.get_offsets(), expected):
                    issues.append(_audit_issue("artist_value_mismatch", "figure.scatter", "rendered scatter points do not match the dataset"))
                    break

    elif chart_type is ChartType.PIE:
        wedges = [patch for patch in ax.patches if isinstance(patch, Wedge)]
        values = [float(point.value) for point in spec.dataset]
        total = sum(values)
        expected_spans = [value / total * 360.0 for value in values]
        actual_spans = [float(wedge.theta2 - wedge.theta1) for wedge in wedges]
        if len(actual_spans) != len(expected_spans):
            issues.append(_audit_issue("artist_count_mismatch", "figure.pie", "rendered pie sector count does not match the dataset"))
        elif not _close_enough(actual_spans, expected_spans, tolerance=1e-5):
            issues.append(_audit_issue("artist_value_mismatch", "figure.pie", "rendered pie sector proportions do not match the dataset"))

    if any(point.series for point in spec.dataset):
        legend = ax.get_legend()
        actual_series = [text.get_text() for text in legend.get_texts()] if legend else []
        expected_series = list(groups.keys())
        if actual_series != expected_series:
            issues.append(_audit_issue("legend_mismatch", "figure.legend", "rendered series legend does not match the dataset"))
    return issues


def _text_elements(ax: Any) -> list[tuple[str, Any]]:
    elements: list[tuple[str, Any]] = [
        ("figure.title", ax.title),
        ("figure.x_label", ax.xaxis.label),
        ("figure.y_label", ax.yaxis.label),
    ]
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    elements.extend(
        ("figure.x_tick", label)
        for location, label in zip(ax.get_xticks(), ax.get_xticklabels())
        if x_min - 1e-9 <= location <= x_max + 1e-9
    )
    elements.extend(
        ("figure.y_tick", label)
        for location, label in zip(ax.get_yticks(), ax.get_yticklabels())
        if y_min - 1e-9 <= location <= y_max + 1e-9
    )
    elements.extend(("figure.annotation", text) for text in ax.texts)
    legend = ax.get_legend()
    if legend is not None:
        elements.extend(("figure.legend", text) for text in legend.get_texts())
        elements.append(("figure.legend", legend.get_title()))
    return [(location, text) for location, text in elements if text is not None and text.get_visible() and text.get_text()]


def _audit_layout(fig: Any, ax: Any) -> list[GenerationIssue]:
    """Check final text bounds and report density as recoverable warnings."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas_width, canvas_height = fig.canvas.get_width_height()
    tolerance = 2.0
    issues: list[GenerationIssue] = []
    for location, text in _text_elements(ax):
        try:
            bbox = text.get_window_extent(renderer=renderer)
        except (AttributeError, RuntimeError, ValueError):
            continue
        if bbox.width <= 0 or bbox.height <= 0:
            continue
        left = max(0.0, -bbox.x0)
        right = max(0.0, bbox.x1 - canvas_width)
        bottom = max(0.0, -bbox.y0)
        top = max(0.0, bbox.y1 - canvas_height)
        if max(left, right, bottom, top) <= tolerance:
            continue
        inside_width = max(0.0, min(float(canvas_width), bbox.x1) - max(0.0, bbox.x0))
        inside_height = max(0.0, min(float(canvas_height), bbox.y1) - max(0.0, bbox.y0))
        outside_area = bbox.width * bbox.height - inside_width * inside_height
        severity = "error" if outside_area >= bbox.width * bbox.height * 0.5 else "warning"
        issues.append(_audit_issue("content_clipped", location, "visible chart text extends beyond the output canvas", severity=severity))

    categories = [label.get_text() for label in ax.get_xticklabels() if label.get_text()]
    if len(categories) > 12:
        issues.append(_audit_issue("label_density", "figure.x_ticks", "chart contains more than 12 category labels", severity="warning"))
    if any(len(label) > 24 for label in categories):
        issues.append(_audit_issue("label_density", "figure.x_ticks", "one or more category labels are unusually long", severity="warning"))
    if len(ax.title.get_text()) > 48:
        issues.append(_audit_issue("label_density", "figure.title", "chart title is unusually long", severity="warning"))
    if len(ax.xaxis.label.get_text()) > 24 or len(ax.yaxis.label.get_text()) > 24:
        issues.append(_audit_issue("label_density", "figure.axis_labels", "one or more axis labels are unusually long", severity="warning"))
    legend = ax.get_legend()
    if legend is not None and len(legend.get_texts()) > 8:
        issues.append(_audit_issue("legend_density", "figure.legend", "chart contains more than 8 series in the legend", severity="warning"))
    return issues


def _audit_figure(fig: Any, ax: Any, spec: ChartSpec) -> list[GenerationIssue]:
    return _audit_artist_fidelity(ax, spec) + _audit_layout(fig, ax)


def _verify_png(content: bytes, width: int, height: int) -> list[GenerationIssue]:
    issues: list[GenerationIssue] = []
    if not content:
        return [_audit_issue("empty_artifact", "artifact", "rendered PNG is empty")]
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
            if image.format != "PNG":
                issues.append(_audit_issue("artifact_format", "artifact", "rendered artifact is not a PNG"))
            if image.size != (width, height):
                issues.append(_audit_issue("artifact_dimensions", "artifact", "rendered PNG dimensions do not match the requested dimensions"))
            pixels = np.asarray(image.convert("RGBA"))
            visible = np.any(pixels[:, :, :3] < 245, axis=2) | (pixels[:, :, 3] < 250)
            if float(visible.mean()) < 0.0001:
                issues.append(_audit_issue("blank_artifact", "artifact", "rendered PNG is effectively blank"))
    except (OSError, ValueError, SyntaxError) as exc:
        issues.append(_audit_issue("artifact_decode", "artifact", f"rendered PNG cannot be fully decoded: {str(exc)[:160]}"))
    return issues


def _validation_summary(
    semantic: GenerationValidation,
    audit_issues: list[GenerationIssue],
    font: _ResolvedFont,
) -> dict[str, Any]:
    issues = list(semantic.issues) + list(audit_issues)
    if font.warning:
        issues.append(GenerationIssue("font_fallback", "readability.font", font.warning, "warning"))
    fidelity_codes = {"artist_count_mismatch", "artist_value_mismatch", "category_mismatch", "legend_mismatch"}
    checks = {
        "semantic": "failed" if any(issue.severity == "error" and issue.code not in {"content_clipped", *fidelity_codes} for issue in issues) else "passed",
        "fidelity": "failed" if any(issue.code in fidelity_codes for issue in issues) else "passed",
        "layout": "warning" if any(issue.code in {"content_clipped", "label_density", "legend_density"} for issue in issues) else "passed",
        "readability": "warning" if font.warning or any(issue.code in {"content_clipped", "label_density", "legend_density"} for issue in issues) else "passed",
        "artifact": "passed",
    }
    status = "warning" if any(issue.severity == "warning" for issue in issues) else "passed"
    return {
        "status": status,
        "checks": checks,
        "issues": [issue.to_dict() for issue in issues[:32]],
    }


def render_chart(
    spec: dict[str, Any],
    width: int = DEFAULT_CHART_WIDTH,
    height: int = DEFAULT_CHART_HEIGHT,
) -> ToolResult | dict[str, Any]:
    """Render a validated ChartSpec as a bounded PNG-backed ToolResult."""
    try:
        chart_spec = ChartSpec.from_dict(spec if isinstance(spec, dict) else {})
        semantic_validation = validate_generation(chart_spec)
        width = int(width)
        height = int(height)
        if not 1 <= width <= MAX_CHART_WIDTH or not 1 <= height <= MAX_CHART_HEIGHT:
            dimension_issue = GenerationIssue(
                "invalid_dimensions",
                "dimensions",
                f"dimensions must be within {MAX_CHART_WIDTH}x{MAX_CHART_HEIGHT}",
            )
            semantic_validation = GenerationValidation(semantic_validation.issues + (dimension_issue,)).bounded()
        if semantic_validation.blocking:
            return {
                "error": "ChartSpec cannot be rendered",
                "issues": semantic_validation.legacy_issues(),
                "validation": semantic_validation.to_dict(),
            }

        font = _resolve_font()
        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        audit_issues: list[GenerationIssue] = []
        try:
            chart_type = chart_spec.metadata.chart_type
            if chart_type is ChartType.BAR:
                _render_bar(ax, chart_spec, font)
            elif chart_type is ChartType.LINE:
                _render_line(ax, chart_spec, font)
            elif chart_type is ChartType.PIE:
                _render_pie(ax, chart_spec, font)
            elif chart_type is ChartType.SCATTER:
                _render_scatter(ax, chart_spec, font)
            else:  # pragma: no cover - ChartType.from_dict closes this set.
                return {"error": f"unsupported chart type: {chart_type}"}
            _configure_axes(ax, chart_spec, font)
            _apply_axis_ranges(ax, chart_spec)
            fig.tight_layout()
            audit_issues = _audit_figure(fig, ax, chart_spec)
            if any(issue.severity == "error" for issue in audit_issues):
                return {
                    "error": "ChartSpec rendered chart failed quality audit",
                    "issues": [issue.to_dict() for issue in audit_issues[:32]],
                    "validation": {
                        "status": "failed",
                        "checks": {"semantic": "passed", "fidelity": "failed", "layout": "failed", "readability": "not_run", "artifact": "not_run"},
                        "issues": [issue.to_dict() for issue in audit_issues[:32]],
                    },
                }
            output = BytesIO()
            fig.savefig(output, format="png", dpi=100)
            content = output.getvalue()
        finally:
            plt.close(fig)

        if len(content) > MAX_CHART_BYTES:
            issue = GenerationIssue(
                "artifact_too_large",
                "artifact",
                "rendered chart exceeds the configured byte limit",
            )
            return {
                "error": issue.message,
                "issues": [issue.to_dict()],
                "validation": {
                    "status": "failed",
                    "checks": {"semantic": "passed", "fidelity": "passed", "layout": "passed", "readability": "passed", "artifact": "failed"},
                    "issues": [issue.to_dict()],
                },
            }
        artifact_issues = _verify_png(content, width, height)
        if artifact_issues:
            return {
                "error": "rendered chart failed artifact verification",
                "issues": [issue.to_dict() for issue in artifact_issues[:32]],
                "validation": {
                    "status": "failed",
                    "checks": {"semantic": "passed", "fidelity": "passed", "layout": "passed", "readability": "not_run", "artifact": "failed"},
                    "issues": [issue.to_dict() for issue in artifact_issues[:32]],
                },
            }
        actual_width, actual_height = width, height
        title = chart_spec.metadata.title[:MAX_TITLE_LENGTH] or f"{chart_spec.metadata.chart_type.value} chart"
        validation = _validation_summary(semantic_validation, audit_issues, font)
        data = {
            "kind": "generated_chart",
            "chart_type": chart_spec.metadata.chart_type.value,
            "title": title,
            "chart_spec_digest": chart_spec_digest(chart_spec),
            "media_type": "image/png",
            "byte_count": len(content),
            "width": actual_width,
            "height": actual_height,
            "point_count": len(chart_spec.dataset),
            "series": _unique(_series_name(point) for point in chart_spec.dataset),
            "font": {
                "status": font.status,
                "source": font.source,
                "family": font.family,
            },
            "validation": validation,
        }
        warnings = tuple(
            issue["message"]
            for issue in validation["issues"]
            if issue["severity"] == "warning"
        )
        return ToolResult(
            data=data,
            images=(
                GeneratedImage(
                    content=content,
                    media_type="image/png",
                    caption=f"生成图表：{title}",
                    metadata={
                        "kind": "generated_chart",
                        "chart_type": chart_spec.metadata.chart_type.value,
                        "title": title,
                        "chart_spec_digest": chart_spec_digest(chart_spec),
                        "width": actual_width,
                        "height": actual_height,
                        "font_status": font.status,
                        "font_source": font.source,
                        "font_family": font.family,
                    },
                ),
            ),
            warnings=warnings,
        )
    except (TypeError, ValueError, KeyError) as exc:
        return {"error": f"ChartSpec cannot be rendered: {str(exc)[:240]}"}
    except Exception as exc:  # noqa: BLE001 - renderer failures stay inside the tool boundary.
        return {"error": f"chart renderer unavailable: {str(exc)[:240]}"}


RENDER_CHART = Tool(
    name="render_chart",
    description=(
        "Render a validated ChartSpec into a bounded PNG chart candidate and return "
        "the image, render metadata, deterministic validation summary, and any "
        "warnings. Use after assembling chart data when a visual "
        "output is requested; do not use with incomplete specs, unsupported chart "
        "types, or as a substitute for the mandatory post-generation review. A "
        "successful tool call means only that rendering and local artifact checks "
        "passed: the image remains a candidate until review_generated_chart accepts "
        "it and publication status is reported."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spec": CHART_SPEC_SCHEMA,
            "width": {"type": "integer", "minimum": 1, "maximum": MAX_CHART_WIDTH},
            "height": {"type": "integer", "minimum": 1, "maximum": MAX_CHART_HEIGHT},
        },
        "required": ["spec"],
        "additionalProperties": False,
    },
    fn=render_chart,
    group="chart-generation",
)


__all__ = [
    "DEFAULT_CHART_HEIGHT",
    "DEFAULT_CHART_WIDTH",
    "MAX_CHART_BYTES",
    "MAX_CHART_HEIGHT",
    "MAX_CHART_POINTS",
    "MAX_CHART_WIDTH",
    "RENDER_CHART",
    "render_chart",
]
