"""Immutable Panel metadata and normalized polygon values."""

from __future__ import annotations

from dataclasses import dataclass

from figura.runtime import RunError, RunErrorCode


@dataclass(frozen=True)
class PanelPoint:
    x: int
    y: int

    def __post_init__(self) -> None:
        if type(self.x) is not int or type(self.y) is not int:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not 0 <= self.x <= 1000 or not 0 <= self.y <= 1000:
            raise RunError(RunErrorCode.INVALID_REQUEST)


@dataclass(frozen=True)
class PanelRecord:
    panel_id: str
    session_id: str
    run_id: str
    source_attachment_id: str
    name: str
    points: tuple[PanelPoint, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.panel_id,
            self.session_id,
            self.run_id,
            self.source_attachment_id,
        )):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(self.name, str) or not self.name.strip():
            raise RunError(RunErrorCode.INVALID_REQUEST)
        try:
            name_size = len(self.name.encode("utf-8"))
        except UnicodeEncodeError:
            raise RunError(RunErrorCode.INVALID_REQUEST) from None
        if name_size > 256:
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if (
            not isinstance(self.points, tuple)
            or not 3 <= len(self.points) <= 64
            or any(not isinstance(point, PanelPoint) for point in self.points)
        ):
            raise RunError(RunErrorCode.INVALID_REQUEST)
