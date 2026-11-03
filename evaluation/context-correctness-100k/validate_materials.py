"""Validate the frozen 100k pilot inputs before a real Provider run."""
from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from pathlib import Path

from PIL import Image

from figura.charts.chartspec.models import ChartSpecData
from figura.charts.chartfigure import parse_chart_figure
from figura.charts.chartfigure.rendering import render_chart_figure_image


ROOT = Path(__file__).resolve().parent
EXPECTED_TURNS = {
    "01-chart-analysis": 20,
    "02-chart-construction": 30,
    "03-chart-modification": 34,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_turns() -> None:
    for task_dir in sorted(path for path in ROOT.iterdir() if path.is_dir() and path.name[:2].isdigit()):
        source = (task_dir / "conversation.md").read_text(encoding="utf-8")
        turns = [int(number) for number in re.findall(r"^## 第 (\d+) 轮：", source, re.MULTILINE)]
        expected_count = EXPECTED_TURNS.get(task_dir.name)
        if expected_count is None or turns != list(range(1, expected_count + 1)):
            raise ValueError(
                f"{task_dir.name}: expected {expected_count} consecutive turns; found {turns}"
            )
        print(f"{task_dir.name}: {len(turns)} consecutive turns")


def validate_construction_fixture() -> None:
    path = ROOT / "02-chart-construction" / "input" / "dataset.json"
    source = json.loads(path.read_text(encoding="utf-8"))
    charts = []
    positions = 0
    nulls = 0
    for panel in source["panels"]:
        spec = {
            "schema_version": 2,
            "metadata": {
                "chart_type": panel["chart_type"],
                "title": panel["title"],
                "source": panel["source"],
                "note": panel["note"],
            },
            "coordinate_system": panel["coordinate_system"],
            "dataset": panel["dataset"],
        }
        ChartSpecData.from_dict(spec)
        charts.append({"chart_id": panel["chart_id"], "chart_spec": spec})
        data = panel["dataset"]
        if panel["chart_type"] == "bar":
            positions += sum(len(series["values"]) for series in data["series"])
        elif panel["chart_type"] == "line":
            positions += sum(len(series["points"]) for series in data["series"])
            nulls += sum(point["y"] is None for series in data["series"] for point in series["points"])
        elif panel["chart_type"] == "heatmap":
            positions += sum(len(row) for row in data["values"])
            nulls += sum(value is None for row in data["values"] for value in row)
        elif panel["chart_type"] == "scatter":
            positions += sum(len(series["points"]) for series in data["series"])

    figure = parse_chart_figure({
        "schema_version": 2,
        "title": source["dataset_id"],
        "layout": {"columns": 2},
        "charts": charts,
    })
    if len(figure.charts) != 4 or positions != 88 or nulls != 2:
        raise ValueError(f"unexpected fixture counts: charts={len(figure.charts)}, positions={positions}, nulls={nulls}")
    print(f"construction fixture: ChartSpec v2 valid; {positions} data positions; {nulls} explicit nulls")
    for chart in charts:
        single = parse_chart_figure({
            "schema_version": 2, "title": chart["chart_id"],
            "layout": {"columns": 1}, "charts": [chart],
        })
        try:
            render_chart_figure_image(single)
        except ValueError as error:
            raise ValueError(f"single-panel render failed for {chart['chart_id']}: {error}") from error
    rendered, width, height = render_chart_figure_image(figure)
    with Image.open(BytesIO(rendered)) as image:
        image.verify()
    print(f"construction fixture render: valid PNG {width}x{height}; {len(rendered)} bytes")


def validate_images() -> None:
    for relative in (
        "01-chart-analysis/input/bar_line_dashboard.png",
        "03-chart-modification/input/quarterly-regional-sales.png",
    ):
        path = ROOT / relative
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            print(f"{relative}: {image.width}x{image.height}, sha256={sha256(path)}")


if __name__ == "__main__":
    validate_turns()
    validate_construction_fixture()
    validate_images()
