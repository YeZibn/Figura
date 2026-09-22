"""Bounded task context shared by source-linked chart generation stages.

ChartSpec describes what is rendered.  ``GenerationContext`` describes why it
is rendered, which source scope it belongs to, and what source coverage the
candidate intentionally represents.  Keeping the two contracts separate lets
legacy source-free ChartSpec callers remain compatible while making review
scope explicit for source-linked candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from collections.abc import Mapping
from typing import Any


MAX_CONTEXT_TEXT = 240
MAX_CONTEXT_IDS = 16
MAX_CONTEXT_SERIES = 64
MAX_CONTEXT_SERIES_TEXT = 160
MAX_CONTEXT_VERSION = 4


class GenerationMode(str, Enum):
    RECONSTRUCT = "reconstruct"
    TRANSFORM = "transform"
    SUMMARIZE = "summarize"
    SYNTHESIZE = "synthesize"


class CoverageBasis(str, Enum):
    FULL_SOURCE = "full_source"
    REQUESTED_SUBSET = "requested_subset"
    NOT_APPLICABLE = "not_applicable"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class SelectionBasis(str, Enum):
    USER_EXPLICIT = "user_explicit"
    AGENT_RESOLVED = "agent_resolved"
    USER_CONFIRMED = "user_confirmed"


def _bounded_text(value: object, limit: int = MAX_CONTEXT_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bounded_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for item in value[:MAX_CONTEXT_IDS]:
        text = _bounded_text(item, 160)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _bounded_series(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for item in value[:MAX_CONTEXT_SERIES]:
        text = _bounded_text(item, MAX_CONTEXT_SERIES_TEXT)
        if text and text not in result:
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class GenerationSourceScope:
    """Opaque attachment/panel identity used to resolve an authorized crop."""

    attachment_id: str | None = None
    panel_ids: tuple[str, ...] = ()
    revision: int | None = None

    @property
    def bound(self) -> bool:
        return bool(self.attachment_id and self.panel_ids)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "attachment_id": self.attachment_id,
            "panel_ids": list(self.panel_ids[:MAX_CONTEXT_IDS]),
        }
        if self.revision is not None:
            result["revision"] = max(1, int(self.revision))
        return result

    @classmethod
    def from_dict(cls, value: object) -> "GenerationSourceScope | None":
        if not isinstance(value, Mapping):
            return None
        attachment = _bounded_text(value.get("attachment_id") or value.get("attachmentId"), 160) or None
        panel_values = value.get("panel_ids") or value.get("panelIds") or ()
        revision_value = value.get("revision")
        try:
            revision = max(1, int(revision_value)) if revision_value is not None else None
        except (TypeError, ValueError):
            revision = None
        scope = cls(attachment_id=attachment, panel_ids=_bounded_ids(panel_values), revision=revision)
        return scope if attachment or scope.panel_ids else None

    def validate(self, location: str = "source_scope") -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        if not self.attachment_id:
            issues.append({"location": f"{location}.attachment_id", "message": "source scope requires attachment_id"})
        if not self.panel_ids:
            issues.append({"location": f"{location}.panel_ids", "message": "source scope requires at least one panel_id"})
        if len(self.panel_ids) > MAX_CONTEXT_IDS:
            issues.append({"location": f"{location}.panel_ids", "message": "source scope contains too many panels"})
        if self.revision is not None and self.revision < 1:
            issues.append({"location": f"{location}.revision", "message": "source scope revision must be positive"})
        return issues


@dataclass(frozen=True)
class GenerationCoverage:
    """Source-series coverage as understood by the generation task."""

    basis: CoverageBasis = CoverageBasis.NOT_APPLICABLE
    source_series: tuple[str, ...] = ()
    represented_series: tuple[str, ...] = ()
    intentionally_omitted_series: tuple[str, ...] = ()
    status: CoverageStatus = CoverageStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis.value,
            "source_series": list(self.source_series[:MAX_CONTEXT_SERIES]),
            "represented_series": list(self.represented_series[:MAX_CONTEXT_SERIES]),
            "intentionally_omitted_series": list(self.intentionally_omitted_series[:MAX_CONTEXT_SERIES]),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> "GenerationCoverage":
        if not isinstance(value, Mapping):
            return cls()
        try:
            basis = CoverageBasis(str(value.get("basis") or CoverageBasis.NOT_APPLICABLE.value))
        except ValueError:
            basis = CoverageBasis.NOT_APPLICABLE
        try:
            status = CoverageStatus(str(value.get("status") or CoverageStatus.UNKNOWN.value))
        except ValueError:
            status = CoverageStatus.UNKNOWN
        return cls(
            basis=basis,
            source_series=_bounded_series(value.get("source_series") or value.get("sourceSeries")),
            represented_series=_bounded_series(value.get("represented_series") or value.get("representedSeries")),
            intentionally_omitted_series=_bounded_series(
                value.get("intentionally_omitted_series")
                or value.get("intentionallyOmittedSeries")
                or value.get("omitted_series")
                or value.get("omittedSeries")
            ),
            status=status,
        )

    def validate(self, location: str = "coverage") -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        source = set(self.source_series)
        represented = set(self.represented_series)
        omitted = set(self.intentionally_omitted_series)
        if represented & omitted:
            issues.append({"location": location, "message": "represented and intentionally omitted series must not overlap"})
        if source and not represented.issubset(source):
            issues.append({"location": f"{location}.represented_series", "message": "represented series must come from source_series"})
        if source and not omitted.issubset(source):
            issues.append({"location": f"{location}.intentionally_omitted_series", "message": "omitted series must come from source_series"})
        if self.basis is CoverageBasis.FULL_SOURCE and omitted:
            issues.append({"location": f"{location}.basis", "message": "full_source coverage cannot intentionally omit source series"})
        if self.basis is CoverageBasis.NOT_APPLICABLE and (source or represented or omitted):
            issues.append({"location": f"{location}.basis", "message": "not_applicable coverage cannot list source series"})
        if self.status is CoverageStatus.COMPLETE and self.basis is CoverageBasis.FULL_SOURCE and source != represented:
            issues.append({"location": f"{location}.status", "message": "complete full_source coverage must represent every source series"})
        return issues


@dataclass(frozen=True)
class GenerationContext:
    """Immutable, bounded intent and source contract for one candidate."""

    mode: GenerationMode
    source_scope: GenerationSourceScope | None
    coverage: GenerationCoverage
    selection_basis: SelectionBasis
    goal_summary: str = ""
    version: int = 1

    @property
    def source_linked(self) -> bool:
        return self.mode is not GenerationMode.SYNTHESIZE or self.source_scope is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "version": max(1, min(int(self.version), MAX_CONTEXT_VERSION)),
            "mode": self.mode.value,
            "source_scope": self.source_scope.to_dict() if self.source_scope is not None else None,
            "coverage": self.coverage.to_dict(),
            "selection_basis": self.selection_basis.value,
            "goal_summary": _bounded_text(self.goal_summary),
        }
        return result

    @classmethod
    def from_dict(cls, value: object) -> "GenerationContext | None":
        if not isinstance(value, Mapping):
            return None
        try:
            mode = GenerationMode(str(value.get("mode") or ""))
        except ValueError:
            return None
        try:
            selection_basis = SelectionBasis(str(value.get("selection_basis") or value.get("selectionBasis") or SelectionBasis.AGENT_RESOLVED.value))
        except ValueError:
            selection_basis = SelectionBasis.AGENT_RESOLVED
        try:
            version = max(1, min(int(value.get("version", 1)), MAX_CONTEXT_VERSION))
        except (TypeError, ValueError):
            version = 1
        return cls(
            mode=mode,
            source_scope=GenerationSourceScope.from_dict(value.get("source_scope") or value.get("sourceScope")),
            coverage=GenerationCoverage.from_dict(value.get("coverage")),
            selection_basis=selection_basis,
            goal_summary=_bounded_text(value.get("goal_summary") or value.get("goalSummary")),
            version=version,
        )

    def validate(self, location: str = "generation_context") -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        if self.mode is not GenerationMode.SYNTHESIZE and self.source_scope is None:
            issues.append({"location": f"{location}.source_scope", "message": "source-linked generation mode requires source_scope"})
        if self.source_scope is not None:
            issues.extend(self.source_scope.validate(f"{location}.source_scope"))
        issues.extend(self.coverage.validate(f"{location}.coverage"))
        if self.mode is GenerationMode.SYNTHESIZE and self.coverage.basis is not CoverageBasis.NOT_APPLICABLE and self.source_scope is None:
            issues.append({"location": f"{location}.coverage.basis", "message": "source-free synthesis must use not_applicable coverage"})
        if not self.goal_summary:
            issues.append({"location": f"{location}.goal_summary", "message": "generation context requires a bounded goal_summary"})
        return issues


def context_digest(context: GenerationContext | Mapping[str, Any] | None) -> str | None:
    """Return a stable digest for a normalized context snapshot."""
    normalized = context if isinstance(context, GenerationContext) else GenerationContext.from_dict(context)
    if normalized is None:
        return None
    encoded = json.dumps(normalized.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_generation_context(
    value: object,
    *,
    source_scope_hint: Mapping[str, Any] | GenerationSourceScope | None = None,
) -> GenerationContext | None:
    """Parse a context and bind only a unique, authorized runtime scope hint."""
    candidate = dict(value) if isinstance(value, Mapping) else value
    if isinstance(candidate, dict):
        raw_scope = candidate.get("source_scope") or candidate.get("sourceScope")
        mode = str(candidate.get("mode") or "")
        if raw_scope is None and mode != GenerationMode.SYNTHESIZE.value and source_scope_hint is not None:
            hint = (
                source_scope_hint
                if isinstance(source_scope_hint, GenerationSourceScope)
                else GenerationSourceScope.from_dict(source_scope_hint)
            )
            if hint is not None and not hint.validate():
                candidate["source_scope"] = hint.to_dict()
    context = GenerationContext.from_dict(candidate)
    return context


def generation_context_schema() -> dict[str, Any]:
    """Return the bounded JSON Schema shared by chart-facing tools."""
    return {
        "type": "object",
        "description": "当前生成任务的来源与覆盖合同；source-linked 模式需要 source_scope，唯一授权 panel 可由工具安全绑定；工具不替主 Agent 决定系列语义。",
        "properties": {
            "version": {"type": "integer", "minimum": 1, "maximum": MAX_CONTEXT_VERSION, "description": "上下文版本。"},
            "mode": {
                "type": "string",
                "enum": [item.value for item in GenerationMode],
                "description": "任务模式：reconstruct、transform、summarize 或 synthesize。",
            },
            "source_scope": {
                "type": ["object", "null"],
                "description": "授权来源范围；source-linked 模式必须有 attachment_id 和 panel_ids，可由唯一已授权 panel 安全绑定。",
                "properties": {
                    "attachment_id": {"type": "string", "maxLength": 160, "description": "当前授权附件 ID。"},
                    "panel_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_CONTEXT_IDS,
                        "items": {"type": "string", "maxLength": 160},
                        "description": "当前候选允许观察的 panel ID。",
                    },
                    "revision": {"type": "integer", "minimum": 1, "description": "可选的 panel handoff revision。"},
                },
                "required": ["attachment_id", "panel_ids"],
                "additionalProperties": False,
            },
            "coverage": {
                "type": "object",
                "description": "源系列覆盖说明；requested_subset 必须显式记录有意省略。",
                "properties": {
                    "basis": {"type": "string", "enum": [item.value for item in CoverageBasis], "description": "覆盖基准。"},
                    "source_series": {"type": "array", "maxItems": MAX_CONTEXT_SERIES, "items": {"type": "string", "maxLength": MAX_CONTEXT_SERIES_TEXT}, "description": "可见源系列。"},
                    "represented_series": {"type": "array", "maxItems": MAX_CONTEXT_SERIES, "items": {"type": "string", "maxLength": MAX_CONTEXT_SERIES_TEXT}, "description": "实际表示的系列。"},
                    "intentionally_omitted_series": {"type": "array", "maxItems": MAX_CONTEXT_SERIES, "items": {"type": "string", "maxLength": MAX_CONTEXT_SERIES_TEXT}, "description": "主 Agent 明确省略的系列。"},
                    "status": {"type": "string", "enum": [item.value for item in CoverageStatus], "description": "当前覆盖状态。"},
                },
                "required": ["basis", "status"],
                "additionalProperties": False,
            },
            "selection_basis": {
                "type": "string",
                "enum": [item.value for item in SelectionBasis],
                "description": "系列选择依据。",
            },
            "goal_summary": {"type": "string", "maxLength": MAX_CONTEXT_TEXT, "description": "当前生成目标的简短说明。"},
        },
        "required": ["mode", "coverage", "selection_basis", "goal_summary"],
        "anyOf": [
            {
                "required": ["mode", "source_scope"],
                "properties": {
                    "mode": {"enum": [item.value for item in GenerationMode if item is not GenerationMode.SYNTHESIZE]},
                    "source_scope": {"type": "object"},
                },
            },
            {
                "required": ["mode"],
                "properties": {"mode": {"const": GenerationMode.SYNTHESIZE.value}},
            },
        ],
        "additionalProperties": False,
    }


__all__ = [
    "CoverageBasis",
    "CoverageStatus",
    "GenerationContext",
    "GenerationCoverage",
    "GenerationMode",
    "GenerationSourceScope",
    "MAX_CONTEXT_IDS",
    "MAX_CONTEXT_SERIES",
    "MAX_CONTEXT_TEXT",
    "SelectionBasis",
    "context_digest",
    "generation_context_schema",
    "normalize_generation_context",
]
