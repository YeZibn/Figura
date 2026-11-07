"""Create a separate B08-v2 task and run it once in a fresh Session."""
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

from dotenv import load_dotenv
import requests
import run_feedback_followup as evidence


ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / 'evaluation/e2e-30-v1/tasks/B08'
MATERIAL = ROOT / 'evaluation/e2e-30-revisions/B08-v2'
SOURCE_BATCH = 'feedback-20261106-104507'
FROZEN = ROOT / '.figura/evaluation' / SOURCE_BATCH / 'source'
BATCH = 'B08-v2-' + datetime.now().strftime('%Y%m%d-%H%M%S')
OUT = ROOT / 'evaluation/e2e-30-followups' / BATCH
RUNTIME = ROOT / '.figura/evaluation' / BATCH


def main():
    # Deliberately choose the previously executed source snapshot to isolate the task revision.
    expected = evidence.read(ROOT / 'evaluation/e2e-30-followups' / SOURCE_BATCH / 'source-manifest.json')
    assert expected == evidence.source_manifest(FROZEN / 'src/figura')
    if MATERIAL.exists():
        raise RuntimeError('B08-v2 already exists; do not overwrite versioned inputs')
    MATERIAL.mkdir(parents=True)
    conversation = copy.deepcopy(evidence.read(ORIGINAL / 'agent-input/conversation.json'))
    conversation[0]['text'] = conversation[0]['text'].replace('内半径比例 0.5', '内半径比例 0.35')
    assert '内半径比例 0.35' in conversation[0]['text']
    figure = copy.deepcopy(evidence.read(ORIGINAL / 'judge-only/reference-turn-01.json'))
    figure['charts'][0]['chart_spec']['dataset']['inner_radius_ratio'] = 0.35
    answer = copy.deepcopy(evidence.read(ORIGINAL / 'judge-only/answer-key.json'))
    answer['task_id'] = 'B08-v2'
    answer['facts']['required'] = answer['facts']['required'].replace('内半径比例 0.5', '内半径比例 0.35')
    answer['reference_figures'] = [figure]
    answer['visual_reference_note'] = '查看实际输出PNG。内半径0.35，所有百分比必须可读；不以原题故障图作通过样板。'
    evidence.put(MATERIAL / 'agent-input/conversation.json', conversation)
    (MATERIAL / 'agent-input/conversation.md').write_text('# B08-v2 固定输入\n\n' + conversation[0]['text'] + '\n')
    evidence.put(MATERIAL / 'agent-input/dataset.json', evidence.read(ORIGINAL / 'agent-input/dataset.json'))
    evidence.put(MATERIAL / 'judge-only/reference-turn-01.json', figure)
    evidence.put(MATERIAL / 'judge-only/answer-key.json', answer)
    evidence.put(MATERIAL / 'task.json', {'task_id': 'B08-v2', 'category': 'construction', 'turns': 1,
        'parent_task': 'figura-e2e-30-v1/B08', 'change': 'inner_radius_ratio0.5->0.35 only; values/order/title/source/readability criteria unchanged',
        'selection': 'diagnostic revision informed by observed B08 failure and feedback experiment, not a held-out task',
        'success': 'all semantic, rendering, and delivery critical checks pass'})
    (MATERIAL / 'README.md').write_text('# B08-v2：环图构建修订题\n\n'
        '旧题没有输入原图；已知遮挡来自原生渲染器的固定标签位置与0.5内孔组合。\n'
        '本版只将内半径要求改为0.35，其余数据、顺序、标题、来源、PNG交付及可读性标准保持。\n'
        '该选择参考了失败诊断，不是盲测。它不修复渲染器，也不替换原30题的成绩。\n'
        '只向Agent发送agent-input/conversation.json中的正文，不提供答案、历史失败或反馈。\n')
    evidence.put(MATERIAL / 'checksums.json', evidence.source_manifest(MATERIAL))
    OUT.mkdir(parents=True, exist_ok=False)
    RUNTIME.mkdir(parents=True, exist_ok=False)
    load_dotenv(ROOT / '.env', override=False)
    evidence.RUNTIME = RUNTIME
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    evidence.BASE = f'http://127.0.0.1:{port}/api/v1'
    env = os.environ.copy()
    env.update(FIGURA_DATA_DIR=str(RUNTIME), FIGURA_GATEWAY_PORT=str(port),
               FIGURA_WEB_ORIGINS='http://127.0.0.1:1421,http://localhost:1421', PYTHONPATH=str(FROZEN / 'src'))
    evidence.put(OUT / 'batch.json', {'batch_id': BATCH, 'task_id': 'B08-v2', 'status': 'running',
        'source_snapshot_batch': SOURCE_BATCH, 'source_manifest_sha256': evidence.sha(ROOT / 'evaluation/e2e-30-followups' / SOURCE_BATCH / 'source-manifest.json'),
        'materials': str(MATERIAL.relative_to(ROOT)), 'material_checksums_sha256': evidence.sha(MATERIAL / 'checksums.json'),
        'fresh_session': True, 'feedback_turns': 0, 'attempts': 1, 'provider': 'deepseek', 'model': 'deepseek-flash',
        'per_turn_timeout_seconds': 600, 'original_27_of_30_unchanged': True,
        'acceptance_frozen_before_run': answer['checks'], 'review': 'current assistant evidence and PNG review, not independent Judge'})
    process = None
    try:
        with (RUNTIME / 'gateway.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'figura.gateway'], cwd=FROZEN,
                                       env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(45):
                if process.poll() is not None:
                    raise RuntimeError('Snapshot Gateway exited')
                try:
                    evidence.api('/health')
                    break
                except requests.RequestException:
                    time.sleep(1)
            else:
                raise RuntimeError('Gateway health timeout')
            session = evidence.api('/sessions', 'POST', {'name': BATCH})['session']['id']
            dest = OUT / 'tasks/B08-v2'
            request = {'text': conversation[0]['text'], 'attachmentIds': [], 'providerId': 'deepseek'}
            evidence.put(dest / 'turn-01/submitted-input.json', request)
            started = time.monotonic()
            run = evidence.api(f'/sessions/{session}/runs', 'POST', request,
                               headers={'Idempotency-Key': uuid.uuid4().hex})['run']
            evidence.put(dest / 'active-run.json', {'session_id': session, 'run_id': run['runId']})
            evidence.emit('revised_task_started', batch=BATCH, run_id=run['runId'], fresh_session=True)
            timedout = False
            last = 0
            while run['status'] == 'running':
                time.sleep(2)
                run = evidence.api(f'/sessions/{session}/runs/{run["runId"]}/history?afterSequence=0')['run']
                elapsed = time.monotonic() - started
                if elapsed - last >= 30:
                    evidence.emit('revised_task_running', seconds=round(elapsed))
                    last = elapsed
                if elapsed > 600 and not timedout:
                    evidence.api(f'/sessions/{session}/runs/{run["runId"]}/stop', 'POST', {})
                    timedout = True
                if timedout and elapsed > 780:
                    raise RuntimeError('Stop did not converge')
            exported = evidence.export_turn(dest, session, run, 1, time.monotonic() - started, timedout)
            evidence.put(dest / 'execution.json', {'task_id': 'B08-v2', 'batch_id': BATCH, 'session_id': session,
                'execution_status': 'completed', 'turns': [exported]})
            batch = evidence.read(OUT / 'batch.json')
            batch.update(status='execution_complete_pending_review', finished_at=datetime.now().isoformat())
            evidence.put(OUT / 'batch.json', batch)
            evidence.emit('revised_task_completed', status=run['status'], seconds=exported['wall_seconds'],
                          tokens=exported['usage']['total_tokens'], renders=len(exported['renders']), output=str(OUT))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        evidence.put(OUT / 'isolation-check.json', {'gateway_stopped': process is None or process.poll() is not None,
            'source_snapshot_unchanged': expected == evidence.source_manifest(FROZEN / 'src/figura'),
            'fresh_database_only': True})


if __name__ == '__main__':
    main()
