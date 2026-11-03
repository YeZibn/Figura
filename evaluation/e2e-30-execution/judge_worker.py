from pathlib import Path
import json,subprocess,sys,time
REPO=Path(__file__).resolve().parents[2];BATCH=sys.argv[1]
OUT=REPO/'evaluation/e2e-30-runs'/BATCH
for c in 'ABC':
 for i in range(1,11):
  tid=f'{c}{i:02}';p=OUT/'tasks'/tid/'execution.json'
  while not p.exists() or json.loads(p.read_text()).get('execution_status')!='completed':
   if (OUT/'driver-error.json').exists():raise RuntimeError('Figura driver failed; refusing partial batch as complete')
   time.sleep(2)
  result=subprocess.run([sys.executable,str(REPO/'evaluation/e2e-30-execution/judge_batch.py'),BATCH,'formal',tid])
  if result.returncode:
   (OUT/'judge-worker-error.json').write_text(json.dumps({'task_id':tid,'returncode':result.returncode}))
   raise SystemExit(result.returncode)
(OUT/'initial-judgement-complete.json').write_text(json.dumps({'tasks':30,'status':'pending_review'}))
