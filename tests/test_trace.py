"""Offline tests for Agent execution traces and their sanitization boundary."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from chartagent import (
    Agent,
    GeneratedImage,
    JsonlTraceRenderer,
    TextTraceRenderer,
    Tool,
    ToolRegistry,
    ToolResult,
)
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.trace import TraceEmitter, TraceEvent, TraceLimits


class _ScriptedClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append([dict(message) for message in messages])
        return self.results.pop(0)


def _call(name: str, arguments: str, call_id: str) -> NormalizedResult:
    return NormalizedResult(tool_calls=[ToolCall(call_id, name, arguments)])


def test_llm_client_emits_model_boundary_events(backend_factory):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok", reasoning_content="", tool_calls=None
                ),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    client, _backend = backend_factory([lambda _request: response])
    events = []

    assert client.chat(
        [{"role": "user", "content": "hello"}],
        model="trace-model",
        stream=False,
        trace_sink=events.append,
        trace_run_id="client-run",
        trace_turn=3,
    ).content == "ok"
    assert [event.kind for event in events] == ["model_started", "model_completed"]
    assert all(event.run_id == "client-run" and event.turn == 3 for event in events)


def test_trace_event_serializes_in_order_and_redacts_bounded_data():
    events = []
    emitter = TraceEmitter(
        events.append,
        run_id="run-1",
        limits=TraceLimits(max_text=24, max_arguments=24, max_result=24),
    )

    emitter.emit(
        "tool_call",
        turn=2,
        api_key="do-not-print",
        authorization="Bearer do-not-print",
        arguments={"path": "x" * 100},
        binary=b"secret-image-bytes",
    )
    emitter.emit("final_answer", turn=2, answer="done")

    assert [event.sequence for event in events] == [1, 2]
    assert events[0].run_id == "run-1"
    assert events[0].turn == 2
    encoded = events[0].to_json()
    assert json.loads(encoded)["kind"] == "tool_call"
    assert "do-not-print" not in encoded
    assert "secret-image-bytes" not in encoded
    assert "truncated" in encoded


def test_trace_redacts_local_paths_inside_measurement_arguments():
    event = TraceEvent(
        "tool_call",
        payload={
            "arguments": {
                "measurement_target": {
                    "reason": "复查 /Users/yezibin/Project/Figura/photo/chart.png",
                }
            }
        },
    )

    encoded = event.to_json()
    assert "/Users/yezibin/Project/Figura" not in encoded
    assert "[PATH_OMITTED]" in encoded


def test_trace_event_direct_payload_is_json_safe():
    event = TraceEvent(
        "visual_observation",
        run_id="r",
        turn=1,
        payload={"image": {"content": b"raw-bytes", "caption": "overlay"}},
    )

    payload = event.to_dict()["payload"]
    assert payload["image"]["content"]["binary_omitted"] is True
    assert "raw-bytes" not in event.to_json()


def test_agent_trace_orders_tools_visuals_and_keeps_reasoning_out_of_history():
    registry = ToolRegistry()
    registry.register(
        Tool(
            "ocr",
            "read labels",
            {"type": "object"},
            lambda: ToolResult(
                {"labels": ["A"], "api_key": "secret"},
                [GeneratedImage(b"overlay-bytes", "image/png", "OCR overlay")],
            ),
        )
    )
    registry.register(
        Tool(
            "bars",
            "measure bars",
            {"type": "object"},
            lambda: {"bars": [8, 16]},
        )
    )
    client = _ScriptedClient(
        [
            NormalizedResult(reasoning="private plan", tool_calls=[ToolCall("ocr-1", "ocr", "{}")]),
            NormalizedResult(reasoning="measure next", tool_calls=[ToolCall("bar-1", "bars", "{}")]),
            NormalizedResult(reasoning="final private plan", content="answer"),
        ]
    )
    events = []
    agent = Agent(client, registry, trace=events.append, trace_reasoning=True)

    assert agent.run("inspect") == "answer"

    kinds = [event.kind for event in events]
    assert kinds == [
        "model_started",
        "model_completed",
        "reasoning",
        "tool_call",
        "tool_result",
        "visual_observation",
        "model_started",
        "model_completed",
        "reasoning",
        "tool_call",
        "tool_result",
        "model_started",
        "model_completed",
        "reasoning",
        "final_answer",
    ]
    visual = next(event for event in events if event.kind == "visual_observation")
    assert visual.payload["images"][0] == {
        "media_type": "image/png",
        "caption": "OCR overlay",
        "byte_count": len(b"overlay-bytes"),
    }
    serialized = "\n".join(event.to_json() for event in events)
    assert "overlay-bytes" not in serialized
    assert "secret" not in serialized
    assert all("private plan" not in message for message in agent.messages)


def test_layout_tool_trace_uses_localized_frontend_label():
    registry = ToolRegistry()
    registry.register(
        Tool(
            "inspect_chart_layout",
            "Use this tool to inspect a chart layout when needed; do not use it for unrelated work. The result is bounded layout evidence.",
            {"type": "object"},
            lambda: {"layout_context": {"validation": {"status": "accepted"}}},
        )
    )
    client = _ScriptedClient(
        [
            NormalizedResult(
                tool_calls=[ToolCall("layout-1", "inspect_chart_layout", "{}")]
            ),
            NormalizedResult(content="done"),
        ]
    )
    events = []

    assert Agent(client, registry, trace=events.append).run("inspect") == "done"

    tool_events = [event for event in events if event.kind in {"tool_call", "tool_result"}]
    assert [event.payload["tool_label"] for event in tool_events] == [
        "检查图表布局 (inspect_chart_layout)",
        "检查图表布局 (inspect_chart_layout)",
    ]
    assert [event.payload["tool_display_name"] for event in tool_events] == [
        "检查图表布局",
        "检查图表布局",
    ]


def test_trace_is_a_side_channel_and_does_not_change_agent_messages_or_answer():
    def run(trace=None):
        registry = ToolRegistry()
        registry.register(Tool("echo", "echo", {"type": "object"}, lambda value: {"value": value}))
        client = _ScriptedClient(
            [
                _call("echo", '{"value":"x"}', "echo-1"),
                NormalizedResult(content="same answer", reasoning="hidden"),
            ]
        )
        agent = Agent(client, registry, trace=trace)
        return agent.run("q"), agent.messages, client.calls

    plain_answer, plain_messages, plain_calls = run()
    traced_events = []
    traced_answer, traced_messages, traced_calls = run(traced_events.append)

    assert traced_answer == plain_answer
    assert traced_messages == plain_messages
    assert traced_calls == plain_calls
    assert all(event.kind != "reasoning" for event in traced_events)


def test_trace_preserves_multi_tool_order_and_structured_errors():
    registry = ToolRegistry()
    registry.register(Tool("ok", "works", {"type": "object"}, lambda: {"ok": True}))
    client = _ScriptedClient(
        [
            NormalizedResult(
                tool_calls=[
                    ToolCall("bad-1", "missing", "{}"),
                    ToolCall("ok-1", "ok", "{}"),
                ]
            ),
            NormalizedResult(content="recovered"),
        ]
    )
    events = []
    assert Agent(client, registry, trace=events.append).run("run both") == "recovered"
    relevant = [
        (event.kind, event.payload.get("call_id"), event.payload.get("status"))
        for event in events
        if event.kind in {"tool_call", "tool_result"}
    ]
    assert relevant == [
        ("tool_call", "bad-1", None),
        ("tool_result", "bad-1", "error"),
        ("tool_call", "ok-1", None),
        ("tool_result", "ok-1", "success"),
    ]
    assert all(event.payload.get("tool_status") == event.payload.get("status") for event in events if event.kind == "tool_result")


def test_trace_records_structured_tool_error_and_budget_termination():
    client = _ScriptedClient(
        [
            _call("missing", "{}", "bad-1"),
            _call("missing", "{}", "bad-2"),
        ]
    )
    events = []
    agent = Agent(client, ToolRegistry(), max_steps=2, trace=events.append)

    assert agent.run("keep trying") == "*stopped: max_steps reached*"
    results = [event for event in events if event.kind == "tool_result"]
    assert [event.payload["status"] for event in results] == ["error", "error"]
    assert all("Unknown tool" in json.dumps(event.payload) for event in results)
    assert events[-1].kind == "budget_exhausted"


def test_reasoning_unavailable_is_valid_and_text_jsonl_renderers_are_separate():
    events = []
    agent = Agent(
        _ScriptedClient([NormalizedResult(content="done")]),
        ToolRegistry(),
        trace=events.append,
        trace_reasoning=True,
    )
    assert agent.run("hello") == "done"
    reasoning = next(event for event in events if event.kind == "reasoning")
    assert reasoning.payload == {"status": "unavailable", "reasoning": ""}

    text_stream = StringIO()
    json_stream = StringIO()
    text_renderer = TextTraceRenderer(text_stream)
    json_renderer = JsonlTraceRenderer(json_stream)
    for event in events:
        text_renderer(event)
        json_renderer(event)
    assert "provider-returned reasoning (unavailable)" in text_stream.getvalue()
    records = [json.loads(line) for line in json_stream.getvalue().splitlines()]
    assert records[-1]["kind"] == "final_answer"


def test_recorded_trajectory_covers_ocr_bar_retry_and_both_renderers():
    fixture_path = Path(__file__).parent / "fixtures" / "agent_trace_trajectory.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    measure_calls = 0

    def measure_bars(region: str):
        nonlocal measure_calls
        measure_calls += 1
        if region == "full":
            raise ValueError("plot region is ambiguous")
        return ToolResult(
            {
                "image_size": [320, 240],
                "plot_area": {"bbox": [40, 20, 240, 180]},
                "baseline": {"slope": 0.0, "intercept": 200.0},
                "bars": [
                    {"id": 1, "measure": {"ratio": 1.0}},
                    {"id": 2, "measure": {"ratio": 2.0}},
                    {"id": 3, "measure": {"ratio": 3.0}},
                ],
                "warnings": [],
            },
            [GeneratedImage(b"bar-overlay", "image/png", "Bar measurements")],
        )

    registry = ToolRegistry()
    registry.register(
        Tool("extract_text", "OCR labels", {"type": "object"}, lambda: {"labels": ["A", "B", "C"]})
    )
    registry.register(
        Tool(
            "measure_bars",
            "measure bars",
            {"type": "object", "properties": {"region": {"type": "string"}}},
            measure_bars,
        )
    )
    scripted = [
        _call("extract_text", "{}", "ocr-1"),
        _call("measure_bars", '{"region":"full"}', "bars-1"),
        _call("measure_bars", '{"region":"plot"}', "bars-2"),
        NormalizedResult(content=fixture["final_answer"]),
    ]
    events = []
    answer = Agent(scripted_client := _ScriptedClient(scripted), registry, trace=events.append).run(
        fixture["prompt"]
    )

    assert answer == fixture["final_answer"]
    assert measure_calls == 2
    assert [event.payload.get("tool_name") for event in events if event.kind == "tool_call"] == [
        "extract_text",
        "measure_bars",
        "measure_bars",
    ]
    assert any(event.kind == "visual_observation" for event in events)
    assert any(event.kind == "final_answer" for event in events)
    assert len(scripted_client.calls) == len(fixture["model_turns"])

    text_stream = StringIO()
    json_stream = StringIO()
    text_renderer = TextTraceRenderer(text_stream)
    json_renderer = JsonlTraceRenderer(json_stream)
    for event in events:
        text_renderer(event)
        json_renderer(event)
    assert "tool call" in text_stream.getvalue()
    assert "raw" not in text_stream.getvalue().lower()
    assert all(json.loads(line)["kind"] for line in json_stream.getvalue().splitlines())
