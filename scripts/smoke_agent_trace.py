#!/usr/bin/env python3
"""Bounded live smoke for the Agent trace mode.

The provider is free to choose chart tools. Trace records are rendered as
sanitized JSONL on stderr; only a short final-answer preview is printed on
stdout. Missing credentials produce a CI-safe skip.

Usage:
    conda run -n agent python scripts/smoke_agent_trace.py
    conda run -n agent python scripts/smoke_agent_trace.py --model qwen-vl-plus
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chartagent import Agent, ToolRegistry, build_attachment_turn  # noqa: E402
from chartagent.cli import AGENT_SYSTEM_PROMPT  # noqa: E402
from chartagent.client import LLMClient, load_environment  # noqa: E402
from chartagent.trace import JsonlTraceRenderer, TraceEvent  # noqa: E402
from chartagent.tools.chart import register_chart_tools  # noqa: E402
from tests.chart_fixtures import annotated_bar_chart  # noqa: E402


class _RecordingJsonlTrace:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.renderer = JsonlTraceRenderer(sys.stderr)

    def __call__(self, event: TraceEvent) -> None:
        self.events.append(event)
        self.renderer(event)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="Override DASH_MODEL.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=6,
        help="Maximum model/tool turns; clamped to the bounded range 1..8.",
    )
    args = parser.parse_args()
    max_steps = min(8, max(1, args.max_steps))

    load_environment()
    try:
        client = LLMClient()
    except ValueError as exc:
        print(f"SKIP: {exc}")
        return 0

    registry = ToolRegistry()
    register_chart_tools(registry)
    trace = _RecordingJsonlTrace()
    chat_kwargs = {"model": args.model} if args.model else {}
    agent = Agent(
        client,
        registry,
        system=AGENT_SYSTEM_PROMPT,
        max_steps=max_steps,
        trace=trace,
        **chat_kwargs,
    )

    with tempfile.TemporaryDirectory(prefix="chartagent-trace-") as raw_dir:
        chart_path = Path(raw_dir) / "known-bars.png"
        png_bytes, _ = annotated_bar_chart(
            values=(8, 16, 24),
            categories=("Alpha", "Beta", "Gamma"),
            source=str(chart_path),
        )
        chart_path.write_bytes(png_bytes)
        prompt = (
            "Inspect this chart and describe the bar count and values. "
            "Choose useful tools freely and use generated visual evidence when useful."
        )
        try:
            answer = agent.run(build_attachment_turn(prompt, [str(chart_path)]))
        except Exception as exc:  # noqa: BLE001 - smoke reports provider failures
            print(f"FAIL: provider call failed: {exc}")
            return 1

    counts: dict[str, int] = {}
    for event in trace.events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
    print(f"model={args.model or client.config.model or '<configured default>'}")
    print(f"trace_events={len(trace.events)} kinds={counts!r}")
    print(f"answer={answer[:500]!r}")
    if not counts.get("tool_call"):
        print("FAIL: provider trajectory contained no tool call")
        return 1
    print("agent trace smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
