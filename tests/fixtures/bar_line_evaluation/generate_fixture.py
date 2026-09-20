"""Generate the deterministic bar-and-line real-evaluation fixture."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "bar_line_dashboard.png"


def _add_card(fig: plt.Figure, bounds: tuple[float, float, float, float]) -> None:
    x, y, width, height = bounds
    card = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.008,rounding_size=0.012",
        transform=fig.transFigure,
        facecolor="white",
        edgecolor="#D4DCE5",
        linewidth=1.2,
        zorder=0,
    )
    fig.add_artist(card)


def generate() -> Path:
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor="#F3F6F9")

    left_card = (0.03, 0.10, 0.45, 0.80)
    right_card = (0.52, 0.10, 0.45, 0.80)
    _add_card(fig, left_card)
    _add_card(fig, right_card)

    fig.text(
        0.5,
        0.955,
        "Quarterly Sales and Monthly Orders",
        ha="center",
        va="center",
        fontsize=24,
        fontweight="bold",
        color="#17365D",
    )
    fig.text(
        left_card[0] + 0.025,
        left_card[1] + left_card[3] - 0.055,
        "Quarterly Sales",
        ha="left",
        va="center",
        fontsize=18,
        fontweight="bold",
        color="#17365D",
    )
    fig.text(
        right_card[0] + 0.025,
        right_card[1] + right_card[3] - 0.055,
        "Monthly Orders",
        ha="left",
        va="center",
        fontsize=18,
        fontweight="bold",
        color="#17365D",
    )

    bar_ax = fig.add_axes((0.085, 0.245, 0.34, 0.54), facecolor="white")
    categories = ["Q1", "Q2", "Q3", "Q4"]
    target = [40, 55, 48, 62]
    actual = [36, 51, 45, 59]
    positions = list(range(len(categories)))
    width = 0.34
    bar_ax.bar(
        [position - width / 2 for position in positions],
        target,
        width=width,
        label="Target",
        color="#2F80ED",
        edgecolor="#2366BD",
        linewidth=0.6,
    )
    bar_ax.bar(
        [position + width / 2 for position in positions],
        actual,
        width=width,
        label="Actual",
        color="#F2994A",
        edgecolor="#C8752D",
        linewidth=0.6,
    )
    bar_ax.set_xticks(positions, categories)
    bar_ax.set_xlabel("Quarter", labelpad=8)
    bar_ax.set_ylabel("Revenue (million USD)", labelpad=8)
    bar_ax.set_ylim(0, 70)
    bar_ax.set_yticks(range(0, 71, 10))
    bar_ax.grid(axis="y", color="#DCE3EA", linestyle="--", linewidth=0.8)
    bar_ax.set_axisbelow(True)
    bar_ax.legend(loc="upper left", frameon=False, ncols=2, bbox_to_anchor=(0, 1.08))

    line_ax = fig.add_axes((0.575, 0.245, 0.34, 0.54), facecolor="white")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"]
    orders = [22, 28, 25, 36, 44, 41, 53]
    line_ax.plot(
        months,
        orders,
        label="Orders",
        color="#27AE60",
        marker="o",
        markersize=7,
        linewidth=2.8,
    )
    line_ax.set_xlabel("Month", labelpad=8)
    line_ax.set_ylabel("Number of Orders", labelpad=8)
    line_ax.set_ylim(0, 60)
    line_ax.set_yticks(range(0, 61, 10))
    line_ax.grid(axis="both", color="#DCE3EA", linestyle="--", linewidth=0.8)
    line_ax.set_axisbelow(True)
    line_ax.legend(loc="upper left", frameon=False, bbox_to_anchor=(0, 1.08))

    for axis in (bar_ax, line_ax):
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#425466")
        axis.spines["bottom"].set_color("#425466")
        axis.tick_params(colors="#263746", labelsize=11)
        axis.xaxis.label.set_color("#263746")
        axis.yaxis.label.set_color("#263746")

    fig.savefig(OUTPUT, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return OUTPUT


if __name__ == "__main__":
    print(generate())
