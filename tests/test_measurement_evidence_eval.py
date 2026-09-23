from __future__ import annotations

from pathlib import Path

from chartagent.tools.chart.observation.bars import measure_bars
from chartagent.tools.chart.observation.dashboard import decompose_chart_image
from chartagent.tools.chart.observation.pie import extract_pie_slices
from chartagent.tools.chart.observation.segmentation import DeterministicPanelSegmenter


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_crops_are_measured_independently(tmp_path):
    dashboard = PROJECT_ROOT / "photo" / "dashboard_text_two_bars_pie.png"
    regions = [
        {
            "proposal_id": "summary",
            "name": "Quarterly Business Summary",
            "role": "text_block",
            "bbox_norm": [0.012, 0.040, 0.976, 0.237],
        },
        {
            "proposal_id": "revenue",
            "name": "Revenue by Region",
            "role": "chart",
            "chart_type": "bar",
            "bbox_norm": [0.013, 0.302, 0.348, 0.657],
        },
        {
            "proposal_id": "orders",
            "name": "Monthly Orders",
            "role": "chart",
            "chart_type": "bar",
            "bbox_norm": [0.371, 0.302, 0.320, 0.656],
        },
        {
            "proposal_id": "segments",
            "name": "Customer Segments",
            "role": "chart",
            "chart_type": "pie",
            "bbox_norm": [0.703, 0.303, 0.285, 0.655],
        },
    ]
    decomposition = decompose_chart_image(
        str(dashboard),
        regions=regions,
        segmenter=DeterministicPanelSegmenter(),
    )
    crops = {
        image.metadata["panel_id"]: image
        for image in decomposition.images
        if image.metadata.get("kind") == "dashboard_panel_crop"
    }
    chart_panels = [
        panel for panel in decomposition.data["panels"]
        if panel["chart_type"] in {"bar", "pie"}
    ]

    assert len(crops) == 4
    assert len(chart_panels) == 3
    for panel in chart_panels:
        crop_path = tmp_path / f"{panel['id']}.png"
        crop_path.write_bytes(crops[panel["id"]].content)
        result = (
            measure_bars(str(crop_path))
            if panel["chart_type"] == "bar"
            else extract_pie_slices(str(crop_path))
        )
        assert result.data["image_size"] == panel["crop"]["size_px"]
        if panel["chart_type"] == "bar":
            assert result.data["bars"]
        else:
            assert "plot_region" in result.data
            assert isinstance(result.data["warnings"], list)
