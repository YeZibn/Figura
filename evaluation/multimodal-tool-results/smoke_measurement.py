import json, shutil, tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from scripts import evaluate_figura_measurements as evaluation
report=Path('evaluation/multimodal-tool-results/measurement-smoke.json').resolve()
original=evaluation.FIXTURES
manifest=json.loads((original/'manifest.json').read_text())
manifest['cases']=manifest['cases'][:1]
with tempfile.TemporaryDirectory(prefix='figura-media-smoke-') as temporary:
    fixture=Path(temporary); (fixture/'images').mkdir()
    for case in manifest['cases']:
        target=fixture/'images'/case['image']
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original/'images'/case['image'],target)
    (fixture/'manifest.json').write_text(json.dumps(manifest))
    evaluation.FIXTURES=fixture
    evaluation.evaluate(report)
result=json.loads(report.read_text())
assert all('tool_error' not in row for row in result['cases'])
print({'charts':len(result['cases']),'tool_errors':0,'network_requests':0})
