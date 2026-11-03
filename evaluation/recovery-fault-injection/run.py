#!/usr/bin/env python3
"""Run and summarize Figura's process-level recovery fault-injection matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
EVALUATION_ROOT = Path(__file__).resolve().parent
TEST_PATH = ROOT / "tests" / "test_figura_recovery_process.py"
EXPECTED_INTERRUPTION_CASES = 36
EXPECTED_CONCURRENCY_CASES = 5


def _batch_name(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise SystemExit("--batch 只允许 1 到 64 位字母、数字、下划线或连字符")
    return value


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _load_case_reports(batch_dir: Path) -> list[dict[str, object]]:
    reports = []
    for path in sorted((batch_dir / "cases").glob("*/case-report.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    return reports


def _rate(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _summarize(reports: list[dict[str, object]]) -> dict[str, object]:
    interruption = [item for item in reports if item.get("case_class") in {"recoverable", "fail_closed"}]
    recoverable = [item for item in reports if item.get("case_class") == "recoverable"]
    fail_closed = [item for item in reports if item.get("case_class") == "fail_closed"]
    concurrency = [item for item in reports if item.get("case_class") == "concurrency"]

    def count(items: list[dict[str, object]], predicate) -> int:
        return sum(bool(predicate(item)) for item in items)

    return {
        "interruption_cases_observed": len(interruption),
        "recoverable_cases_observed": len(recoverable),
        "fail_closed_cases_observed": len(fail_closed),
        "concurrency_cases_observed": len(concurrency),
        "auto_recovery_success_rate": _rate(
            count(recoverable, lambda item: item.get("recovery_success") is True), len(recoverable)
        ),
        "recovery_policy_conformance_rate": _rate(
            count(reports, lambda item: item.get("policy_correct") is True), len(reports)
        ),
        "state_consistency_rate": _rate(
            count(reports, lambda item: item.get("state_consistent") is True), len(reports)
        ),
        "fail_closed_policy_correct_rate": _rate(
            count(fail_closed, lambda item: item.get("policy_correct") is True), len(fail_closed)
        ),
        "dual_dispatcher_competition_success_rate": _rate(
            count(concurrency, lambda item: item.get("policy_correct") is True), len(concurrency)
        ),
        "duplicate_side_effects": sum(
            int(item.get("duplicate_side_effects", 0))
            for item in interruption
            if isinstance(item.get("duplicate_side_effects", 0), (int, float))
        ),
        "repeated_tool_handler_invocations": sum(
            int(item.get("repeated_handler_invocations", 0))
            for item in reports
            if isinstance(item.get("repeated_handler_invocations", 0), (int, float))
        ),
        "expected_counts": {
            "interruption_cases": EXPECTED_INTERRUPTION_CASES,
            "recoverable_cases": 33,
            "fail_closed_cases": 3,
            "concurrency_cases": EXPECTED_CONCURRENCY_CASES,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", help="批次目录名；必须唯一")
    args = parser.parse_args()

    batch = _batch_name(args.batch)
    batch_dir = EVALUATION_ROOT / "runs" / batch
    try:
        batch_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(f"批次已存在，不会覆盖：{batch_dir}") from None

    git_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    git_revision = git_result.stdout.strip() if git_result.returncode == 0 else None
    pytest_args = ["-m", "pytest", "-q", str(TEST_PATH.relative_to(ROOT)), "--tb=short"]
    command = ["python", *pytest_args]
    environment = os.environ.copy()
    environment["FIGURA_RECOVERY_FAULT_RUN_DIR"] = str(batch_dir)
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"批次: {batch}")
    print("执行进程级 SIGKILL 故障注入矩阵（Fake Provider，无真实 API 调用）")

    result = subprocess.run([sys.executable, *pytest_args], cwd=ROOT, env=environment, check=False)
    reports = _load_case_reports(batch_dir)
    summary = _summarize(reports)
    expected_total = EXPECTED_INTERRUPTION_CASES + EXPECTED_CONCURRENCY_CASES
    payload = {
        "schema_version": 1,
        "batch": batch,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": git_revision,
        "provider_mode": "local_fake_provider",
        "live_provider_calls": 0,
        "command": command,
        "pytest_exit_code": result.returncode,
        "cases_observed": len(reports),
        "cases_expected": expected_total,
        "matrix_complete": len(reports) == expected_total,
        "summary": summary,
        "cases": reports,
    }
    report_path = batch_dir / "report.json"
    _write_json(report_path, payload)
    print(f"已观察用例: {len(reports)}/{expected_total}")
    print(f"自动恢复成功率: {summary['auto_recovery_success_rate']}")
    print(f"恢复策略符合率: {summary['recovery_policy_conformance_rate']}")
    print(f"状态一致率: {summary['state_consistency_rate']}")
    print(f"报告: {report_path}")
    return result.returncode if result.returncode else (0 if len(reports) == expected_total else 2)


if __name__ == "__main__":
    raise SystemExit(main())
