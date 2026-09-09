#!/usr/bin/env python3
"""Live provider smoke for chart-tool JSON plus generated-image observations.

The prompt leaves tool choice to the model. The smoke records the exact
message roles sent on each turn and verifies that any generated overlay is
placed after all native tool messages before the next model request.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chartagent import Agent, ToolRegistry  # noqa: E402
from chartagent.attachments import AttachmentRegistry  # noqa: E402
from chartagent.multimodal import build_registered_attachment_turn  # noqa: E402
from chartagent.cli import AGENT_SYSTEM_PROMPT  # noqa: E402
from chartagent.client import LLMClient, load_environment  # noqa: E402
from chartagent.tools.chart import register_chart_tools  # noqa: E402
from tests.chart_fixtures import annotated_bar_chart  # noqa: E402


class RecordingClient:
    """Record requests while delegating provider calls to the real client."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, messages, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return self.client.chat(messages, **kwargs)


def _tool_names(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        for call in message.get("tool_calls", []):
            names.append(call["function"]["name"])
    return names


def _observation_check(requests: list[list[dict[str, Any]]]) -> tuple[bool, str]:
    """Check native tool ordering and count generated multimodal turns."""
    evidence_turns = 0
    generated_images = 0
    for messages in requests:
        for index, message in enumerate(messages):
            if message.get("role") != "user" or not isinstance(message.get("content"), list):
                continue
            content = message["content"]
            if not content or content[0].get("type") != "text":
                continue
            if "Tool-generated visual evidence follows." not in content[0].get("text", ""):
                continue
            evidence_turns += 1
            generated_images += sum(part.get("type") == "image_url" for part in content)
            prior_roles = [entry.get("role") for entry in messages[:index]]
            if not prior_roles or prior_roles[-1] != "tool":
                return False, "evidence turn was not preceded by a native tool message"
            if "assistant" not in prior_roles:
                return False, "evidence turn had no originating assistant tool-call turn"
    if evidence_turns == 0:
        return False, "provider trajectory produced no generated visual evidence turn"
    if generated_images == 0:
        return False, "evidence turn contained no image parts"
    return True, f"evidence_turns={evidence_turns}; generated_images={generated_images}"


def _answer_mentions_fixture(answer: str) -> bool:
    normalized = answer.lower()
    return all(token in normalized for token in ("8", "16", "24")) and (
        "3" in normalized or "three" in normalized
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="Override DASH_MODEL.")
    args = parser.parse_args()

    load_environment()
    try:
        provider = LLMClient()
    except ValueError as exc:
        print(f"SKIP: {exc}")
        return 0

    attachments = AttachmentRegistry()
    registry = ToolRegistry()
    registry.register(attachments.load_tool())
    register_chart_tools(registry, attachments=attachments)
    recorder = RecordingClient(provider)
    chat_kwargs: dict[str, Any] = {}
    if args.model:
        chat_kwargs["model"] = args.model
    agent = Agent(
        recorder,
        registry,
        system=AGENT_SYSTEM_PROMPT,
        max_steps=8,
        **chat_kwargs,
    )

    with tempfile.TemporaryDirectory(prefix="chartagent-observation-") as raw_dir:
        chart_path = Path(raw_dir) / "known-bars.png"
        png_bytes, _ = annotated_bar_chart(
            values=(8, 16, 24),
            categories=("Alpha", "Beta", "Gamma"),
            source=str(chart_path),
        )
        chart_path.write_bytes(png_bytes)
        prompt = (
            "Inspect this chart and describe the visual evidence you find, "
            "including the number of bars and their values. Choose any useful "
            "tools yourself; do not assume a prescribed tool order."
        )
        try:
            attachment = attachments.register(str(chart_path))
            answer = agent.run(build_registered_attachment_turn(prompt, [attachment.metadata()]))
        except Exception as exc:  # noqa: BLE001 - smoke reports provider failures
            print(f"FAIL: provider call failed: {exc}")
            return 1

    names = _tool_names([message for request in recorder.requests for message in request])
    observation_ok, observation_detail = _observation_check(recorder.requests)
    answer_ok = _answer_mentions_fixture(answer)
    model_name = args.model or provider.config.model or "<call-time/default>"
    print(f"model={model_name}")
    print(f"requests={len(recorder.requests)}; tool_trace={names!r}")
    print(f"message_sequence={[[message.get('role') for message in request] for request in recorder.requests]!r}")
    print(f"observation={observation_detail}")
    print(f"answer_check={'PASS' if answer_ok else 'FAIL'}")
    print(f"answer={answer[:500]!r}")

    if not observation_ok:
        print(f"FAIL: {observation_detail}")
        return 1
    if not names:
        print("FAIL: model did not execute a chart tool")
        return 1
    if not answer_ok:
        print("FAIL: answer did not mention the known bar values and count")
        return 1
    print("multimodal tool-observation smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
