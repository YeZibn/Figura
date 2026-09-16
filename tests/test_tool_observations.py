"""Tests for enriched tool results and bounded generated-image handling."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from chartagent import Tool, ToolRegistry, dispatch
from chartagent.tools import (
    DEFAULT_MAX_GENERATED_IMAGE_BYTES,
    DEFAULT_MAX_GENERATED_IMAGES,
    DispatchedObservation,
    GeneratedImage,
    ToolResult,
    dispatch_observation,
)


def _registry(result) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("observe", "return evidence", {"type": "object"}, lambda: result))
    return registry


def test_generated_image_is_frozen_and_uses_bytes():
    image = GeneratedImage(b"png", "image/png", "detected regions")

    assert isinstance(image.content, bytes)
    with pytest.raises(FrozenInstanceError):
        image.content = b"changed"  # type: ignore[misc]


def test_tool_result_normalizes_collections_to_tuples():
    image = GeneratedImage(b"png", "image/png", "overlay")
    result = ToolResult(data={"ok": True}, images=[image], warnings=["low contrast"])

    assert result.images == (image,)
    assert result.warnings == ("low contrast",)


def test_enriched_dispatch_separates_json_and_image_bytes():
    image = GeneratedImage(b"valid-png-payload", "image/png", "OCR boxes")

    observation = dispatch_observation(
        _registry(ToolResult({"count": 2}, [image])), "observe", "{}"
    )

    assert isinstance(observation, DispatchedObservation)
    assert observation.images == (image,)
    payload = json.loads(observation.content)
    assert payload["data"] == {"count": 2}
    assert payload["warnings"] == []
    assert payload["images"] == [
        {"media_type": "image/png", "caption": "OCR boxes", "attached": True}
    ]
    assert "valid-png-payload" not in observation.content


def test_legacy_dispatch_output_is_unchanged():
    registry = _registry({"n": 3})

    observation = dispatch_observation(registry, "observe", "{}")

    assert observation.content == '{"n": 3}'
    assert observation.images == ()
    assert dispatch(registry, "observe", "{}") == '{"n": 3}'


@pytest.mark.parametrize(
    ("image", "warning_text"),
    [
        (GeneratedImage(b"", "image/png", "empty"), "empty"),
        (GeneratedImage(b"x", "image/gif", "gif"), "unsupported"),
        (GeneratedImage(b"x", "image/png", ""), "caption"),
        (GeneratedImage(bytearray(b"x"), "image/png", "mutable"), "bytes"),
        ("/tmp/not-authorized.png", "GeneratedImage"),
    ],
)
def test_invalid_images_become_warnings_without_losing_data(image, warning_text):
    observation = dispatch_observation(
        _registry(ToolResult({"ok": True}, [image])), "observe", "{}"
    )

    payload = json.loads(observation.content)
    assert payload["data"] == {"ok": True}
    assert any(warning_text in warning for warning in payload["warnings"])
    assert payload["images"] == []
    assert observation.images == ()


def test_oversized_image_is_rejected_but_valid_sibling_survives():
    valid = GeneratedImage(b"ok", "image/png", "valid")
    oversized = GeneratedImage(
        b"x" * (DEFAULT_MAX_GENERATED_IMAGE_BYTES + 1), "image/png", "too large"
    )

    observation = dispatch_observation(
        _registry(ToolResult({"ok": True}, [oversized, valid])), "observe", "{}"
    )

    payload = json.loads(observation.content)
    assert observation.images == (valid,)
    assert any("exceeds" in warning for warning in payload["warnings"])
    assert payload["images"][0]["caption"] == "valid"


def test_excess_images_are_rejected_independently():
    images = [
        GeneratedImage(f"image-{index}".encode(), "image/png", f"image {index}")
        for index in range(DEFAULT_MAX_GENERATED_IMAGES + 2)
    ]

    observation = dispatch_observation(
        _registry(ToolResult({"ok": True}, images)), "observe", "{}"
    )

    payload = json.loads(observation.content)
    assert len(observation.images) == DEFAULT_MAX_GENERATED_IMAGES
    assert len(payload["images"]) == DEFAULT_MAX_GENERATED_IMAGES
    assert any("limit" in warning for warning in payload["warnings"])


def test_existing_warning_is_preserved():
    observation = dispatch_observation(
        _registry(ToolResult({"ok": True}, warnings=["low confidence"])),
        "observe",
        "{}",
    )

    assert json.loads(observation.content)["warnings"] == ["low confidence"]


def test_chart_dispatch_adds_attributable_evidence_summary():
    image = GeneratedImage(b"png", "image/png", "bar overlay")
    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {
                "type": "object",
                "properties": {"attachment_id": {"type": "string"}},
                "required": ["attachment_id"],
            },
            lambda attachment_id: ToolResult(
                {
                    "image_size": [120, 80],
                    "frame": {"bbox_px": [10, 10, 100, 60]},
                    "confidence": {"overall": 0.8, "geometry": 0.9},
                },
                [image],
                ["baseline is partial"],
            ),
        )
    )

    observation = dispatch_observation(
        registry,
        "measure_bars",
        '{"attachment_id":"att_chart"}',
    )
    payload = json.loads(observation.content)
    evidence = payload["evidence"]

    assert evidence["evidence_type"] == "geometry"
    assert evidence["source_tool"] == "measure_bars"
    assert evidence["source_attachment_id"] == "att_chart"
    assert evidence["confidence"] == {"overall": 0.8, "geometry": 0.9}
    assert evidence["warnings"] == ["baseline is partial"]
    assert {item["scope"] for item in evidence["source_image_refs"]} >= {"source_image", "frame"}
    assert evidence["visual_observations"] == {"count": 1, "captions": ["bar overlay"]}
    assert "image_path" not in json.dumps(evidence)


def test_evidence_summary_is_bounded_and_json_safe():
    from chartagent.tools import build_evidence_summary

    summary = build_evidence_summary(
        source_tool="extract_text",
        source_attachment_id="att_chart",
        data={"plot_area": {"bbox": [0, 0, 10, 10]}, "confidence": float("inf")},
        warnings=["w" * 1000] * 20,
        images=[GeneratedImage(b"x", "image/png", "caption" * 100)],
    )

    encoded = json.dumps(summary, ensure_ascii=False)
    assert json.loads(encoded) == summary
    assert summary["evidence_type"] == "text"
    assert len(summary["warnings"]) == 12
    assert all(len(item) <= 160 for item in summary["warnings"])
    assert len(summary["visual_observations"]["captions"][0]) <= 160
    assert summary["confidence"] == {}


def test_evidence_summary_preserves_bounded_conflict_candidates():
    from chartagent.tools import build_evidence_summary

    summary = build_evidence_summary(
        source_tool="measure_bars",
        source_attachment_id="att_chart",
        data={
            "evidence": {
                "conflicts": [
                    {
                        "field": "baseline",
                        "sources": ["pixel_geometry", "ocr", "ignored-extra-source"],
                        "message": "baseline candidate disagrees with printed value",
                        "untrusted": {"should": "not leak"},
                    }
                ]
            }
        },
        warnings=[],
        images=[],
    )

    assert summary["conflicts"] == [
        {
            "field": "baseline",
            "sources": ["pixel_geometry", "ocr", "ignored-extra-source"],
            "message": "baseline candidate disagrees with printed value",
        }
    ]
    assert json.loads(json.dumps(summary, ensure_ascii=False)) == summary


def test_unserializable_enriched_data_is_structured_error():
    observation = dispatch_observation(
        _registry(ToolResult(object())), "observe", "{}"
    )

    assert "error" in json.loads(observation.content)
    assert observation.images == ()


def test_tool_exception_is_structured_error():
    def fail():
        raise RuntimeError("broken tool")

    registry = ToolRegistry()
    registry.register(Tool("fail", "fails", {"type": "object"}, fail))

    observation = dispatch_observation(registry, "fail", "{}")

    assert "broken tool" in json.loads(observation.content)["error"]
    assert observation.images == ()
