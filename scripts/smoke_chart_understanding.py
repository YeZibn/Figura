#!/usr/bin/env python3
"""Live U0 acceptance smoke for annotated bar-chart understanding.

Generates two clean charts, sends each image to the configured multimodal model,
and checks freely planned restoration against each chart's ground-truth dataset.
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

from chartagent import Agent, ToolRegistry, build_attachment_turn  # noqa: E402
from chartagent.cli import AGENT_SYSTEM_PROMPT  # noqa: E402
from chartagent.client import LLMClient, load_environment  # noqa: E402
from chartagent.tools.chart import register_chart_tools  # noqa: E402
from chartagent.tools.chart.spec_tools import validate_spec  # noqa: E402
from tests.chart_fixtures import annotated_bar_chart  # noqa: E402


def _json_object(text: str) -> dict:
    """Extract one JSON object even if a provider adds surrounding prose."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model response did not contain a JSON object")


def _case(
    client: LLMClient,
    directory: Path,
    index: int,
    values: tuple[float, ...],
    categories: tuple[str, ...],
    model: str | None,
) -> tuple[bool, str]:
    image_path = directory / f"u0-{index}.png"
    png_bytes, expected = annotated_bar_chart(
        values,
        categories,
        title=f"U0 Sales {index}",
        source=str(image_path),
    )
    image_path.write_bytes(png_bytes)

    registry = ToolRegistry()
    register_chart_tools(registry)
    chat_kwargs: dict[str, Any] = {}
    if model:
        chat_kwargs["model"] = model
    agent = Agent(
        client,
        registry,
        system=AGENT_SYSTEM_PROMPT,
        max_steps=8,
        **chat_kwargs,
    )
    prompt = (
        "Restore the underlying data from this annotated bar chart as a valid "
        "ChartSpec JSON object."
    )
    answer = agent.run(build_attachment_turn(prompt, [str(image_path)]))

    called = [
        call["function"]["name"]
        for message in agent.messages
        for call in message.get("tool_calls", [])
    ]
    try:
        actual = _json_object(answer)
    except ValueError as exc:
        return False, f"{exc}; tools={called!r}; answer={answer!r}"

    validation = validate_spec(actual)
    if not validation["ok"]:
        return False, f"validation={validation!r}\ntools={called!r}"

    expected_dataset = [
        (point["category"], float(point["value"]))
        for point in expected["dataset"]
    ]
    actual_dataset = [
        (point.get("category"), float(point["value"]))
        for point in actual.get("dataset", [])
    ]
    if actual_dataset != expected_dataset:
        return False, (
            f"validation={validation!r}\n"
            f"expected_dataset={expected_dataset!r}\n"
            f"actual_dataset={actual_dataset!r}\n"
            f"tools={called!r}"
        )
    return True, f"dataset={actual_dataset!r}; tools={called!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="Override DASH_MODEL.")
    args = parser.parse_args()

    load_environment()
    try:
        client = LLMClient()
    except ValueError as exc:
        print(f"SKIP: {exc}")
        return 0

    cases = [
        ((8.0, 16.0, 24.0), ("Alpha", "Beta", "Gamma")),
        ((12.0, 18.0, 30.0, 24.0), ("North", "South", "East", "West")),
    ]
    failures = 0
    with tempfile.TemporaryDirectory(prefix="chartagent-u0-") as raw_dir:
        directory = Path(raw_dir)
        for index, (values, categories) in enumerate(cases, start=1):
            try:
                ok, detail = _case(
                    client, directory, index, values, categories, args.model
                )
            except Exception as exc:  # noqa: BLE001 - smoke should report all cases
                ok, detail = False, str(exc)
            status = "PASS" if ok else "FAIL"
            print(f"case {index}: {status} - {detail}")
            failures += int(not ok)

    if failures:
        print(f"U0 smoke failed: {failures}/{len(cases)} case(s)")
        return 1
    print(f"U0 smoke passed: {len(cases)}/{len(cases)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
