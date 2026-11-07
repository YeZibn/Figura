"""Verify exported feedback evidence and record the assistant's content review."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from PIL import Image

root = Path(__file__).resolve().parents[2]
batch_name = sys.argv[1]
out = root / 'evaluation/e2e-30-followups' / batch_name
private = root / '.figura/evaluation' / batch_name
old = sqlite3.connect((private / 'baseline/figura.sqlite3').as_uri() + '?mode=ro', uri=True)
new = sqlite3.connect((private / 'working/figura.sqlite3').as_uri() + '?mode=ro', uri=True)


def read(path):
    return json.loads(path.read_text())


def put(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


results = []
tables = [row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")
          if any(col[1] == 'run_id' for col in old.execute('PRAGMA table_info("' + row[0] + '")'))]
for tid in ('B08', 'C02', 'C03'):
    folder = out / 'tasks' / tid
    execution = read(folder / 'execution.json')
    evidence = execution['turns'][0]
    turn = folder / f'turn-{evidence["turn"]:02}'
    for run in read(folder / 'baseline.json')['runs']:
        for table in tables:
            query = f'SELECT * FROM "{table}" WHERE run_id=?'
            assert old.execute(query, (run['run_id'],)).fetchall() == new.execute(query, (run['run_id'],)).fetchall(), (tid, table)
    for render in evidence['renders']:
        path = turn / render['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == render['result']['image_sha256']
        with Image.open(path) as image:
            image.verify()
    summary = {'task_id': tid, 'run_status': evidence['status'], 'feedback_turn': evidence['turn'],
               'original_run_facts_preserved': True, 'wall_seconds': evidence['wall_seconds'],
               'usage': evidence['usage'], 'usage_complete': evidence['usage_complete'],
               'new_figures': len(evidence['figures']), 'new_renders': len(evidence['renders']),
               'review_method': 'Current assistant reviewed full answer and structured evidence; B08 actual PNG visually inspected. Not an independent LLM Judge.'}
    if tid == 'B08':
        assert len(evidence['figures']) == 1
        spec = read(turn / evidence['figures'][0]['file'])['charts'][0]['chart_spec']
        assert spec['dataset']['inner_radius_ratio'] == 0.35
        assert [(s['label'], s['value']) for s in spec['dataset']['slices']] == [('Online', 45), ('Store', 30), ('Partner', 15), ('Other', 10)]
        summary.update(verdict='fail', correction_success=False, limitation_acknowledged=True,
                       reason='New PNG is readable but uses radius0.35 instead of required0.5. Agent labels it diagnostic and explicitly denies repair; no compliant repaired PNG.',
                       additional_findings=['The reply mixes original-session attempts and current attempts. Current turn has one failed assembly and one successful0.35 assembly/render, not a new0.5 rerender. Do not count narrative claims as new execution evidence.'])
    else:
        assert evidence['figures'] == [] and evidence['renders'] == []
        tools = read(turn / 'tool-overview.json')
        assert len(tools) == 1 and tools[0]['tool_name'] == 'read_history' and tools[0]['outcome'] == 'succeeded'
        summary.update(verdict='pass', correction_success=True,
                       reason=('Correct Q3 South19>East17>North15; other quarters East>South>North. Retains final East/Q2=31.' if tid == 'C02' else 'Correct East21 to18 decline atQ2->Q3, decrease3 and approximately14.3%; retainsQ5 and note.'))
    put(folder / 'review.json', summary)
    results.append(summary)

assert new.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert new.execute('PRAGMA foreign_key_check').fetchall() == []
report = {'batch_id': batch_name, 'scope': 'One targeted feedback on each original session clone, using current frozen source; C02/C03 continue after all3 original turns.',
          'original_e2e_score': '27/30 unchanged', 'correction_success': {'numerator': 2, 'denominator': 3},
          'independent_judge': False, 'total_wall_seconds': round(sum(r['wall_seconds'] for r in results), 3),
          'total_provider_tokens': sum(r['usage']['total_tokens'] for r in results), 'state_integrity': 'ok', 'cases': results}
put(out / 'report.json', report)
batch = read(out / 'batch.json')
batch['status'] = 'complete_assistant_reviewed'
put(out / 'batch.json', batch)
print(json.dumps({'correction_success': '2/3', 'total_wall_seconds': report['total_wall_seconds'],
                  'total_provider_tokens': report['total_provider_tokens'], 'original_facts_preserved': True}, ensure_ascii=False))
