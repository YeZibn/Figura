"""Immutable values for staged charts, verification results, and artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from ..spec import ChartFigure, ChartSpec, chart_figure_digest, chart_spec_digest

MANIFEST_VERSION = 1
VERIFICATION_POLICY_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
MAX_VERIFICATION_BYTES = 16 * 1024
MAX_ISSUES = 32
MAX_ISSUE_TEXT = 240
_REF = re.compile(r"^(?:stg|ver|artifact)_[A-Za-z0-9_-]{8,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHECK_VALUES = frozenset({"pass", "warning", "fail", "not_run"})
VerificationStatus = Literal["pass", "pass_with_warning", "fail", "unavailable"]


class VerificationError(ValueError):
    """A staged chart or verification value violates its bounded contract."""


def canonical_json(value: Any, *, limit: int, name: str) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"{name} is not JSON-safe") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise VerificationError(f"{name} exceeds the size limit")
    return encoded


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _bounded_strings(value: object, *, limit: int, item_limit: int = 160) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item[:item_limit] for item in value[:limit] if isinstance(item, str) and item.strip())


def _valid_opaque_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 160
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


@dataclass(frozen=True)
class ChartManifest:
    """Exact immutable identity and attribution for one staged render output."""

    staged_ref: str
    run_id: str
    session_id: str
    work_key: str
    tool_call_id: str
    output_ordinal: int
    image_sha256: str
    media_type: str
    byte_count: int
    chart_spec: Mapping[str, Any]
    chart_spec_digest: str
    chart_type: str
    title: str
    width: int
    height: int
    source_attachment_ids: tuple[str, ...] = ()
    panel_ids: tuple[str, ...] = ()
    generation_context: Mapping[str, Any] | None = None
    generation_context_digest: str | None = None
    figure_id: str | None = None
    collection_id: str | None = None
    child_chart_ids: tuple[str, ...] = ()
    source_revision: str | None = None
    policy_version: int = VERIFICATION_POLICY_VERSION
    semantic_required: bool = False
    allow_warnings: bool = True
    max_attempts: int = 3
    version: int = MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        if self.version != MANIFEST_VERSION or not _REF.fullmatch(self.staged_ref) or not self.staged_ref.startswith("stg_"):
            raise VerificationError("staged chart reference or manifest version is invalid")
        if not all(_valid_opaque_id(value) for value in (self.run_id, self.session_id, self.work_key, self.tool_call_id)):
            raise VerificationError("staged chart identity is incomplete")
        if not 0 <= self.output_ordinal < 16 or not 0 < self.byte_count <= 32 * 1024 * 1024:
            raise VerificationError("staged chart bounds are invalid")
        if not _SHA256.fullmatch(self.image_sha256) or not _SHA256.fullmatch(self.chart_spec_digest):
            raise VerificationError("staged chart digest is invalid")
        if not 1 <= self.width <= 16384 or not 1 <= self.height <= 16384:
            raise VerificationError("staged chart dimensions are invalid")
        if self.media_type != "image/png" or not 1 <= len(self.chart_type) <= 64 or not 1 <= len(self.title) <= 240:
            raise VerificationError("staged chart metadata is invalid")
        if self.policy_version != VERIFICATION_POLICY_VERSION or not 1 <= self.max_attempts <= 8:
            raise VerificationError("verification policy is invalid")
        if len(self.source_attachment_ids) > 16 or len(self.panel_ids) > 16 or len(self.child_chart_ids) > 16:
            raise VerificationError("staged chart source or collection bounds are invalid")
        if any(not _valid_opaque_id(item) for item in (*self.source_attachment_ids, *self.panel_ids, *self.child_chart_ids)):
            raise VerificationError("staged chart source or collection identity is invalid")
        if self.generation_context is not None:
            context_text = canonical_json(self.generation_context, limit=16 * 1024, name="generation context")
            if self.generation_context_digest is not None:
                actual_context_digest = content_digest(context_text.encode("utf-8"))
                if actual_context_digest != self.generation_context_digest:
                    raise VerificationError("generation context digest does not match")
        elif self.generation_context_digest is not None:
            raise VerificationError("generation context digest has no context")
        if isinstance(self.chart_spec, Mapping):
            canonical_json(self.chart_spec, limit=MAX_MANIFEST_BYTES // 2, name="chart spec")
            try:
                computed_digest = (
                    chart_figure_digest(ChartFigure.from_dict(self.chart_spec))
                    if self.chart_spec.get("kind") == "chart_figure"
                    else chart_spec_digest(ChartSpec.from_dict(self.chart_spec))
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise VerificationError("staged chart spec is invalid") from exc
            if computed_digest != self.chart_spec_digest:
                raise VerificationError("staged chart spec digest does not match")
        else:
            raise VerificationError("staged chart spec must be an object")
        value = {
            "version": self.version,
            "stagedRef": self.staged_ref,
            "runId": self.run_id,
            "sessionId": self.session_id,
            "workKey": self.work_key,
            "toolCallId": self.tool_call_id,
            "outputOrdinal": self.output_ordinal,
            "imageSha256": self.image_sha256,
            "mediaType": self.media_type,
            "byteCount": self.byte_count,
            "chartSpec": dict(self.chart_spec),
            "chartSpecDigest": self.chart_spec_digest,
            "chartType": self.chart_type,
            "title": self.title,
            "width": self.width,
            "height": self.height,
            "sourceAttachmentIds": list(self.source_attachment_ids[:16]),
            "panelIds": list(self.panel_ids[:16]),
            "generationContext": dict(self.generation_context) if self.generation_context is not None else None,
            "generationContextDigest": self.generation_context_digest,
            "figureId": self.figure_id,
            "collectionId": self.collection_id,
            "childChartIds": list(self.child_chart_ids[:16]),
            "sourceRevision": self.source_revision,
            "policyVersion": self.policy_version,
            "semanticRequired": bool(self.semantic_required),
            "allowWarnings": bool(self.allow_warnings),
            "maxAttempts": self.max_attempts,
        }
        canonical_json(value, limit=MAX_MANIFEST_BYTES, name="chart manifest")
        return value

    @classmethod
    def from_dict(cls, value: object) -> "ChartManifest":
        if not isinstance(value, Mapping):
            raise VerificationError("chart manifest must be an object")
        expected = {
            "version", "stagedRef", "runId", "sessionId", "workKey", "toolCallId", "outputOrdinal",
            "imageSha256", "mediaType", "byteCount", "chartSpec", "chartSpecDigest", "chartType",
            "title", "width", "height", "sourceAttachmentIds", "panelIds", "generationContext",
            "generationContextDigest", "figureId", "collectionId", "childChartIds", "sourceRevision",
            "policyVersion", "semanticRequired", "allowWarnings", "maxAttempts",
        }
        if set(value) != expected:
            raise VerificationError("chart manifest has missing or unexpected fields")
        strings = ("stagedRef", "runId", "sessionId", "workKey", "toolCallId", "imageSha256", "mediaType", "chartSpecDigest", "chartType", "title")
        if any(not isinstance(value.get(key), str) for key in strings) or not isinstance(value.get("chartSpec"), Mapping):
            raise VerificationError("chart manifest fields are invalid")
        ints = ("version", "outputOrdinal", "byteCount", "width", "height", "policyVersion", "maxAttempts")
        if any(isinstance(value.get(key), bool) or not isinstance(value.get(key), int) for key in ints):
            raise VerificationError("chart manifest counters are invalid")
        for key in ("semanticRequired", "allowWarnings"):
            if not isinstance(value.get(key), bool):
                raise VerificationError("chart manifest policy flags are invalid")
        for key in ("generationContextDigest", "figureId", "collectionId", "sourceRevision"):
            if value.get(key) is not None and not isinstance(value.get(key), str):
                raise VerificationError("chart manifest optional identity is invalid")
        for key in ("sourceAttachmentIds", "panelIds", "childChartIds"):
            raw = value.get(key)
            if not isinstance(raw, list) or len(raw) > 16 or any(not isinstance(item, str) for item in raw):
                raise VerificationError("chart manifest reference list is invalid")
        if value.get("generationContext") is not None and not isinstance(value.get("generationContext"), Mapping):
            raise VerificationError("chart manifest generation context is invalid")
        result = cls(
            staged_ref=value["stagedRef"], run_id=value["runId"], session_id=value["sessionId"],
            work_key=value["workKey"], tool_call_id=value["toolCallId"], output_ordinal=value["outputOrdinal"],
            image_sha256=value["imageSha256"], media_type=value["mediaType"], byte_count=value["byteCount"],
            chart_spec=dict(value["chartSpec"]), chart_spec_digest=value["chartSpecDigest"],
            chart_type=value["chartType"], title=value["title"], width=value["width"], height=value["height"],
            source_attachment_ids=_bounded_strings(value.get("sourceAttachmentIds"), limit=16),
            panel_ids=_bounded_strings(value.get("panelIds"), limit=16),
            generation_context=dict(value["generationContext"]) if isinstance(value.get("generationContext"), Mapping) else None,
            generation_context_digest=value["generationContextDigest"], figure_id=value["figureId"],
            collection_id=value["collectionId"], child_chart_ids=_bounded_strings(value.get("childChartIds"), limit=16),
            source_revision=value["sourceRevision"], policy_version=value["policyVersion"],
            semantic_required=value["semanticRequired"], allow_warnings=value["allowWarnings"],
            max_attempts=value["maxAttempts"], version=value["version"],
        )
        result.to_dict()
        return result

    @property
    def identity_digest(self) -> str:
        return content_digest(canonical_json(self.to_dict(), limit=MAX_MANIFEST_BYTES, name="chart manifest").encode("utf-8"))


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    location: str
    message: str
    severity: Literal["warning", "error"] = "error"
    suggested_action: str | None = None
    target: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: object) -> "VerificationIssue":
        if not isinstance(value, Mapping):
            raise VerificationError("verification issue must be an object")
        expected = {"code", "location", "message", "severity"}
        optional = {"suggestedAction", "target"}
        if not expected.issubset(value) or set(value) - expected - optional:
            raise VerificationError("verification issue has missing or unexpected fields")
        if any(not isinstance(value.get(key), str) for key in expected - {"severity"}):
            raise VerificationError("verification issue text is invalid")
        if value.get("severity") not in {"warning", "error"}:
            raise VerificationError("verification issue severity is invalid")
        suggested = value.get("suggestedAction")
        target = value.get("target")
        if suggested is not None and not isinstance(suggested, str):
            raise VerificationError("verification issue action is invalid")
        if target is not None and not isinstance(target, Mapping):
            raise VerificationError("verification issue target is invalid")
        result = cls(value["code"], value["location"], value["message"], value["severity"], suggested, dict(target) if target else None)
        result.to_dict()
        return result

    def to_dict(self) -> dict[str, Any]:
        if not self.code.strip() or not self.location.strip() or not self.message.strip():
            raise VerificationError("verification issue fields must be non-empty")
        if self.severity not in {"warning", "error"}:
            raise VerificationError("verification issue severity is invalid")
        if self.target is not None:
            canonical_json(self.target, limit=2048, name="verification issue target")
        result = {
            "code": self.code[:64],
            "location": self.location[:160],
            "message": self.message[:MAX_ISSUE_TEXT],
            "severity": self.severity,
        }
        if self.suggested_action:
            result["suggestedAction"] = self.suggested_action[:64]
        if self.target:
            result["target"] = dict(self.target)
        return result


@dataclass(frozen=True)
class VerificationResult:
    verification_ref: str
    staged_ref: str
    manifest_digest: str
    policy_version: int
    status: VerificationStatus
    checks: Mapping[str, str]
    issues: tuple[VerificationIssue, ...] = ()
    decision: str | None = None
    confidence: float | None = None
    attempt: int = 1

    @classmethod
    def from_dict(cls, value: object) -> "VerificationResult":
        if not isinstance(value, Mapping):
            raise VerificationError("verification result must be an object")
        expected = {
            "verificationRef", "stagedRef", "manifestDigest", "policyVersion", "status",
            "checks", "issues", "decision", "confidence", "attempt",
        }
        if set(value) != expected or not isinstance(value.get("checks"), Mapping) or not isinstance(value.get("issues"), list):
            raise VerificationError("verification result has missing or unexpected fields")
        for key in ("verificationRef", "stagedRef", "manifestDigest", "status"):
            if not isinstance(value.get(key), str):
                raise VerificationError("verification result identity or status is invalid")
        for key in ("policyVersion", "attempt"):
            if isinstance(value.get(key), bool) or not isinstance(value.get(key), int):
                raise VerificationError("verification result counters are invalid")
        if value.get("decision") is not None and not isinstance(value.get("decision"), str):
            raise VerificationError("verification result decision is invalid")
        if value.get("confidence") is not None and (
            isinstance(value.get("confidence"), bool)
            or not isinstance(value.get("confidence"), (int, float))
        ):
            raise VerificationError("verification result confidence is invalid")
        if len(value["issues"]) > MAX_ISSUES:
            raise VerificationError("verification result has too many issues")
        if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value["checks"].items()):
            raise VerificationError("verification check values are invalid")
        result = cls(
            verification_ref=value["verificationRef"], staged_ref=value["stagedRef"],
            manifest_digest=value["manifestDigest"], policy_version=value["policyVersion"],
            status=value["status"], checks=dict(value["checks"]),
            issues=tuple(VerificationIssue.from_dict(item) for item in value["issues"]),
            decision=value["decision"], confidence=value["confidence"], attempt=value["attempt"],
        )
        result.to_dict()
        return result

    def to_dict(self) -> dict[str, Any]:
        if not self.verification_ref.startswith("ver_") or not _REF.fullmatch(self.verification_ref):
            raise VerificationError("verification reference is invalid")
        if not self.staged_ref.startswith("stg_") or not _REF.fullmatch(self.staged_ref):
            raise VerificationError("verification staged reference is invalid")
        if self.status not in {"pass", "pass_with_warning", "fail", "unavailable"}:
            raise VerificationError("verification status is invalid")
        if not 1 <= self.attempt <= 8 or self.policy_version != VERIFICATION_POLICY_VERSION:
            raise VerificationError("verification attempt or policy version is invalid")
        if self.confidence is not None and (not math.isfinite(float(self.confidence)) or not 0 <= float(self.confidence) <= 1):
            raise VerificationError("verification confidence is invalid")
        if not _SHA256.fullmatch(self.manifest_digest):
            raise VerificationError("verification manifest digest is invalid")
        if len(self.checks) > 64 or any(
            not isinstance(name, str) or not name or len(name) > 96
            or not isinstance(value, str) or value not in _CHECK_VALUES
            for name, value in self.checks.items()
        ):
            raise VerificationError("verification checks are invalid")
        if self.decision is not None and self.decision not in {"pass", "pass_with_warning", "fail"}:
            raise VerificationError("verification decision is invalid")
        if len(self.issues) > MAX_ISSUES:
            raise VerificationError("verification has too many issues")
        value = {
            "verificationRef": self.verification_ref,
            "stagedRef": self.staged_ref,
            "manifestDigest": self.manifest_digest,
            "policyVersion": self.policy_version,
            "status": self.status,
            "checks": dict(list(self.checks.items())[:64]),
            "issues": [issue.to_dict() for issue in self.issues[:MAX_ISSUES]],
            "decision": self.decision,
            "confidence": self.confidence,
            "attempt": self.attempt,
        }
        canonical_json(value, limit=MAX_VERIFICATION_BYTES, name="verification result")
        return value


@dataclass(frozen=True)
class PublishedChart:
    artifact_id: str
    staged_ref: str
    verification_ref: str
    warning: bool
    work_key: str

    def to_dict(self) -> dict[str, Any]:
        if not self.artifact_id.startswith("artifact_") or not _REF.fullmatch(self.artifact_id):
            raise VerificationError("published artifact identity is invalid")
        if not self.staged_ref.startswith("stg_") or not self.verification_ref.startswith("ver_"):
            raise VerificationError("published artifact references are invalid")
        if not _REF.fullmatch(self.staged_ref) or not _REF.fullmatch(self.verification_ref) or not _valid_opaque_id(self.work_key):
            raise VerificationError("published artifact reference or work identity is invalid")
        return {
            "artifactId": self.artifact_id,
            "stagedRef": self.staged_ref,
            "verificationRef": self.verification_ref,
            "warning": self.warning,
            "workKey": self.work_key,
        }


__all__ = [
    "ChartManifest", "PublishedChart", "VerificationError", "VerificationIssue", "VerificationResult",
    "VerificationStatus", "content_digest", "canonical_json", "MANIFEST_VERSION", "VERIFICATION_POLICY_VERSION",
]
