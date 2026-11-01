"""Provider-neutral opaque resource identities shared by all owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, TypeAlias

ImageResourceKind: TypeAlias = Literal["attachment", "panel"]
ToolResourceKind: TypeAlias = Literal["ocr", "measurement", "chart_figure", "chart_render"]
ResourceKind: TypeAlias = ImageResourceKind | ToolResourceKind


@dataclass(frozen=True)
class ImageResourceRef:
    kind: ImageResourceKind
    id: str

    def __post_init__(self) -> None:
        if self.kind not in {"attachment", "panel"} or not _nonempty(self.id):
            raise ValueError("invalid image resource reference")


@dataclass(frozen=True)
class ToolResourceRef:
    kind: ToolResourceKind
    run_id: str
    call_id: str

    def __post_init__(self) -> None:
        if (
            self.kind not in {"ocr", "measurement", "chart_figure", "chart_render"}
            or not _nonempty(self.run_id)
            or not _nonempty(self.call_id)
        ):
            raise ValueError("invalid tool resource reference")


ResourceRef: TypeAlias = ImageResourceRef | ToolResourceRef



def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)
