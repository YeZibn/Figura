"""Tests for the ReAct Agent loop (fake LLM client, no real API).

A fake client gives deterministic, scripted turns so the loop's behavior —
final answer, serial tool observations, error feedback, budget cap, reset,
history shape — is verified offline.
"""

from __future__ import annotations

import json
import io
import re
from threading import Event
from typing import Any, Dict, List

from PIL import Image, ImageDraw
from chartagent import (
    Agent,
    GeneratedImage,
    Tool,
    ToolRegistry,
    ToolResult,
    register_builtins,
)
from chartagent.agent import AgentInterrupted, registry_tools
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.agent.messages import assistant_entry
from chartagent.agent.final_answer import guard_final_answer
from chartagent.tools.chart.observation.layout_tool import INSPECT_CHART_LAYOUT
from chartagent.tools.chart.specification import ASSEMBLE_SPEC


class ScriptedClient:
    """Fake LLMClient: plays a scripted list of results, one per chat() call."""

    def __init__(self, script: List[NormalizedResult]) -> None:
        self.script = list(script)
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, **kwargs):
        self.calls.append({
            "n_messages": len(messages),
            "messages": list(messages),
            "tools": kwargs.get("tools"),
        })
        assert self.script, "script exhausted"
        return self.script.pop(0)


class RecordingObservationClient(ScriptedClient):
    """Record full request payloads while driving a one-tool observation."""

    def __init__(self, script: List[NormalizedResult]) -> None:
        super().__init__(script)
        self.requests: List[List[Dict[str, Any]]] = []

    def chat(self, messages, **kwargs):
        self.requests.append(list(messages))
        return super().chat(messages, **kwargs)


def _final(text: str = "done") -> NormalizedResult:
    return NormalizedResult(content=text, tool_calls=[])


