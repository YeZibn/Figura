"""Synthetic annotated charts with explicit ground truth for tests and smokes."""

from __future__ import annotations

from io import BytesIO
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from chartagent.spec import Axes, Axis, ChartMetadata, ChartSpec, ChartType, DataPoint


def annotated_bar_chart(
    values: Sequence[float] = (10, 20, 30),
    categories: Sequence[str] = ("Alpha", "Beta", "Gamma"),
    *,
    title: str = "Quarterly Sales",
    x_label: str = "Category",
    y_label: str = "Value",
    source: str = "synthetic",
) -> tuple[bytes, dict]:
    """Render a clean, single-series bar chart and return PNG bytes plus IR."""
    if len(values) != len(categories) or not values:
        raise ValueError("values and categories must have the same non-zero length")

    numeric_values = [float(value) for value in values]
    labels = [str(category) for category in categories]
    figure, axis = plt.subplots(figsize=(6, 4), dpi=120)
    bars = axis.bar(labels, numeric_values, color="#4c78a8", width=0.62)
    axis.set_title(title)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.set_ylim(0, max(numeric_values) * 1.25)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)

    for bar, value in zip(bars, numeric_values):
        axis.annotate(
            f"{value:g}",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
        )

    output = BytesIO()
    figure.savefig(output, format="png", facecolor="white")
    plt.close(figure)

    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, title=title, source=source),
        axes=Axes(
            x=Axis(label=x_label, categories=labels),
            y=Axis(label=y_label),
        ),
        dataset=[
            DataPoint(category=category, value=value)
            for category, value in zip(labels, numeric_values)
        ],
    )
    return output.getvalue(), spec.to_dict()


def line_chart(
    values_by_series: dict[str, Sequence[float]] | None = None,
    x_values: Sequence[float] = (0, 1, 2, 3, 4),
    *,
    title: str = "Trend",
    x_label: str = "Time",
    y_label: str = "Value",
    source: str = "synthetic-line",
) -> tuple[bytes, dict]:
    """Render a clean, marked line chart with explicit multi-series truth."""
    series_values = values_by_series or {
        "North": (1, 3, 2, 4, 5),
        "South": (2, 2, 4, 3, 6),
    }
    if any(len(values) != len(x_values) for values in series_values.values()):
        raise ValueError("every line series must match x_values length")

    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")
    figure, axis = plt.subplots(figsize=(6, 4), dpi=120)
    for index, (label, values) in enumerate(series_values.items()):
        axis.plot(
            list(x_values),
            [float(value) for value in values],
            color=colors[index % len(colors)],
            marker="o",
            linewidth=2,
            label=label,
        )
    axis.set_title(title)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.set_xticks(list(x_values))
    all_values = [float(value) for values in series_values.values() for value in values]
    axis.set_ylim(min(0, min(all_values)), max(all_values) + 1)
    axis.set_yticks(range(int(min(0, min(all_values))), int(max(all_values) + 2), 2))
    axis.legend()
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)

    output = BytesIO()
    figure.savefig(output, format="png", facecolor="white")
    plt.close(figure)

    dataset = [
        DataPoint(x=float(x), y=float(value), series=label)
        for label, values in series_values.items()
        for x, value in zip(x_values, values)
    ]
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.LINE, title=title, source=source),
        axes=Axes(
            x=Axis(label=x_label, min_value=float(min(x_values)), max_value=float(max(x_values))),
            y=Axis(label=y_label, min_value=float(min(0, min(all_values))), max_value=float(max(all_values) + 1)),
        ),
        dataset=dataset,
    )
    return output.getvalue(), spec.to_dict()


def scatter_chart(
    values_by_series: dict[str, Sequence[float]] | None = None,
    x_values: Sequence[float] = (0, 1, 2, 3, 4),
    *,
    title: str = "Distribution",
    x_label: str = "Input",
    y_label: str = "Output",
    source: str = "synthetic-scatter",
) -> tuple[bytes, dict]:
    """Render a clean, marker-only scatter chart with explicit ground truth."""
    series_values = values_by_series or {
        "North": (1, 3, 2, 5, 4),
        "South": (2, 4, 5, 3, 6),
    }
    if any(len(values) != len(x_values) for values in series_values.values()):
        raise ValueError("every scatter series must match x_values length")

    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")
    figure, axis = plt.subplots(figsize=(6, 4), dpi=120)
    for index, (label, values) in enumerate(series_values.items()):
        axis.scatter(
            list(x_values),
            [float(value) for value in values],
            color=colors[index % len(colors)],
            s=64,
            label=label,
        )
    axis.set_title(title)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.set_xlim(min(x_values) - 0.25, max(x_values) + 0.25)
    all_values = [float(value) for values in series_values.values() for value in values]
    axis.set_ylim(0, max(all_values) + 2)
    axis.set_xticks(list(x_values))
    axis.set_yticks(range(0, int(max(all_values) + 3), 2))
    axis.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)

    output = BytesIO()
    figure.savefig(output, format="png", facecolor="white")
    plt.close(figure)

    dataset = [
        DataPoint(x=float(x), y=float(value), series=label)
        for label, values in series_values.items()
        for x, value in zip(x_values, values)
    ]
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.SCATTER, title=title, source=source),
        axes=Axes(
            x=Axis(
                label=x_label,
                min_value=float(min(x_values)),
                max_value=float(max(x_values)),
            ),
            y=Axis(
                label=y_label,
                min_value=0.0,
                max_value=float(max(all_values) + 2),
            ),
        ),
        dataset=dataset,
    )
    return output.getvalue(), spec.to_dict()


