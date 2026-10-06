"""Resolve an authorized Attachment or Panel for a measurement tool call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_resources import AttachmentContent, ImageResourceRef, PanelContent, RunExecutionState
from figura.runtime.errors import RunError

from figura.tools.contracts import ToolFailure


@dataclass(frozen=True)
class MeasurementSource:
    source_kind: Literal["attachment", "panel"]
    source_id: str
    name: str
    coordinate_system: Literal["attachment_px", "panel_px"]
    image_bytes: bytes
    width: int
    height: int


def resolve_measurement_source(
    session_id: str,
    source_kind: Literal["attachment", "panel"],
    source_id: str,
    inventory: Callable[[str, str], RunExecutionState],
    image_reader: RunExecutionImageReader,
    run_id: str,
) -> MeasurementSource:
    state = inventory(session_id, run_id)
    ref = ImageResourceRef(source_kind, source_id)
    try:
        resource = state.get(ref)
    except RunError:
        raise ToolFailure("image_not_available", "请求的图像不在当前 Session 的可用清单中。") from None
    if source_kind == "attachment":
        if not isinstance(resource.content, AttachmentContent):
            raise ToolFailure("image_not_available", "请求的附件类型无效。")
        name = resource.content.filename
        coordinate_system: Literal["attachment_px", "panel_px"] = "attachment_px"
    else:
        if not isinstance(resource.content, PanelContent):
            raise ToolFailure("image_not_available", "请求的 Panel 类型无效。")
        name = resource.content.name
        coordinate_system = "panel_px"

    try:
        image_bytes, width, height = image_reader.read_source(session_id, state, ref)
    except RunError:
        raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True)
    if not image_bytes:
        raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True)
    return MeasurementSource(source_kind, source_id, name, coordinate_system, image_bytes, width, height)