def _call(name: str, arguments: str, call_id: str = "call_1") -> NormalizedResult:
    return NormalizedResult(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def _registry():
    reg = ToolRegistry()
    register_builtins(reg)
    return reg


def _execution_fact(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "payload": payload}


def test_final_answer_chart_claims_follow_verification_and_publication_records():
    failed_output = {
        "kind": "generated_chart",
        "staged_ref": "stg_chart_a",
        "verification": {"verificationRef": "ver_chart_a"},
    }
    failed = _execution_fact(
        "verification_result",
        {"stagedRef": "stg_chart_a", "verificationRef": "ver_chart_a", "status": "fail"},
    )
    assert "未通过验证" in guard_final_answer("图表验证通过，已发布。", [failed], [failed_output])
    assert "不能报告验证通过" in guard_final_answer("图表验证通过。", [failed], [failed_output])

    passed = _execution_fact(
        "verification_result",
        {"stagedRef": "stg_chart_a", "verificationRef": "ver_chart_a", "status": "pass"},
    )
    passed_output = {
        "kind": "generated_chart",
        "staged_ref": "stg_chart_a",
        "verification": {"verificationRef": "ver_chart_a"},
    }
    assert "发布尚未全部确认" in guard_final_answer("图表已发布。", [passed], [passed_output])

    promotion = _execution_fact(
        "promotion_result",
        {
            "stagedRef": "stg_chart_a",
            "verificationRef": "ver_chart_a",
            "artifactId": "artifact_0123456789abcdef",
        },
    )
    assert guard_final_answer("图表验证通过并已发布。", [passed, promotion], [passed_output]) == "图表验证通过并已发布。"
    assert "没有可确认的已发布图表" in guard_final_answer(
        "请打开 artifact_fedcba9876543210。", [passed, promotion], [passed_output]
    )


def test_final_answer_guard_uses_latest_output_after_failed_attempt():
    records = [
        _execution_fact("verification_result", {"stagedRef": "stg_old", "verificationRef": "ver_old", "status": "fail"}),
        _execution_fact("verification_result", {"stagedRef": "stg_new", "verificationRef": "ver_new", "status": "pass"}),
        _execution_fact("promotion_result", {"stagedRef": "stg_new", "verificationRef": "ver_new", "artifactId": "artifact_0123456789abcdef"}),
    ]
    current_output = [{
        "kind": "generated_chart",
        "staged_ref": "stg_new",
        "artifact_id_published": "artifact_0123456789abcdef",
        "verification": {"verificationRef": "ver_new"},
    }]

    assert guard_final_answer("当前图表验证通过并已发布。", records, current_output) == "当前图表验证通过并已发布。"


def test_final_answer_guard_rejects_latest_failed_attempt_after_pass():
    records = [
        _execution_fact("verification_result", {"stagedRef": "stg_old", "verificationRef": "ver_old", "status": "pass"}),
        _execution_fact("promotion_result", {"stagedRef": "stg_old", "verificationRef": "ver_old", "artifactId": "artifact_0123456789abcdef"}),
        _execution_fact("verification_result", {"stagedRef": "stg_new", "verificationRef": "ver_new", "status": "fail"}),
    ]
    current_output = [{
        "kind": "generated_chart",
        "staged_ref": "stg_new",
        "verification": {"verificationRef": "ver_new"},
    }]

    assert "不能报告验证通过" in guard_final_answer("图表验证通过。", records, current_output)
    assert "未通过验证" in guard_final_answer("图表已发布。", records, current_output)


def test_final_answer_guard_does_not_accept_reference_to_failed_artifact():
    records = [
        _execution_fact("verification_result", {"stagedRef": "stg_failed", "verificationRef": "ver_failed", "status": "fail"}),
        _execution_fact(
            "promotion_result",
            {
                "stagedRef": "stg_failed",
                "verificationRef": "ver_failed",
                "artifactId": "artifact_fedcba9876543210",
            },
        ),
    ]
    current_output = [{
        "kind": "generated_chart",
        "staged_ref": "stg_failed",
        "verification": {"verificationRef": "ver_failed"},
    }]

    answer = guard_final_answer("请打开 artifact_fedcba9876543210。", records, current_output)
    assert "没有可确认的已发布图表" in answer


def test_final_answer_guard_checks_every_current_collection_child():
    records = [
        _execution_fact("verification_result", {"stagedRef": "stg_child_a", "verificationRef": "ver_child_a", "status": "pass"}),
        _execution_fact("verification_result", {"stagedRef": "stg_child_b", "verificationRef": "ver_child_b", "status": "fail"}),
    ]
    current_output = [
        {
            "kind": "generated_chart",
            "staged_ref": "stg_child_a",
            "verification": {"verificationRef": "ver_child_a"},
        },
        {
            "kind": "generated_chart",
            "staged_ref": "stg_child_b",
            "verification": {"verificationRef": "ver_child_b"},
        },
    ]

    assert "不能报告验证通过" in guard_final_answer("集合中的图表都验证通过。", records, current_output)


def test_final_answer_returned_no_tools():
    client = ScriptedClient([_final("hello")])
    agent = Agent(client, ToolRegistry(), system="sys")
    assert agent.run("hi") == "hello"


def test_clear_chart_can_assemble_without_layout_inspection():
    registry = ToolRegistry()
    registry.register(INSPECT_CHART_LAYOUT)
    registry.register(ASSEMBLE_SPEC)
    client = ScriptedClient(
        [
            _call(
                "assemble_spec",
                json.dumps(
                    {
                        "chart_type": "bar",
                        "title": "Sales",
                        "x_label": "Category",
                        "y_label": "Value",
                        "points": [{"category": "A", "value": 3}],
                    }
                ),
            ),
            _final("assembled"),
        ]
    )

    assert Agent(client, registry).run("restore this clear bar chart") == "assembled"
    assert client.calls[0]["messages"][0]["role"] == "user"
    assert len(client.calls) == 2
    assert json.loads(client.calls[1]["messages"][-1]["content"])["metadata"]["chart_type"] == "bar"


def test_descriptive_chart_question_does_not_require_restoration_tools():
    registry = ToolRegistry()
    registry.register(INSPECT_CHART_LAYOUT)
    registry.register(ASSEMBLE_SPEC)
    client = ScriptedClient([_final("蓝线上升，橙线下降")])

    assert Agent(client, registry).run("这张图的趋势是什么？") == "蓝线上升，橙线下降"
    assert len(client.calls) == 1
    assert client.calls[0]["tools"]


def test_multi_step_tool_loop(tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"n": 3}', encoding="utf-8")
    script = [
        _call("read_json_file", '{"path": "%s"}' % p),
        _final('{"n": 3}'),
    ]
    client = ScriptedClient(script)
    got = Agent(client, _registry()).run("read it")
    assert got == '{"n": 3}'
    # history before final turn: user + assistant(tool_calls) + tool obs = 3
    assert client.calls[-1]["n_messages"] == 3


def test_multi_tool_batch_keeps_the_bounded_artifact_context_shared():
    registry = ToolRegistry()

    def chart_verification(prefix: str) -> dict[str, Any]:
        return {
            "data": {
                "chartVerification": [
                    {
                        "stagedRef": f"stg_{prefix}_{index:02d}",
                        "verification": {
                            "verificationRef": f"ver_{prefix}_{index:02d}",
                            "status": "pass",
                        },
                    }
                    for index in range(16)
                ]
            }
        }

    for name, prefix in (("charts_a", "batcha"), ("charts_b", "batchb")):
        registry.register(
            Tool(
                name,
                "return chart outcomes",
                {"type": "object"},
                lambda current_prefix=prefix: chart_verification(current_prefix),
            )
        )

    client = ScriptedClient([
        NormalizedResult(
            tool_calls=[
                ToolCall(id="call_a", name="charts_a", arguments="{}"),
                ToolCall(id="call_b", name="charts_b", arguments="{}"),
            ]
        ),
        _final("本次生成图表尚未发布。"),
    ])
    seed_artifacts = [
        {"artifact_id": f"seed_{index:02d}", "kind": "measurement", "status": "observed"}
        for index in range(40)
    ]

    result = Agent(client, registry, system="sys").run(
        "inspect outcomes",
        recovery_context={"artifactIndex": seed_artifacts, "currentTurn": 0},
    )

    assert result == "本次生成图表尚未发布。"
    system_prompt = next(
        message["content"]
        for message in client.calls[-1]["messages"]
        if message["role"] == "system"
    )
    artifact_json = re.search(r"## 过程产物层\s+.*?```json\n(.*?)\n```", system_prompt, re.DOTALL)
    assert artifact_json is not None
    retained_artifacts = json.loads(artifact_json.group(1))
    retained_ids = {item["artifact_id"] for item in retained_artifacts}
    assert len(retained_artifacts) == 48
    assert "seed_00" not in retained_ids
    assert "seed_39" in retained_ids
    assert {f"stg_batcha_{index:02d}" for index in range(16)}.issubset(retained_ids)
    assert {f"stg_batchb_{index:02d}" for index in range(16)}.issubset(retained_ids)


def test_layout_preflight_context_is_cached_and_injected_into_sensor():
    context = {
        "context_id": "layout_test",
        "validation": {"status": "accepted", "accepted_for_measurement": True, "confidence": 0.9},
        "measurement_frame": {"bbox_px": [10, 10, 80, 60]},
    }
    seen: list[dict[str, Any] | None] = []
    registry = ToolRegistry()
    registry.register(
        Tool(
            "inspect_chart_layout",
            "inspect layout",
            {"type": "object", "properties": {"attachment_id": {"type": "string"}}, "required": ["attachment_id"]},
            lambda attachment_id: ToolResult({"layout_context": context}),
        )
    )

    def sensor(attachment_id: str, layout_context: dict[str, Any] | None = None):
        seen.append(layout_context)
        return ToolResult(
            {
                "image_size": [320, 240],
                "scope": {"panel_id": "panel_line"},
                "plot_frame": {
                    "x_axis": {"points_px": [[40, 200], [280, 200]]},
                    "y_axis": {"points_px": [[40, 20], [40, 200]]},
                },
                "series": [{
                    "id": "series_1",
                    "trace": {"polyline_px": [[40, 180], [160, 120], [280, 80]]},
                }],
                "warnings": [],
            },
            [GeneratedImage(b"overlay", "image/png", "line overlay")],
        )

    registry.register(
        Tool(
            "extract_line_series",
            "extract line",
            {
                "type": "object",
                "properties": {
                    "attachment_id": {"type": "string"},
                    "layout_context": {"type": "object", "additionalProperties": True},
                },
                "required": ["attachment_id"],
            },
            sensor,
        )
    )
    registry.register(ASSEMBLE_SPEC)

    class LayoutClient:
        def __init__(self):
            self.turn = 0
            self.calls: list[dict[str, Any]] = []

        def chat(self, messages, **kwargs):
            self.turn += 1
            self.calls.append({"messages": list(messages), "tools": kwargs.get("tools")})
            if self.turn == 1:
                return _call("inspect_chart_layout", '{"attachment_id":"att_chart"}', "layout-1")
            if self.turn == 2:
                return _call("extract_line_series", '{"attachment_id":"att_chart"}', "line-1")
            if self.turn == 3:
                tool_message = next(item for item in reversed(messages) if item.get("role") == "tool")
                measurement = json.loads(tool_message["content"])["data"]["measurement"]
                ref = measurement["evidence"]["refs"][0]["ref"]
                return _call(
                    "assemble_spec",
                    json.dumps(
                        {
                            "chart_type": "line",
                            "x_label": "月份",
                            "y_label": "数值",
                            "points": [{"x": 1, "y": 2}],
                            "measurement_ref": measurement["reference"],
                            "evidence_refs": [ref],
                        },
                        ensure_ascii=False,
                    ),
                    "assemble-1",
                )
            return _final("done")

    client = LayoutClient()

    assert Agent(client, registry).run("analyze att_chart") == "done"
    assert seen[0]["context_id"] == context["context_id"]
    assert seen[0]["measurement_frame"] == context["measurement_frame"]
    assert seen[0]["source_attachment_id"] == "att_chart"


def test_tool_error_fed_back_as_observation():
    script = [
        _call("read_file", '{"path": "/definitely/missing/xyz"}'),
        _final("recovered"),
    ]
    client = ScriptedClient(script)
    got = Agent(client, ToolRegistry()).run("try")
    assert got == "recovered"
    assert len(client.calls) == 2  # error observation did not abort the loop


def test_max_steps_budget():
    client = ScriptedClient([_call("read_file", '{"path": "x"}') for _ in range(50)])
    agent = Agent(client, _registry(), max_steps=3)
    out = agent.run("loop")
    assert out == "*stopped: max_steps reached*"
    assert len(client.calls) == 3


def test_agent_stops_before_model_request_when_interrupted():
    stop = Event()
    stop.set()
    client = ScriptedClient([_final("must not run")])
    agent = Agent(client, ToolRegistry(), interruption_event=stop)

    try:
        agent.run("stop now")
    except AgentInterrupted:
        pass
    else:
        raise AssertionError("expected cooperative interruption")
    assert client.calls == []


def test_agent_stops_before_next_tool_result_is_published():
    stop = Event()
    registry = ToolRegistry()

    def interrupting_tool():
        stop.set()
        return {"ok": True}

    registry.register(Tool("interrupting", "interrupt", {"type": "object"}, interrupting_tool))
    client = ScriptedClient([_call("interrupting", "{}"), _final("must not continue")])
    agent = Agent(client, registry, interruption_event=stop)

    try:
        agent.run("stop after tool")
    except AgentInterrupted:
        pass
    else:
        raise AssertionError("expected cooperative interruption")
    assert len(client.calls) == 1


def test_reset_clears_history():
    client = ScriptedClient([_final("one")])
    agent = Agent(client, ToolRegistry())
    agent.run("a")
    agent.reset()
    assert agent.messages == []


def test_assistant_history_keeps_tool_calls_strips_reasoning():
    result = NormalizedResult(
        content="hi",
        reasoning="SECRET_THOUGHT",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments='{"path":"x"}')],
    )
    entry = assistant_entry(result)
    assert entry["content"] == "hi"
    assert "SECRET_THOUGHT" not in entry
    assert entry["tool_calls"][0]["id"] == "c1"


