from pathlib import Path
import hashlib,json,sqlite3,sys
from jsonschema import Draft202012Validator
from PIL import Image
from figura.charts.chartfigure import parse_chart_figure,chart_figure_digest
REPO=Path(__file__).resolve().parents[2];BATCH=sys.argv[1];OUT=REPO/'evaluation/e2e-30-runs'/BATCH;DATA=REPO/'evaluation/e2e-30-v1';DB=REPO/'.figura/evaluation'/('e2e30-'+BATCH)/'figura.sqlite3'
def j(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=j(DATA/'checksums.json')['files'];assert all(sha(DATA/p)==h for p,h in checks.items()),'frozen dataset changed'
schema=Draft202012Validator(j(DATA/'judge/verdict.schema.json'))
c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
turns=figs=pngs=judged=reviews=0;runids=[]
for task in j(DATA/'manifest.json')['tasks']:
 tid=task['task_id'];source=DATA/'tasks'/tid;folder=OUT/'tasks'/tid;e=j(folder/'execution.json');assert e['execution_status']=='completed'
 expected=j(source/'agent-input/conversation.json');assert len(e['turns'])==len(expected)
 for et,ut in zip(e['turns'],expected):
  runids.append(et['run_id']);d=folder/f'turn-{et["turn"]:02}';submitted=j(d/'submitted-input.json')
  assert submitted['text']==ut['text']
  raw=c.execute("SELECT payload_json FROM run_execution_records WHERE run_id=? AND record_kind='input'",(et['run_id'],)).fetchone();actual=json.loads(raw[0])
  assert actual['text']==ut['text'] and actual['requested_provider']=='deepseek' and actual['requested_model']=='deepseek-flash'
  assert len(actual['attachment_ids'])==len(ut['attachments'])
  assert submitted['attachment_sha256']==[sha(source/'agent-input'/n) for n in ut['attachments']]
  for f in et['figures']:
   assert chart_figure_digest(parse_chart_figure(j(d/f['file'])))==f['result']['figure_digest'];figs+=1
  for r in et['renders']:
   p=d/r['file'];assert sha(p)==r['result']['image_sha256']
   with Image.open(p) as im:im.verify()
   pngs+=1
  turns+=1
 for name in ('verdict.json','review-independent.json'):
  p=folder/name
  if p.exists():
   v=j(p);schema.validate(v);assert v['task_id']==tid
   assert sorted(x['id'] for x in v['checks'])==sorted(x['id'] for x in j(source/'judge-only/answer-key.json')['checks'])
   if name=='verdict.json':judged+=1
   else:reviews+=1
assert len(runids)==len(set(runids))==50
assert len(set(j(p)['session_id'] for p in (OUT/'tasks').glob('*/execution.json')))==30
batch=j(OUT/'batch.json');assert sha(DATA/'checksums.json')==batch['dataset_checksums_sha256']
assert all(sha(REPO/p)==h for p,h in batch['harness']['scripts'].items()),'frozen harness changed'
result={'status':'passed','formal_tasks':30,'independent_sessions':30,'formal_runs':turns,'distinct_runs':len(set(runids)),'figures_verified':figs,'pngs_verified':pngs,'initial_judgements_validated':judged,'reviews_validated':reviews,'frozen_input_and_rubric_checksums':'unchanged','submitted_and_durable_user_inputs':'exact_match','frozen_harness_scripts':'unchanged','no_agent_reexecution_for_judge':True}
(OUT/'evidence-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
