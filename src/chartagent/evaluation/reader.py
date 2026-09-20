"""Read-only catalog and resource projection for persisted evaluations.

The evaluation runner owns the bundle on disk.  The desktop Gateway only
needs a safe, read-only projection of that bundle, so this module deliberately
does not instantiate the writable Gateway history store and never returns raw
SQLite rows or provider payloads.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..trace import truncate_text


EVALUATION_SCHEMA_VERSION = 1
VALID_EVALUATION_STATUSES = frozenset({"running", "completed", "partial", "blocked"})
VALID_CASE_STATUSES = frozenset({
    "pending",
    "running",
    "completed",
    "failed",
    "interrupted",
    "blocked",
    "not_run",
    "unknown",
})
SUPPORTED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_EVALUATIONS = 128
MAX_CASES = 64
MAX_EVENTS = 512
MAX_TEXT_BYTES = 64 * 1024
MAX_TEXT_CHARS = 12_000
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_RESOURCE_BYTES = 8 * 1024 * 1024
MAX_RESOURCES_PER_CASE = 128
MAX_DETAIL_ENTRIES = 256
MAX_DETAIL_ITEMS = 64
# This is a hard safety ceiling, not a normal projection rule.  Chart data
# commonly nests geometry below result/data/panels/proposal; scalar and
# numeric-array values must not disappear merely because of that shape.
MAX_DETAIL_DEPTH = 32
MAX_DETAIL_VALUE_BYTES = 48 * 1024
_EVALUATION_ID = re.compile(r"^eval_[A-Za-z0-9_-]{1,96}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,192}$")
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|private|tmp|var|opt|etc)/)[^\s\"'`，。；;]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b[A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|authorization|password|secret|private[_-]?key)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
_DETAIL_SENSITIVE_KEYS = frozenset({
    "api_key",
    "access_token",
    "authorization",
    "password",
    "secret",
    "private_key",
    "client_secret",
    "credentials",
    "reasoning",
    "reasoning_content",
    "raw",
    "raw_response",
    "image_bytes",
    "data_url",
})


class EvaluationReaderError(RuntimeError):
    """A stable, safe error for evaluation catalog operations."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message[:240]


@dataclass(frozen=True)
class _Resource:
    resource_id: str
    evaluation_id: str
    case_id: str
    kind: str
    label: str
    media_type: str
    path: Path
    byte_count: int
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resourceId": self.resource_id,
            "caseId": self.case_id,
            "kind": self.kind,
            "label": self.label,
            "mediaType": self.media_type,
            "byteCount": self.byte_count,
            **({"sha256": self.sha256} if self.sha256 else {}),
        }


@dataclass(frozen=True)
class _ArtifactRow:
    observation_id: str
    managed_path: str
    media_type: str
    caption: str
    byte_count: int
    artifact_kind: str
    chart_type: str | None
    title: str | None


