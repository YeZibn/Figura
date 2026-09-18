"""Tests for VLM-guided dashboard decomposition and named crops."""

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from chartagent.agent.loop import Agent, _attach_visual_observation_refs
from chartagent.attachments import AttachmentRegistry
from chartagent.tools import ToolResult, ToolRegistry, dispatch_observation, get_tool_presentation
from chartagent.tools.chart import register_chart_tools
from chartagent.tools.chart.observation.dashboard import decompose_chart_image
from chartagent.tools.chart.observation.bars import measure_bars
from chartagent.tools.chart.observation.pie import extract_pie_slices
from chartagent.tools.chart.observation.segmentation import (
    DeterministicPanelSegmenter,
    SegmentationResult,
    build_panel_segmenter,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPLEX_IMAGE = PROJECT_ROOT / "photo" / "dashboard_text_two_bars_pie.png"

REGIONS = [
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


class _ProposalSegmenter:
    def segment(self, image, candidate):
        bbox = candidate["bbox_px"]
        return SegmentationResult(
            status="accepted",
            source="sam",
            bbox_px=list(bbox),
            polygon_px=[
                [bbox[0], bbox[1]],
                [bbox[0] + bbox[2] - 1, bbox[1]],
                [bbox[0] + bbox[2] - 1, bbox[1] + bbox[3] - 1],
                [bbox[0], bbox[1] + bbox[3] - 1],
            ],
            confidence=0.94,
        )


def test_dashboard_uses_vlm_regions_and_returns_named_crops():
    result = decompose_chart_image(str(COMPLEX_IMAGE), regions=REGIONS, segmenter=_ProposalSegmenter())

    assert isinstance(result, ToolResult)
    assert result.data["status"] == "accepted"
    assert [panel["name"] for panel in result.data["panels"]] == [
        "Quarterly Business Summary",
        "Revenue by Region",
        "Monthly Orders",
        "Customer Segments",
    ]
    assert [panel["chart_type"] for panel in result.data["panels"]] == [
        "unknown",
        "bar",
        "bar",
        "pie",
    ]
    assert "ocr" not in result.data
    assert "text_ids" not in json.dumps(result.data)
    assert len(result.data["panels"]) == 4
    assert len(result.images) == 5
    assert all(panel["crop"]["status"] == "available" for panel in result.data["panels"])
    assert all(panel["crop"]["resource_ref"] is None for panel in result.data["panels"])
    assert all(image.metadata.get("kind") == "dashboard_panel_crop" for image in result.images[1:])


def test_dashboard_crop_frames_preserve_source_coordinates_and_layout_context():
    result = decompose_chart_image(str(COMPLEX_IMAGE), regions=REGIONS, segmenter=_ProposalSegmenter())
    image_size = result.data["image_size"]

    assert result.data["segmentation"]["crop_count"] == 4
    for panel in result.data["panels"]:
        bbox = panel["bbox_px"]
        assert 0 <= bbox[0] < image_size[0]
        assert 0 <= bbox[1] < image_size[1]
        assert bbox[0] + bbox[2] <= image_size[0]
        assert bbox[1] + bbox[3] <= image_size[1]
        context = panel["layout_context"]
        assert context["analysis_scope"]["bbox_px"] == bbox
        assert context["measurement_frame"] is None
        assert context["validation"]["accepted_for_measurement"] is False
        assert context["validation"]["accepted_for_analysis"] is True
        assert panel["analysis_transform"]["source_origin_px"] == bbox[:2]
        assert panel["crop"]["name"].startswith(panel["id"] + "_")

    assert result.data["panels"][1]["layout_context"]["coordinate_system"] == "cartesian_2d"
    assert result.data["panels"][2]["layout_context"]["coordinate_system"] == "cartesian_2d"
    assert result.data["panels"][3]["layout_context"]["coordinate_system"] == "polar_2d"

    with Image.open(BytesIO(result.images[0].content)) as overlay:
        assert list(overlay.size) == image_size
    with Image.open(BytesIO(result.images[1].content)) as crop:
        assert crop.width == result.data["panels"][0]["crop"]["size_px"][0]
        assert crop.height == result.data["panels"][0]["crop"]["size_px"][1]


def test_missing_vlm_regions_returns_one_advisory_region_without_ocr_discovery():
    result = decompose_chart_image(str(COMPLEX_IMAGE), segmenter=DeterministicPanelSegmenter())

    assert isinstance(result, ToolResult)
    assert len(result.data["panels"]) == 1
    assert result.data["panels"][0]["proposal"]["proposal_id"] == "whole_image"
    assert result.data["panels"][0]["status"] == "partial"
    assert any("VLM region proposals" in warning for warning in result.data["warnings"])
    assert "ocr" not in result.data


def test_invalid_and_overlapping_proposals_are_bounded():
    result = decompose_chart_image(
        str(COMPLEX_IMAGE),
        regions=[
            {"name": "left", "bbox_norm": [0.0, 0.0, 0.7, 0.7]},
            {"name": "overlap", "bbox_norm": [0.02, 0.02, 0.68, 0.68]},
            {"name": "invalid", "bbox_norm": [0.9, 0.9, 0.3, 0.3]},
        ],
        segmenter=DeterministicPanelSegmenter(),
    )

    assert len(result.data["panels"]) == 2
    assert any("materially" in warning for warning in result.data["warnings"])
    assert any("invalid normalized bbox" in warning for warning in result.data["warnings"])


def test_duplicate_display_names_receive_distinct_crop_slugs():
    result = decompose_chart_image(
        str(COMPLEX_IMAGE),
        regions=[
            {"name": "重复图表", "role": "chart", "chart_type": "bar", "bbox_norm": [0.02, 0.30, 0.30, 0.40]},
            {"name": "重复图表", "role": "chart", "chart_type": "bar", "bbox_norm": [0.40, 0.30, 0.30, 0.40]},
        ],
        segmenter=DeterministicPanelSegmenter(),
    )

    panels = result.data["panels"]
    assert len(panels) == 2
    assert panels[0]["slug"] != panels[1]["slug"]
    assert panels[0]["crop"]["name"] != panels[1]["crop"]["name"]
    assert any("unique slug" in warning for warning in result.data["warnings"])


class _InvalidSegmenter:
    def segment(self, image, candidate):
        return SegmentationResult(
            status="accepted",
            source="sam",
            bbox_px=[-10, -10, 2, 2],
            polygon_px=[],
            confidence=0.99,
        )


def test_invalid_sam_result_keeps_vlm_panel_as_partial_fallback():
    result = decompose_chart_image(
        str(COMPLEX_IMAGE),
        regions=REGIONS,
        segmenter=_InvalidSegmenter(),
    )

    assert isinstance(result, ToolResult)
    assert result.data["panels"]
    assert result.data["status"] == "partial"
    assert all(panel["status"] == "partial" for panel in result.data["panels"])
    assert all(panel["segmentation"]["source"] == "deterministic_fallback" for panel in result.data["panels"])
    assert all(panel["crop"]["status"] == "available" for panel in result.data["panels"])


def test_explicit_sam_mode_degrades_without_optional_backend(monkeypatch):
    class _UnavailableSam:
        def segment(self, image, candidate):
            return SegmentationResult(
                status="partial",
                source="none",
                bbox_px=None,
                polygon_px=[],
                confidence=0.0,
                warnings=("SAM refinement unavailable: RuntimeError",),
            )

    monkeypatch.setattr(
        "chartagent.tools.chart.observation.dashboard.build_panel_segmenter",
        lambda _mode: _UnavailableSam(),
    )
    result = decompose_chart_image(
        str(COMPLEX_IMAGE),
        regions=REGIONS,
        segmentation_mode="sam",
    )

    assert isinstance(result, ToolResult)
    assert result.data["panels"]
    assert result.data["status"] == "partial"
    assert any("SAM refinement unavailable" in warning for warning in result.data["warnings"])
    assert all(panel["segmentation"]["source"] == "deterministic_fallback" for panel in result.data["panels"])


def test_auto_mode_does_not_activate_sam_from_environment(monkeypatch):
    monkeypatch.setenv("FIGURA_SAM_CHECKPOINT", "/tmp/sam-checkpoint.pth")

    segmenter = build_panel_segmenter("auto")

    assert isinstance(segmenter, DeterministicPanelSegmenter)


def test_authorized_decomposition_contract_accepts_vlm_regions_and_hides_paths():
    attachments = AttachmentRegistry(session_id="dashboard-test")
    item = attachments.register(str(COMPLEX_IMAGE))
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)

    public = registry.get("decompose_chart_image")
    assert public is not None
    assert set(public.parameters["properties"]) == {
        "attachment_id",
        "regions",
        "segmentation_mode",
        "max_panels",
        "crop_padding",
    }
    assert "image_path" not in json.dumps(public.parameters)
    presentation = get_tool_presentation("decompose_chart_image", tool=public)
    assert presentation.display_name == "拆解复杂图表图片"
    assert presentation.english_name == "decompose_chart_image"
    assert presentation.group == "chart-observation"
    dispatched = dispatch_observation(
        registry,
        "decompose_chart_image",
        json.dumps({"attachment_id": item.id, "regions": REGIONS}, ensure_ascii=False),
    )
    payload = json.loads(dispatched.content)
    assert len(payload["data"]["panels"]) == 4
    assert len(dispatched.images) == 5
    assert str(COMPLEX_IMAGE) not in dispatched.content


def test_managed_crop_references_are_attached_to_panel_records():
    attachments = AttachmentRegistry(session_id="dashboard-ref-test")
    item = attachments.register(str(COMPLEX_IMAGE))
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    dispatched = dispatch_observation(
        registry,
        "decompose_chart_image",
        json.dumps({"attachment_id": item.id, "regions": REGIONS}, ensure_ascii=False),
    )
    references = [
        {"observationId": "obs_overlay", "resourceKey": "overlay"},
        *[
            {"observationId": f"obs_{index}", "resourceKey": f"panel_{index}_crop"}
            for index in range(1, 5)
        ],
    ]
    attached = _attach_visual_observation_refs(dispatched, references)
    payload = json.loads(attached.content)
    crops = [panel["crop"] for panel in payload["data"]["panels"]]
    assert [crop["resource_ref"]["observationId"] for crop in crops] == [
        "obs_1",
        "obs_2",
        "obs_3",
        "obs_4",
    ]
    assert all(crop["status"] == "persisted" for crop in crops)


def test_panel_context_can_be_handed_to_existing_chart_sensor():
    result = decompose_chart_image(str(COMPLEX_IMAGE), regions=REGIONS, segmenter=_ProposalSegmenter())
    chart_panels = [panel for panel in result.data["panels"] if panel["role"] == "chart"]

    assert len(chart_panels) == 3
    assert all(panel["layout_context"]["validation"]["accepted_for_analysis"] for panel in chart_panels)
    assert all(panel["layout_context"]["panel"]["id"] == panel["id"] for panel in chart_panels)

    first_bar_result = measure_bars(str(COMPLEX_IMAGE), layout_context=chart_panels[0]["layout_context"])
    second_bar_result = measure_bars(str(COMPLEX_IMAGE), layout_context=chart_panels[1]["layout_context"])
    pie_result = extract_pie_slices(str(COMPLEX_IMAGE), layout_context=chart_panels[-1]["layout_context"])
    assert first_bar_result.data["bars"]
    assert second_bar_result.data["bars"]
    assert pie_result.data["plot_region"]["bbox_px"][0] >= chart_panels[-1]["bbox_px"][0]
    assert "donut" in " ".join(pie_result.data["warnings"])
    for sensor_result in (first_bar_result, second_bar_result, pie_result):
        sensor_data = sensor_result.data if isinstance(sensor_result, ToolResult) else sensor_result
        assert isinstance(sensor_data, dict)
        sensor_context = sensor_data.get("layout_context") or sensor_data["evidence"]["layout_context"]
        assert sensor_context["analysis_scope"]["bbox_px"] in [
            panel["bbox_px"] for panel in chart_panels
        ]
        assert sensor_context["measurement_frame"] is None


def test_panel_id_selects_the_matching_scoped_layout_context():
    contexts = {
        "att_dashboard::panel_2": {
            "coordinate_system": "cartesian_2d",
            "measurement_frame": {"bbox_px": [100, 200, 300, 240]},
        },
        "att_dashboard::panel_4": {
            "coordinate_system": "polar_2d",
            "measurement_frame": {"bbox_px": [900, 200, 300, 300]},
        },
    }
    arguments = Agent._layout_arguments(
        "extract_pie_slices",
        json.dumps({"attachment_id": "att_dashboard", "panel_id": "panel_4"}),
        contexts,
    )
    parsed = json.loads(arguments)
    assert parsed["layout_context"]["coordinate_system"] == "polar_2d"
    assert parsed["layout_context"]["measurement_frame"]["bbox_px"] == [900, 200, 300, 300]


def test_unresolved_panel_route_is_bounded_before_sensor_dispatch():
    error = Agent._panel_routing_error(
        "measure_bars",
        json.dumps({"attachment_id": "att_dashboard", "panel_id": "missing_panel"}),
        {
            "att_dashboard::panel_2": {
                "analysis_scope": {"bbox_px": [100, 200, 300, 240]},
            }
        },
    )

    assert error is not None
    assert "not registered" in error


def test_resolved_panel_route_requires_an_analysis_scope():
    error = Agent._panel_routing_error(
        "extract_pie_slices",
        json.dumps({"attachment_id": "att_dashboard", "panel_id": "panel_4"}),
        {"att_dashboard::panel_4": {"measurement_frame": {"bbox_px": [1, 2, 3, 4]}}},
    )

    assert error is not None
    assert "no usable analysis scope" in error


def test_decomposition_contexts_are_cached_per_attachment_and_panel():
    contexts = {}
    Agent._remember_layout_context(
        json.dumps(
            {
                "data": {
                    "kind": "dashboard_decomposition",
                    "panels": [
                        {
                            "id": "panel_4",
                            "name": "Customer Segments",
                            "chart_type": "pie",
                            "layout_context": {
                                "coordinate_system": "polar_2d",
                                "measurement_frame": {"bbox_px": [10, 20, 30, 40]},
                            },
                        }
                    ]
                }
            }
        ),
        json.dumps({"attachment_id": "att_dashboard"}),
        contexts,
    )
    assert contexts["att_dashboard::panel_4"]["panel"]["name"] == "Customer Segments"
