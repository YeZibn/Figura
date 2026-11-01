"""Resolve authorized committed media; normal reads never draw or repair images."""
from __future__ import annotations

from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.media import ResourceImage, ToolImageAttachment
from figura.shared.resource_refs import ImageResourceRef, ResourceRef
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.panels import FiguraPanelService
from figura.sources.tool_media import FiguraToolMediaService, ToolMediaCommitter
from figura.tools import ToolOutcome
from .execution_resources import AttachmentContent, PanelContent, RunExecutionState


class RunExecutionImageReader:
    def __init__(self, attachments: FiguraAttachmentService, panels: FiguraPanelService,
                 chart_renders: FiguraChartRenderService | None = None,
                 media: FiguraToolMediaService | None = None) -> None:
        self._attachments, self._panels, self._chart_renders = attachments, panels, chart_renders
        self._media = media or FiguraToolMediaService(attachments.data_root)

    def media_committer(self, inventory) -> ToolMediaCommitter:
        """Compose the neutral installer with this reader's full authorization path."""
        def resolve(context, ref):
            state = inventory(context.session_id, context.run_id)
            descriptor = self.descriptor(context.session_id, state, ref)
            return self.read_attachment(context.session_id, state, descriptor), descriptor
        return ToolMediaCommitter(self._media, resolve, renders=self._chart_renders)

    def read_source(self, session_id: str, state: RunExecutionState,
                    ref: ImageResourceRef) -> tuple[bytes, int, int]:
        resource = state.get(ref)
        if ref.kind == 'attachment':
            content = resource.content
            if not isinstance(content, AttachmentContent) or content.session_id != session_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            image = self._attachments.resolve(session_id, ref.id)
            if image.media_type != content.media_type or len(image.image_bytes) != content.byte_count:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            content = resource.content
            if not isinstance(content, PanelContent) or content.session_id != session_id:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            record, image, _, _ = self._panels.resolve(session_id, ref.id)
            if (record.run_id != content.run_id or record.source_attachment_id != content.source_attachment_id
                    or record.name != content.name or record.points != content.points):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return image.image_bytes, image.width, image.height

    def descriptor(self, session_id: str, state: RunExecutionState, ref: ResourceRef) -> ToolImageAttachment:
        content = state.get(ref).content
        if isinstance(ref, ImageResourceRef):
            raw, _, _ = self.read_source(session_id, state, ref)
            return ToolImageAttachment.describe(ref, 'original', ResourceImage.from_bytes(raw))
        if ref.kind == 'chart_figure' or getattr(content, 'outcome', None) is not ToolOutcome.SUCCEEDED:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        attachments = getattr(content, 'attachments', ())
        if len(attachments) != 1 or attachments[0].resource_ref != ref:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return attachments[0]

    def read_attachment(self, session_id: str, state: RunExecutionState,
                        descriptor: ToolImageAttachment) -> ResourceImage:
        ref = descriptor.resource_ref
        expected = self.descriptor(session_id, state, ref)
        if expected != descriptor:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if isinstance(ref, ImageResourceRef):
            raw, _, _ = self.read_source(session_id, state, ref)
            image = ResourceImage.from_bytes(raw)
        elif descriptor.image_kind in {'ocr_annotation', 'measurement_annotation'}:
            # The source must still be authorized, but reading annotations does not reread/repaint it.
            source_ref = getattr(state.get(ref).content, 'source_ref', None)
            if source_ref is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            state.get(source_ref)
            image = self._media.read(session_id, descriptor)
        elif descriptor.image_kind == 'rendered' and self._chart_renders is not None:
            raw, _, _ = self._chart_renders.resolve(ref.run_id, ref.call_id)
            image = ResourceImage.from_bytes(raw)
            result = state.get(ref).content.result
            if (result.get('image_sha256') != descriptor.sha256 or result.get('byte_count') != descriptor.byte_count
                    or result.get('width') != descriptor.width or result.get('height') != descriptor.height
                    or result.get('media_type') != descriptor.media_type):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        else:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        try:
            descriptor.verify(image)
        except ValueError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        return image

    def read(self, session_id: str, state: RunExecutionState, ref: ResourceRef) -> tuple[bytes, int, int]:
        descriptor = self.descriptor(session_id, state, ref)
        image = self.read_attachment(session_id, state, descriptor)
        return image.image_bytes, image.width, image.height
