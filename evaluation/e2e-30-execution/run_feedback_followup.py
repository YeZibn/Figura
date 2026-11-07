"""One feedback turn per failed task, on backed-up sessions and frozen source."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from figura.charts.chartfigure import parse_chart_figure, chart_figure_digest
from figura.providers.config import ProviderSettings
from figura.providers.models import MODEL_IDS, ProviderId


REPO = Path(__file__).resolve().parents[2]
PARENT = REPO / 'evaluation/e2e-30-runs/20261102-正式首测-01'
SOURCE = REPO / '.figura/evaluation/e2e30-20261102-正式首测-01'
BATCH = 'feedback-' + datetime.now().strftime('%Y%m%d-%H%M%S')
OUT = REPO / 'evaluation/e2e-30-followups' / BATCH
PRIVATE = REPO / '.figura/evaluation' / BATCH
RUNTIME = PRIVATE / 'working'
FROZEN = PRIVATE / 'source'
PROMPTS = {
    'B08': 'Online 的百分比标签被中心圆遮挡，容易误读。请在保留原有数据、切片顺序、标题、来源和内半径比例 0.5 的前提下修复，重新交付可查看的 PNG。仅解释问题不算修复。若当前工具能力无法满足，请如实说明，不能声称已修复。',
    'C02': '你第一轮声称四个季度均为 East > South > North，这个结论可能有误。请根据已保存数据逐季度核对并纠正，明确哪些季度的系列排序不同；同时保留第三轮已经确认的数据及其他要求，不需要重新绘图。',
    'C03': '你第一轮声称三个系列逐季度递增，请根据已保存数据核对是否成立，明确实际下降区间；保留当前 Q5、注释及其他数据，不需要重新绘图。',
}
ACCEPTANCE = {
    'B08': ['实际交付新成功 render 对应 PNG', 'Online 百分比完整可读，其他关键标签无遮挡', '单环图，inner_radius_ratio=0.5；顺序 Online/Store/Partner/Other；值45/30/15/10；标题渠道贡献及来源不变', '回答与实际产物一致；承认无法修复不计修复成功'],
    'C02': ['明确纠正第一轮全季度排序说法', 'Q3 South19>East17>North15；Q1/Q2/Q4为East>South>North', '采用第三轮 East/Q2=31，不能回退到20或28', '不产生与当前数据冲突的新陈述，不修改已有数据'],
    'C03': ['明确否定三个系列逐季度递增', 'East Q2=21到Q3=18下降；含Q5的当前East为15/21/18/27/35', 'South=12/17/20/23/29，North=10/14/16/19/24；保留Q5和注释', '不产生新错误，不修改已有数据'],
}


def read(path):
    return json.loads(path.read_text())


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p.suffix in ('.py', '.md', '.json')}


def emit(event, **values):
    print(json.dumps({'event': event, **values}, ensure_ascii=False), flush=True)


def rows(sql, args=()):
    with sqlite3.connect((RUNTIME / 'figura.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, args)]


def api(path, method='GET', obj=None, data=None, headers=None):
    response = requests.request(method, BASE + path, json=obj, data=data,
                                headers={'Origin': 'http://127.0.0.1:1421', **(headers or {})}, timeout=45)
    if not response.ok:
        raise RuntimeError(f'Gateway HTTP {response.status_code}; inspect private Gateway log')
    return response.json() if 'json' in response.headers.get('Content-Type', '') else response.content


# Reuse only the export function; never import the original batch driver's startup.
tree = ast.parse((REPO / 'evaluation/e2e-30-execution/run_batch.py').read_text())
export = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'export_turn')
exec(compile(ast.Module(body=[export], type_ignores=[]), '<existing-evidence-export>', 'exec'))


def main():
    global BASE
    OUT.mkdir(parents=True, exist_ok=False)
    PRIVATE.mkdir(parents=True, exist_ok=False)
    load_dotenv(REPO / '.env', override=False)
    profile = ProviderSettings.from_env().profiles[ProviderId.DEEPSEEK]
    if not profile.availability().available:
        raise RuntimeError('DeepSeek unavailable; no requests sent')

    original_db = SOURCE / 'figura.sqlite3'
    original_sha = sha(original_db)
    with sqlite3.connect(original_db.as_uri() + '?mode=ro', uri=True) as connection:
        if connection.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0]:
            raise RuntimeError('Original evaluation has active Runs; refusing snapshot')
        backup = PRIVATE / 'baseline'
        shutil.copytree(SOURCE, backup, ignore=shutil.ignore_patterns('*.sqlite3', '*-wal', '*-shm', '*.lock', '__pycache__'))
        with sqlite3.connect(backup / 'figura.sqlite3') as target:
            connection.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert target.execute('PRAGMA foreign_key_check').fetchall() == []
    shutil.copytree(backup, RUNTIME)
    before = source_manifest(REPO / 'src/figura')
    shutil.copytree(REPO / 'src/figura', FROZEN / 'src/figura', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if before != source_manifest(FROZEN / 'src/figura') or before != source_manifest(REPO / 'src/figura'):
        raise RuntimeError('Source changed during snapshot; no requests sent')
    put(OUT / 'source-manifest.json', before)
    put(OUT / 'feedback-plan.json', {'batch_id': BATCH, 'parent_batch': PARENT.name,
        'prompts': PROMPTS, 'acceptance': ACCEPTANCE, 'max_feedback_turns_per_task': 1,
        'per_turn_timeout_seconds': 600, 'scope': 'current source snapshot; continuation after all original turns; original 27/30 unchanged',
        'review': 'current assistant checks structured evidence and actual PNG; no independent Judge invocation'})
    put(OUT / 'batch.json', {'batch_id': BATCH, 'status': 'running', 'started_at': datetime.now().isoformat(),
        'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'dirty_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=REPO)).hexdigest(),
        'runtime_dir': str(RUNTIME.relative_to(REPO)), 'baseline_dir': str(backup.relative_to(REPO)),
        'source_snapshot': str(FROZEN.relative_to(REPO)), 'source_manifest_sha256': sha(OUT / 'source-manifest.json'),
        'original_database_sha256': original_sha, 'parent_code': read(PARENT / 'batch.json')['code'],
        'provider': 'deepseek', 'model': MODEL_IDS[ProviderId.DEEPSEEK],
        'settings': {'context_capacity': profile.context_window_tokens, 'thinking_mode': profile.thinking_mode,
                     'reasoning_effort': profile.reasoning_effort, 'max_completion_tokens': profile.max_completion_tokens}})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    BASE = f'http://127.0.0.1:{port}/api/v1'
    env = os.environ.copy()
    env.update(FIGURA_DATA_DIR=str(RUNTIME), FIGURA_GATEWAY_PORT=str(port),
               FIGURA_WEB_ORIGINS='http://127.0.0.1:1421,http://localhost:1421',
               PYTHONPATH=str(FROZEN / 'src'))
    process = None
    try:
        with (PRIVATE / 'gateway.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'figura.gateway'], cwd=FROZEN,
                                       env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(45):
                if process.poll() is not None:
                    raise RuntimeError('Snapshot Gateway exited; inspect private log')
                try:
                    health = api('/health')
                    break
                except requests.RequestException:
                    time.sleep(1)
            else:
                raise RuntimeError('Snapshot Gateway health timeout')
            emit('gateway_ready', batch=BATCH, isolated=True)
            for tid, prompt in PROMPTS.items():
                original = read(PARENT / 'tasks' / tid / 'execution.json')
                session = original['session_id']
                ordinal = len(original['turns']) + 1
                dest = OUT / 'tasks' / tid
                baseline_rows = rows('SELECT run_id,ordinal,status FROM runs WHERE session_id=? ORDER BY ordinal', (session,))
                assert len(baseline_rows) == ordinal - 1 and all(r['status'] == 'completed' for r in baseline_rows)
                put(dest / 'baseline.json', {'session_id': session, 'runs': baseline_rows, 'parent_task': tid})
                submitted = {'text': prompt, 'attachmentIds': [], 'providerId': 'deepseek'}
                put(dest / f'turn-{ordinal:02}' / 'submitted-input.json', submitted)
                started = time.monotonic()
                run = api(f'/sessions/{session}/runs', 'POST', submitted,
                          headers={'Idempotency-Key': uuid.uuid4().hex})['run']
                put(dest / 'active-run.json', {'session_id': session, 'run_id': run['runId'], 'ordinal': ordinal})
                emit('feedback_started', task=tid, ordinal=ordinal, run_id=run['runId'])
                timedout = False
                last = 0
                while run['status'] == 'running':
                    time.sleep(2)
                    run = api(f'/sessions/{session}/runs/{run["runId"]}/history?afterSequence=0')['run']
                    elapsed = time.monotonic() - started
                    if elapsed - last >= 30:
                        emit('feedback_running', task=tid, seconds=round(elapsed))
                        last = elapsed
                    if elapsed > 600 and not timedout:
                        api(f'/sessions/{session}/runs/{run["runId"]}/stop', 'POST', {})
                        timedout = True
                    if timedout and elapsed > 780:
                        raise RuntimeError('Cooperative stop did not converge; refusing additional tasks')
                evidence = export_turn(dest, session, run, ordinal, time.monotonic() - started, timedout)
                put(dest / 'execution.json', {'task_id': tid, 'batch_id': BATCH, 'session_id': session,
                    'execution_status': 'completed', 'parent_turn_count': ordinal - 1, 'turns': [evidence]})
                emit('feedback_completed', task=tid, status=run['status'], seconds=evidence['wall_seconds'],
                     tokens=evidence['usage']['total_tokens'], figures=len(evidence['figures']), renders=len(evidence['renders']))
            manifest = read(OUT / 'batch.json')
            manifest.update(status='execution_complete_pending_review', finished_at=datetime.now().isoformat())
            put(OUT / 'batch.json', manifest)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        unchanged = sha(original_db) == original_sha
        put(OUT / 'isolation-check.json', {'original_database_unchanged': unchanged,
            'source_snapshot_unchanged': before == source_manifest(FROZEN / 'src/figura'),
            'gateway_stopped': process is None or process.poll() is not None})
        emit('cleanup', original_database_unchanged=unchanged, output=str(OUT))


if __name__ == '__main__':
    main()
