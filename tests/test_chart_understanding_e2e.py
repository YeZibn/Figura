"""Offline full-loop acceptance test for annotated bar-chart restoration."""

from __future__ import annotations

import json

import pytest

from chartagent import Agent, AttachmentRegistry, ToolRegistry, build_registered_attachment_turn
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools.core import ToolResult
from chartagent.tools.chart import register_chart_tools
from chartagent.tools.chart.observation import line as line_observation
from chartagent.tools.chart.observation import scatter as scatter_observation
from tests.chart_fixtures import annotated_bar_chart, line_chart, pie_chart, scatter_chart


def _call(call_id: str, name: str, arguments: dict) -> NormalizedResult:
    return NormalizedResult(
        tool_calls=[
            ToolCall(id=call_id, name=name, arguments=json.dumps(arguments))
        ]
    )


def _augment_axis_ocr(original, *, y_values: list[int]):
    """Keep fixture OCR deterministic while supplying calibration anchors."""

    def read(path: str):
        result = original(path)
        snippets = list(result.data) if isinstance(result, ToolResult) and isinstance(result.data, list) else []
        snippets.extend(
            {
                "text": str(value),
                "bbox": [center_x - 4, 429, 8, 8],
                "confidence": 1.0,
            }
            for center_x, value in zip([104, 235, 366, 497, 628], [0, 1, 2, 3, 4])
        )
        y_centers = [428, 335, 242, 149, 57] if len(y_values) == 5 else [428, 322, 216, 110]
        snippets.extend(
            {
                "text": str(value),
                "bbox": [80, center_y - 4, 8, 8],
                "confidence": 1.0,
            }
            for center_y, value in zip(y_centers, y_values)
        )
        return ToolResult(snippets)

    return read


def _measurement_assembly_fields(observed: dict) -> dict:
    """Carry the exact candidate refs the scripted model uses into assembly."""
    measurement = observed.get("measurement")
    assert isinstance(measurement, dict)
    reference = measurement.get("reference")
    assert isinstance(reference, dict)
    result = {"measurement_ref": reference}
    evidence = measurement.get("evidence")
    refs = evidence.get("refs") if isinstance(evidence, dict) else []
    evidence_refs = [
        item.get("ref")
        for item in refs or []
        if isinstance(item, dict) and isinstance(item.get("ref"), str)
    ]
    if evidence_refs:
        result["evidence_refs"] = evidence_refs
    return result


class _UnderstandingClient:
    """Script the decisions while requiring every real tool observation."""

    def __init__(self, image_path: str, ground_truth: dict) -> None:
        self.image_path = image_path
        self.ground_truth = ground_truth
        self.attachment_id = ""
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
            result = _call("ocr", "extract_text", {"attachment_id": self.attachment_id})
        elif self.stage == 1:
            snippets = last_tool_data()
            expected = {
                f'{point["value"]:g}' for point in self.ground_truth["dataset"]
            }
            assert expected <= {snippet["text"] for snippet in snippets}
            result = _call("geometry", "measure_bars", {"attachment_id": self.attachment_id})
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
                    **_measurement_assembly_fields(geometry),
                },
            )
        elif self.stage == 3:
            self.assembled = last_tool_data()
            provenance = self.assembled.pop("provenance", None)
            assert isinstance(provenance, dict)
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

    attachments = AttachmentRegistry()
    attachment = attachments.register(str(image_path))
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    client = _UnderstandingClient(str(image_path), ground_truth)
    client.attachment_id = attachment.id
    agent = Agent(client, registry, system="Restore the chart to ChartSpec.", attachments=attachments)

    answer = agent.run(
        build_registered_attachment_turn("Extract and validate this chart.", [attachment.metadata()])
    )

    assert json.loads(answer) == ground_truth
    assert client.stage == 4