def test_deepseek_tool_followup_replays_reasoning_only_to_model_context():
    registry = ToolRegistry()
    registry.register(Tool("inspect", "inspect", {"type": "object"}, lambda: {"ok": True}))

    class DeepSeekClient(ScriptedClient):
        config = type("Config", (), {"provider": "deepseek", "enable_thinking": True})()

    client = DeepSeekClient([
        NormalizedResult(
            reasoning="private deepseek plan",
            tool_calls=[ToolCall("call-1", "inspect", "{}")],
        ),
        NormalizedResult(content="done", reasoning="final private thought"),
    ])
    agent = Agent(client, registry)

    assert agent.run("inspect") == "done"
    assistant_messages = [message for message in client.calls[1]["messages"] if message.get("role") == "assistant"]
    assert assistant_messages[0]["reasoning_content"] == "private deepseek plan"
    assert all("reasoning_content" not in record.payload.get("message", {}) for record in agent.memory.runs[0].records)
    assert "final private thought" not in repr(agent.memory.runs[0].records)


def test_registry_tools_lists_openai_schema():
    tools = registry_tools(_registry())
    assert len(tools) == 4
    assert tools[0]["type"] == "function"
    assert "name" in tools[0]["function"]


def test_multimodal_input_passes_through_unchanged():
    content = [
        {"type": "text", "text": "read this chart"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    client = ScriptedClient([_final("a bar chart")])
    agent = Agent(client, ToolRegistry(), system="sys")
    assert agent.run(content) == "a bar chart"
    # history: system + user(content list), unchanged
    user_entries = [m for m in agent.messages if m["role"] == "user"]
    assert user_entries[0]["content"] == content
    # the client received the same list verbatim on the first turn
    sent = client.calls[0]["messages"]
    assert [m for m in sent if m["role"] == "user"][0]["content"] == content


def _visual_registry(*, invalid: bool = False):
    registry = ToolRegistry()
    image = GeneratedImage(
        b"" if invalid else b"generated-image",
        "image/png",
        "Detected regions",
    )
    registry.register(
        Tool(
            "visual",
            "return visual evidence",
            {"type": "object"},
            lambda: ToolResult({"count": 2}, [image]),
        )
    )
    return registry


def test_visual_tool_result_adds_attributed_multimodal_observation():
    client = ScriptedClient([_call("visual", "{}", "visual-1"), _final("accepted")])
    agent = Agent(client, _visual_registry())

    assert agent.run("inspect") == "accepted"

    messages = client.calls[1]["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "tool",
        "user",
    ]
    assert json.loads(messages[2]["content"])["data"] == {"count": 2}
    evidence = messages[3]["content"]
    assert evidence[1]["text"] == (
        "Tool: visual\nTool call ID: visual-1\nCaption: Detected regions"
    )
    assert evidence[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_chart_generation_emits_staging_and_verification_facts():
    pixels = Image.new("RGB", (64, 40), "white")
    draw = ImageDraw.Draw(pixels)
    draw.rectangle((8, 8, 22, 34), fill="#3568a8")
    draw.rectangle((34, 16, 48, 34), fill="#df824b")
    encoded = io.BytesIO()
    pixels.save(encoded, format="PNG")
    spec = {"metadata": {"chart_type": "pie", "title": "销售"}, "dataset": [{"category": "A", "value": 3}, {"category": "B", "value": 2}]}
    registry = ToolRegistry()
    registry.register(
        Tool(
            "render_chart",
            "return a generated chart",
            {"type": "object", "properties": {"spec": {"type": "object"}}},
            lambda spec: ToolResult(
                {"kind": "generated_chart", "chart_type": "pie"},
                [GeneratedImage(
                    encoded.getvalue(),
                    "image/png",
                    "生成图表：销售",
                    metadata={"kind": "generated_chart", "chart_type": "pie", "title": "销售", "width": 64, "height": 40},
                )],
            ),
        )
    )
    events = []
    client = ScriptedClient([_call("render_chart", json.dumps({"spec": spec}, ensure_ascii=False), "chart-1"), _final("done")])
    staged = []
    verified = []
    promoted = []
    assert Agent(
        client,
        registry,
        trace_sink=events.append,
        stage_chart_sink=lambda _image, manifest: staged.append(manifest) or {"stagedRef": manifest.staged_ref},
        verification_sink=lambda result: verified.append(result) or True,
        promotion_sink=lambda *_args: promoted.append(True) or {"artifactId": "artifact_chart_12345678"},
    ).run("重绘") == "done"
    assert [event.kind for event in events if event.kind.startswith("chart_")] == ["chart_staged"]
    assert len(staged) == len(verified) == len(promoted) == 1
    assert "generated_chart" not in [event.kind for event in events]


def test_multiple_tools_append_all_tool_messages_before_visual_observation():
    registry = ToolRegistry()
    registry.register(
        Tool(
            "first",
            "first visual",
            {"type": "object"},
            lambda: ToolResult(
                {"first": True}, [GeneratedImage(b"one", "image/png", "First")]
            ),
        )
    )
    registry.register(
        Tool(
            "second",
            "second visual",
            {"type": "object"},
            lambda: ToolResult(
                {"second": True}, [GeneratedImage(b"two", "image/png", "Second")]
            ),
        )
    )
    calls = NormalizedResult(
        tool_calls=[
            ToolCall("call-1", "first", "{}"),
            ToolCall("call-2", "second", "{}"),
        ]
    )
    client = ScriptedClient([calls, _final("done")])

    assert Agent(client, registry).run("inspect both") == "done"

    messages = client.calls[1]["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "user",
    ]
    evidence = messages[-1]["content"]
    assert "Tool call ID: call-1" in evidence[1]["text"]
    assert "Tool call ID: call-2" in evidence[3]["text"]


def test_measurement_quality_does_not_stop_the_tool_batch_after_observation():
    registry = ToolRegistry()
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {"type": "object"},
            lambda attachment_id: ToolResult(
                {
                    "image_size": [320, 240],
                    "scope": {"panel_id": "panel_bars"},
                    "plot_area": {"bbox": [40, 20, 240, 180]},
                    "baseline": {"slope": 0.0, "intercept": 200.0},
                    "bars": [{"id": 1, "measure": {"ratio": 1.0}}],
                    "confidence": {"overall": 0.9},
                    "warnings": [],
                },
                warnings=("baseline fit is uncertain; measurements may be partial",),
            ),
        )
    )
    registry.register(
        Tool(
            "extract_line_series",
            "extract line",
            {"type": "object"},
            lambda attachment_id: ToolResult(
                {
                    "image_size": [320, 240],
                    "scope": {"panel_id": "panel_line"},
                    "plot_area": {"bbox": [40, 20, 240, 180]},
                    "baseline": {"slope": 0.0, "intercept": 200.0},
                    "series": [{"id": "line-1", "points": [[40, 200], [80, 160]]}],
                    "confidence": {"overall": 0.9},
                    "warnings": [],
                },
                warnings=("baseline fit is uncertain; measurements may be partial",),
            ),
        )
    )
    events = []
    client = ScriptedClient(
        [
            NormalizedResult(
                tool_calls=[
                    ToolCall("bars-1", "measure_bars", '{"attachment_id":"att_chart"}'),
                    ToolCall("line-1", "extract_line_series", '{"attachment_id":"att_chart"}'),
                ],
                finish_reason="tool_calls",
            ),
            _final("done"),
        ]
    )

    answer = Agent(client, registry, max_steps=2, trace=events.append).run("检查两个 panel")
    assert answer == "done"

    messages = client.calls[1]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "tool", "tool"]
    assert [message["tool_call_id"] for message in messages[2:4]] == ["bars-1", "line-1"]
    assert not any(message["role"] == "user" and "measurement_repairs" in str(message["content"]) for message in messages)
    assert any(message["role"] == "tool" and "measurement" in str(message["content"]) for message in messages[2:3])
    skipped = [event for event in events if event.kind == "tool_skipped"]
    assert skipped == []
    assert any(
        event.kind == "tool_call" and event.payload.get("tool_name") == "measure_bars"
        for event in events
    )
    assert any(
        event.kind == "tool_result" and event.payload.get("tool_name") == "measure_bars"
        for event in events
    )


