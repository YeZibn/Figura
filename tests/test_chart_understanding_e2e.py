"""Offline full-loop acceptance test for annotated bar-chart restoration."""

from __future__ import annotations

import json

import pytest

from chartagent import Agent, ToolRegistry, build_user_content
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.chart import register_chart_tools
from tests.chart_fixtures import annotated_bar_chart, line_chart, pie_chart, scatter_chart


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
            "decompose_chart_image",
            "inspect_chart_layout",
            "measure_bars",
            "extract_line_series",
            "extract_pie_slices",
            "extract_scatter_points",
            "assemble_spec",
            "render_chart",
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
            measured_ratios = [bar["measure"]["ratio"] for bar in geometry["bars"]]
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
    assert client.stage == 4


class _MultiSeriesUnderstandingClient:
    """Script a non-fixed sensor order for a multi-series line restoration."""

    def __init__(self, image_path: str, ground_truth: dict) -> None:
        self.image_path = image_path
        self.ground_truth = ground_truth
        self.stage = 0
        self.assembled: dict | None = None

    def chat(self, messages, **kwargs):
        tool_names = {
            entry["function"]["name"] for entry in kwargs.get("tools", [])
        }
        assert "extract_line_series" in tool_names

        def last_tool_data() -> object:
            tool_messages = [message for message in messages if message["role"] == "tool"]
            assert tool_messages
            payload = json.loads(tool_messages[-1]["content"])
            return payload.get("data", payload)

        if self.stage == 0:
            # The model is free to inspect the image before using a sensor.
            result = _call("line", "extract_line_series", {"image_path": self.image_path})
        elif self.stage == 1:
            observed = last_tool_data()
            assert {entry["id"] for entry in observed["series"]} == {"series_1", "series_2"}
            assert all(entry["trace"]["polyline_px"] for entry in observed["series"])
            assert all(
                point["source"] in {"marker", "tick_sample"}
                for entry in observed["series"]
                for point in entry["points"]
            )
            points = [
                {
                    "x": point["x"],
                    "y": point["y"],
                    "series": point["series"],
                }
                for point in self.ground_truth["dataset"]
            ]
            result = _call(
                "assemble",
                "assemble_spec",
                {
                    "chart_type": "line",
                    "x_label": self.ground_truth["axes"]["x"]["label"],
                    "y_label": self.ground_truth["axes"]["y"]["label"],
                    "points": points,
                    "source": self.ground_truth["metadata"]["source"],
                },
            )
        elif self.stage == 2:
            self.assembled = last_tool_data()
            assert self.assembled["dataset"] == self.ground_truth["dataset"]
            result = NormalizedResult(content=json.dumps(self.assembled))
        else:
            raise AssertionError("unexpected extra model call")
        self.stage += 1
        return result


def test_agent_restores_multi_series_line_without_fixed_tool_sequence(tmp_path, monkeypatch):
    png_bytes, ground_truth = line_chart()
    image_path = tmp_path / "lines.png"
    image_path.write_bytes(png_bytes)
    # The deterministic sensor test focuses on series separation. The scripted
    # model supplies semantic values from the same fixture after observing it.
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.line.extract_text",
        lambda _path: __import__("chartagent.tools", fromlist=["ToolResult"]).ToolResult([]),
    )
    registry = ToolRegistry()
    register_chart_tools(registry)
    client = _MultiSeriesUnderstandingClient(str(image_path), ground_truth)
    agent = Agent(client, registry, system="Restore the line chart to ChartSpec.")

    answer = agent.run(
        build_user_content("Extract and validate the multi-series data.", [str(image_path)])
    )

    assert json.loads(answer) == client.assembled
    assert client.stage == 3


