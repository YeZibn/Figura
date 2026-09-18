"""Offline coverage for named memory and authorized attachments."""

import json
import pytest

from chartagent.attachments import AttachmentRegistry
from chartagent.memory import SQLiteAgentMemory, RunStatus
from chartagent.memory.context import build_context, sanitize_payload
from chartagent.memory.models import Record, Run
from chartagent.tools import ToolRegistry
from chartagent.tools.core.registry import dispatch_observation
from chartagent.agent import Agent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.core.definition import Tool


def test_sqlite_reopens_completed_runs_and_interrupts_active(tmp_path):
    db = tmp_path / "sessions.db"
    memory = SQLiteAgentMemory("demo", database=db)
    completed = memory.begin_run()
    memory.append(completed, "user", {"message": {"role": "user", "content": "first"}, "text": "first"})
    memory.finish(completed, RunStatus.COMPLETED, "final")
    active = memory.begin_run()
    memory.append(active, "user", {"message": {"role": "user", "content": "partial"}, "text": "partial"})
    memory.close()

    reopened = SQLiteAgentMemory("demo", database=db)
    runs = reopened._load_runs()
    assert [run.status for run in runs] == [RunStatus.COMPLETED, RunStatus.INTERRUPTED]
    current = reopened.begin_run()
    context = reopened.context(current, {"role": "system", "content": "sys"})
    assert any(message.get("content") == "first" for message in context)
    assert not any(message.get("content") == "partial" for message in context)


def test_external_run_id_is_persisted_and_rejects_cross_session_collision(tmp_path):
    db = tmp_path / "sessions.db"
    first = SQLiteAgentMemory("first", database=db)
    run = first.begin_run("gateway-run-1")
    assert run.id == "gateway-run-1"
    first.finish(run, RunStatus.COMPLETED, "final")
    first.close()

    reopened = SQLiteAgentMemory("first", database=db, create=False)
    with pytest.raises(ValueError, match="already exists"):
        reopened.begin_run("gateway-run-1")
    reopened.close()

    second = SQLiteAgentMemory("second", database=db)
    with pytest.raises(ValueError, match="another session"):
        second.begin_run("gateway-run-1")
    second.close()


def test_attachment_load_is_validated_and_does_not_expose_path(tmp_path):
    path = tmp_path / "chart.png"
    path.write_bytes(b"stable image")
    registry = AttachmentRegistry(session_id="session")
    item = registry.register(str(path))
    tool_registry = ToolRegistry()
    tool_registry.register(registry.load_tool())
    loaded = dispatch_observation(tool_registry, "load_image", json.dumps({"attachment_id": item.id}))
    assert len(loaded.images) == 1
    assert str(path) not in loaded.content
    path.write_bytes(b"changed image")
    rejected = dispatch_observation(tool_registry, "load_image", json.dumps({"attachment_id": item.id}))
    assert "changed" in rejected.content
    assert not rejected.images


def test_attachment_ids_are_session_scoped(tmp_path):
    path = tmp_path / "chart.png"
    path.write_bytes(b"image")
    first = AttachmentRegistry(session_id="one")
    item = first.register(str(path))
    second = AttachmentRegistry(session_id="two", load=first.get)
    tool_registry = ToolRegistry()
    tool_registry.register(second.load_tool())
    result = dispatch_observation(tool_registry, "load_image", json.dumps({"attachment_id": item.id}))
    assert "authorized" in result.content
    assert not result.images


def test_chart_sensor_uses_authorized_attachment_id(tmp_path):
    from chartagent.tools import ToolRegistry, dispatch_observation
    from chartagent.tools.chart import register_chart_tools
    from tests.chart_fixtures import line_chart
    import json

    image = tmp_path / "line.png"
    image.write_bytes(line_chart()[0])
    attachments = AttachmentRegistry(session_id="session")
    item = attachments.register(str(image))
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)

    authorized = dispatch_observation(
        registry,
        "extract_line_series",
        json.dumps({"attachment_id": item.id}),
    )
    unauthorized = dispatch_observation(
        registry,
        "extract_line_series",
        json.dumps({"attachment_id": "att_unknown"}),
    )

    assert json.loads(authorized.content)["data"]["image_size"] == [720, 480]
    assert "authorized" in json.loads(unauthorized.content)["error"]
    assert str(image) not in unauthorized.content
    assert unauthorized.images == ()


