from __future__ import annotations

import json

from PIL import Image

from chartagent.attachments import AttachmentRegistry
from chartagent.memory.sqlite import SQLiteAgentMemory
from chartagent.tools.chart import register_chart_tools
from chartagent.tools.core import ToolRegistry, dispatch_observation
from tests.test_dashboard_decomposition import COMPLEX_IMAGE, REGIONS


def _dispatch(registry: ToolRegistry, name: str, payload: dict) -> dict:
    result = dispatch_observation(registry, name, json.dumps(payload, ensure_ascii=False))
    return json.loads(result.content)


def test_decomposition_persists_and_reuses_panel_handoffs(tmp_path):
    memory = SQLiteAgentMemory("panel-reuse", database=tmp_path / "sessions.db")
    try:
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
            panel_store=memory,
        )
        item = attachments.register(str(COMPLEX_IMAGE))
        registry = ToolRegistry()
        register_chart_tools(registry, attachments=attachments)

        first = _dispatch(registry, "decompose_chart_image", {"attachment_id": item.id, "regions": REGIONS})
        first_panels = first["data"]["panels"]
        stored = memory.list_panel_handoffs(item.id)
        assert len(stored) == len(first_panels)
        assert all(panel["id"].startswith("panel_") for panel in first_panels)

        second = _dispatch(registry, "decompose_chart_image", {"attachment_id": item.id, "regions": REGIONS})
        assert second["data"]["reuse"] is True
        assert [panel["id"] for panel in second["data"]["panels"]] == [item.panel_id for item in stored]
        assert "decomposition was not repeated" in second["warnings"][0]
    finally:
        memory.close()


def test_panel_scoped_ocr_returns_local_and_source_scope(tmp_path):
    memory = SQLiteAgentMemory("panel-ocr", database=tmp_path / "sessions.db")
    try:
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
            panel_store=memory,
        )
        item = attachments.register(str(COMPLEX_IMAGE))
        registry = ToolRegistry()
        register_chart_tools(registry, attachments=attachments)
        decomposition = _dispatch(registry, "decompose_chart_image", {"attachment_id": item.id, "regions": REGIONS})
        panel_id = decomposition["data"]["panels"][1]["id"]
        observed = _dispatch(registry, "extract_text", {"attachment_id": item.id, "panel_id": panel_id})
        scope = observed["evidence"]["scope"]
        assert scope["panel_id"] == panel_id
        assert scope["local_image_size"][0] < scope["source_image_size"][0]
        assert all("source_bbox" in snippet for snippet in observed["data"])
    finally:
        memory.close()


def test_panel_scoped_bar_measurement_uses_local_image(tmp_path):
    memory = SQLiteAgentMemory("panel-bars", database=tmp_path / "sessions.db")
    try:
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
            panel_store=memory,
        )
        item = attachments.register(str(COMPLEX_IMAGE))
        registry = ToolRegistry()
        register_chart_tools(registry, attachments=attachments)
        decomposition = _dispatch(registry, "decompose_chart_image", {"attachment_id": item.id, "regions": REGIONS})
        panel_id = decomposition["data"]["panels"][1]["id"]
        observed = _dispatch(registry, "measure_bars", {"attachment_id": item.id, "panel_id": panel_id})
        assert observed["data"]["bars"]
        scope = observed["data"]["scope"]
        assert scope["local_image_size"][0] < scope["source_image_size"][0]
        assert observed["data"]["bars"][0]["geometry"].get("source_bbox_px")
    finally:
        memory.close()


def test_panel_scoped_targeted_measurement_preserves_source_mapping(tmp_path):
    memory = SQLiteAgentMemory("panel-target", database=tmp_path / "sessions.db")
    try:
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
            panel_store=memory,
        )
        item = attachments.register(str(COMPLEX_IMAGE))
        registry = ToolRegistry()
        register_chart_tools(registry, attachments=attachments)
        decomposition = _dispatch(registry, "decompose_chart_image", {"attachment_id": item.id, "regions": REGIONS})
        panel_id = decomposition["data"]["panels"][1]["id"]
        panel = memory.get_panel_handoff(panel_id, attachment_id=item.id)
        assert panel is not None
        with Image.open(item.canonical_path) as image:
            source_size = [image.width, image.height]
        left, top, width, height = panel.analysis_scope
        target = {
            "target_id": "bars-focus",
            "panel_id": panel_id,
            "parent_attempt_id": "matt_parent",
            "region_kind": "bars",
            "fields": ["bars", "baseline"],
            "bbox_source_px": [left + 4, top + 4, max(1, width - 8), max(1, height - 8)],
            "source_image_size": source_size,
            "reason": "复查当前柱状图 panel",
        }
        observed = dispatch_observation(
            registry,
            "measure_bars",
            json.dumps({"attachment_id": item.id, "panel_id": panel_id, "measurement_target": target}, ensure_ascii=False),
            source_run_id="run_target",
            source_panel_id=panel_id,
        )
        payload = json.loads(observed.content)
        resolved = payload["data"]["measurement_target"]
        assert resolved["bbox_source_px"] == target["bbox_source_px"]
        assert resolved["bbox_px"][0] == 4
        assert resolved["local_to_source"]["origin_px"] == [left, top]
        assert payload["data"]["measurement"]["target"]["source_image_size"] == source_size
        assert payload["data"]["focus"]["requested"] is True

        invalid = dict(target)
        invalid["panel_id"] = "panel_other"
        rejected = _dispatch(
            registry,
            "measure_bars",
            {"attachment_id": item.id, "panel_id": panel_id, "measurement_target": invalid},
        )
        assert "measurement target routing failed" in rejected["error"]
        assert rejected["measurement_target_error"]["code"] == "measurement_target_invalid"
    finally:
        memory.close()
