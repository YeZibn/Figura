"""Durable, bounded storage for one real-chart evaluation batch."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from ..storage import resolve_storage_paths
from ..trace import sanitize_payload, truncate_text
from .manifest import DiagnosticManifest, DiagnosticSample


EVALUATION_BUNDLE_SCHEMA_VERSION = 1
EvaluationStatus = Literal["running", "completed", "partial", "blocked"]
CASE_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "interrupted",
    "blocked",
    "not_run",
}
_SENSITIVE_ERROR_PATTERN = re.compile(
    r"(?i)\b[A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|authorization|password|secret|private[_-]?key)\b"
    r"\s*[:=]\s*[^\s,;]+"
)


class EvaluationBundleError(RuntimeError):
    """Raised when an evaluation bundle cannot be created or persisted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_case_stem(case_id: str) -> str:
    """Return the same bounded filename stem used by diagnostic reports."""

    stem = "".join(character if character.isalnum() or character in "-_" else "_" for character in case_id)
    return stem[:96] or "diagnostic"


def _new_evaluation_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"eval_{timestamp}_{uuid.uuid4().hex[:8]}"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise EvaluationBundleError(f"无法写入评测文件: {path.name}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _safe_error(value: object, limit: int = 500) -> str:
    sanitized = sanitize_payload({"message": str(value)}).get("message", "")
    text = str(sanitized)
    text = _SENSITIVE_ERROR_PATTERN.sub("[REDACTED]", text)
    return truncate_text(text, limit)


class EvaluationBundle:
    """Own one evaluation directory and its bounded batch metadata."""

    def __init__(
        self,
        *,
        root: Path,
        evaluation_id: str,
        provider: str,
        model: str | None,
        manifest: DiagnosticManifest,
        samples: Sequence[DiagnosticSample],
    ) -> None:
        self.root = root
        self.evaluation_id = evaluation_id
        self.provider = provider
        self.model = model
        self.manifest = manifest
        self.samples = tuple(samples)
        self.diagnostics_dir = root / "diagnostics"
        self.index_path = root / "evaluation.json"
        self.manifest_path = root / "manifest.json"
        self.summary_json_path = root / "summary.json"
        self.summary_markdown_path = root / "summary.md"
        self._index: dict[str, Any] = self._initial_index()

    @classmethod
    def create(
        cls,
        *,
        manifest: DiagnosticManifest,
        samples: Sequence[DiagnosticSample],
        provider: str,
        model: str | None = None,
        data_dir: str | Path | None = None,
        evaluation_root: str | Path | None = None,
    ) -> "EvaluationBundle":
        """Create an unused root and write its initial index and manifest."""

        if not provider.strip():
            raise EvaluationBundleError("评测批次必须显式指定 provider")
        selected = tuple(samples)
        if not selected:
            raise EvaluationBundleError("评测批次至少需要一个样本")

        if evaluation_root is not None:
            root = Path(evaluation_root).expanduser()
            if not root.is_absolute():
                root = (Path.cwd() / root).resolve()
            else:
                root = root.resolve()
            evaluation_id = _new_evaluation_id()
            try:
                root.mkdir(parents=True, exist_ok=False)
            except FileExistsError as exc:
                raise EvaluationBundleError(f"评测目录已存在，拒绝复用: {root.name}") from exc
            except OSError as exc:
                raise EvaluationBundleError("无法创建显式评测目录") from exc
        else:
            storage_root = resolve_storage_paths(data_dir=data_dir).root
            parent = storage_root / "evaluations"
            parent.mkdir(parents=True, exist_ok=True)
            for _ in range(8):
                evaluation_id = _new_evaluation_id()
                root = parent / evaluation_id
                try:
                    root.mkdir(parents=False, exist_ok=False)
                    break
                except FileExistsError:
                    continue
                except OSError as exc:
                    raise EvaluationBundleError("无法创建评测批次目录") from exc
            else:
                raise EvaluationBundleError("无法生成唯一的评测批次目录")

        bundle = cls(
            root=root,
            evaluation_id=evaluation_id,
            provider=provider.strip(),
            model=model,
            manifest=manifest,
            samples=selected,
        )
        bundle.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        (root / "attachments").mkdir(parents=True, exist_ok=True)
        (root / "run-artifacts").mkdir(parents=True, exist_ok=True)
        bundle._write_manifest_snapshot()
        bundle._persist()
        return bundle

    def _initial_index(self) -> dict[str, Any]:
        cases: dict[str, dict[str, Any]] = {}
        for sample in self.samples:
            stem = safe_case_stem(sample.case_id)
            cases[sample.case_id] = {
                "case_id": sample.case_id,
                "asset": sample.asset,
                "sha256": sample.sha256,
                "status": "pending",
                "session_id": None,
                "run_id": None,
                "report": {
                    "json": f"diagnostics/{stem}.json",
                    "markdown": f"diagnostics/{stem}.md",
                },
                "first_failure": None,
                "error": None,
            }
        return {
            "schema_version": EVALUATION_BUNDLE_SCHEMA_VERSION,
            "evaluation_id": self.evaluation_id,
            "status": "running",
            "started_at": _utc_now(),
            "ended_at": None,
            "provider": self.provider,
            "model": self.model,
            "manifest": {
                "path": "manifest.json",
                "schema_version": self.manifest.schema_version,
                "sample_count": len(self.samples),
            },
            "paths": {
                "database": "sessions.db",
                "attachments": "attachments/",
                "run_artifacts": "run-artifacts/",
                "diagnostics": "diagnostics/",
                "summary_json": "summary.json",
                "summary_markdown": "summary.md",
            },
            "cases": cases,
            "error": None,
        }

    def _write_manifest_snapshot(self) -> None:
        selected_ids = {sample.case_id for sample in self.samples}
        payload = {
            "schema_version": self.manifest.schema_version,
            "samples": [
                sample.to_dict()
                for sample in self.manifest.samples
                if sample.case_id in selected_ids
            ],
        }
        _atomic_write(self.manifest_path, _json_text(payload))

    def _persist(self) -> None:
        _atomic_write(self.index_path, _json_text(sanitize_payload(self._index)))
        self._write_summary()

    def _write_summary(self) -> None:
        summary = self.summary_dict()
        _atomic_write(self.summary_json_path, _json_text(summary))
        _atomic_write(self.summary_markdown_path, self.summary_markdown(summary))

    def summary_dict(self) -> dict[str, Any]:
        cases = list(self._index.get("cases", {}).values())
        counts: dict[str, int] = {}
        for case in cases:
            status = str(case.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return sanitize_payload(
            {
                "schema_version": EVALUATION_BUNDLE_SCHEMA_VERSION,
                "evaluation_id": self.evaluation_id,
                "status": self._index.get("status", "unknown"),
                "started_at": self._index.get("started_at"),
                "ended_at": self._index.get("ended_at"),
                "provider": self._index.get("provider"),
                "model": self._index.get("model"),
                "sample_count": len(cases),
                "case_counts": counts,
                "cases": cases,
                "error": self._index.get("error"),
            }
        )

    @staticmethod
    def summary_markdown(summary: Mapping[str, Any]) -> str:
        lines = [
            f"# 真实图表评测：{summary.get('evaluation_id', 'unknown')}",
            "",
            f"- 状态：`{summary.get('status', 'unknown')}`",
            f"- provider / model：`{summary.get('provider', 'unknown')}` / `{summary.get('model') or 'unknown'}`",
            f"- 样本数：`{summary.get('sample_count', 0)}`",
            "",
            "原始 `sessions.db`、`attachments/` 和 `run-artifacts/` 是本地诊断材料；本摘要只包含有界引用。",
            "",
            "## Case 汇总",
            "",
            "| Case | 状态 | Session | Run | 首个失败 | 报告 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for case in summary.get("cases", []):
            if not isinstance(case, Mapping):
                continue
            report = case.get("report") if isinstance(case.get("report"), Mapping) else {}
            failure = case.get("first_failure")
            failure_text = "—"
            if isinstance(failure, Mapping):
                failure_text = f"{failure.get('category', 'unknown')} / {failure.get('stage', 'unknown')}"
            report_text = report.get("markdown") or "—"
            lines.append(
                "| `{case}` | `{status}` | `{session}` | `{run}` | `{failure}` | `{report}` |".format(
                    case=case.get("case_id", "unknown"),
                    status=case.get("status", "unknown"),
                    session=case.get("session_id") or "—",
                    run=case.get("run_id") or "—",
                    failure=truncate_text(failure_text, 120),
                    report=report_text,
                )
            )
        error = summary.get("error")
        if error:
            lines.extend(["", "## 批次错误", "", f"`{truncate_text(error, 240)}`"])
        return "\n".join(lines) + "\n"

    def start_case(self, sample: DiagnosticSample) -> None:
        case = self._case(sample)
        case["status"] = "running"
        case["error"] = None
        self._persist()

    def finish_case(
        self,
        sample: DiagnosticSample,
        *,
        run: Any,
        report: Mapping[str, Any] | None = None,
        report_paths: tuple[Path, Path] | None = None,
    ) -> None:
        case = self._case(sample)
        run_status = str(getattr(run, "status", "unknown"))
        case["status"] = {
            "completed": "completed",
            "interrupted": "interrupted",
        }.get(run_status, "failed")
        case["session_id"] = _bounded_id(getattr(run, "session_id", None))
        case["run_id"] = _bounded_id(getattr(run, "run_id", None))
        if getattr(run, "model", None):
            self._index["model"] = truncate_text(str(run.model), 240)
        if report_paths:
            case["report"] = {
                "json": self._relative_path(report_paths[0]),
                "markdown": self._relative_path(report_paths[1]),
            }
        if report:
            timeline = report.get("timeline")
            if isinstance(timeline, Mapping):
                case["first_failure"] = sanitize_payload(
                    timeline.get("first_failure")
                    if isinstance(timeline.get("first_failure"), Mapping)
                    else {}
                ) or None
        self._persist()

    def record_case_error(
        self,
        sample: DiagnosticSample,
        *,
        code: str,
        message: str,
        status: str = "blocked",
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        case = self._case(sample)
        case["status"] = status if status in CASE_STATUSES else "failed"
        if session_id:
            case["session_id"] = _bounded_id(session_id)
        if run_id:
            case["run_id"] = _bounded_id(run_id)
        case["error"] = {
            "code": truncate_text(code, 120),
            "message": _safe_error(message),
        }
        self._persist()

    def finalize(self, *, status: EvaluationStatus | None = None, error: str | None = None) -> EvaluationStatus:
        if status is None:
            statuses = [str(case.get("status")) for case in self._index["cases"].values()]
            if statuses and all(item == "completed" for item in statuses):
                status = "completed"
            elif statuses and all(item in {"blocked", "not_run"} for item in statuses):
                status = "blocked"
            else:
                status = "partial"
        self._index["status"] = status
        self._index["ended_at"] = _utc_now()
        if error:
            self._index["error"] = _safe_error(error)
        self._persist()
        return status

    def _case(self, sample: DiagnosticSample) -> dict[str, Any]:
        cases = self._index.get("cases")
        if not isinstance(cases, dict) or sample.case_id not in cases:
            raise EvaluationBundleError(f"样本不属于当前评测批次: {sample.case_id}")
        return cases[sample.case_id]

    def _relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError as exc:
            raise EvaluationBundleError("评测报告必须位于评测根目录内") from exc


def _bounded_id(value: Any) -> str | None:
    if value is None:
        return None
    return truncate_text(str(value), 160)


__all__ = [
    "CASE_STATUSES",
    "EVALUATION_BUNDLE_SCHEMA_VERSION",
    "EvaluationBundle",
    "EvaluationBundleError",
    "EvaluationStatus",
    "safe_case_stem",
]
