"""Bounded JSON facts and a human-readable Markdown view for diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..trace import sanitize_payload, truncate_text
from .manifest import DiagnosticSample
from .timeline import DiagnosticTimeline, build_timeline


REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DiagnosticReport:
    """Serializable diagnostic result; raw event history is intentionally absent."""

    sample: Mapping[str, Any]
    run: Mapping[str, Any]
    timeline: DiagnosticTimeline
    mode: str = "gateway"
    report_version: int = REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = {
            "report_version": self.report_version,
            "mode": self.mode,
            "sample": dict(self.sample),
            "run": dict(self.run),
            "timeline": self.timeline.to_dict(),
        }
        return sanitize_payload(result)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        data = self.to_dict()
        sample = data["sample"]
        run = data["run"]
        timeline = data["timeline"]
        lines = [
            f"# 真实图表链路诊断：{sample.get('case_id', 'unknown')}",
            "",
            f"- 模式：`{self.mode}`",
            f"- 样本：`{sample.get('asset', 'unknown')}`",
            f"- 指纹：`{sample.get('sha256', 'unknown')}`",
            f"- run：`{run.get('run_id', 'unknown')}`",
            f"- provider / model：`{run.get('provider', 'unknown')}` / `{run.get('model', 'unknown')}`",
            f"- 运行状态：`{run.get('status', 'unknown')}`",
            "",
            "## 阶段时间线",
            "",
            "| 阶段 | 状态 | 事件序号 | panel 引用 | 说明 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for stage in timeline.get("stages", []):
            sequence = ", ".join(str(value) for value in stage.get("sequences", [])) or "—"
            panels = ", ".join(f"`{value}`" for value in stage.get("panel_ids", [])) or "—"
            notes = "；".join(stage.get("errors", []) + stage.get("notes", [])) or "—"
            lines.append(
                f"| `{stage.get('name')}` | `{stage.get('status')}` | {sequence} | {panels} | {truncate_text(notes, 180)} |"
            )

        first_failure = timeline.get("first_failure")
        lines.extend(["", "## 第一个可确认失败", ""])
        if isinstance(first_failure, Mapping):
            lines.extend(
                [
                    f"- 类别：`{first_failure.get('category', 'unknown')}`",
                    f"- 阶段：`{first_failure.get('stage', 'unknown')}`",
                    f"- 事件序号：`{first_failure.get('sequence', 'unknown')}`",
                    f"- 原因：{first_failure.get('message', '未提供原因')}",
                ]
            )
        else:
            lines.append("没有足够证据确认失败阶段，不能把未观察到误判为失败。")

        lines.extend(["", "## 异常", ""])
        anomalies = timeline.get("anomalies", [])
        if anomalies:
            for anomaly in anomalies:
                lines.append(
                    f"- `{anomaly.get('code', 'unknown')}`（{anomaly.get('category', 'unknown')}）："
                    f"{anomaly.get('message', '未提供说明')}"
                )
        else:
            lines.append("未发现已定义的链路异常。")

        lines.extend(["", "## 最终引用", ""])
        final_refs = timeline.get("final_references", {})
        if any(final_refs.values()):
            for key, values in final_refs.items():
                if values:
                    lines.append(f"- {key}：" + ", ".join(f"`{value}`" for value in values))
        else:
            lines.append("没有观察到最终 artifact 引用。")
        return "\n".join(lines) + "\n"


def build_report(
    history: Mapping[str, Any],
    sample: DiagnosticSample,
    *,
    requested_provider: str | None = None,
    mode: str = "gateway",
    timed_out: bool = False,
) -> DiagnosticReport:
    """Create a report from a Gateway history without embedding raw payloads."""

    summary = history.get("run")
    summary = summary if isinstance(summary, Mapping) else {}
    provider = summary.get("provider") or requested_provider
    run = {
        "run_id": _safe_value(summary.get("runId")),
        "status": _safe_value(summary.get("status"), default="unknown"),
        "provider": _safe_value(provider, default="unknown"),
        "model": _safe_value(summary.get("model"), default="unknown"),
        "terminal_code": _safe_value(summary.get("terminalCode")),
        "event_count": _bounded_int(summary.get("eventCount")),
        "history_gap": bool(history.get("historyGap")),
        "timed_out": bool(timed_out),
    }
    run = {key: value for key, value in run.items() if value is not None}
    timeline = build_timeline(history, sample=sample, timed_out=timed_out)
    return DiagnosticReport(
        sample=sample.to_dict(),
        run=run,
        timeline=timeline,
        mode=mode,
    )


def write_report(report: DiagnosticReport, output_dir: str | Path) -> tuple[Path, Path]:
    """Write the bounded JSON facts and Markdown view for one sample."""

    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    case_id = str(report.sample.get("case_id") or "diagnostic")
    safe_case_id = "".join(character if character.isalnum() or character in "-_" else "_" for character in case_id)
    safe_case_id = safe_case_id[:96] or "diagnostic"
    json_path = output_root / f"{safe_case_id}.json"
    markdown_path = output_root / f"{safe_case_id}.md"
    json_path.write_text(report.to_json(), encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path


def _safe_value(value: Any, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, (str, int, float, bool)):
        return truncate_text(str(value), 240)
    return default


def _bounded_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, min(value, 100000))
    return None
