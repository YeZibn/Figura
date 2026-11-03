"""Run the fixed three-task context-compression pilot in isolated Gateways."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from figura.charts.chartfigure import chart_figure_digest, parse_chart_figure
from figura.providers.config import ProviderSettings
from figura.providers.models import ProviderId

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "evaluation/context-correctness-pilot"
PROVIDER = ProviderId.DEEPSEEK
PROVIDER_ID = PROVIDER.value
TURN_TIMEOUT_SECONDS = int(os.environ.get("FIGURA_CONTEXT_PILOT_TURN_TIMEOUT_SECONDS", "600"))
SCHEDULE = (
    ("01-chart-analysis", "compaction"),
    ("01-chart-analysis", "baseline"),
    ("02-chart-construction", "baseline"),
    ("02-chart-construction", "compaction"),
    ("03-chart-modification", "compaction"),
    ("03-chart-modification", "baseline"),
)


def now():
    return datetime.now().astimezone().isoformat()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(path.read_bytes())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def parse_turns(task_id):
    task_dir = PILOT / task_id
    source = (task_dir / "conversation.md").read_text()
    headings = list(re.finditer(r"(?m)^## 第 (\d+) 轮：[^\n]*\n", source))
    if len(headings) != 3:
        raise ValueError(f"{task_id}: expected exactly three fixed turns")
    turns = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        turns.append({
            "turn": int(heading.group(1)),
            "text": source[heading.end():end].strip(),
            "attachments": [],
        })
    if task_id == "01-chart-analysis":
        turns[0]["attachments"] = ["input/bar_line_dashboard.png"]
    elif task_id == "02-chart-construction":
        dataset = task_dir / "input/dataset.json"
        turns[0]["text"] = turns[0]["text"].replace(
            "请读取附件中的结构化数据", "请读取以下结构化数据"
        ) + "\n\n" + chr(96) * 3 + "json\n" + dataset.read_text().strip() + "\n" + chr(96) * 3
        turns[0]["dataset_sha256"] = sha_file(dataset)
    elif task_id == "03-chart-modification":
        turns[0]["attachments"] = ["input/quarterly-regional-sales.png"]
    else:
        raise ValueError(f"unknown task: {task_id}")
    return turns


class Gateway:
    def __init__(self, runtime, capacity):
        self.runtime = runtime
        self.capacity = capacity
        self.process = None
        self.log = None
        self.base = ""

    def __enter__(self):
        self.runtime.mkdir(parents=True, exist_ok=False)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        self.base = f"http://127.0.0.1:{port}/api/v1"
        env = os.environ.copy()
        env.update({
            "FIGURA_DATA_DIR": str(self.runtime),
            "FIGURA_GATEWAY_PORT": str(port),
            "FIGURA_WEB_ORIGINS": "http://127.0.0.1:1421,http://localhost:1421",
            f"FIGURA_{PROVIDER_ID.upper()}_CONTEXT_WINDOW_TOKENS": str(self.capacity),
        })
        self.log = (self.runtime / "gateway.log").open("ab", buffering=0)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "figura.gateway"],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for _ in range(60):
            if self.process.poll() is not None:
                raise RuntimeError(f"Gateway exited; inspect {self.runtime / 'gateway.log'}")
            try:
                self.request("/health")
                return self
            except requests.RequestException:
                time.sleep(1)
        raise RuntimeError("Gateway health check timed out")

    def __exit__(self, exc_type, exc, traceback):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()

    def request(self, path, method="GET", obj=None, data=None, headers=None):
        response = requests.request(
            method, self.base + path, json=obj, data=data,
            headers={"Origin": "http://127.0.0.1:1421", **(headers or {})},
            timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"Gateway HTTP {response.status_code}: {response.text[:300]}")
        return response.json() if "json" in response.headers.get("Content-Type", "") else response.content


def db_rows(runtime, sql, args=()):
    database = runtime / "figura.sqlite3"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, args)]


def export_turn(gateway, runtime, session_id, run, turn, output):
    records = db_rows(
        runtime,
        "SELECT record_id,record_kind,payload_json FROM run_execution_records "
        "WHERE run_id=? ORDER BY record_sequence",
        (run["runId"],),
    )
    by_id = {item["record_id"]: json.loads(item["payload_json"]) for item in records}
    final = next((json.loads(item["payload_json"]) for item in records if item["record_kind"] == "final_answer"), None)
    response = by_id.get(final.get("response_record_id")) if final else None
    turn_dir = output / f"turn-{turn:02}"
    turn_dir.mkdir(parents=True, exist_ok=True)
    (turn_dir / "final-answer.txt").write_text((response.get("assistant_content", "") if response else "") + "\n")

    facts = [json.loads(item["payload_json"]) for item in db_rows(
        runtime,
        "SELECT payload_json FROM run_tool_execution_facts WHERE run_id=? ORDER BY tool_sequence",
        (run["runId"],),
    )]
    calls = {item["call_id"]: item for item in facts if item["fact_kind"] == "tool_call"}
    outcomes = [item for item in facts if item["fact_kind"] == "tool_result"]
    figures, renders, tool_summary = [], [], []
    for outcome in outcomes:
        tool_summary.append({key: outcome.get(key) for key in ("call_id", "tool_name", "outcome", "error")})
        if outcome.get("outcome") != "succeeded":
            continue
        call = calls[outcome["call_id"]]
        if outcome["tool_name"] == "assemble_chart_figure":
            value = json.loads(call["arguments_json"])
            digest = chart_figure_digest(parse_chart_figure(value))
            if digest != outcome["result"]["figure_digest"]:
                raise ValueError("assembled Figure digest mismatch")
            name = f"figure-{len(figures) + 1:02}.json"
            write_json(turn_dir / name, value)
            figures.append({"file": name, "figure_digest": digest, "verified": True})
        elif outcome["tool_name"] == "render_chart_figure":
            image = gateway.request(
                f"/sessions/{session_id}/runs/{quote(run['runId'], safe='')}/chart-renders/"
                f"{quote(outcome['call_id'], safe='')}/content"
            )
            digest = sha_bytes(image)
            if digest != outcome["result"]["image_sha256"]:
                raise ValueError("render PNG digest mismatch")
            name = f"render-{len(renders) + 1:02}.png"
            (turn_dir / name).write_bytes(image)
            renders.append({"file": name, "image_sha256": digest, "verified": True})

    attempts = db_rows(
        runtime,
        "SELECT a.attempt_id,a.request_id,a.status,a.response_record_id,a.failure_code,a.http_status,"
        "a.usage_json,a.attempt_sequence,q.purpose FROM run_provider_attempts a "
        "JOIN run_provider_requests q ON q.request_id=a.request_id "
        "WHERE a.run_id=? ORDER BY a.run_attempt_sequence",
        (run["runId"],),
    )
    by_purpose, missing = {}, []
    for attempt in attempts:
        usage = json.loads(attempt["usage_json"]) if attempt["usage_json"] else None
        if not usage and attempt.get("response_record_id"):
            usage = by_id.get(attempt["response_record_id"], {}).get("usage")
        attempt.pop("usage_json")
        attempt["usage"] = usage
        if not isinstance(usage, dict):
            missing.append(attempt["attempt_id"])
            continue
        bucket = by_purpose.setdefault(attempt["purpose"], {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })
        for key in bucket:
            if isinstance(usage.get(key), int):
                bucket[key] += usage[key]
            else:
                missing.append(f"{attempt['attempt_id']}:{key}")
    total = {
        key: sum(bucket[key] for bucket in by_purpose.values())
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    operations = db_rows(
        runtime,
        "SELECT operation_id,status,failure_code FROM session_context_compaction_operations WHERE target_run_id=?",
        (run["runId"],),
    )
    write_json(turn_dir / "tool-overview.json", tool_summary)
    write_json(turn_dir / "provider-attempts.json", attempts)
    evidence = {
        "turn": turn, "run_id": run["runId"], "session_id": session_id,
        "status": run.get("status"), "terminal_code": run.get("terminalCode"),
        "final_answer_committed": bool(final), "figures": figures, "renders": renders,
        "provider_attempt_count": len(attempts), "usage_by_purpose": by_purpose,
        "usage_total_including_compaction": total, "usage_complete": not missing,
        "usage_missing_attempts": missing, "compaction_operations": operations,
    }
    write_json(turn_dir / "evidence.json", evidence)
    return evidence


def execute_pair(batch, task_id, condition, output_root, runtime_root, compaction_capacity):
    capacity = compaction_capacity if condition == "compaction" else 100_000_000
    name = f"{task_id}__{condition}"
    output, runtime = output_root / name, runtime_root / name
    if output.exists() or runtime.exists():
        raise FileExistsError(f"batch path already exists: {name}")
    task_dir = PILOT / task_id
    turns = parse_turns(task_id)
    attachment_hashes = {
        relative: sha_file(task_dir / relative)
        for turn in turns for relative in turn["attachments"]
    }
    execution = {
        "task_id": task_id, "condition": condition, "capacity_tokens": capacity,
        "provider_id": PROVIDER_ID, "batch_id": batch, "started_at": now(),
        "session_id": None, "turns": [], "execution_status": "running",
        "input_adjustments": (
            ["dataset.json 原文内嵌至第 1 轮用户消息；附件入口只接受图片，JSON 内容保持不变。"]
            if task_id == "02-chart-construction" else []
        ),
        "attachment_sha256": attachment_hashes,
    }
    write_json(output / "execution.json", execution)
    try:
        with Gateway(runtime, capacity) as gateway:
            created = gateway.request("/sessions", "POST", {"name": f"Context pilot {batch} {name}"})
            session_id = created["session"]["id"]
            execution["session_id"] = session_id
            uploaded = {}
            for turn in turns:
                attachment_ids = []
                for relative in turn["attachments"]:
                    if relative not in uploaded:
                        path = task_dir / relative
                        result = gateway.request(
                            f"/sessions/{session_id}/attachments?filename={quote(path.name)}",
                            "POST", data=path.read_bytes(), headers={"Content-Type": "image/png"},
                        )
                        uploaded[relative] = result["attachment"]["id"]
                    attachment_ids.append(uploaded[relative])
                submitted = {
                    "turn": turn["turn"], "text": turn["text"],
                    "attachment_sha256": [attachment_hashes[item] for item in turn["attachments"]],
                    "provider_id": PROVIDER_ID,
                }
                if "dataset_sha256" in turn:
                    submitted["dataset_sha256"] = turn["dataset_sha256"]
                write_json(output / f"submitted-turn-{turn['turn']:02}.json", submitted)
                started = time.monotonic()
                created_run = gateway.request(
                    f"/sessions/{session_id}/runs", "POST",
                    {"text": turn["text"], "attachmentIds": attachment_ids, "providerId": PROVIDER_ID},
                    headers={"Idempotency-Key": uuid.uuid4().hex},
                )
                run = created_run["run"]
                timed_out = False
                while run["status"] == "running":
                    time.sleep(2)
                    states = db_rows(
                        runtime,
                        "SELECT status,terminal_code FROM runs WHERE run_id=? AND session_id=?",
                        (run["runId"], session_id),
                    )
                    if not states:
                        raise RuntimeError(f"run disappeared from Gateway database: {run['runId']}")
                    run.update(
                        status=states[0]["status"],
                        terminalCode=states[0]["terminal_code"],
                    )
                    elapsed = time.monotonic() - started
                    if elapsed > TURN_TIMEOUT_SECONDS and not timed_out:
                        timed_out = True
                        gateway.request(f"/sessions/{session_id}/runs/{run['runId']}/stop", "POST", {})
                    if timed_out and elapsed > TURN_TIMEOUT_SECONDS + 180:
                        raise TimeoutError(f"{task_id} {condition} turn {turn['turn']} did not stop")
                evidence = export_turn(gateway, runtime, session_id, run, int(turn["turn"]), output)
                evidence["wall_seconds"] = round(time.monotonic() - started, 3)
                evidence["timed_out"] = timed_out
                execution["turns"].append(evidence)
                write_json(output / "execution.json", execution)
                print(json.dumps({
                    "event": "turn_complete", "task": task_id, "condition": condition,
                    "turn": turn["turn"], "status": evidence["status"],
                    "seconds": evidence["wall_seconds"],
                    "tokens": evidence["usage_total_including_compaction"]["total_tokens"],
                    "compaction_count": len(evidence["compaction_operations"]),
                }, ensure_ascii=False), flush=True)
                if evidence["status"] != "completed":
                    raise RuntimeError(
                        f"{task_id} {condition} turn {turn['turn']} ended as {evidence['status']}; "
                        "remaining turns in this session were not submitted"
                    )
        execution.update(execution_status="completed", completed_at=now())
    except BaseException as error:
        execution.update(
            execution_status="error", error_type=type(error).__name__,
            error_message=str(error)[:500], completed_at=now(),
        )
        write_json(output / "execution.json", execution)
        raise
    write_json(output / "execution.json", execution)
    return execution


def summarize(executions):
    rows = []
    for execution in executions:
        usages = [turn["usage_total_including_compaction"] for turn in execution["turns"]]
        totals = {
            key: sum((usage or {}).get(key, 0) for usage in usages)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        operations = [op for turn in execution["turns"] for op in turn["compaction_operations"]]
        rows.append({
            "task_id": execution["task_id"], "condition": execution["condition"],
            "status": execution["execution_status"], "turns": len(execution["turns"]),
            "provider_usage_including_compaction": totals,
            "usage_complete": all(turn["usage_complete"] for turn in execution["turns"]),
            "compaction_operations": operations,
            "successful_compaction_count": sum(op["status"] == "completed" for op in operations),
            "all_turns_completed": all(turn["status"] == "completed" for turn in execution["turns"]),
        })
    pairs = {}
    for task_id in sorted({row["task_id"] for row in rows}):
        arms = {row["condition"]: row for row in rows if row["task_id"] == task_id}
        if set(arms) != {"baseline", "compaction"}:
            continue
        base = arms["baseline"]["provider_usage_including_compaction"]["total_tokens"]
        compact = arms["compaction"]["provider_usage_including_compaction"]["total_tokens"]
        triggered = arms["compaction"]["successful_compaction_count"] > 0
        usage_complete = arms["baseline"]["usage_complete"] and arms["compaction"]["usage_complete"]
        turns_completed = arms["baseline"]["all_turns_completed"] and arms["compaction"]["all_turns_completed"]
        pairs[task_id] = {
            "baseline_total_tokens": base, "compaction_total_tokens": compact,
            "observed_usage_delta_percent": round((base - compact) / base * 100, 2) if base else None,
            "compression_saving_percent": round((base - compact) / base * 100, 2)
            if base and triggered and usage_complete and turns_completed else None,
            "compression_saving_eligible": bool(triggered and usage_complete and turns_completed),
            "compaction_triggered": triggered,
            "usage_complete": usage_complete,
            "all_turns_completed": turns_completed,
        }
    return {"paired_tasks": pairs, "executions": rows}


def write_report(path, summary, metadata):
    lines = [
        f"# 上下文压缩三类任务配对评测：{metadata['batch_id']}", "",
        f"- Provider / Model：{metadata['provider_id']} / {metadata['model_id']}",
        f"- 条件：压缩组 {metadata['conditions']['compaction']} tokens；基线组 100,000,000 tokens。",
        "- Provider 总 Token 包含摘要压缩请求；压缩正确性只对至少成功压缩一次的任务评分。",
        "- 原始 usage 差异与可归因于压缩的降幅分开列示。", "",
        "| 任务 | 基线总 Token | 压缩组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 成功压缩次数 | usage 完整 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    by_task = {}
    for row in summary["executions"]:
        by_task.setdefault(row["task_id"], {})[row["condition"]] = row
    for task_id, pair in summary["paired_tasks"].items():
        compact = by_task[task_id]["compaction"]
        raw = f"{pair['observed_usage_delta_percent']}%" if pair["observed_usage_delta_percent"] is not None else "—"
        saving = f"{pair['compression_saving_percent']}%" if pair["compression_saving_eligible"] else "不适用"
        lines.append(
            f"| {task_id} | {pair['baseline_total_tokens']} | {pair['compaction_total_tokens']} | "
            f"{raw} | {saving} | {compact['successful_compaction_count']} | "
            f"{'是' if pair['usage_complete'] else '否'} |"
        )
    if metadata.get("omitted_schedule_entries"):
        lines += ["", "## 未在本批次启动的项目", ""]
        for item in metadata["omitted_schedule_entries"]:
            lines.append(f"- {item['task_id']} / {item['condition']}（原计划序号 {item['index']}）")
    if metadata.get("execution_failures"):
        lines += ["", "## 执行失败", ""]
        for failure in metadata["execution_failures"]:
            lines.append(
                f"- {failure['task_id']} / {failure['condition']}: "
                f"{failure['type']}: {failure['message']}"
            )
    lines += ["", "任务语义评分待按对应 scorecard 完成后补入。", ""]
    path.write_text("\n".join(lines))


def main():
    if len(sys.argv) not in (2, 3, 4, 5) or not re.fullmatch(r"[A-Za-z0-9._-]+", sys.argv[1]):
        print(
            "usage: run_paired.py <batch-id> [compaction-capacity-tokens] "
            "[start-schedule-index] [end-schedule-index]",
            file=sys.stderr,
        )
        return 2
    batch = sys.argv[1]
    compaction_capacity = int(sys.argv[2]) if len(sys.argv) >= 3 else 50_000
    start_schedule_index = int(sys.argv[3]) if len(sys.argv) == 4 else 0
    if len(sys.argv) == 5:
        start_schedule_index = int(sys.argv[3])
        end_schedule_index = int(sys.argv[4])
    else:
        end_schedule_index = len(SCHEDULE)
    if compaction_capacity <= 0 or compaction_capacity >= 100_000_000:
        raise ValueError("compaction capacity must be positive and below baseline capacity")
    if not 0 <= start_schedule_index < end_schedule_index <= len(SCHEDULE):
        raise ValueError(f"schedule range must satisfy 0 <= start < end <= {len(SCHEDULE)}")
    schedule = SCHEDULE[start_schedule_index:end_schedule_index]
    output_root = PILOT / "runs" / batch
    runtime_root = ROOT / ".figura/evaluation" / f"context-pilot-{batch}"
    if output_root.exists() or runtime_root.exists():
        raise FileExistsError(f"batch already exists: {batch}")
    load_dotenv(ROOT / ".env", override=False)
    profile = ProviderSettings.from_env().profiles[PROVIDER]
    if not profile.availability().available:
        raise RuntimeError(f"configured provider unavailable: {PROVIDER_ID}")
    output_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    inputs = {}
    for task_id, _condition in schedule:
        if task_id in inputs:
            continue
        task_dir = PILOT / task_id
        inputs[task_id] = {
            "conversation_sha256": sha_file(task_dir / "conversation.md"),
            "answer_key_sha256": sha_file(task_dir / "answer-key.md"),
            "scorecard_sha256": sha_file(task_dir / "scorecard.md"),
            "input_sha256": {
                str(path.relative_to(task_dir)): sha_file(path)
                for path in sorted((task_dir / "input").iterdir()) if path.is_file()
            },
        }
    metadata = {
        "batch_id": batch, "status": "running", "started_at": now(),
        "git_revision": revision, "provider_id": PROVIDER_ID,
        "model_id": profile.model_id,
        "thinking_mode": profile.thinking_mode,
        "reasoning_effort": profile.reasoning_effort,
        "max_completion_tokens": profile.max_completion_tokens,
        "profile_capacity_before_override": profile.context_window_tokens,
        "conditions": {"baseline": 100_000_000, "compaction": compaction_capacity},
        "compaction_threshold_fraction": 0.8, "turn_timeout_seconds": TURN_TIMEOUT_SECONDS,
        "schedule_range": {"start_index": start_schedule_index, "end_index_exclusive": end_schedule_index},
        "schedule": [{"task_id": task, "condition": condition} for task, condition in schedule],
        "omitted_schedule_entries": [
            {
                "task_id": task,
                "condition": condition,
                "index": index,
                "reason": "before_selected_range" if index < start_schedule_index else "after_selected_range",
            }
            for index, (task, condition) in enumerate(SCHEDULE)
            if index < start_schedule_index or index >= end_schedule_index
        ],
        "input_hashes": inputs,
        "protocol_notes": [
            "每个任务与条件使用隔离的 Gateway、SQLite 数据目录和 Session。",
            "图表构建任务的 dataset.json 原文内嵌首轮消息；两组提交内容相同。",
            "Provider 总 Token 包含 agent_turn 与 context_compaction 的所有物理 attempt。",
            "每类一个配对样本，结果作固定任务的描述性比较。",
        ],
    }
    write_json(output_root / "batch.json", metadata)
    completed, failures = [], []
    try:
        for task_id, condition in schedule:
            try:
                completed.append(
                    execute_pair(batch, task_id, condition, output_root, runtime_root, compaction_capacity)
                )
            except Exception as error:
                execution_path = output_root / f"{task_id}__{condition}" / "execution.json"
                if execution_path.exists():
                    completed.append(json.loads(execution_path.read_text()))
                failure = {
                    "task_id": task_id,
                    "condition": condition,
                    "type": type(error).__name__,
                    "message": str(error)[:500],
                }
                failures.append(failure)
                print(json.dumps({"event": "schedule_item_failed", **failure}, ensure_ascii=False), flush=True)
    except BaseException as error:
        metadata.update(
            status="incomplete",
            completed_at=now(),
            error_type=type(error).__name__,
            error_message=str(error)[:500],
        )
        write_json(output_root / "batch.json", metadata)
        raise
    metadata.update(
        status="execution_complete_with_failures" if failures else "execution_complete",
        completed_at=now(),
        execution_failures=failures,
    )
    write_json(output_root / "batch.json", metadata)
    summary = summarize(completed)
    write_json(output_root / "summary.json", summary)
    write_report(output_root / "report.md", summary, metadata)
    print(json.dumps({"event": "batch_complete", "summary": summary}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
