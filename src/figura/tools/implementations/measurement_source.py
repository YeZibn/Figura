"""Resolve an authorized Attachment or Panel for a measurement tool call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from figura.runtime.errors import RunError
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.models import PanelRecord
from figura.sources.panels import FiguraPanelService

from figura.tools.contracts import ToolFailure


class _AvailableAttachment(Protocol):
    attachment_id: str
    filename: str


class _RunImageInventory(Protocol):
    available_attachments: tuple[_AvailableAttachment, ...]
    panels: tuple[PanelRecord, ...]


@dataclass(frozen=True)
class MeasurementSource:
    source_kind: Literal["attachment", "panel"]
    source_id: str
    name: str
    coordinate_system: Literal["attachment_px", "panel_px"]
    image_bytes: bytes


def resolve_measurement_source(
    session_id: str,
    source_kind: Literal["attachment", "panel"],
    source_id: str,
    inventory: Callable[[str, str], _RunImageInventory],
    attachments: FiguraAttachmentService,
    panels: FiguraPanelService,
    run_id: str,
) -> MeasurementSource:
    state = inventory(session_id, run_id)
    if source_kind == "attachment":
        item = next(
            (entry for entry in state.available_attachments if entry.attachment_id == source_id),
            None,
        )
        if item is None:
            raise ToolFailure("image_not_available", "请求的附件不在当前 Session 的可用清单中。")
        try:
            image = attachments.resolve(session_id, source_id)
        except RunError:
            raise ToolFailure("image_unavailable", "附件图像当前无法读取。", retryable=True) from None
        name = item.filename
        coordinate_system: Literal["attachment_px", "panel_px"] = "attachment_px"
    else:
        item = next((entry for entry in state.panels if entry.panel_id == source_id), None)
        if item is None:
            raise ToolFailure("image_not_available", "请求的 Panel 不在当前 Session 的可用清单中。")
        try:
            _record, image, _width, _height = panels.resolve(session_id, source_id)
        except RunError:
            raise ToolFailure("image_unavailable", "Panel 图像当前无法读取。", retryable=True) from None
        name = item.name
        coordinate_system = "panel_px"

    if not isinstance(image.image_bytes, bytes) or not image.image_bytes:
        raise ToolFailure("image_unavailable", "图像内容当前无法用于测量。", retryable=True)
    return MeasurementSource(source_kind, source_id, name, coordinate_system, image.image_bytes)