class _MultiSeriesUnderstandingClient:
    """Script a non-fixed sensor order for a multi-series line restoration."""

    def __init__(self, image_path: str, ground_truth: dict) -> None:
        self.image_path = image_path
        self.ground_truth = ground_truth
        self.attachment_id = ""
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
            result = _call("line", "extract_line_series", {"attachment_id": self.attachment_id})
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
                    **_measurement_assembly_fields(observed),
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
    png_bytes, ground_truth = line_chart(
        values_by_series={"North": (1, 2, 3, 4, 5), "South": (5, 6, 7, 8, 9)},
        markers=False,
    )
    image_path = tmp_path / "lines.png"
    image_path.write_bytes(png_bytes)
    attachments = AttachmentRegistry()
    attachment = attachments.register(str(image_path))
    # The deterministic sensor test focuses on series separation. The scripted
    # model supplies semantic values from the same fixture after observing it.
    monkeypatch.setattr(
        line_observation,
        "extract_text",
        _augment_axis_ocr(line_observation.extract_text, y_values=[0, 2, 4, 6]),
    )
    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    client = _MultiSeriesUnderstandingClient(str(image_path), ground_truth)
    client.attachment_id = attachment.id
    agent = Agent(client, registry, system="Restore the line chart to ChartSpec.", attachments=attachments)

    answer = agent.run(
        build_registered_attachment_turn("Extract and validate the multi-series data.", [attachment.metadata()])
    )

    assert json.loads(answer) == client.assembled
    assert client.stage == 3


class _PieUnderstandingClient:
    def __init__(self, image_path: str) -> None:
        self.image_path = image_path
        self.attachment_id = ""
        self.stage = 0
        self.assembled: dict | None = None

    def chat(self, messages, **kwargs):
        def last_tool_data() -> object:
            tool_messages = [message for message in messages if message["role"] == "tool"]
            payload = json.loads(tool_messages[-1]["content"])
            return payload.get("data", payload)

        if self.stage == 0:
            result = _call("pie", "extract_pie_slices", {"attachment_id": self.attachment_id})
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
                    **_measurement_assembly_fields(observed),
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
    attachments = AttachmentRegistry()
    attachment = attachments.register(str(image_path))
    monkeypatch.setattr("chartagent.tools.chart.observation.pie.extract_text", lambda _path: __import__("chartagent.tools", fromlist=["ToolResult"]).ToolResult([]))

    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    client = _PieUnderstandingClient(str(image_path))
    client.attachment_id = attachment.id
    agent = Agent(client, registry, system="Restore the pie chart to ChartSpec.", attachments=attachments)

    answer = agent.run(build_registered_attachment_turn("Extract and validate this pie chart.", [attachment.metadata()]))

    assert json.loads(answer) == client.assembled
    assert client.stage == 3


class _ScatterUnderstandingClient:
    def __init__(self, image_path: str, ground_truth: dict) -> None:
        self.image_path = image_path
        self.ground_truth = ground_truth
        self.attachment_id = ""
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
                {"attachment_id": self.attachment_id},
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
                    **_measurement_assembly_fields(observed),
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
    attachments = AttachmentRegistry()
    attachment = attachments.register(str(image_path))
    monkeypatch.setattr(
        scatter_observation,
        "extract_text",
        _augment_axis_ocr(scatter_observation.extract_text, y_values=[0, 2, 4, 6, 8]),
    )
    original_legend_entries = scatter_observation._legend_entries

    def labelled_legend(*args, **kwargs):
        entries = original_legend_entries(*args, **kwargs)
        return [
            {**entry, "label": entry.get("label") or label}
            for entry, label in zip(entries, ["North", "South"])
        ]

    monkeypatch.setattr(scatter_observation, "_legend_entries", labelled_legend)

    registry = ToolRegistry()
    register_chart_tools(registry, attachments=attachments)
    client = _ScatterUnderstandingClient(str(image_path), ground_truth)
    client.attachment_id = attachment.id
    agent = Agent(client, registry, system="Restore the scatter chart to ChartSpec.", attachments=attachments)

    answer = agent.run(
        build_registered_attachment_turn("Extract and validate this scatter chart.", [attachment.metadata()])
    )

    assert json.loads(answer) == client.assembled
    assert client.stage == 3
