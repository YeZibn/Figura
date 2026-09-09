"""Offline full-loop acceptance test for annotated bar-chart restoration."""

from __future__ import annotations

import json

import pytest

from chartagent import Agent, ToolRegistry, build_user_content
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.chart import register_chart_tools
from tests.chart_fixtures import annotated_bar_chart


def _call(call_id: str, name: str, arguments: dict) -> NormalizedResult:
    return NormalizedResult(
        tool_calls=[
            ToolCall(id=call_id, name=name, arguments=json.dumps(arguments))
        ]
    )


class _UnderstandingClient:
    """Script the decisions while requiring every real tool observation."""

    def __init__(self, image_path: str, ground_truth: dict) -> None:
        self.image_path = image_path
        self.ground_truth = ground_truth
        self.stage = 0
        self.assembled: dict | None = None

    def chat(self, messages, **kwargs):
        tool_names = {
            entry["function"]["name"] for entry in kwargs.get("tools", [])
        }
        assert tool_names == {
            "extract_text",
            "measure_bars",
            "assemble_spec",
            "validate_spec",
        }

        def last_tool_data() -> object:
            tool_messages = [message for message in messages if message["role"] == "tool"]
            assert tool_messages
            payload = json.loads(tool_messages[-1]["content"])
            return payload.get("data", payload)

        if self.stage == 0:
            user_content = messages[-1]["content"]
            assert isinstance(user_content, list)
            assert user_content[1]["type"] == "image_url"
            result = _call("ocr", "extract_text", {"image_path": self.image_path})
        elif self.stage == 1:
            snippets = last_tool_data()
            expected = {
                f'{point["value"]:g}' for point in self.ground_truth["dataset"]
            }
            assert expected <= {snippet["text"] for snippet in snippets}
            result = _call("geometry", "measure_bars", {"image_path": self.image_path})
        elif self.stage == 2:
            geometry = last_tool_data()
            values = [point["value"] for point in self.ground_truth["dataset"]]
            expected_ratios = [value / min(values) for value in values]
            measured_ratios = [bar["ratio"] for bar in geometry["bars"]]
            assert measured_ratios == pytest.approx(expected_ratios, rel=0.1)
            result = _call(
                "assemble",
                "assemble_spec",
                {
                    "chart_type": "bar",
                    "title": self.ground_truth["metadata"]["title"],
                    "x_label": self.ground_truth["axes"]["x"]["label"],
                    "y_label": self.ground_truth["axes"]["y"]["label"],
                    "points": [
                        {"category": point["category"], "value": point["value"]}
                        for point in self.ground_truth["dataset"]
                    ],
                    "source": self.ground_truth["metadata"]["source"],
                },
            )
        elif self.stage == 3:
            self.assembled = last_tool_data()
            assert self.assembled == self.ground_truth
            result = _call("validate", "validate_spec", {"spec": self.assembled})
        elif self.stage == 4:
            validation = last_tool_data()
            assert validation == {"ok": True, "issues": []}
            result = NormalizedResult(content=json.dumps(self.assembled))
        else:
            raise AssertionError("unexpected extra model call")

        self.stage += 1
        return result


def test_agent_restores_annotated_bar_chart_through_full_tool_loop(tmp_path):
    png_bytes, ground_truth = annotated_bar_chart(values=(8, 16, 24))
    image_path = tmp_path / "bars.png"
    image_path.write_bytes(png_bytes)

    registry = ToolRegistry()
    register_chart_tools(registry)
    client = _UnderstandingClient(str(image_path), ground_truth)
    agent = Agent(client, registry, system="Restore the chart to ChartSpec.")

    answer = agent.run(
        build_user_content("Extract and validate this chart.", [str(image_path)])
    )

    assert json.loads(answer) == ground_truth
    assert client.stage == 5
