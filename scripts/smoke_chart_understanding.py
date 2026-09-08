#!/usr/bin/env python3
"""Live U0 acceptance smoke for annotated bar-chart understanding.

Generates two clean charts, sends each image to the configured multimodal model,
and requires the Agent to use OCR, geometry, assembly, and validation tools.
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

from chartagent import Agent, ToolRegistry, build_user_content  # noqa: E402
from chartagent.client import LLMClient, load_environment  # noqa: E402
from chartagent.tools.chart import register_chart_tools  # noqa: E402
from chartagent.tools.chart.spec_tools import validate_spec  # noqa: E402
from tests.chart_fixtures import annotated_bar_chart  # noqa: E402

SYSTEM_PROMPT = """You restore clean annotated bar charts to ChartSpec JSON.
For every image, you MUST follow this order:
1. Call extract_text with the exact local image path from the user prompt.
2. Call measure_bars with that same path.
3. Compare printed annotation values with the bar-height ratios. Use the values
   consistent with both evidence channels.
4. Call assemble_spec. Never hand-write the intermediate spec.
5. Call validate_spec with the assembled spec. If invalid, fix and validate it.
After validation succeeds, answer with exactly the assembled ChartSpec JSON and
no markdown or explanation.
"""


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
        system=SYSTEM_PROMPT,
        max_steps=8,
        **chat_kwargs,
    )
    prompt = (
        f"Restore this annotated bar chart. Its local image path is {image_path}."
    )
    answer = agent.run(build_user_content(prompt, [str(image_path)]))
    actual = _json_object(answer)

    called = [
        call["function"]["name"]
        for message in agent.messages
        for call in message.get("tool_calls", [])
    ]
    required = ["extract_text", "measure_bars", "assemble_spec", "validate_spec"]
    positions = [called.index(name) for name in required if name in called]
    if len(positions) != len(required) or positions != sorted(positions):
        return False, f"required tool order missing; called={called!r}"

    validation = validate_spec(actual)
    expected_dataset = [
        (point["category"], float(point["value"]))
        for point in expected["dataset"]
    ]
    actual_dataset = [
        (point.get("category"), float(point["value"]))
        for point in actual.get("dataset", [])
    ]
    if not validation["ok"] or actual_dataset != expected_dataset:
        return False, (
            f"validation={validation!r}\n"
            f"expected_dataset={expected_dataset!r}\n"
            f"actual_dataset={actual_dataset!r}"
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
