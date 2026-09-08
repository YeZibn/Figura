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