class _PieUnderstandingClient:
    def __init__(self, image_path: str) -> None:
        self.image_path = image_path
        self.stage = 0
        self.assembled: dict | None = None

    def chat(self, messages, **kwargs):
        def last_tool_data() -> object:
            tool_messages = [message for message in messages if message["role"] == "tool"]
            payload = json.loads(tool_messages[-1]["content"])
            return payload.get("data", payload)

        if self.stage == 0:
            result = _call("pie", "extract_pie_slices", {"image_path": self.image_path})
        elif self.stage == 1:
            observed = last_tool_data()
            assert observed["totals"]["consistent"] is True
            result = _call(
                "assemble",
                "assemble_spec",
                {
                    "chart_type": "pie",
                    "points": [
                        {"category": "Alpha", "value": 0.35},
                        {"category": "Beta", "value": 0.25},
                        {"category": "Gamma", "value": 0.20},
                        {"category": "Delta", "value": 0.20},
                    ],
                },
            )
        elif self.stage == 2:
            self.assembled = last_tool_data()
            assert self.assembled["axes"] is None
            result = NormalizedResult(content=json.dumps(self.assembled))
        else:
            raise AssertionError("unexpected extra model call")
        self.stage += 1
        return result


def test_agent_restores_pie_without_cartesian_tool_sequence(tmp_path, monkeypatch):
    png_bytes, _ = pie_chart(values=(35, 25, 20, 20))
    image_path = tmp_path / "pie.png"
    image_path.write_bytes(png_bytes)
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: __import__("chartagent.tools", fromlist=["ToolResult"]).ToolResult([]))

    registry = ToolRegistry()
    register_chart_tools(registry)
    client = _PieUnderstandingClient(str(image_path))
    agent = Agent(client, registry, system="Restore the pie chart to ChartSpec.")

    answer = agent.run(build_user_content("Extract and validate this pie chart.", [str(image_path)]))

    assert json.loads(answer) == client.assembled
    assert client.stage == 3


class _ScatterUnderstandingClient:
    def __init__(self, image_path: str, ground_truth: dict) -> None:
        self.image_path = image_path
        self.ground_truth = ground_truth
        self.stage = 0
        self.assembled: dict | None = None

    def chat(self, messages, **kwargs):
        tool_names = {
            entry["function"]["name"] for entry in kwargs.get("tools", [])
        }
        assert "extract_scatter_points" in tool_names

        def last_tool_data() -> object:
            tool_messages = [message for message in messages if message["role"] == "tool"]
            payload = json.loads(tool_messages[-1]["content"])
            return payload.get("data", payload)

        if self.stage == 0:
            result = _call(
                "scatter",
                "extract_scatter_points",
                {"image_path": self.image_path},
            )
        elif self.stage == 1:
            observed = last_tool_data()
            assert len(observed["series"]) == 2
            assert len(observed["points"]) == 10
            result = _call(
                "assemble",
                "assemble_spec",
                {
                    "chart_type": "scatter",
                    "x_label": self.ground_truth["axes"]["x"]["label"],
                    "y_label": self.ground_truth["axes"]["y"]["label"],
                    "points": self.ground_truth["dataset"],
                    "source": self.ground_truth["metadata"]["source"],
                },
            )
        elif self.stage == 2:
            self.assembled = last_tool_data()
            assert self.assembled["metadata"]["chart_type"] == "scatter"
            assert self.assembled["axes"] is not None
            result = NormalizedResult(content=json.dumps(self.assembled))
        else:
            raise AssertionError("unexpected extra model call")
        self.stage += 1
        return result


def test_agent_restores_scatter_without_fixed_tool_sequence(tmp_path, monkeypatch):
    png_bytes, ground_truth = scatter_chart()
    image_path = tmp_path / "scatter.png"
    image_path.write_bytes(png_bytes)
    monkeypatch.setattr(
        "chartagent.tools.chart.observation.scatter.extract_text",
        lambda _path: __import__("chartagent.tools", fromlist=["ToolResult"]).ToolResult([]),
    )

    registry = ToolRegistry()
    register_chart_tools(registry)
    client = _ScatterUnderstandingClient(str(image_path), ground_truth)
    agent = Agent(client, registry, system="Restore the scatter chart to ChartSpec.")

    answer = agent.run(
        build_user_content("Extract and validate this scatter chart.", [str(image_path)])
    )

    assert json.loads(answer) == client.assembled
    assert client.stage == 3