def test_authorized_chart_tools_keep_identity_and_hide_local_paths():
    from chartagent.tools.chart import register_chart_tools
    from chartagent.tools.chart.catalog import CHART_TOOLS

    attachments = AttachmentRegistry(session_id="session")
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    source_by_name = {tool.name: tool for tool in CHART_TOOLS}

    expected_fields = {
        "extract_text": {"attachment_id"},
        "decompose_chart_image": {"attachment_id", "regions", "segmentation_mode", "max_panels", "crop_padding"},
        "inspect_chart_layout": {"attachment_id", "layout_hint", "chart_type"},
        "measure_bars": {"attachment_id", "panel_id"},
        "extract_line_series": {"attachment_id", "panel_id"},
        "extract_pie_slices": {"attachment_id", "panel_id"},
        "extract_scatter_points": {"attachment_id", "panel_id"},
    }
    for name, fields in expected_fields.items():
        public = registry.get(name)
        source = source_by_name[name]
        assert public is not None
        assert public.name == source.name
        assert public.description == source.description
        assert public.group == source.group == "chart-observation"
        assert set(public.parameters["properties"]) == fields
        assert "image_path" not in json.dumps(public.parameters)
        assert "image_path" not in public.description


def test_pie_sensor_uses_authorized_attachment_id(tmp_path, monkeypatch):
    from chartagent.tools import ToolRegistry, dispatch_observation
    from chartagent.tools.chart import register_chart_tools
    from tests.chart_fixtures import pie_chart

    image = tmp_path / "pie.png"
    image.write_bytes(pie_chart()[0])
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: __import__("chartagent.tools", fromlist=["ToolResult"]).ToolResult([]))
    attachments = AttachmentRegistry(session_id="session")
    item = attachments.register(str(image))
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)

    authorized = dispatch_observation(
        registry,
        "extract_pie_slices",
        json.dumps({"attachment_id": item.id}),
    )
    unauthorized = dispatch_observation(
        registry,
        "extract_pie_slices",
        json.dumps({"attachment_id": "att_unknown"}),
    )

    assert json.loads(authorized.content)["data"]["sectors"]
    assert "authorized" in json.loads(unauthorized.content)["error"]
    assert str(image) not in unauthorized.content
    assert unauthorized.images == ()


def test_scatter_sensor_uses_authorized_attachment_id(tmp_path, monkeypatch):
    from chartagent.tools import ToolRegistry, dispatch_observation
    from chartagent.tools.chart import register_chart_tools
    from tests.chart_fixtures import scatter_chart

    image = tmp_path / "scatter.png"
    image.write_bytes(scatter_chart()[0])
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: __import__("chartagent.tools", fromlist=["ToolResult"]).ToolResult([]),
    )
    attachments = AttachmentRegistry(session_id="session")
    item = attachments.register(str(image))
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)

    authorized = dispatch_observation(
        registry,
        "extract_scatter_points",
        json.dumps({"attachment_id": item.id}),
    )
    unauthorized = dispatch_observation(
        registry,
        "extract_scatter_points",
        json.dumps({"attachment_id": "att_unknown"}),
    )

    assert json.loads(authorized.content)["data"]["points"]
    assert "authorized" in json.loads(unauthorized.content)["error"]
    assert str(image) not in unauthorized.content
    assert unauthorized.images == ()


def test_context_summarizes_complete_old_runs_and_filters_sensitive_values():
    old = Run("old", None, 1, RunStatus.COMPLETED)
    old.records = [
        Record("user", {"message": {"role": "user", "content": "a" * 3000}, "text": "intent"}),
        Record("assistant", {"message": {"role": "assistant", "content": "answer"}}),
        Record("tool", {"message": {"role": "tool", "tool_call_id": "c", "content": "result"}, "tool_name": "inspect", "status": "success"}),
        Record("final", {"answer": "done", "reasoning": "secret"}),
    ]
    current = [Record("user", {"message": {"role": "user", "content": "now"}})]
    context = build_context({"role": "system", "content": "sys"}, [old], current, budget=200)
    assert context[0]["role"] == "system"
    assert context[-1]["content"] == "now"
    summary = " ".join(str(message.get("content", "")) for message in context)
    assert "secret" not in summary
    assert "Prior completed runs" in summary


