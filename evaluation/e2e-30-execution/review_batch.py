from pathlib import Path
from datetime import datetime
import json,math,random,subprocess,sys,time
REPO=Path(__file__).resolve().parents[2];BATCH=sys.argv[1];OUT=REPO/'evaluation/e2e-30-runs'/BATCH
def j(p):return json.loads(p.read_text())
def put(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
while not (OUT/'initial-judgement-complete.json').exists():
 if (OUT/'judge-worker-error.json').exists():raise RuntimeError('Initial judge worker failed')
 time.sleep(3)
initial={p.parent.name:j(p) for p in sorted((OUT/'tasks').glob('*/verdict.json'))};assert len(initial)==30
rng=random.Random(20261102);selected={tid for tid,v in initial.items() if v['verdict']!='pass'};samples={}
for c in 'ABC':
 candidates=sorted(tid for tid,v in initial.items() if tid.startswith(c) and v['verdict']=='pass')
 samples[c]=sorted(rng.sample(candidates,math.ceil(.2*len(candidates)))) if candidates else []
 selected.update(samples[c])
put(OUT/'review-selection.json',{'seed':20261102,'pass_sampling':'ceil(20% of pass count) per category, sorted IDs, one seeded generator','pass_samples':samples,'all_fail_and_needs_review':sorted(tid for tid,v in initial.items() if v['verdict']!='pass'),'selected':sorted(selected)})
for tid in sorted(selected):
 subprocess.run([sys.executable,str(REPO/'evaluation/e2e-30-execution/judge_batch.py'),BATCH,'review',tid],check=True)
 records=[]
 for task,v in initial.items():
  rp=OUT/'tasks'/task/'review-independent.json';rv=j(rp) if rp.exists() else None
  if rv:
   diffs=[{'id':x['id'],'initial':x['status'],'review':next(y['status'] for y in rv['checks'] if y['id']==x['id'])} for x in v['checks'] if next(y['status'] for y in rv['checks'] if y['id']==x['id'])!=x['status']]
   final=v['verdict'] if rv['verdict']==v['verdict'] and v['verdict']!='needs_review' else None
  else:diffs=[];final=v['verdict'] if task not in selected else None
  records.append({'task_id':task,'initial':v['verdict'],'selected_for_review':task in selected,'review':rv['verdict'] if rv else None,'check_disagreements':diffs,'final_verdict':final,'requires_adjudication':bool(rv and final is None)})
 put(OUT/'final-status.json',records)
 print(json.dumps({'reviewed':tid,'initial':initial[tid]['verdict'],'review':j(OUT/'tasks'/tid/'review-independent.json')['verdict']},ensure_ascii=False),flush=True)
put(OUT/'review-complete.json',{'at':datetime.now().astimezone().isoformat(),'reviewed_tasks':len(selected),'status':'check_final_status_for_unresolved_disagreements'})
