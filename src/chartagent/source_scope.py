"""Resolve generation context into an authorized source crop.

The resolver is deliberately independent from review and measurement.  Those
consumers need the same attachment/panel authorization and must not each
invent their own fallback to the full dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .attachments import AttachmentRegistry
from .panels import PanelHandoff, normalize_bbox
from .spec import GenerationContext, GenerationMode


MAX_SCOPE_PANELS = 16
MAX_SCOPE_ISSUES = 8


@dataclass(frozen=True)
class SourceScopeResolution:
    """Bounded result of resolving one generation source scope."""

    status: str
    attachment_id: str | None = None
    panel_ids: tuple[str, ...] = ()
    media_type: str = "image/png"
    content: bytes = field(default=b"", repr=False, compare=False)
    effective_scope: dict[str, Any] = field(default_factory=dict)
    handoffs: tuple[PanelHandoff, ...] = ()
    issues: tuple[dict[str, str], ...] = ()
    action_hint: str | None = None

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and bool(self.content)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "attachment_id": self.attachment_id,
            "panel_ids": list(self.panel_ids[:MAX_SCOPE_PANELS]),
            "effective_scope": dict(self.effective_scope),
            "issues": [dict(item) for item in self.issues[:MAX_SCOPE_ISSUES]],
        }
        if self.action_hint:
            result["action_hint"] = self.action_hint[:160]
        if self.resolved:
            result["media_type"] = self.media_type
            result["byte_count"] = len(self.content)
        return result


def _failure(
    status: str,
    message: str,
    *,
    attachment_id: str | None = None,
    panel_ids: tuple[str, ...] = (),
    action_hint: str | None = None,
) -> SourceScopeResolution:
    return SourceScopeResolution(
        status=status,
        attachment_id=attachment_id,
        panel_ids=panel_ids,
        issues=({"location": "source_scope", "message": message[:240]},),
        action_hint=action_hint,
    )


def _handoff_for_panel(
    store: Any,
    panel_id: str,
    *,
    attachment_id: str,
    revision: int | None,
) -> PanelHandoff | None:
    getter = getattr(store, "get_panel_handoff", None)
    if not callable(getter):
        return None
    try:
        return getter(panel_id, attachment_id=attachment_id, revision=revision)
    except TypeError:
        # Keep compatibility with lightweight panel stores used by tests and
        # adapters that do not yet expose the revision keyword.
        try:
            return getter(panel_id, attachment_id=attachment_id)
        except (TypeError, ValueError):
            return None
    except (TypeError, ValueError):
        return None


def _union_bbox(handoffs: tuple[PanelHandoff, ...]) -> list[int] | None:
    boxes = [normalize_bbox(item.analysis_scope) for item in handoffs]
    boxes = [item for item in boxes if item is not None]
    if not boxes:
        return None
    left = min(item[0] for item in boxes)
    top = min(item[1] for item in boxes)
    right = max(item[0] + item[2] for item in boxes)
    bottom = max(item[1] + item[3] for item in boxes)
    return [left, top, max(1, right - left), max(1, bottom - top)]


def _crop_image(raw: bytes, bbox: list[int]) -> bytes:
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
        left, top, box_width, box_height = bbox
        left = max(0, min(max(0, width - 1), left))
        top = max(0, min(max(0, height - 1), top))
        right = min(width, left + max(1, box_width))
        bottom = min(height, top + max(1, box_height))
        if right <= left or bottom <= top:
            raise ValueError("source scope bbox is outside the attachment")
        crop = image.crop((left, top, right, bottom))
        output = BytesIO()
        crop.save(output, format="PNG")
        return output.getvalue()


def resolve_generation_scope(
    attachments: AttachmentRegistry | None,
    context: GenerationContext | None,
) -> SourceScopeResolution:
    """Resolve one context into a crop without widening its authorization."""
    if context is None:
        return _failure(
            "source_scope_unavailable",
            "generation context is missing; source scope cannot be resolved",
            action_hint="提供 generation_context.source_scope，或将任务声明为 synthesize",
        )
    scope = context.source_scope
    if scope is None:
        if context.mode is GenerationMode.SYNTHESIZE:
            return SourceScopeResolution(status="not_applicable")
        return _failure(
            "source_scope_unavailable",
            "source-linked generation mode has no source scope",
            action_hint="重新绑定 attachment_id 和 panel_id",
        )
    attachment_id = scope.attachment_id
    panel_ids = tuple(scope.panel_ids[:MAX_SCOPE_PANELS])
    if not attachment_id or not panel_ids:
        return _failure(
            "ambiguous",
            "source scope must include one attachment and at least one panel",
            attachment_id=attachment_id,
            panel_ids=panel_ids,
            action_hint="补充明确的 attachment_id 和 panel_ids",
        )
    if attachments is None:
        return _failure(
            "source_scope_unavailable",
            "authorized attachment registry is unavailable",
            attachment_id=attachment_id,
            panel_ids=panel_ids,
            action_hint="重新绑定当前 session 的附件",
        )
    attachment, error = attachments.validate(attachment_id)
    if error or attachment is None:
        status = "stale" if error and "changed" in error else "source_scope_unavailable"
        return _failure(
            status,
            error or "authorized attachment is unavailable",
            attachment_id=attachment_id,
            panel_ids=panel_ids,
            action_hint="重新绑定附件或重新生成 panel handoff",
        )
    store = getattr(attachments, "panel_store", None)
    if store is None:
        return _failure(
            "source_scope_unavailable",
            "panel handoff store is unavailable",
            attachment_id=attachment_id,
            panel_ids=panel_ids,
            action_hint="先完成 dashboard panel handoff",
        )
    handoffs: list[PanelHandoff] = []
    for panel_id in panel_ids:
        handoff = _handoff_for_panel(
            store,
            panel_id,
            attachment_id=attachment_id,
            revision=scope.revision,
        )
        if handoff is None:
            if scope.revision is not None:
                current = _handoff_for_panel(
                    store,
                    panel_id,
                    attachment_id=attachment_id,
                    revision=None,
                )
                if current is not None and current.revision != scope.revision:
                    return _failure(
                        "stale",
                        f"panel handoff revision is stale for {panel_id}",
                        attachment_id=attachment_id,
                        panel_ids=panel_ids,
                        action_hint="重新读取当前 active panel handoff revision",
                    )
            return _failure(
                "ambiguous",
                f"active panel handoff is unavailable for {panel_id}",
                attachment_id=attachment_id,
                panel_ids=panel_ids,
                action_hint="重新拆解或重新绑定指定 panel",
            )
        if handoff.session_id != getattr(attachments, "session_id", None) and getattr(attachments, "session_id", None) is not None:
            return _failure(
                "stale",
                f"panel handoff session does not match attachment session for {panel_id}",
                attachment_id=attachment_id,
                panel_ids=panel_ids,
                action_hint="使用当前 session 的 panel handoff",
            )
        if handoff.attachment_id != attachment.id or handoff.attachment_sha256 != attachment.sha256:
            return _failure(
                "stale",
                f"panel handoff is stale for {panel_id}",
                attachment_id=attachment_id,
                panel_ids=panel_ids,
                action_hint="重新生成 panel handoff",
            )
        if handoff.status != "active":
            return _failure(
                "stale",
                f"panel handoff is not active for {panel_id}",
                attachment_id=attachment_id,
                panel_ids=panel_ids,
                action_hint="重新绑定有效 panel",
            )
        handoffs.append(handoff)
    union = _union_bbox(tuple(handoffs))
    if union is None:
        return _failure(
            "ambiguous",
            "panel handoff has no usable analysis scope",
            attachment_id=attachment_id,
            panel_ids=panel_ids,
            action_hint="重新生成带有有效 bbox 的 panel handoff",
        )
    try:
        raw = Path(attachment.canonical_path).read_bytes()
        with Image.open(BytesIO(raw)) as source_image:
            source_size = [source_image.width, source_image.height]
        content = _crop_image(raw, union)
        with Image.open(BytesIO(content)) as cropped_image:
            local_size = [cropped_image.width, cropped_image.height]
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        return _failure(
            "source_scope_unavailable",
            f"authorized panel crop failed: {type(exc).__name__}",
            attachment_id=attachment_id,
            panel_ids=panel_ids,
            action_hint="重新绑定可读附件或 panel 范围",
        )
    return SourceScopeResolution(
        status="resolved",
        attachment_id=attachment_id,
        panel_ids=panel_ids,
        media_type="image/png",
        content=content,
        effective_scope={
            "attachment_id": attachment_id,
            "panel_ids": list(panel_ids),
            "bbox_source_px": union,
            "source_image_size": source_size,
            "local_image_size": local_size,
            "source_origin_px": union[:2],
            "local_to_source": "x_source = x_local + source_origin_px[0]; y_source = y_local + source_origin_px[1]",
            "panel_bboxes_source_px": {
                handoff.panel_id: list(handoff.analysis_scope) for handoff in handoffs
            },
            "panel_revisions": {handoff.panel_id: handoff.revision for handoff in handoffs},
        },
        handoffs=tuple(handoffs),
    )


__all__ = ["SourceScopeResolution", "resolve_generation_scope"]
