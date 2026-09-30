"""Bounded ChartSpec parsing and validation errors."""

from __future__ import annotations

from dataclasses import dataclass

from ..limits import (
    MAX_ISSUE_CODE_LENGTH,
    MAX_ISSUE_MESSAGE_LENGTH,
    MAX_ISSUE_PATH_BYTES,
)


@dataclass(frozen=True)
class ChartSpecIssue:
    code: str
    field_path: str
    message: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or not self.code.isascii()
            or len(self.code) > MAX_ISSUE_CODE_LENGTH
        ):
            raise ValueError("ChartSpec issue code is invalid or exceeds its limit")
        if (
            not isinstance(self.field_path, str)
            or len(self.field_path.encode("utf-8")) > MAX_ISSUE_PATH_BYTES
        ):
            raise ValueError("ChartSpec issue path is invalid or exceeds its limit")
        if (
            not isinstance(self.message, str)
            or len(self.message) > MAX_ISSUE_MESSAGE_LENGTH
        ):
            raise ValueError("ChartSpec issue message is invalid or exceeds its limit")


class ChartSpecParseError(ValueError):
    """A bounded parse failure that never includes the submitted payload."""

    def __init__(self, issue: ChartSpecIssue) -> None:
        if not isinstance(issue, ChartSpecIssue):
            raise TypeError("issue must be a ChartSpecIssue")
        self.issue = issue
        super().__init__(issue.message)


class ChartSpecSerializationError(ValueError):
    """A bounded serialization failure."""

    def __init__(self, issue: ChartSpecIssue) -> None:
        if not isinstance(issue, ChartSpecIssue):
            raise TypeError("issue must be a ChartSpecIssue")
        self.issue = issue
        super().__init__(issue.message)