def test_invalid_generated_image_does_not_add_multimodal_turn():
    client = ScriptedClient([_call("visual", "{}"), _final("used JSON")])
    agent = Agent(client, _visual_registry(invalid=True))

    assert agent.run("inspect") == "used JSON"

    messages = client.calls[1]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "tool"]
    assert "content is empty" in messages[-1]["content"]


def test_json_only_history_shape_remains_unchanged():
    client = ScriptedClient([_call("parse_json", '{"text":"{\\"n\\":3}"}'), _final("done")])
    agent = Agent(client, _registry())

    agent.run("parse")

    messages = client.calls[1]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "tool"]
    assert messages[-1]["content"] == '{"n": 3}'


def test_reset_and_close_release_generated_observation_history(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    client = ScriptedClient(
        [
            _call("visual", "{}", "visual-1"),
            _final("done"),
            _call("visual", "{}", "visual-2"),
            _final("done again"),
        ]
    )
    agent = Agent(client, _visual_registry())

    agent.run("inspect")
    assert any(message["role"] == "user" and isinstance(message["content"], list) for message in agent.messages)
    agent.reset()
    assert agent.messages == []
    assert source.read_bytes() == b"source"
    agent.run("inspect again")
    agent.close()
    assert agent.messages == []
    assert source.read_bytes() == b"source"


def test_recording_client_receives_source_json_and_generated_overlay(tmp_path):
    source = tmp_path / "chart.png"
    source.write_bytes(b"original-chart-bytes")
    registry = _visual_registry()
    client = RecordingObservationClient(
        [_call("visual", "{}", "visual-1"), _final("accepted")]
    )
    agent = Agent(client, registry)

    source_turn = [
        {"type": "text", "text": "inspect"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,c291cmNl"},
        },
    ]
    assert agent.run(source_turn) == "accepted"

    next_turn = client.requests[1]
    assert next_turn[0]["role"] == "user"
    assert next_turn[0]["content"] == source_turn
    assert next_turn[2]["role"] == "tool"
    assert json.loads(next_turn[2]["content"])["data"] == {"count": 2}
    evidence = next_turn[3]["content"]
    assert evidence[0]["type"] == "text"
    assert evidence[1]["text"].startswith("Tool: visual\nTool call ID: visual-1")
    assert evidence[2]["image_url"]["url"].endswith("Z2VuZXJhdGVkLWltYWdl")


def test_visual_observation_can_be_rejected_and_recovered_with_new_tool_call():
    registry = ToolRegistry()
    observations = iter(
        [
            ToolResult({"axis": "unclear"}, [GeneratedImage(b"first", "image/png", "First pass")]),
            ToolResult({"axis": "clear"}, [GeneratedImage(b"second", "image/png", "Second pass")]),
        ]
    )
    registry.register(
        Tool(
            "inspect_axis",
            "inspect chart axis",
            {"type": "object", "properties": {"crop": {"type": "string"}}},
            lambda **_kwargs: next(observations),
        )
    )
    client = ScriptedClient(
        [
            _call("inspect_axis", '{"crop":"full"}', "axis-1"),
            _call("inspect_axis", '{"crop":"axis-label"}', "axis-2"),
            _final("axis confirmed"),
        ]
    )
    agent = Agent(client, registry)

    assert agent.run("read the axis") == "axis confirmed"
    assert len(client.calls) == 3
    first_observation = json.loads(client.calls[1]["messages"][2]["content"])
    second_observation = json.loads(client.calls[2]["messages"][5]["content"])
    assert first_observation["data"] == {"axis": "unclear"}
    assert second_observation["data"] == {"axis": "clear"}
    assert "Tool call ID: axis-1" in client.calls[1]["messages"][3]["content"][1]["text"]
    assert "Tool call ID: axis-2" in client.calls[2]["messages"][6]["content"][1]["text"]
