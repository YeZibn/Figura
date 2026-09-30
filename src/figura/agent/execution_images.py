"""Read authorized images referenced by a Run's resource catalog."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from io import BytesIO

from PIL import Image

from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.image_limits import MAX_IMAGE_BYTES
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.tools import ToolOutcome
from figura.tools.measurements.visualization import render_measurement_overlay

from .execution_resources import (
    AttachmentContent,
    ChartRenderContent,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)


class RunExecutionImageReader:
    __slots__ = ("_attachments", "_panels", "_chart_renders")

    def __init__(
        self,
        attachments: FiguraAttachmentService,
        panels: FiguraPanelService,
        chart_renders: FiguraChartRenderService | None = None,
    ) -> None:
        if not isinstance(attachments, FiguraAttachmentService) or not isinstance(panels, FiguraPanelService):
            raise TypeError("invalid RunExecutionImageReader sources")
        if chart_renders is not None and not isinstance(chart_renders, FiguraChartRenderService):
            raise TypeError("chart_renders must be a FiguraChartRenderService")
        object.__setattr__(self, "_attachments", attachments)
        object.__setattr__(self, "_panels", panels)
        object.__setattr__(self, "_chart_renders", chart_renders)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("RunExecutionImageReader is immutable")

    def read_source(
        self,
        session_id: str,
        state: RunExecutionState,
        ref: ImageResourceRef,
    ) -> tuple[bytes, int, int]:
        resource = state.get(ref)
        if ref.kind == "attachment":
            if not isinstance(resource.content, AttachmentContent) or resource.content.session_id != session_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            block = self._attachments.resolve(session_id, ref.id)
            if (
                block.media_type != resource.content.media_type
                or len(block.image_bytes) != resource.content.byte_count
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            width, height = _image_dimensions(block.image_bytes)
            return block.image_bytes, width, height

        if not isinstance(resource.content, PanelContent) or resource.content.session_id != session_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        record, block, width, height = self._panels.resolve(session_id, ref.id)
        if (
            record.run_id != resource.content.run_id
            or record.source_attachment_id != resource.content.source_attachment_id
            or record.name != resource.content.name
            or record.points != resource.content.points
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return block.image_bytes, width, height

    def read(
        self,
        session_id: str,
        state: RunExecutionState,
        ref: ImageResourceRef | ToolResourceRef,
    ) -> tuple[bytes, int, int]:
        resource = state.get(ref)
        if isinstance(ref, ImageResourceRef):
            return self.read_source(session_id, state, ref)

        content = resource.content
        if ref.kind in {"ocr", "measurement"}:
            if (
                not isinstance(content, (OcrContent, MeasurementContent))
                or content.outcome is not ToolOutcome.SUCCEEDED
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if content.result is None or content.source_ref is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            image_bytes, source_width, source_height = self.read_source(session_id, state, content.source_ref)
            image_size = content.result.get("image_size")
            if (
                not isinstance(image_size, Mapping)
                or image_size.get("width") != source_width
                or image_size.get("height") != source_height
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            tool_name = "extract_text" if isinstance(content, OcrContent) else content.tool_name
            try:
                annotated = render_measurement_overlay(image_bytes, content.result, tool_name)
            except (TypeError, ValueError, OSError):
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
            if not annotated or len(annotated) > MAX_IMAGE_BYTES:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            width, height = _image_dimensions(annotated)
            if (width, height) != (source_width, source_height):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return annotated, width, height

        if ref.kind == "chart_render":
            if not isinstance(content, ChartRenderContent) or content.outcome is not ToolOutcome.SUCCEEDED:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            if content.result is None or self._chart_renders is None:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            image_bytes, width, height = self._chart_renders.resolve(ref.run_id, ref.call_id)
            result = content.result
            if (
                hashlib.sha256(image_bytes).hexdigest() != result.get("image_sha256")
                or len(image_bytes) != result.get("byte_count")
                or width != result.get("width")
                or height != result.get("height")
                or result.get("media_type") != "image/png"
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return image_bytes, width, height

        raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)


def _image_dimensions(content: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            return image.size
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