def test_sanitize_payload_removes_data_urls_and_provider_fields():
    clean = sanitize_payload({"raw": "provider", "reasoning": "private", "reasoning_content": "private-provider", "image": {"url": "data:image/png;base64,AAAA"}, "ok": 1})
    assert clean == {"image": {"url": "[image content omitted from memory]"}, "ok": 1}


def test_checkpoint_context_can_replay_bounded_private_reasoning():
    from chartagent.gateway.recovery import sanitize_checkpoint_state

    state = {"messages": [{"role": "assistant", "content": "", "reasoning_content": "keep exactly"}]}
    clean = sanitize_checkpoint_state(state)
    assert clean["messages"][0]["reasoning_content"] == "keep exactly"
    assert "reasoning_content" not in sanitize_payload(state)["messages"][0]


def test_oversized_tool_content_remains_valid_json_with_marker():
    payload = {"message": {"role": "tool", "content": json.dumps({"items": ["x" * 5000]})}}
    clean = sanitize_payload(payload, limit=100)
    content = clean["message"]["content"]
    assert json.loads(content)["truncated"] is True


def test_sqlite_schema_does_not_downgrade_newer_database(tmp_path):
    db = tmp_path / "sessions.db"
    SQLiteAgentMemory("demo", database=db).close()
    import sqlite3
    connection = sqlite3.connect(db)
    connection.execute("UPDATE schema_meta SET version = 99")
    connection.commit()
    connection.close()
    try:
        SQLiteAgentMemory("demo", database=db)
    except RuntimeError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("newer schema must be rejected")


def test_sqlite_delete_cascades_session_state_but_not_source(tmp_path):
    db = tmp_path / "sessions.db"
    source = tmp_path / "chart.png"
    source.write_bytes(b"source")
    memory = SQLiteAgentMemory("remove-me", database=db)
    registry = AttachmentRegistry(session_id=memory.session.id, save=memory.save_attachment)
    registry.register(str(source))
    memory.close()
    assert SQLiteAgentMemory.delete_session("remove-me", database=db)
    assert SQLiteAgentMemory.list_sessions(database=db) == []
    assert source.read_bytes() == b"source"


def test_context_never_splits_assistant_tool_protocol_block():
    old = Run("old", None, 1, RunStatus.COMPLETED)
    old.records = [
        Record("user", {"message": {"role": "user", "content": "inspect"}}),
        Record("assistant", {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]}}),
        Record("tool", {"message": {"role": "tool", "tool_call_id": "c1", "content": "{}"}}),
        Record("final", {"answer": "done"}),
    ]
    context = build_context(None, [old], [Record("user", {"message": {"role": "user", "content": "now"}})], budget=260)
    serialized = json.dumps(context)
    assert not ("tool_calls" in serialized and "tool_call_id" not in serialized)


class _RestartProvider:
    def __init__(self, calls):
        self.calls = calls

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return NormalizedResult(tool_calls=[ToolCall("call-1", "echo", "{}")])
        return NormalizedResult(content="completed")


def test_named_session_restart_reloads_attachment_and_completed_context(tmp_path):
    db = tmp_path / "sessions.db"
    image = tmp_path / "chart.png"
    image.write_bytes(b"restart image")
    memory = SQLiteAgentMemory("restart", database=db)
    attachments = AttachmentRegistry(session_id=memory.session.id, save=memory.save_attachment, load=memory.get_attachment)
    item = attachments.register(str(image))
    registry = ToolRegistry()
    registry.register(Tool("echo", "echo", {"type": "object"}, lambda: {"ok": True}))
    first_calls = []
    Agent(_RestartProvider(first_calls), registry, memory=memory, attachments=attachments).run(f"inspect attachment_id={item.id}")
    memory.close()

    reopened = SQLiteAgentMemory("restart", database=db)
    reloaded = AttachmentRegistry(session_id=reopened.session.id, load=reopened.get_attachment)
    load_registry = ToolRegistry()
    load_registry.register(reloaded.load_tool())
    observation = dispatch_observation(load_registry, "load_image", json.dumps({"attachment_id": item.id}))
    assert len(observation.images) == 1
    second_calls = []
    Agent(_RestartProvider(second_calls), load_registry, memory=reopened, attachments=reloaded).run("continue the inspection")
    assert any("completed" in json.dumps(request) for request in second_calls)
    reopened.close()
