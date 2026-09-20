"""Shared, bounded review records and execution gates.

Domain reviewers remain responsible for their own checks.  This module owns
the small lifecycle envelope that keeps measurement and generated-chart
reviews from being bypassed by the main Agent chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from ..trace import DETAIL_TRACE_LIMITS, sanitize_payload, truncate_text

MAX_REVIEW_RECORDS = 64
MAX_REVIEW_ISSUES = 32
MAX_REVIEW_TEXT = 240
MAX_REVIEW_FIELDS = 24
MAX_REVIEW_ATTEMPTS = 8
MAX_REVIEW_ACTIONS = 16


class ReviewGateBlocked(RuntimeError):
    """Raised when unrelated work attempts to cross an active review gate."""


class ReviewType(str, Enum):
    MEASUREMENT = "measurement"
    GENERATED_CHART = "generated_chart"


class ReviewState(str, Enum):
    REVIEWING = "reviewing"
    PASSED = "passed"
    PASSED_WITH_WARNING = "passed_with_warning"
    REPAIR_REQUIRED = "repair_required"
    FAILED = "failed"
    EXHAUSTED = "exhausted"
    UNCERTAIN = "uncertain"


class GateState(str, Enum):
    OPEN = "open"
    REVIEWING = "reviewing"
    REPAIR_REQUIRED = "repair_required"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, limit: int = MAX_REVIEW_TEXT) -> str:
    return truncate_text(str(value or "").strip(), limit)


def _bounded_int(value: object, *, default: int = 1, maximum: int = MAX_REVIEW_ATTEMPTS) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _confidence(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return max(0.0, min(1.0, parsed))


def _safe_mapping(value: object, *, limit: int = MAX_REVIEW_FIELDS) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    sanitized = sanitize_payload(dict(list(value.items())[:limit]), limits=DETAIL_TRACE_LIMITS)
    return {str(key)[:96]: item for key, item in list(sanitized.items())[:limit]}


@dataclass(frozen=True)
class ReviewIssue:
    """Domain-neutral bounded issue used by the shared gate projection."""

    code: str
    location: str
    message: str
    severity: str = "error"

    @classmethod
    def from_value(cls, value: object) -> "ReviewIssue | None":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return None
        code = _text(value.get("code"), 64)
        location = _text(value.get("location"), 160)
        message = _text(value.get("message"))
        if not code or not location or not message:
            return None
        severity = _text(value.get("severity") or "error", 16)
        if severity == "blocking":
            severity = "error"
        if severity not in {"error", "warning", "info"}:
            severity = "error"
        return cls(code, location, message, severity)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": _text(self.code, 64),
            "location": _text(self.location, 160),
            "message": _text(self.message),
            "severity": self.severity if self.severity in {"error", "warning", "info"} else "error",
        }


def _issues(values: object) -> tuple[ReviewIssue, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    result: list[ReviewIssue] = []
    for value in values[:MAX_REVIEW_ISSUES]:
        issue = ReviewIssue.from_value(value)
        if issue is not None:
            result.append(issue)
    return tuple(result)


@dataclass(frozen=True)
class ReviewDecision:
    """A validated domain decision submitted to the shared coordinator."""

    decision: str
    issues: tuple[ReviewIssue, ...] = ()
    confidence: float | None = None
    next_action: str | None = None
    repair_action: Mapping[str, Any] | None = None
    evidence: tuple[Mapping[str, Any], ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: object) -> "ReviewDecision":
        if isinstance(value, cls):
            return value
        payload = value if isinstance(value, Mapping) else {}
        decision = _text(payload.get("decision") or payload.get("state") or "fail", 32).lower()
        aliases = {
            "pass": "pass",
            "passed": "pass",
            "warning": "pass_with_warning",
            "pass_with_warning": "pass_with_warning",
            "repair": "repair_required",
            "repair_required": "repair_required",
            "timeout": "fail",
            "timed_out": "fail",
            "failed": "fail",
            "fail": "fail",
            "exhausted": "exhausted",
        }
        decision = aliases.get(decision, "fail")
        raw_evidence = payload.get("evidence")
        evidence = tuple(
            _safe_mapping(item)
            for item in raw_evidence[:MAX_REVIEW_ACTIONS]
            if isinstance(item, Mapping)
        ) if isinstance(raw_evidence, list) else ()
        return cls(
            decision=decision,
            issues=_issues(payload.get("issues")),
            confidence=_confidence(payload.get("confidence")),
            next_action=_text(payload.get("next_action") or payload.get("nextAction"), 240) or None,
            repair_action=_safe_mapping(payload.get("repair_action") or payload.get("repairAction")) or None,
            evidence=evidence,
            details=_safe_mapping(payload.get("details")),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "decision": self.decision,
            "issues": [item.to_dict() for item in self.issues[:MAX_REVIEW_ISSUES]],
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.next_action:
            result["nextAction"] = _text(self.next_action, 240)
        if self.repair_action:
            result["repairAction"] = _safe_mapping(self.repair_action)
        if self.evidence:
            result["evidence"] = [_safe_mapping(item) for item in self.evidence[:MAX_REVIEW_ACTIONS]]
        if self.details:
            result["details"] = _safe_mapping(self.details)
        return result


@dataclass(frozen=True)
class ReviewRecord:
    """A durable-friendly review envelope for one measurement or candidate."""

    review_id: str
    run_id: str
    review_type: ReviewType
    subject_id: str
    state: ReviewState = ReviewState.REVIEWING
    attempt: int = 1
    max_attempts: int = 3
    parent_id: str | None = None
    subject_ref: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[ReviewIssue, ...] = ()
    next_action: str | None = None
    repair_action: Mapping[str, Any] | None = None
    evidence: tuple[Mapping[str, Any], ...] = ()
    decision: str | None = None
    confidence: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def blocking(self) -> bool:
        return self.state is not ReviewState.PASSED and self.state is not ReviewState.PASSED_WITH_WARNING

    @property
    def remaining_attempts(self) -> int:
        return max(0, self.max_attempts - self.attempt)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "reviewId": _text(self.review_id, 128),
            "runId": _text(self.run_id, 128),
            "reviewType": self.review_type.value,
            "subjectId": _text(self.subject_id, 160),
            "state": self.state.value,
            "blocking": self.blocking,
            "attempt": self.attempt,
            "maxAttempts": self.max_attempts,
            "remainingAttempts": self.remaining_attempts,
            "issues": [item.to_dict() for item in self.issues[:MAX_REVIEW_ISSUES]],
            "subjectRef": _safe_mapping(self.subject_ref),
            "evidence": [_safe_mapping(item) for item in self.evidence[:MAX_REVIEW_ACTIONS]],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if self.parent_id:
            result["parentId"] = _text(self.parent_id, 160)
        if self.next_action:
            result["nextAction"] = _text(self.next_action, 240)
        if self.repair_action:
            result["repairAction"] = _safe_mapping(self.repair_action)
        if self.decision:
            result["decision"] = _text(self.decision, 32)
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.details:
            result["details"] = _safe_mapping(self.details)
        return result

    @classmethod
    def from_dict(cls, value: object) -> "ReviewRecord | None":
        if not isinstance(value, Mapping):
            return None
        try:
            review_type = ReviewType(str(value.get("reviewType") or value.get("review_type")))
            state = ReviewState(str(value.get("state") or ReviewState.REVIEWING.value))
        except ValueError:
            return None
        review_id = _text(value.get("reviewId") or value.get("review_id"), 128)
        run_id = _text(value.get("runId") or value.get("run_id"), 128)
        subject_id = _text(value.get("subjectId") or value.get("subject_id"), 160)
        if not review_id or not run_id or not subject_id:
            return None
        raw_evidence = value.get("evidence")
        evidence = tuple(
            _safe_mapping(item) for item in raw_evidence[:MAX_REVIEW_ACTIONS] if isinstance(item, Mapping)
        ) if isinstance(raw_evidence, list) else ()
        return cls(
            review_id=review_id,
            run_id=run_id,
            review_type=review_type,
            subject_id=subject_id,
            state=state,
            attempt=_bounded_int(value.get("attempt")),
            max_attempts=_bounded_int(value.get("maxAttempts") or value.get("max_attempts"), maximum=MAX_REVIEW_ATTEMPTS),
            parent_id=_text(value.get("parentId") or value.get("parent_id"), 160) or None,
            subject_ref=_safe_mapping(value.get("subjectRef") or value.get("subject_ref")),
            issues=_issues(value.get("issues")),
            next_action=_text(value.get("nextAction") or value.get("next_action"), 240) or None,
            repair_action=_safe_mapping(value.get("repairAction") or value.get("repair_action")) or None,
            evidence=evidence,
            decision=_text(value.get("decision"), 32) or None,
            confidence=_confidence(value.get("confidence")),
            details=_safe_mapping(value.get("details")),
            idempotency_key=_text(value.get("idempotencyKey") or value.get("idempotency_key"), 160),
            created_at=_text(value.get("createdAt") or value.get("created_at"), 64) or _now(),
            updated_at=_text(value.get("updatedAt") or value.get("updated_at"), 64) or _now(),
        )


@dataclass(frozen=True)
class ExecutionGate:
    """Run-level projection that decides whether ordinary work may proceed."""

    state: GateState = GateState.OPEN
    blocking: bool = False
    review_type: ReviewType | None = None
    review_id: str | None = None
    subject_id: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    next_action: str | None = None
    issues: tuple[ReviewIssue, ...] = ()
    repair_action: Mapping[str, Any] | None = None
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state.value,
            "blocking": self.blocking,
            "updatedAt": self.updated_at,
            "issues": [item.to_dict() for item in self.issues[:MAX_REVIEW_ISSUES]],
        }
        if self.review_type:
            result["reviewType"] = self.review_type.value
        if self.review_id:
            result["reviewId"] = _text(self.review_id, 128)
        if self.subject_id:
            result["subjectId"] = _text(self.subject_id, 160)
        if self.attempt is not None:
            result["attempt"] = self.attempt
        if self.max_attempts is not None:
            result["maxAttempts"] = self.max_attempts
        if self.next_action:
            result["nextAction"] = _text(self.next_action, 240)
        if self.repair_action:
            result["repairAction"] = _safe_mapping(self.repair_action)
        return result

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionGate":
        if not isinstance(value, Mapping):
            return cls()
        try:
            state = GateState(str(value.get("state") or GateState.OPEN.value))
        except ValueError:
            state = GateState.OPEN
        raw_type = value.get("reviewType") or value.get("review_type")
        try:
            review_type = ReviewType(str(raw_type)) if raw_type else None
        except ValueError:
            review_type = None
        return cls(
            state=state,
            blocking=bool(value.get("blocking", state is not GateState.OPEN)),
            review_type=review_type,
            review_id=_text(value.get("reviewId") or value.get("review_id"), 128) or None,
            subject_id=_text(value.get("subjectId") or value.get("subject_id"), 160) or None,
            attempt=_bounded_int(value.get("attempt"), default=1) if value.get("attempt") is not None else None,
            max_attempts=_bounded_int(value.get("maxAttempts") or value.get("max_attempts"), maximum=MAX_REVIEW_ATTEMPTS) if value.get("maxAttempts") is not None or value.get("max_attempts") is not None else None,
            next_action=_text(value.get("nextAction") or value.get("next_action"), 240) or None,
            issues=_issues(value.get("issues")),
            repair_action=_safe_mapping(value.get("repairAction") or value.get("repair_action")) or None,
            updated_at=_text(value.get("updatedAt") or value.get("updated_at"), 64) or _now(),
        )


def review_idempotency_key(
    run_id: str,
    review_type: ReviewType | str,
    subject_id: str,
    attempt: int,
    parent_id: str | None = None,
) -> str:
    """Return a stable identity for one review intent."""
    kind = review_type.value if isinstance(review_type, ReviewType) else str(review_type)
    raw = "|".join((_text(run_id, 128), kind[:64], _text(subject_id, 160), str(int(attempt)), _text(parent_id, 160)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _gate_for(record: ReviewRecord) -> ExecutionGate:
    if record.state in {ReviewState.PASSED, ReviewState.PASSED_WITH_WARNING}:
        return ExecutionGate(
            state=GateState.OPEN,
            blocking=False,
            review_type=record.review_type,
            review_id=record.review_id,
            subject_id=record.subject_id,
            attempt=record.attempt,
            max_attempts=record.max_attempts,
        )
    gate_state = {
        ReviewState.REVIEWING: GateState.REVIEWING,
        ReviewState.REPAIR_REQUIRED: GateState.REPAIR_REQUIRED,
        ReviewState.EXHAUSTED: GateState.EXHAUSTED,
        ReviewState.FAILED: GateState.FAILED,
        ReviewState.UNCERTAIN: GateState.REVIEWING,
    }.get(record.state, GateState.FAILED)
    return ExecutionGate(
        state=gate_state,
        blocking=True,
        review_type=record.review_type,
        review_id=record.review_id,
        subject_id=record.subject_id,
        attempt=record.attempt,
        max_attempts=record.max_attempts,
        next_action=record.next_action,
        issues=record.issues,
        repair_action=record.repair_action,
    )


class ReviewCoordinator:
    """Thread-safe in-run coordinator for shared review state.

    Persistence is intentionally injected through the caller's event and
    checkpoint sinks.  This keeps the coordinator useful for the in-memory
    Agent tests while making every transition available to the Gateway.
    """

    def __init__(self, *, max_records: int = MAX_REVIEW_RECORDS) -> None:
        self.max_records = max(1, min(int(max_records), MAX_REVIEW_RECORDS))
        self._records: dict[str, ReviewRecord] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._gates: dict[str, ExecutionGate] = {}
        self._lock = RLock()

    def begin(
        self,
        run_id: str,
        review_type: ReviewType | str,
        subject_id: str,
        *,
        attempt: int = 1,
        max_attempts: int = 3,
        parent_id: str | None = None,
        subject_ref: Mapping[str, Any] | None = None,
        evidence: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        next_action: str | None = None,
        idempotency_key: str | None = None,
    ) -> ReviewRecord:
        kind = ReviewType(review_type)
        normalized_run = _text(run_id, 128)
        normalized_subject = _text(subject_id, 160)
        normalized_attempt = _bounded_int(attempt)
        normalized_max = _bounded_int(max_attempts, maximum=MAX_REVIEW_ATTEMPTS)
        key = idempotency_key or review_idempotency_key(
            normalized_run,
            kind,
            normalized_subject,
            normalized_attempt,
            parent_id,
        )
        index = (normalized_run, key)
        with self._lock:
            existing_id = self._by_key.get(index)
            if existing_id:
                return self._records[existing_id]
            active_gate = self._gates.get(normalized_run)
            if (
                active_gate is not None
                and active_gate.blocking
                and active_gate.subject_id
                and _text(parent_id, 160) != active_gate.subject_id
            ):
                raise ReviewGateBlocked(
                    f"review gate is blocking run {normalized_run}: {active_gate.state.value}"
                )
            record = ReviewRecord(
                review_id=f"review_{uuid4().hex}",
                run_id=normalized_run,
                review_type=kind,
                subject_id=normalized_subject,
                attempt=normalized_attempt,
                max_attempts=max(normalized_attempt, normalized_max),
                parent_id=_text(parent_id, 160) or None,
                subject_ref=_safe_mapping(subject_ref),
                evidence=tuple(_safe_mapping(item) for item in list(evidence)[:MAX_REVIEW_ACTIONS]),
                next_action=_text(next_action, 240) or None,
                idempotency_key=key,
            )
            self._records[record.review_id] = record
            self._by_key[index] = record.review_id
            self._gates[normalized_run] = _gate_for(record)
            self._trim_locked()
            return record

    def get(self, review_id: str) -> ReviewRecord | None:
        with self._lock:
            return self._records.get(str(review_id))

    def gate(self, run_id: str) -> ExecutionGate:
        with self._lock:
            return self._gates.get(str(run_id), ExecutionGate())

    def can_continue(self, run_id: str) -> bool:
        return self.gate(run_id).state is GateState.OPEN

    def apply(self, review_id: str, decision: ReviewDecision | Mapping[str, Any]) -> ReviewRecord:
        normalized = ReviewDecision.from_value(decision)
        with self._lock:
            current = self._records.get(str(review_id))
            if current is None:
                raise KeyError(f"unknown review_id: {review_id}")
            if current.state in {ReviewState.PASSED, ReviewState.PASSED_WITH_WARNING, ReviewState.EXHAUSTED}:
                return current
            next_state = self._next_state(current, normalized)
            record = replace(
                current,
                state=next_state,
                issues=normalized.issues,
                next_action=normalized.next_action,
                repair_action=normalized.repair_action,
                evidence=normalized.evidence or current.evidence,
                decision=normalized.decision,
                confidence=normalized.confidence,
                details=normalized.details,
                updated_at=_now(),
            )
            self._records[record.review_id] = record
            self._gates[record.run_id] = _gate_for(record)
            return record

    @staticmethod
    def _next_state(record: ReviewRecord, decision: ReviewDecision) -> ReviewState:
        if decision.decision == "pass":
            return ReviewState.PASSED
        if decision.decision == "pass_with_warning":
            return ReviewState.PASSED_WITH_WARNING
        if decision.decision == "exhausted":
            return ReviewState.EXHAUSTED
        if decision.decision == "repair_required":
            return ReviewState.REPAIR_REQUIRED if record.attempt < record.max_attempts else ReviewState.EXHAUSTED
        return ReviewState.FAILED

    def mark_uncertain(self, review_id: str, *, next_action: str | None = None) -> ReviewRecord:
        with self._lock:
            current = self._records.get(str(review_id))
            if current is None:
                raise KeyError(f"unknown review_id: {review_id}")
            record = replace(current, state=ReviewState.UNCERTAIN, next_action=_text(next_action, 240) or current.next_action, updated_at=_now())
            self._records[record.review_id] = record
            self._gates[record.run_id] = _gate_for(record)
            return record

    def records_for_run(self, run_id: str) -> tuple[ReviewRecord, ...]:
        with self._lock:
            return tuple(item for item in self._records.values() if item.run_id == str(run_id))

    def restore(self, values: object) -> None:
        records = values if isinstance(values, list) else []
        with self._lock:
            for value in records[: self.max_records]:
                record = ReviewRecord.from_dict(value)
                if record is None:
                    continue
                self._records[record.review_id] = record
                key = (record.run_id, record.idempotency_key or review_idempotency_key(record.run_id, record.review_type, record.subject_id, record.attempt, record.parent_id))
                self._by_key[key] = record.review_id
                self._gates[record.run_id] = _gate_for(record)
            self._trim_locked()

    def restore_gate(self, run_id: str, value: object) -> None:
        """Restore a run projection when a checkpoint has no full record list."""
        gate = ExecutionGate.from_dict(value)
        with self._lock:
            self._gates[_text(run_id, 128)] = gate

    def to_state(self, run_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            records = [item.to_dict() for item in self._records.values() if run_id is None or item.run_id == str(run_id)]
            result: dict[str, Any] = {"records": records[-self.max_records :]}
            if run_id is not None:
                result["executionGate"] = self.gate(run_id).to_dict()
            return result

    def _trim_locked(self) -> None:
        if len(self._records) <= self.max_records:
            return
        keep = set(list(self._records)[-self.max_records :])
        self._records = {key: value for key, value in self._records.items() if key in keep}
        self._by_key = {
            key: value for key, value in self._by_key.items() if value in self._records
        }


def normalize_review_event(kind: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize legacy domain events for trace/evaluation consumers."""
    raw = dict(payload or {})
    legacy_kind = str(kind or "")
    review_type = "measurement" if legacy_kind.startswith("measurement_repair") else "generated_chart" if legacy_kind.startswith("chart_review") or legacy_kind.startswith("generated_chart") else str(raw.get("reviewType") or "unknown")
    if legacy_kind in {"measurement_repair_required", "chart_review_repair_required"}:
        state = ReviewState.REPAIR_REQUIRED.value
    elif legacy_kind in {"measurement_repair_exhausted", "generated_chart_rejected"}:
        state = ReviewState.EXHAUSTED.value if legacy_kind == "measurement_repair_exhausted" else ReviewState.FAILED.value
    elif legacy_kind in {"chart_review_started", "chart_review_required"}:
        state = ReviewState.REVIEWING.value
    elif legacy_kind == "chart_review_completed":
        state = ReviewState.PASSED.value if raw.get("publication_status") in {"published", "published_with_warning"} else ReviewState.FAILED.value
    elif legacy_kind == "generated_chart_published":
        state = ReviewState.PASSED_WITH_WARNING.value if raw.get("publication_status") == "published_with_warning" else ReviewState.PASSED.value
    else:
        state = str(raw.get("state") or ReviewState.REVIEWING.value)
    result = {
        "reviewType": review_type,
        "state": state,
        "blocking": state not in {ReviewState.PASSED.value, ReviewState.PASSED_WITH_WARNING.value},
    }
    for source, target in (
        ("review_id", "reviewId"),
        ("candidate_id", "subjectId"),
        ("subject_id", "subjectId"),
        ("attempt", "attempt"),
        ("max_attempts", "maxAttempts"),
        ("next_action", "nextAction"),
    ):
        if source in raw and raw[source] is not None:
            result[target] = raw[source]
    if isinstance(raw.get("repair"), Mapping):
        result["repairAction"] = _safe_mapping(raw["repair"])
    if isinstance(raw.get("issues"), list):
        result["issues"] = [issue.to_dict() for issue in _issues(raw["issues"])]
    return result


__all__ = [
    "ExecutionGate",
    "GateState",
    "ReviewCoordinator",
    "ReviewDecision",
    "ReviewIssue",
    "ReviewRecord",
    "ReviewState",
    "ReviewType",
    "ReviewGateBlocked",
    "normalize_review_event",
    "review_idempotency_key",
]