def grouped_bar_chart(
    values_by_series: dict[str, Sequence[float]] | None = None,
    categories: Sequence[str] = ("A", "B", "C"),
    *,
    stacked: bool = False,
) -> tuple[bytes, dict]:
    """Render grouped or stacked bars with legend-defined series truth."""
    series_values = values_by_series or {
        "North": (10, 20, 15),
        "South": (12, 16, 19),
    }
    if any(len(values) != len(categories) for values in series_values.values()):
        raise ValueError("every bar series must match categories length")

    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")
    figure, axis = plt.subplots(figsize=(6, 4), dpi=120)
    positions = list(range(len(categories)))
    width = 0.78 / max(1, len(series_values))
    bottoms = [0.0] * len(categories)
    for index, (label, values) in enumerate(series_values.items()):
        numeric_values = [float(value) for value in values]
        if stacked:
            axis.bar(
                positions,
                numeric_values,
                width=0.68,
                bottom=bottoms,
                color=colors[index % len(colors)],
                label=label,
            )
            bottoms = [bottom + value for bottom, value in zip(bottoms, numeric_values)]
        else:
            offset = (index - (len(series_values) - 1) / 2) * width
            axis.bar(
                [position + offset for position in positions],
                numeric_values,
                width=width * 0.92,
                color=colors[index % len(colors)],
                label=label,
            )
    axis.set_xticks(positions, list(categories))
    maximum = max(bottoms) if stacked else max(float(value) for values in series_values.values() for value in values)
    axis.set_ylim(0, maximum * 1.25)
    axis.legend()
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    output = BytesIO()
    figure.savefig(output, format="png", facecolor="white")
    plt.close(figure)

    dataset = [
        DataPoint(category=str(category), value=float(value), series=label)
        for label, values in series_values.items()
        for category, value in zip(categories, values)
    ]
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.BAR, source="synthetic-bars"),
        axes=Axes(x=Axis(label="Category", categories=list(categories)), y=Axis(label="Value")),
        dataset=dataset,
    )
    return output.getvalue(), spec.to_dict()


def pie_chart(
    values: Sequence[float] = (35, 25, 20, 20),
    labels: Sequence[str] = ("Alpha", "Beta", "Gamma", "Delta"),
    *,
    title: str = "Share",
    source: str = "synthetic-pie",
    show_labels: bool = True,
) -> tuple[bytes, dict]:
    """Render a clean non-donut pie chart with optional percentage labels."""
    if len(values) != len(labels) or not values or any(float(value) <= 0 for value in values):
        raise ValueError("values and labels must have the same non-zero positive length")
    numeric_values = [float(value) for value in values]
    label_values = [str(label) for label in labels]
    figure, axis = plt.subplots(figsize=(6, 4), dpi=120)
    pie_result = axis.pie(
        numeric_values,
        startangle=90,
        counterclock=False,
        colors=("#4c78a8", "#f58518", "#e45756", "#72b7b2"),
        labels=None,
        autopct="%1.0f%%" if show_labels else None,
        pctdistance=0.68,
    )
    wedges = pie_result[0]
    axis.set_title(title)
    axis.legend(wedges, label_values, loc="center left", bbox_to_anchor=(1.0, 0.5))
    axis.set_aspect("equal")
    output = BytesIO()
    figure.savefig(output, format="png", facecolor="white", bbox_inches="tight")
    plt.close(figure)
    total = sum(numeric_values)
    spec = ChartSpec(
        metadata=ChartMetadata(chart_type=ChartType.PIE, title=title, source=source),
        dataset=[
            DataPoint(category=label, value=value / total)
            for label, value in zip(label_values, numeric_values)
        ],
    )
    return output.getvalue(), spec.to_dict()
