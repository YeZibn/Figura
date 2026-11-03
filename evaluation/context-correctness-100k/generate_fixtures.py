"""Generate deterministic, labeled dashboard fixtures for the 100k pilot."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent


def analysis_dashboard() -> None:
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    revenue = {
        "North": [42, 47, 53, 61],
        "South": [36, 44, 49, 58],
        "Central": [31, 39, 45, 50],
    }
    orders = [120, 132, 128, 145, 151, 167, 164, 178, 191, 187, 205, 219]
    conversion = [3.2, 3.5, 3.3, 3.8, 4.0, 4.2, 4.1, 4.4, 4.6, 4.5, 4.8, 5.1]
    returns = np.array([[9, 7, 5, 11], [6, 8, 4, 9], [3, 4, 6, 5]])

    figure, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    axis = axes[0, 0]
    positions = np.arange(len(quarters))
    width = 0.24
    for index, (name, values) in enumerate(revenue.items()):
        bars = axis.bar(positions + (index - 1) * width, values, width, label=name)
        axis.bar_label(bars, padding=2, fontsize=8)
    axis.set_title("Quarterly Revenue by Region")
    axis.set_ylabel("Revenue (M USD)")
    axis.set_xticks(positions, quarters)
    axis.legend(frameon=False, ncols=3, fontsize=8)

    axis = axes[0, 1]
    axis.plot(months, orders, marker="o", color="#2878B5")
    for x, y in zip(months, orders):
        axis.annotate(str(y), (x, y), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7)
    axis.set_title("Monthly Orders")
    axis.set_ylabel("Orders (count)")
    axis.tick_params(axis="x", labelrotation=35)

    axis = axes[1, 0]
    axis.plot(months, conversion, marker="o", color="#D95F02")
    for x, y in zip(months, conversion):
        axis.annotate(f"{y:.1f}", (x, y), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7)
    axis.set_title("Monthly Conversion Rate")
    axis.set_ylabel("Conversion (%)")
    axis.tick_params(axis="x", labelrotation=35)

    axis = axes[1, 1]
    image = axis.imshow(returns, cmap="YlGnBu")
    axis.set_title("Returns by Product and Region")
    axis.set_xticks(range(4), ["North", "South", "Central", "Online"])
    axis.set_yticks(range(3), ["Electronics", "Home", "Sports"])
    for row in range(returns.shape[0]):
        for column in range(returns.shape[1]):
            axis.text(column, row, str(returns[row, column]), ha="center", va="center", color="black", fontsize=10)
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, label="Returned units")

    figure.suptitle("Regional Sales and Operations Dashboard, 2025", fontsize=15)
    output = ROOT / "01-chart-analysis" / "input" / "bar_line_dashboard.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180, facecolor="white")
    plt.close(figure)


def modification_dashboard() -> None:
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    revenue = {
        "North": [34, 39, 43, 50],
        "South": [27, 32, 36, 41],
        "Central": [22, 26, 31, 35],
    }
    orders = [82, 90, 87, 95, 101, 108, 105, 115, 123, 119, 130, 138]
    conversion = [2.4, 2.6, 2.5, 2.8, 3.0, 3.1, 3.0, 3.3, 3.4, 3.2, 3.6, 3.8]

    figure, axes = plt.subplots(3, 1, figsize=(13, 12), constrained_layout=True)
    positions = np.arange(len(quarters))
    width = 0.24
    for index, (name, values) in enumerate(revenue.items()):
        bars = axes[0].bar(positions + (index - 1) * width, values, width, label=name)
        axes[0].bar_label(bars, padding=2, fontsize=8)
    axes[0].set_title("Quarterly Revenue by Region")
    axes[0].set_ylabel("Revenue (M USD)")
    axes[0].set_xticks(positions, quarters)
    axes[0].legend(frameon=False, ncols=3, fontsize=8)

    for axis, values, title, label, color in (
        (axes[1], orders, "Monthly Orders", "Orders", "#2878B5"),
        (axes[2], conversion, "Monthly Conversion Rate", "Conversion (%)", "#D95F02"),
    ):
        axis.plot(months, values, marker="o", color=color)
        for x, y in zip(months, values):
            text = f"{y:.1f}" if isinstance(y, float) else str(y)
            axis.annotate(text, (x, y), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7)
        axis.set_title(title)
        axis.set_ylabel(label)
        axis.tick_params(axis="x", labelrotation=35)

    figure.suptitle("Regional Sales and Operations Dashboard, 2025", fontsize=15)
    output = ROOT / "03-chart-modification" / "input" / "quarterly-regional-sales.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180, facecolor="white")
    plt.close(figure)


if __name__ == "__main__":
    analysis_dashboard()
    modification_dashboard()
