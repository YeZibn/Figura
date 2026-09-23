"""Stable data model and stage vocabulary for diagnostic timelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..trace import sanitize_payload, truncate_text


STAGE_NAMES = (
    "input",
    "model",
    "decomposition",
    "panel_handoff",
    "measurement",
    "quality_review",
    "repair",
    "assembly",
    "render",
)
STAGE_STATUSES = ("completed", "needs_repair", "failed", "not_reached", "not_observed")
FAILURE_STATUSES = {
    "error",
    "failed",
    "failure",
    "rejected",
    "exhausted",
    "blocked",
    "timeout",
    "timed_out",
    "unavailable",
}
SUCCESS_STATUSES = {
    "accepted",
    "available",
    "completed",
    "complete",
    "ok",
    "passed",
    "published",
    "published_with_warning",
    "success",
}
MEASUREMENT_TOOLS = {
    "extract_text",
    "measure_bars",
    "extract_line_series",
    "extract_pie_slices",
    "extract_scatter_points",
}
STAGE_ORDER = {name: index for index, name in enumerate(STAGE_NAMES)}


@dataclass
class StageEvidence:
    """Evidence retained for one fixed stage, without raw images or prompts."""

    name: str
    status: str = "not_observed"
    sequences: list[int] = field(default_factory=list)
    event_kinds: list[str] = field(default_factory=list)
    panel_ids: list[str] = field(default_factory=list)
    attempt_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failure_sequences: list[int] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "sequences": self.sequences[:64],
            "event_kinds": self.event_kinds[:32],
            "panel_ids": self.panel_ids[:32],
            "attempt_ids": self.attempt_ids[:32],
            "artifact_ids": self.artifact_ids[:32],
            "observation_ids": self.observation_ids[:32],
        }
        if self.errors:
            result["errors"] = [truncate_text(item, 240) for item in self.errors[:8]]
        if self.notes:
            result["notes"] = [truncate_text(item, 240) for item in self.notes[:8]]
        return result


@dataclass
class DiagnosticTimeline:
    """All stage evidence and bounded anomalies inferred from a run history."""

    stages: tuple[StageEvidence, ...]
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    first_failure: dict[str, Any] | None = None
    final_references: dict[str, list[str]] = field(default_factory=dict)
    history_gap: bool = False
    protocol_status: str = "supported"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "stages": [stage.to_dict() for stage in self.stages],
            "anomalies": [sanitize_payload(item) for item in self.anomalies[:32]],
            "final_references": {
                key: list(values[:32]) for key, values in self.final_references.items()
            },
            "history_gap": self.history_gap,
            "protocol_status": self.protocol_status,
        }
        if self.first_failure is not None:
            result["first_failure"] = sanitize_payload(self.first_failure)
        return result


__all__ = [
    "STAGE_NAMES",
    "STAGE_STATUSES",
    "FAILURE_STATUSES",
    "SUCCESS_STATUSES",
    "MEASUREMENT_TOOLS",
    "STAGE_ORDER",
    "StageEvidence",
    "DiagnosticTimeline",
]