class EvaluationReader:
    """Discover and safely project bundles below one canonical data root."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.evaluations_root = self.data_root / "evaluations"

    def list_summaries(self) -> list[dict[str, Any]]:
        if not self.evaluations_root.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        try:
            children = sorted(
                (path for path in self.evaluations_root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
        except OSError:
            return []
        for root in children[:MAX_EVALUATIONS * 2]:
            try:
                summary = self._read_summary(root)
            except EvaluationReaderError:
                # A malformed batch must not make the desktop Gateway fail.
                continue
            if summary is not None:
                entries.append(summary)
        entries.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        return entries[:MAX_EVALUATIONS]

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        root = self._bundle_root(evaluation_id)
        index = self._read_index(root)
        summary = self._summary_from_index(index)
        cases = [
            self._case_summary(evaluation_id, case_id, raw_case)
            for case_id, raw_case in self._case_items(index)
        ]
        return {
            "evaluation": summary,
            "cases": cases,
            "report": self._evaluation_report(root),
        }

    def get_case(self, evaluation_id: str, case_id: str) -> dict[str, Any]:
        root = self._bundle_root(evaluation_id)
        index = self._read_index(root)
        raw_case = self._find_case(index, case_id)
        case = self._case_detail(root, evaluation_id, case_id, raw_case)
        return {"evaluationId": evaluation_id, "case": case}

    def get_history(
        self,
        evaluation_id: str,
        case_id: str,
        *,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        root = self._bundle_root(evaluation_id)
        index = self._read_index(root)
        raw_case = self._find_case(index, case_id)
        session_id = self._bounded_id(raw_case.get("session_id"))
        run_id = self._bounded_id(raw_case.get("run_id"))
        if not session_id or not run_id:
            raise EvaluationReaderError(
                "evaluation_history_unavailable",
                409,
                "该 case 没有可读取的运行历史",
            )
        database = root / "sessions.db"
        if not database.is_file():
            raise EvaluationReaderError(
                "evaluation_history_unavailable",
                409,
                "评测运行历史尚未就绪",
            )
        try:
            return self._read_history(root, evaluation_id, case_id, database, session_id, run_id, after_sequence)
        except EvaluationReaderError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EvaluationReaderError(
                "evaluation_history_unavailable",
                503,
                "评测运行历史暂时不可读",
            ) from exc

    def get_history_details(
        self,
        evaluation_id: str,
        case_id: str,
        *,
        after_record_sequence: int = 0,
    ) -> dict[str, Any]:
        """Return bounded, read-only supplemental records for a run.

        Gateway events are the primary transcript returned by ``get_history``.
        This endpoint adds model-visible ``records`` and any event context that
        has no corresponding Gateway event while keeping the two sequence
        spaces separate.
        """
        root = self._bundle_root(evaluation_id)
        index = self._read_index(root)
        raw_case = self._find_case(index, case_id)
        session_id = self._bounded_id(raw_case.get("session_id"))
        run_id = self._bounded_id(raw_case.get("run_id"))
        if not session_id or not run_id:
            raise EvaluationReaderError(
                "evaluation_history_unavailable",
                409,
                "该 case 没有可读取的运行历史",
            )
        database = root / "sessions.db"
        if not database.is_file():
            raise EvaluationReaderError(
                "evaluation_history_unavailable",
                409,
                "评测运行历史尚未就绪",
            )
        try:
            return self._read_history_details(
                root,
                evaluation_id,
                case_id,
                database,
                session_id,
                run_id,
                max(0, int(after_record_sequence)),
            )
        except EvaluationReaderError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EvaluationReaderError(
                "evaluation_history_unavailable",
                503,
                "评测详细运行记录暂时不可读",
            ) from exc

    def get_resource(
        self,
        evaluation_id: str,
        resource_id: str,
        *,
        case_id: str | None = None,
    ) -> tuple[bytes, str]:
        root = self._bundle_root(evaluation_id)
        index = self._read_index(root)
        expected_case = case_id.strip() if isinstance(case_id, str) and case_id.strip() else None
        if expected_case is not None:
            self._find_case(index, expected_case)
        if not _IDENTIFIER.fullmatch(resource_id) or ".." in resource_id:
            raise EvaluationReaderError("evaluation_resource_not_found", 404, "评测资源不存在")
        for current_case_id, raw_case in self._case_items(index):
            if expected_case is not None and current_case_id != expected_case:
                continue
            for resource in self._resources(root, evaluation_id, current_case_id, raw_case):
                if resource.resource_id != resource_id:
                    continue
                try:
                    if resource.kind == "history_detail":
                        raw = resource.path.read_bytes()
                        if len(raw) > MAX_ARTIFACT_RESOURCE_BYTES:
                            raise EvaluationReaderError("evaluation_resource_unavailable", 503, "评测资源超过读取限制")
                        envelope = json.loads(raw.decode("utf-8"))
                        payload = envelope.get("payload") if isinstance(envelope, Mapping) else {}
                        projected, truncated, redacted = self._safe_projection(payload)
                        content = json.dumps(
                            {
                                "runId": self._bounded_id(envelope.get("runId")) if isinstance(envelope, Mapping) else None,
                                "sequence": self._bounded_int(envelope.get("sequence")) if isinstance(envelope, Mapping) else None,
                                "kind": self._bounded_text(envelope.get("kind"), 64) if isinstance(envelope, Mapping) else "unknown",
                                "payload": projected,
                                "integrity": {
                                    "status": "truncated" if truncated else "redacted" if redacted else "complete",
                                    "source": "evaluation_history_detail",
                                },
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    elif resource.media_type == "application/json":
                        # Diagnostic JSON is served as the same bounded
                        # timeline projection used by the detail endpoint;
                        # the original file may contain fields not meant for
                        # the desktop client.
                        content = json.dumps(
                            {
                                "caseId": current_case_id,
                                "timeline": self._diagnostic_timeline(root, raw_case),
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    elif resource.media_type in {"text/markdown", "text/plain"}:
                        content = (self._read_text(resource.path) or "").encode("utf-8")
                    else:
                        content = resource.path.read_bytes()
                except EvaluationReaderError:
                    raise
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise EvaluationReaderError("evaluation_resource_unavailable", 503, "评测资源暂时不可用") from exc
                if not content or len(content) > MAX_RESOURCE_BYTES:
                    raise EvaluationReaderError("evaluation_resource_unavailable", 503, "评测资源超过读取限制")
                return content, resource.media_type
        raise EvaluationReaderError("evaluation_resource_not_found", 404, "评测资源不存在")

    def _bundle_root(self, evaluation_id: str) -> Path:
        if not isinstance(evaluation_id, str) or not _EVALUATION_ID.fullmatch(evaluation_id):
            raise EvaluationReaderError("evaluation_not_found", 404, "评测批次不存在")
        root = (self.evaluations_root / evaluation_id).resolve()
        try:
            root.relative_to(self.evaluations_root.resolve())
        except ValueError as exc:
            raise EvaluationReaderError("evaluation_not_found", 404, "评测批次不存在") from exc
        if not root.is_dir():
            raise EvaluationReaderError("evaluation_not_found", 404, "评测批次不存在")
        return root

    def _read_summary(self, root: Path) -> dict[str, Any] | None:
        try:
            index = self._read_index(root)
            return self._summary_from_index(index)
        except EvaluationReaderError:
            return None

    def _read_index(self, root: Path) -> dict[str, Any]:
        payload = self._read_json(root / "evaluation.json", "evaluation_not_ready")
        if payload.get("schema_version") != EVALUATION_SCHEMA_VERSION:
            raise EvaluationReaderError("evaluation_schema_unsupported", 409, "评测批次 schema 不受支持")
        evaluation_id = payload.get("evaluation_id")
        if not isinstance(evaluation_id, str) or not _EVALUATION_ID.fullmatch(evaluation_id) or evaluation_id != root.name:
            raise EvaluationReaderError("evaluation_schema_invalid", 409, "评测批次索引无效")
        status = payload.get("status")
        if status not in VALID_EVALUATION_STATUSES:
            raise EvaluationReaderError("evaluation_schema_invalid", 409, "评测批次状态无效")
        cases = payload.get("cases")
        if not isinstance(cases, Mapping) or len(cases) > MAX_CASES:
            raise EvaluationReaderError("evaluation_schema_invalid", 409, "评测批次 case 清单无效")
        return payload

    @staticmethod
    def _read_json(path: Path, code: str) -> dict[str, Any]:
        try:
            if not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES:
                raise EvaluationReaderError(code, 409, "评测文件尚未就绪")
            value = json.loads(path.read_text(encoding="utf-8"))
        except EvaluationReaderError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvaluationReaderError("evaluation_schema_invalid", 409, "评测文件无法安全读取") from exc
        if not isinstance(value, dict):
            raise EvaluationReaderError("evaluation_schema_invalid", 409, "评测文件格式无效")
        return value

    def _summary_from_index(self, index: Mapping[str, Any]) -> dict[str, Any]:
        cases = [raw_case for _, raw_case in self._case_items(index)]
        counts: dict[str, int] = {}
        failures: list[dict[str, Any]] = []
        for raw_case in cases:
            status = self._case_status(raw_case.get("status"))
            counts[status] = counts.get(status, 0) + 1
            failure = self._first_failure(raw_case.get("first_failure"))
            if failure:
                failures.append(failure)
        first_failure = failures[0] if failures else None
        return {
            "evaluationId": self._bounded_id(index.get("evaluation_id")) or "unknown",
            "status": index.get("status"),
            "provider": self._bounded_text(index.get("provider"), 64),
            "model": self._bounded_text(index.get("model"), 128),
            "startedAt": self._bounded_text(index.get("started_at"), 64),
            "endedAt": self._bounded_text(index.get("ended_at"), 64),
            "updatedAt": self._bounded_text(index.get("ended_at") or index.get("started_at"), 64),
            "caseCount": len(cases),
            "caseCounts": counts,
            "firstFailure": first_failure,
        }

    def _case_items(self, index: Mapping[str, Any]):
        cases = index.get("cases")
        if not isinstance(cases, Mapping):
            return []
        result: list[tuple[str, Mapping[str, Any]]] = []
        for raw_case_id, raw_case in cases.items():
            case_id = str(raw_case_id)
            if not _IDENTIFIER.fullmatch(case_id) or not isinstance(raw_case, Mapping):
                continue
            result.append((case_id, raw_case))
        return result[:MAX_CASES]

    def _find_case(self, index: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
        if not isinstance(case_id, str) or not _IDENTIFIER.fullmatch(case_id):
            raise EvaluationReaderError("evaluation_case_not_found", 404, "评测 case 不存在")
        for current_id, raw_case in self._case_items(index):
            if current_id == case_id:
                return raw_case
        raise EvaluationReaderError("evaluation_case_not_found", 404, "评测 case 不存在")

    def _case_summary(self, evaluation_id: str, case_id: str, raw_case: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "evaluationId": evaluation_id,
            "caseId": case_id,
            "status": self._case_status(raw_case.get("status")),
            "sessionId": self._bounded_id(raw_case.get("session_id")),
            "runId": self._bounded_id(raw_case.get("run_id")),
            "sha256": self._bounded_text(raw_case.get("sha256"), 64),
            "firstFailure": self._first_failure(raw_case.get("first_failure")),
            "error": self._safe_error(raw_case.get("error")),
        }

    def _case_detail(self, root: Path, evaluation_id: str, case_id: str, raw_case: Mapping[str, Any]) -> dict[str, Any]:
        detail = self._case_summary(evaluation_id, case_id, raw_case)
        detail["asset"] = self._safe_asset_label(raw_case.get("asset"))
        detail["expectedPanels"] = self._expected_panels(root, case_id)
        detail["timeline"] = self._diagnostic_timeline(root, raw_case)
        detail["report"] = self._case_report(root, raw_case)
        detail["resources"] = [
            resource.to_dict()
            for resource in self._resources(root, evaluation_id, case_id, raw_case)
        ]
        return detail

    def _expected_panels(self, root: Path, case_id: str) -> list[dict[str, Any]]:
        try:
            manifest = self._read_json(root / "manifest.json", "evaluation_not_ready")
        except EvaluationReaderError:
            return []
        samples = manifest.get("samples")
        if not isinstance(samples, list):
            return []
        for sample in samples:
            if not isinstance(sample, Mapping) or sample.get("case_id") != case_id:
                continue
            expected = sample.get("expected_panels")
            items = expected.get("items") if isinstance(expected, Mapping) else []
            if not isinstance(items, list):
                return []
            result: list[dict[str, Any]] = []
            for item in items[:64]:
                if not isinstance(item, Mapping):
                    continue
                panel: dict[str, Any] = {"name": self._bounded_text(item.get("name"), 240) or "未命名区域"}
                for source, target, limit in (("chart_type", "chartType", 64), ("role", "role", 64)):
                    value = self._bounded_text(item.get(source), limit)
                    if value:
                        panel[target] = value
                bbox = item.get("bbox_norm")
                if isinstance(bbox, list) and len(bbox) == 4:
                    try:
                        values = [float(value) for value in bbox]
                    except (TypeError, ValueError):
                        values = []
                    if len(values) == 4 and all(0 <= value <= 1 for value in values):
                        panel["bboxNorm"] = values
                result.append(panel)
            return result
        return []

    def _diagnostic_timeline(self, root: Path, raw_case: Mapping[str, Any]) -> dict[str, Any]:
        report = raw_case.get("report")
        report_path = self._relative_file(root, report.get("json") if isinstance(report, Mapping) else None)
        if report_path is None:
            return {"stages": [], "anomalies": [], "historyGap": False, "firstFailure": self._first_failure(raw_case.get("first_failure"))}
        try:
            payload = self._read_json(report_path, "evaluation_report_unavailable")
        except EvaluationReaderError:
            return {"stages": [], "anomalies": [], "historyGap": False, "firstFailure": self._first_failure(raw_case.get("first_failure"))}
        timeline = payload.get("timeline") if isinstance(payload.get("timeline"), Mapping) else {}
        stages: list[dict[str, Any]] = []
        raw_stages = timeline.get("stages") if isinstance(timeline, Mapping) else []
        if isinstance(raw_stages, list):
            for raw_stage in raw_stages[:16]:
                if not isinstance(raw_stage, Mapping):
                    continue
                stage: dict[str, Any] = {
                    "name": self._bounded_text(raw_stage.get("name"), 64) or "unknown",
                    "status": self._bounded_text(raw_stage.get("status"), 32) or "not_observed",
                    "sequences": self._bounded_ints(raw_stage.get("sequences"), 64),
                    "panelIds": self._bounded_strings(raw_stage.get("panel_ids"), 32, 128),
                    "attemptIds": self._bounded_strings(raw_stage.get("attempt_ids"), 32, 128),
                    "artifactIds": self._bounded_strings(raw_stage.get("artifact_ids"), 32, 128),
                    "observationIds": self._bounded_strings(raw_stage.get("observation_ids"), 32, 128),
                    "errors": self._bounded_strings(raw_stage.get("errors"), 8, 240),
                    "notes": self._bounded_strings(raw_stage.get("notes"), 8, 240),
                }
                stages.append(stage)
        anomalies: list[dict[str, Any]] = []
        raw_anomalies = timeline.get("anomalies") if isinstance(timeline, Mapping) else []
        if isinstance(raw_anomalies, list):
            for raw_anomaly in raw_anomalies[:32]:
                if not isinstance(raw_anomaly, Mapping):
                    continue
                anomaly = {
                    "code": self._bounded_text(raw_anomaly.get("code"), 96) or "unknown",
                    "category": self._bounded_text(raw_anomaly.get("category"), 96) or "unknown",
                    "stage": self._bounded_text(raw_anomaly.get("stage"), 64) or "unknown",
                    "sequence": self._bounded_int(raw_anomaly.get("sequence")),
                    "message": self._safe_text(raw_anomaly.get("message"), 240) or "未提供说明",
                }
                anomalies.append(anomaly)
        return {
            "stages": stages,
            "anomalies": anomalies,
            "historyGap": bool(timeline.get("history_gap")),
            "firstFailure": self._first_failure(timeline.get("first_failure")) or self._first_failure(raw_case.get("first_failure")),
        }

    def _evaluation_report(self, root: Path) -> dict[str, Any]:
        report_path = root / "report.md"
        if report_path.is_file():
            return {"available": True, "source": "report.md", "truncated": report_path.stat().st_size > MAX_TEXT_BYTES}
        return {"available": False, "source": "standard_summary", "truncated": False}

    def _case_report(self, root: Path, raw_case: Mapping[str, Any]) -> dict[str, Any]:
        root_report = root / "report.md"
        source = root_report if root_report.is_file() else None
        report = raw_case.get("report")
        diagnostic_markdown = self._relative_file(root, report.get("markdown") if isinstance(report, Mapping) else None)
        if source is None and diagnostic_markdown is not None:
            source = diagnostic_markdown
        text = self._read_text(source) if source is not None else ""
        return {
            "available": bool(text),
            "source": "report.md" if source == root_report else "diagnostic_markdown",
            "text": text,
            "truncated": bool(source and source.is_file() and source.stat().st_size > MAX_TEXT_BYTES),
        }

    def _resources(
        self,
        root: Path,
        evaluation_id: str,
        case_id: str,
        raw_case: Mapping[str, Any],
    ) -> list[_Resource]:
        resources: list[_Resource] = []
        seen_paths: set[Path] = set()

        def add(path: Path, *, kind: str, label: str, media_type: str | None = None, token: str | None = None, limit: int = MAX_RESOURCE_BYTES) -> None:
            if len(resources) >= MAX_RESOURCES_PER_CASE:
                return
            safe_path = self._safe_bundle_file(root, path)
            if safe_path is None or safe_path in seen_paths or not safe_path.is_file():
                return
            try:
                byte_count = safe_path.stat().st_size
            except OSError:
                return
            if byte_count <= 0 or byte_count > limit:
                return
            detected = (media_type or mimetypes.guess_type(safe_path.name)[0] or "").lower()
            if detected not in SUPPORTED_IMAGE_TYPES and detected not in {"text/markdown", "application/json", "text/plain"}:
                return
            seen_paths.add(safe_path)
            identifier = token or safe_path.relative_to(root).as_posix()
            resource_id = self._resource_id(evaluation_id, case_id, kind, identifier)
            digest = None
            if kind == "history_detail":
                try:
                    digest = hashlib.sha256(safe_path.read_bytes()).hexdigest()
                except OSError:
                    return
            resources.append(_Resource(resource_id, evaluation_id, case_id, kind, self._safe_text(label, 240) or kind, detected, safe_path, byte_count, digest))

        report_assets = root / "report-assets"
        if report_assets.is_dir():
            try:
                asset_paths = sorted(path for path in report_assets.rglob("*") if path.is_file())
            except OSError:
                asset_paths = []
            for path in asset_paths:
                if (mimetypes.guess_type(path.name)[0] or "").lower() not in SUPPORTED_IMAGE_TYPES:
                    continue
                label = path.stem.replace("-", " ").replace("_", " ")
                kind = "input" if path.stem.lower() == "input" else "report_image"
                add(path, kind=kind, label=label, token=path.relative_to(report_assets).as_posix())

        session_id = self._bounded_id(raw_case.get("session_id"))
        run_id = self._bounded_id(raw_case.get("run_id"))
        if run_id and session_id:
            for row in self._artifact_rows(root, session_id, run_id):
                kind = {
                    "visual_observation": "observation",
                    "generated_candidate": "candidate",
                    "generated_chart": "artifact",
                }.get(row.artifact_kind, "evidence")
                label = row.title or row.caption or row.observation_id
                add(
                    Path(row.managed_path),
                    kind=kind,
                    label=label,
                    media_type=row.media_type,
                    token=row.observation_id,
                    limit=MAX_ARTIFACT_RESOURCE_BYTES,
                )

            history_detail_root = root / "run-artifacts" / "history-details" / run_id
            if history_detail_root.is_dir():
                try:
                    detail_paths = sorted(path for path in history_detail_root.rglob("*.json") if path.is_file())
                except OSError:
                    detail_paths = []
                for path in detail_paths:
                    add(
                        path,
                        kind="history_detail",
                        label=f"事件 {path.stem} 的完整安全结果",
                        media_type="application/json",
                        token=path.relative_to(root / "run-artifacts" / "history-details").as_posix(),
                        limit=MAX_ARTIFACT_RESOURCE_BYTES,
                    )

            attachment_root = root / "attachments" / session_id
            if attachment_root.is_dir() and not any(item.kind == "input" for item in resources):
                try:
                    attachments = sorted(path for path in attachment_root.rglob("*") if path.is_file())
                except OSError:
                    attachments = []
                for path in attachments:
                    add(path, kind="input", label="输入图片", token=path.relative_to(root).as_posix())
                    if any(item.kind == "input" for item in resources):
                        break

        report = raw_case.get("report")
        if isinstance(report, Mapping):
            markdown_path = self._relative_file(root, report.get("markdown"))
            json_path = self._relative_file(root, report.get("json"))
            if markdown_path:
                add(markdown_path, kind="report_text", label="诊断 Markdown", media_type="text/markdown", limit=MAX_TEXT_BYTES)
            if json_path:
                add(json_path, kind="diagnostic_json", label="诊断 JSON", media_type="application/json", limit=MAX_TEXT_BYTES)
        if not any(item.kind == "report_text" for item in resources) and (root / "report.md").is_file():
            add(root / "report.md", kind="report_text", label="评测报告", media_type="text/markdown", limit=MAX_TEXT_BYTES)
        return resources

    def _history_detail_resource(
        self,
        root: Path,
        evaluation_id: str,
        case_id: str,
        run_id: str,
        value: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        token = value.get("token")
        if not isinstance(token, str) or not token or ".." in Path(token).parts:
            return None
        token_path = Path(token)
        if token_path.parts[:1] == ("history-details",):
            token = token_path.relative_to("history-details").as_posix()
        safe_run = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)[:128] or "run"
        if Path(token).parts[:1] != (safe_run,):
            return None
        raw_case = self._case_from_root(root, case_id)
        for resource in self._resources(root, evaluation_id, case_id, raw_case):
            if resource.kind == "history_detail" and resource.path.relative_to(root / "run-artifacts" / "history-details").as_posix() == token:
                return resource.to_dict()
        return None

    def _artifact_rows(self, root: Path, session_id: str, run_id: str) -> list[_ArtifactRow]:
        database = root / "sessions.db"
        if not database.is_file():
            return []
        try:
            with self._readonly_connection(database) as connection:
                rows = connection.execute(
                    "SELECT observation_id, managed_path, media_type, caption, byte_count, artifact_kind, chart_type, title "
                    "FROM gateway_run_artifacts WHERE run_id = ? AND session_id = ? ORDER BY created_at, observation_id",
                    (run_id, session_id),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return []
        result: list[_ArtifactRow] = []
        for row in rows[:MAX_RESOURCES_PER_CASE]:
            result.append(_ArtifactRow(
                observation_id=self._bounded_id(row[0]) or "unknown",
                managed_path=str(row[1] or ""),
                media_type=str(row[2] or "").lower(),
                caption=self._safe_text(row[3], 500) or "评测视觉证据",
                byte_count=self._bounded_int(row[4]) or 0,
                artifact_kind=self._bounded_text(row[5], 64) or "evidence",
                chart_type=self._bounded_text(row[6], 64),
                title=self._bounded_text(row[7], 240),
            ))
        return result

    def _read_history(
        self,
        root: Path,
        evaluation_id: str,
        case_id: str,
        database: Path,
        session_id: str,
        run_id: str,
        after_sequence: int,
    ) -> dict[str, Any]:
        after = max(0, int(after_sequence))
        connection = self._readonly_connection(database)
        try:
            run = connection.execute(
                "SELECT run_id, session_id, status, created_at, updated_at, terminal_code, terminal_message, "
                "answer_source, history_warning, provider, model, cancel_requested, retry_of, parent_run_id, "
                "root_run_id, continuation_kind, recovery_status, recovery_phase, recovery_next_action, "
                "recovery_reason, recovery_version, recovery_updated_at, "
                "(SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count "
                "FROM gateway_runs r WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
            if run is None:
                raise EvaluationReaderError("evaluation_history_unavailable", 404, "评测运行历史不存在")
            first_row = connection.execute(
                "SELECT MIN(sequence) FROM gateway_run_events WHERE run_id = ?", (run_id,)
            ).fetchone()
            first_sequence = int(first_row[0]) if first_row and first_row[0] is not None else None
            rows = connection.execute(
                "SELECT run_id, sequence, kind, payload_json, created_at FROM gateway_run_events "
                "WHERE run_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                (run_id, after, MAX_EVENTS),
            ).fetchall()
        finally:
            connection.close()
        events = [self._safe_event(root, evaluation_id, case_id, run_id, row) for row in rows]
        return {
            "run": self._safe_run_summary(run),
            "events": events,
            "historyGap": first_sequence is not None and after < first_sequence - 1,
            "historyGapCode": "history_gap" if first_sequence is not None and after < first_sequence - 1 else None,
            "firstSequence": first_sequence,
            "integrity": self._history_integrity(events),
        }

    def _read_history_details(
        self,
        root: Path,
        evaluation_id: str,
        case_id: str,
        database: Path,
        session_id: str,
        run_id: str,
        after_record_sequence: int,
    ) -> dict[str, Any]:
        connection = self._readonly_connection(database)
        records_table_available = False
        records: list[Any] = []
        record_count = 0
        first_record_sequence: int | None = None
        event_rows: list[Any] = []
        event_count = 0
        first_event_sequence: int | None = None
        try:
            run = connection.execute(
                "SELECT run_id, session_id, status, created_at, updated_at, terminal_code, terminal_message, "
                "answer_source, history_warning, provider, model, cancel_requested, retry_of, parent_run_id, "
                "root_run_id, continuation_kind, recovery_status, recovery_phase, recovery_next_action, "
                "recovery_reason, recovery_version, recovery_updated_at, "
                "(SELECT COUNT(*) FROM gateway_run_events e WHERE e.run_id = r.run_id) AS event_count "
                "FROM gateway_runs r WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
            if run is None:
                raise EvaluationReaderError("evaluation_history_unavailable", 404, "评测运行历史不存在")

            event_count = max(0, int(run[22] or 0))
            first_row = connection.execute(
                "SELECT MIN(sequence) FROM gateway_run_events WHERE run_id = ?", (run_id,)
            ).fetchone()
            first_event_sequence = int(first_row[0]) if first_row and first_row[0] is not None else None
            event_rows = connection.execute(
                "SELECT run_id, sequence, kind, payload_json, created_at FROM gateway_run_events "
                "WHERE run_id = ? ORDER BY sequence LIMIT ?",
                (run_id, MAX_DETAIL_ENTRIES + 1),
            ).fetchall()

            table_row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'records'"
            ).fetchone()
            records_table_available = table_row is not None
            if records_table_available:
                count_row = connection.execute(
                    "SELECT COUNT(*) FROM records WHERE run_id = ?", (run_id,)
                ).fetchone()
                record_count = max(0, int(count_row[0] or 0)) if count_row else 0
                first_record_row = connection.execute(
                    "SELECT MIN(sequence) FROM records WHERE run_id = ?", (run_id,)
                ).fetchone()
                first_record_sequence = (
                    int(first_record_row[0])
                    if first_record_row and first_record_row[0] is not None
                    else None
                )
                records = connection.execute(
                    "SELECT sequence, kind, payload_json, created_at FROM records "
                    "WHERE run_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                    (run_id, after_record_sequence - 1 if after_record_sequence == 0 else after_record_sequence, MAX_DETAIL_ENTRIES + 1),
                ).fetchall()
        finally:
            connection.close()

        records_truncated = len(records) > MAX_DETAIL_ENTRIES
        event_rows_truncated = len(event_rows) > MAX_DETAIL_ENTRIES
        record_rows = records[:MAX_DETAIL_ENTRIES]
        event_rows = event_rows[:MAX_DETAIL_ENTRIES]
        record_entries = [
            self._safe_record_entry(row)
            for row in record_rows
        ]
        event_entries = [
            self._safe_detail_event(root, evaluation_id, case_id, run_id, row)
            for row in event_rows
        ]
        event_call_ids = {
            entry.get("callId")
            for entry in event_entries
            if entry.get("kind") in {"tool_call", "tool_result"} and entry.get("callId")
        }
        # Gateway events are authoritative for tool lifecycle and correlation.
        # Records remain useful for conversation/repair context, but the same
        # tool message must not be rendered a second time.
        record_entries = [
            entry for entry in record_entries
            if not (entry.get("kind") == "tool_message" and entry.get("callId") in event_call_ids)
        ]
        entries = record_entries + event_entries
        entries.sort(key=self._detail_entry_sort_key)
        redacted = any(bool(entry.get("redacted")) for entry in entries)
        truncated = records_truncated or event_rows_truncated or any(bool(entry.get("truncated")) for entry in entries)
        record_gap = first_record_sequence is not None and after_record_sequence < first_record_sequence - 1
        event_gap = first_event_sequence is not None and first_event_sequence > 1
        notice = None
        if redacted and not records_table_available:
            notice = "模型可见 records 不可用，当前仅展示 Gateway 事件；敏感字段、私有推理、绝对路径和二进制内容已隐藏。"
        elif redacted:
            notice = "敏感字段、私有推理、绝对路径和二进制内容已隐藏。"
        elif not records_table_available:
            notice = "模型可见 records 不可用，当前仅展示 Gateway 事件。"
        return {
            "run": self._safe_run_summary(run),
            "entries": entries,
            "recordsAvailable": bool(records_table_available and record_count > 0),
            "eventsAvailable": bool(event_count > 0),
            "sourceAvailability": {
                "records": records_table_available,
                "gatewayEvents": True,
            },
            "recordCount": record_count,
            "eventCount": event_count,
            "historyGap": record_gap or event_gap,
            "firstRecordSequence": first_record_sequence,
            "firstEventSequence": first_event_sequence,
            "truncated": truncated,
            "redacted": redacted,
            "notice": notice,
            "integrity": self._history_integrity(event_entries, entries=entries, records_available=records_table_available),
        }

    @staticmethod
    def _history_integrity(
        events: list[Mapping[str, Any]],
        *,
        entries: list[Mapping[str, Any]] | None = None,
        records_available: bool = False,
    ) -> dict[str, Any]:
        visible = list(entries or events)
        def flag(item: Mapping[str, Any], key: str) -> bool:
            if item.get(key):
                return True
            payload = item.get("payload")
            return isinstance(payload, Mapping) and bool(payload.get(key))

        def resource(item: Mapping[str, Any]) -> bool:
            if item.get("detailResource"):
                return True
            payload = item.get("payload")
            return isinstance(payload, Mapping) and bool(payload.get("detailResource"))

        def integrity(item: Mapping[str, Any]) -> Mapping[str, Any]:
            direct = item.get("integrity")
            if isinstance(direct, Mapping):
                return direct
            payload = item.get("payload")
            nested = payload.get("integrity") if isinstance(payload, Mapping) else None
            return nested if isinstance(nested, Mapping) else {}

        unavailable = sum(1 for item in visible if flag(item, "detailUnavailable"))
        recoverable = sum(1 for item in visible if resource(item))
        redacted = sum(1 for item in visible if flag(item, "redacted"))
        persisted_truncated = sum(
            1 for item in visible
            if integrity(item).get("persistedTruncated")
        )
        projection_truncated = sum(
            1 for item in visible
            if integrity(item).get("projectionTruncated")
        )
        if unavailable:
            status = "unavailable"
        elif redacted:
            status = "redacted"
        elif persisted_truncated or projection_truncated:
            status = "truncated"
        else:
            status = "complete"
        return {
            "status": status,
            "source": "gateway_events" if events else "records",
            "recordsAvailable": records_available,
            "eventCount": len(events),
            "detailResourceCount": recoverable,
            "unavailableCount": unavailable,
            "redactedCount": redacted,
            "persistedTruncatedCount": persisted_truncated,
            "projectionTruncatedCount": projection_truncated,
        }

    @classmethod
    def _detail_entry_sort_key(cls, entry: Mapping[str, Any]) -> tuple[str, int, int, str]:
        timestamp = str(entry.get("timestamp") or "")
        record_sequence = entry.get("recordSequence")
        event_sequence = entry.get("eventSequence")
        source_order = 0 if record_sequence is not None else 1
        sequence = record_sequence if isinstance(record_sequence, int) else event_sequence
        return timestamp, int(sequence or 0), source_order, str(entry.get("entryId") or "")

    @classmethod
    def _safe_record_entry(cls, row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row[2] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        payload = payload if isinstance(payload, Mapping) else {}
        message = payload.get("message")
        role = message.get("role") if isinstance(message, Mapping) else None
        if role not in {"user", "assistant", "tool", "system"}:
            role = None
        record_kind = cls._bounded_text(row[1], 64) or "record"
        kind = "conversation" if role in {"user", "assistant", "system"} else "tool_message" if role == "tool" else "record"
        if record_kind == "measurement_repair":
            kind = "repair"
        entry: dict[str, Any] = {
            "entryId": f"record:{max(0, int(row[0]))}",
            "source": "record",
            "recordSequence": max(0, int(row[0])),
            "eventSequence": None,
            "timestamp": cls._bounded_text(row[3], 64) or "",
            "kind": kind,
            "recordKind": record_kind,
        }
        if role:
            entry["role"] = role
        tool_name = cls._bounded_text(payload.get("tool_name") or (message.get("name") if isinstance(message, Mapping) else None), 128)
        call_id = cls._bounded_id(payload.get("call_id") or payload.get("tool_call_id") or (message.get("tool_call_id") if isinstance(message, Mapping) else None))
        if tool_name:
            entry["toolName"] = tool_name
        if call_id:
            entry["callId"] = call_id
        status = cls._bounded_text(payload.get("status"), 32)
        if status:
            entry["status"] = status

        truncated = False
        redacted = False
        if isinstance(message, Mapping):
            content = message.get("content")
            if role == "tool" and isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    pass
            projected, content_truncated, content_redacted = cls._safe_projection(content)
            if content is not None:
                entry["content"] = projected
            truncated |= content_truncated
            redacted |= content_redacted
            truncated |= isinstance(content, Mapping) and bool(content.get("truncated"))
            if isinstance(message.get("tool_calls"), list):
                projected_calls, calls_truncated, calls_redacted = cls._safe_projection(message.get("tool_calls"))
                entry["toolCalls"] = projected_calls
                truncated |= calls_truncated
                redacted |= calls_redacted
        elif "text" in payload:
            text = payload.get("text")
            entry["content"] = cls._safe_text(text, MAX_TEXT_CHARS) or ""
            truncated |= isinstance(text, str) and len(text) > MAX_TEXT_CHARS
        if kind in {"record", "repair"}:
            projected, detail_truncated, detail_redacted = cls._safe_projection(payload)
            entry["details"] = projected
            truncated |= detail_truncated
            redacted |= detail_redacted
        if truncated:
            entry["truncated"] = True
        if redacted:
            entry["redacted"] = True
        return entry

    def _safe_detail_event(self, root: Path, evaluation_id: str, case_id: str, run_id: str, row: Any) -> dict[str, Any]:
        try:
            raw_payload = json.loads(row[3] or "{}")
        except (TypeError, json.JSONDecodeError):
            raw_payload = {}
        payload = raw_payload if isinstance(raw_payload, Mapping) else {}
        sequence = max(0, int(row[1]))
        kind = self._bounded_text(row[2], 64) or "unknown"
        entry: dict[str, Any] = {
            "entryId": f"event:{sequence}",
            "source": "event",
            "recordSequence": None,
            "eventSequence": sequence,
            "timestamp": self._bounded_text(row[4], 64) or "",
            "kind": kind,
        }
        for source, target, limit in (
            ("tool_name", "toolName", 128),
            ("tool_display_name", "toolDisplayName", 160),
            ("tool_label", "toolLabel", 240),
            ("call_id", "callId", 192),
            ("status", "status", 32),
            ("code", "code", 96),
            ("reason", "reason", 240),
            ("message", "content", MAX_TEXT_CHARS),
        ):
            value = payload.get(source)
            if value is None:
                continue
            safe = self._safe_text(value, limit) if isinstance(value, str) else value if isinstance(value, (int, float, bool)) else None
            if safe not in (None, ""):
                entry[target] = safe
        raw_result = payload.get("result")
        persisted_truncated = bool(payload.get("truncated")) or (
            isinstance(raw_result, Mapping) and bool(raw_result.get("truncated"))
        )
        truncated = persisted_truncated
        projection_truncated = False
        redacted = False
        detail_resource = self._history_detail_resource(root, evaluation_id, case_id, run_id, payload.get("detail_resource"))
        if kind == "tool_call" and "arguments" in payload:
            projected, value_truncated, value_redacted = self._safe_projection(payload.get("arguments"))
            entry["arguments"] = projected
            truncated |= value_truncated
            projection_truncated |= value_truncated
            redacted |= value_redacted
        if kind == "tool_result":
            result = payload.get("result")
            if result is None and payload.get("truncated"):
                result = {"truncated": True}
            if result is not None:
                projected, value_truncated, value_redacted = self._safe_projection(result)
                entry["result"] = projected
                truncated |= value_truncated
                projection_truncated |= value_truncated
                redacted |= value_redacted
                truncated |= isinstance(result, Mapping) and bool(result.get("truncated"))
        if kind == "visual_observation":
            entry["observations"] = self._safe_observations(root, evaluation_id, case_id, payload.get("observations"))
        if kind == "generated_chart":
            entry["artifacts"] = self._safe_generated_artifacts(evaluation_id, case_id, payload.get("artifacts"))
        if detail_resource is not None:
            entry["detailResource"] = detail_resource
        elif persisted_truncated:
            entry["detailUnavailable"] = True
            entry["detailUnavailableReason"] = "legacy_bundle_no_detail_resource"
        if kind.startswith("measurement_repair") or kind in {"measurement_repair_required", "measurement_repair_rejected", "measurement_repair_exhausted"}:
            projected, value_truncated, value_redacted = self._safe_projection(payload)
            entry["details"] = projected
            truncated |= value_truncated
            projection_truncated |= value_truncated
            redacted |= value_redacted
        if truncated:
            entry["truncated"] = True
        if redacted:
            entry["redacted"] = True
        entry["integrity"] = {
            "status": "unavailable" if entry.get("detailUnavailable") else "truncated" if truncated else "redacted" if redacted else "complete",
            "source": "gateway_event",
            "persistedTruncated": persisted_truncated,
            "projectionTruncated": projection_truncated,
            "detailUnavailable": bool(entry.get("detailUnavailable")),
            "reason": "legacy_persisted_truncation" if entry.get("detailUnavailable") else "persisted_event_limit" if persisted_truncated else "safe_projection_limit" if projection_truncated else "sensitive_field_hidden" if redacted else None,
        }
        return entry

    @classmethod
    def _safe_projection(cls, value: Any, *, depth: int = 0) -> tuple[Any, bool, bool]:
        numeric_tree = cls._numeric_tree(value)
        if numeric_tree is not None:
            return numeric_tree
        if depth >= MAX_DETAIL_DEPTH:
            return {"truncated": True, "reason": "depth_limit"}, True, False
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            truncated = False
            redacted = False
            items = list(value.items())
            for index, (raw_key, raw_value) in enumerate(items):
                if index >= MAX_DETAIL_ITEMS:
                    truncated = True
                    break
                key = cls._bounded_text(raw_key, 96) or "field"
                if cls._is_sensitive_detail_key(key):
                    redacted = True
                    continue
                projected, item_truncated, item_redacted = cls._safe_projection(raw_value, depth=depth + 1)
                result[key] = projected
                truncated |= item_truncated
                redacted |= item_redacted
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
            if len(encoded.encode("utf-8")) > MAX_DETAIL_VALUE_BYTES:
                preview = cls._safe_text(encoded, MAX_DETAIL_VALUE_BYTES // 2) or ""
                return {"preview": preview}, True, redacted
            return result, truncated, redacted
        if isinstance(value, (list, tuple)):
            result: list[Any] = []
            truncated = len(value) > MAX_DETAIL_ITEMS
            redacted = False
            for item in list(value)[:MAX_DETAIL_ITEMS]:
                projected, item_truncated, item_redacted = cls._safe_projection(item, depth=depth + 1)
                result.append(projected)
                truncated |= item_truncated
                redacted |= item_redacted
            return result, truncated, redacted
        if isinstance(value, str):
            if value.startswith("data:"):
                return "[二进制内容已隐藏]", False, True
            safe = cls._safe_text(value, MAX_TEXT_CHARS) or ""
            return safe, len(value) > MAX_TEXT_CHARS, safe != value and len(value) <= MAX_TEXT_CHARS
        if isinstance(value, (int, float, bool)) or value is None:
            return value, False, False
        safe = cls._safe_text(value, MAX_TEXT_CHARS) or ""
        return safe, True, False

    @classmethod
    def _numeric_tree(cls, value: Any) -> tuple[Any, bool, bool] | None:
        """Keep bounded numeric geometry intact at any normal nesting depth."""
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return value, False, False
        if not isinstance(value, (list, tuple)):
            return None
        projected: list[Any] = []
        truncated = len(value) > MAX_DETAIL_ITEMS
        for item in list(value)[:MAX_DETAIL_ITEMS]:
            nested = cls._numeric_tree(item)
            if nested is None:
                return None
            projected.append(nested[0])
            truncated |= nested[1]
        return projected, truncated, False

    @staticmethod
    def _is_sensitive_detail_key(value: str) -> bool:
        lower = value.lower().replace("-", "_")
        return lower in _DETAIL_SENSITIVE_KEYS or any(
            token in lower
            for token in ("api_key", "access_token", "authorization", "password", "private_key", "client_secret")
        )

    def _safe_event(self, root: Path, evaluation_id: str, case_id: str, run_id: str, row: Any) -> dict[str, Any]:
        try:
            raw_payload = json.loads(row[3] or "{}")
        except (TypeError, json.JSONDecodeError):
            raw_payload = {}
        payload = raw_payload if isinstance(raw_payload, Mapping) else {}
        safe: dict[str, Any] = {}
        raw_result = payload.get("result")
        persisted_truncated = bool(payload.get("truncated")) or (
            isinstance(raw_result, Mapping) and bool(raw_result.get("truncated"))
        )
        truncated = persisted_truncated
        projection_truncated = False
        redacted = False
        detail_resource = self._history_detail_resource(root, evaluation_id, case_id, run_id, payload.get("detail_resource"))
        for raw_key, value in payload.items():
            key = self._bounded_text(raw_key, 96) or "field"
            if key in {"detail_resource", "detailResource"}:
                continue
            if self._is_sensitive_detail_key(key):
                redacted = True
                continue
            if key == "observations":
                safe[key] = self._safe_observations(root, evaluation_id, case_id, value)
                continue
            if key == "artifacts":
                safe[key] = self._safe_generated_artifacts(evaluation_id, case_id, value)
                continue
            projected, value_truncated, value_redacted = self._safe_projection(value)
            safe[key] = projected
            truncated |= value_truncated
            projection_truncated |= value_truncated
            redacted |= value_redacted
        if detail_resource is not None:
            safe["detailResource"] = detail_resource
        elif persisted_truncated:
            safe["detailUnavailable"] = True
            safe["detailUnavailableReason"] = "legacy_bundle_no_detail_resource"
        if row[2] == "visual_observation":
            safe["observations"] = self._safe_observations(root, evaluation_id, case_id, payload.get("observations"))
        if row[2] == "generated_chart":
            safe["artifacts"] = self._safe_generated_artifacts(evaluation_id, case_id, payload.get("artifacts"))
        if truncated:
            safe["truncated"] = True
        if redacted:
            safe["redacted"] = True
        safe["integrity"] = {
            "status": "unavailable" if safe.get("detailUnavailable") else "truncated" if truncated else "redacted" if redacted else "complete",
            "source": "gateway_event",
            "persistedTruncated": persisted_truncated,
            "projectionTruncated": projection_truncated,
            "detailUnavailable": bool(safe.get("detailUnavailable")),
            "reason": "legacy_persisted_truncation" if safe.get("detailUnavailable") else "persisted_event_limit" if persisted_truncated else "safe_projection_limit" if projection_truncated else "sensitive_field_hidden" if redacted else None,
        }
        return {
            "runId": run_id,
            "sequence": max(0, int(row[1])),
            "kind": self._bounded_text(row[2], 64) or "unknown",
            "timestamp": self._bounded_text(row[4], 64) or "",
            "payload": safe,
        }

    def _safe_observations(self, root: Path, evaluation_id: str, case_id: str, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        resources = {item.resource_id: item for item in self._resources(root, evaluation_id, case_id, self._case_from_root(root, case_id))}
        by_token = {item.path.name: item for item in resources.values()}
        result: list[dict[str, Any]] = []
        for item in value[:32]:
            if not isinstance(item, Mapping):
                continue
            observation_id = self._bounded_id(item.get("observationId") or item.get("observation_id"))
            match = next((resource for resource in resources.values() if resource.kind == "observation" and resource.path.name.startswith(observation_id or "__never__")), None)
            if match is None and observation_id:
                match = next((resource for resource in resources.values() if resource.path.name == f"{observation_id}.bin"), None)
            observation: dict[str, Any] = {
                "observationId": observation_id,
                "mediaType": self._bounded_text(item.get("mediaType") or item.get("media_type"), 64),
                "caption": self._safe_text(item.get("caption"), 500) or "视觉观察",
                "byteCount": self._bounded_int(item.get("byteCount") or item.get("byte_count")) or 0,
            }
            if match is not None:
                observation["previewResource"] = match.to_dict()
            result.append(observation)
        return result

    def _safe_generated_artifacts(self, evaluation_id: str, case_id: str, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value[:32]:
            if not isinstance(item, Mapping):
                continue
            artifact: dict[str, Any] = {
                "artifactKind": "generated_chart",
                "artifactId": self._bounded_id(item.get("artifactId") or item.get("artifact_id")),
                "candidateId": self._bounded_id(item.get("candidateId") or item.get("candidate_id")),
                "mediaType": self._bounded_text(item.get("mediaType") or item.get("media_type"), 64),
                "caption": self._safe_text(item.get("caption"), 500) or "生成图表",
                "title": self._safe_text(item.get("title"), 240) or "生成图表",
                "chartType": self._bounded_text(item.get("chartType") or item.get("chart_type"), 64),
                "status": self._bounded_text(item.get("status"), 32) or "unavailable",
                "reason": self._safe_text(item.get("reason"), 240),
            }
            artifact = {key: value for key, value in artifact.items() if value not in (None, "")}
            resource_key = artifact.get("artifactId") or artifact.get("candidateId")
            if isinstance(resource_key, str):
                artifact["previewResource"] = {
                    "resourceId": self._resource_id(evaluation_id, case_id, "artifact", resource_key),
                    "caseId": case_id,
                    "kind": "artifact",
                }
            result.append(artifact)
        return result

    def _case_from_root(self, root: Path, case_id: str) -> Mapping[str, Any]:
        try:
            return self._find_case(self._read_index(root), case_id)
        except EvaluationReaderError:
            return {}

    @staticmethod
    def _readonly_connection(database: Path):
        uri = f"file:{database.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _safe_bundle_file(root: Path, path: Path) -> Path | None:
        try:
            root_resolved = root.resolve()
            candidate = path if path.is_absolute() else root / path
            resolved = candidate.resolve()
            resolved.relative_to(root_resolved)
            return resolved
        except (OSError, ValueError):
            return None

    def _relative_file(self, root: Path, value: Any) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = Path(value.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        # The index may point only at the bundle's generated diagnostic files;
        # it can never turn this helper into an arbitrary-file reader.
        if len(candidate.parts) < 2 or candidate.parts[0] != "diagnostics" or candidate.suffix.lower() not in {".md", ".json"}:
            return None
        return self._safe_bundle_file(root, candidate)

    def _read_text(self, path: Path | None) -> str:
        if path is None or not path.is_file():
            return ""
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        truncated = raw[:MAX_TEXT_BYTES]
        try:
            text = truncated.decode("utf-8", errors="replace")
        except UnicodeError:
            return ""
        return self._safe_text(text, MAX_TEXT_CHARS) or ""

    @staticmethod
    def _resource_id(evaluation_id: str, case_id: str, kind: str, token: str) -> str:
        digest = hashlib.sha256(f"{evaluation_id}\0{case_id}\0{kind}\0{token}".encode("utf-8")).hexdigest()[:28]
        return f"r_{digest}"

    @staticmethod
    def _case_status(value: Any) -> str:
        return value if isinstance(value, str) and value in VALID_CASE_STATUSES else "unknown"

    @staticmethod
    def _bounded_id(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip()
        return value[:192] if _IDENTIFIER.fullmatch(value) else None

    @staticmethod
    def _bounded_text(value: Any, limit: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, (str, int, float, bool)):
            return None
        text = str(value).strip()
        return text[:limit] if text else None

    @classmethod
    def _safe_text(cls, value: Any, limit: int) -> str | None:
        text = cls._bounded_text(value, limit)
        if not text:
            return None
        text = _ABSOLUTE_PATH.sub("[已隐藏路径]", text)
        text = _SECRET_ASSIGNMENT.sub("[REDACTED]", text)
        text = re.sub(r"\[PATH_OMITTED\][^\s\"'`，。；;]+", "[已隐藏路径]", text)
        text = text.replace("[PATH_OMITTED]", "[已隐藏路径]").replace("[IMAGE_DATA_OMITTED]", "[二进制内容已隐藏]")
        return truncate_text(text, limit)

    @classmethod
    def _safe_error(cls, value: Any) -> dict[str, str] | None:
        if not isinstance(value, Mapping):
            return None
        code = cls._bounded_text(value.get("code"), 120)
        message = cls._safe_text(value.get("message"), 500)
        if not code and not message:
            return None
        return {key: value for key, value in (("code", code), ("message", message)) if value}

    @classmethod
    def _first_failure(cls, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        result: dict[str, Any] = {}
        for source, target, limit in (("code", "code", 96), ("category", "category", 96), ("stage", "stage", 64)):
            safe = cls._bounded_text(value.get(source), limit)
            if safe:
                result[target] = safe
        sequence = cls._bounded_int(value.get("sequence"))
        if sequence is not None:
            result["sequence"] = sequence
        message = cls._safe_text(value.get("message"), 240)
        if message:
            result["message"] = message
        return result or None

    @staticmethod
    def _bounded_int(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return max(0, min(value, 1_000_000))

    @classmethod
    def _bounded_ints(cls, value: Any, limit: int) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value[:limit]:
            safe = cls._bounded_int(item)
            if safe is not None:
                result.append(safe)
        return result

    @classmethod
    def _bounded_strings(cls, value: Any, limit: int, item_limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [safe for item in value[:limit] if (safe := cls._bounded_text(item, item_limit))]

    @classmethod
    def _safe_asset_label(cls, value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return Path(value.replace("\\", "/")).name[:240]

    @classmethod
    def _safe_run_summary(cls, row: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "runId": cls._bounded_id(row[0]) or "unknown",
            "sessionId": cls._bounded_id(row[1]) or "unknown",
            "status": cls._bounded_text(row[2], 32) or "unknown",
            "createdAt": cls._bounded_text(row[3], 64) or "",
            "updatedAt": cls._bounded_text(row[4], 64) or "",
            "eventCount": max(0, int(row[22] or 0)),
            "terminalCode": cls._bounded_text(row[5], 64),
            "terminalMessage": cls._safe_text(row[6], 240),
            "answer": cls._safe_text(row[7], 12000),
            "historyWarning": cls._safe_text(row[8], 240),
            "provider": cls._bounded_text(row[9], 64),
            "model": cls._bounded_text(row[10], 128),
            "cancelRequested": bool(row[11]),
            "retryOf": cls._bounded_id(row[12]),
            "parentRunId": cls._bounded_id(row[13]),
            "rootRunId": cls._bounded_id(row[14]) or cls._bounded_id(row[0]),
            "continuationKind": cls._bounded_text(row[15], 32),
        }
        recovery_status = cls._bounded_text(row[16], 32) or "unavailable"
        result["recovery"] = {
            "status": recovery_status,
            **({"phase": cls._bounded_text(row[17], 32)} if row[17] else {}),
            **({"nextAction": cls._safe_text(row[18], 120)} if row[18] else {}),
            **({"blockedReason": cls._safe_text(row[19], 240)} if row[19] else {}),
            **({"checkpointVersion": cls._bounded_int(row[20])} if row[20] is not None else {}),
            **({"updatedAt": cls._bounded_text(row[21], 64)} if row[21] else {}),
        }
        return {key: value for key, value in result.items() if value is not None}


__all__ = [
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationReader",
    "EvaluationReaderError",
    "SUPPORTED_IMAGE_TYPES",
]
