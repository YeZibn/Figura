"""Local, single-batch evaluation driver. Never edits Figura or frozen inputs."""
from __future__ import annotations
import hashlib, json, math, os, signal, socket, sqlite3, subprocess, sys, time, uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import requests
from dotenv import load_dotenv
from figura.providers.config import ProviderSettings
from figura.providers.models import ProviderId
from figura.charts.chartfigure import parse_chart_figure, chart_figure_digest

REPO=Path(__file__).resolve().parents[2]
DATASET=REPO/'evaluation/e2e-30-v1'
BATCH=sys.argv[1]
OUT=REPO/'evaluation/e2e-30-runs'/BATCH
RUNTIME=REPO/'.figura/evaluation'/('e2e30-'+BATCH)
OUT.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def read(p):return json.loads(p.read_text())
def put(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def emit(event,**kw):print(json.dumps({'at':now(),'event':event,**kw},ensure_ascii=False),flush=True)
def rows(sql,args=()):
 with sqlite3.connect(f'file:{RUNTIME}/figura.sqlite3?mode=ro',uri=True,timeout=5) as c:
  c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute(sql,args)]
def api(path,method='GET',obj=None,data=None,headers=None):
 h={'Origin':'http://127.0.0.1:1421',**(headers or {})}
 r=requests.request(method,BASE+path,json=obj,data=data,headers=h,timeout=45)
 if not r.ok:raise RuntimeError(f'Gateway HTTP {r.status_code}: {r.text[:300]}')
 return r.json() if 'json' in r.headers.get('Content-Type','') else r.content

def export_turn(taskdir,session,run,turn,elapsed,timedout):
 dest=taskdir/f'turn-{turn:02}';dest.mkdir(parents=True,exist_ok=True)
 records=rows('SELECT record_id,record_kind,payload_json FROM run_execution_records WHERE run_id=? ORDER BY record_sequence',(run['runId'],))
 byid={r['record_id']:json.loads(r['payload_json']) for r in records}
 final=next((json.loads(r['payload_json']) for r in records if r['record_kind']=='final_answer'),None)
 response=byid.get(final.get('response_record_id')) if final else None
 answer=response.get('assistant_content','') if response else ''
 (dest/'final-answer.txt').write_text(answer+'\n')
 facts=[json.loads(r['payload_json']) for r in rows('SELECT payload_json FROM run_tool_execution_facts WHERE run_id=? ORDER BY tool_sequence',(run['runId'],))]
 calls={f['call_id']:f for f in facts if f['fact_kind']=='tool_call'}
 outcomes=[f for f in facts if f['fact_kind']=='tool_result']
 overview=[];figures=[];renders=[]
 for f in outcomes:
  overview.append({k:f.get(k) for k in ('call_id','tool_name','outcome','error')})
  if f['outcome']!='succeeded':continue
  c=calls[f['call_id']]
  if f['tool_name']=='assemble_chart_figure':
   value=json.loads(c['arguments_json']);digest=chart_figure_digest(parse_chart_figure(value))
   assert digest==f['result']['figure_digest']
   name=f'figure-{len(figures)+1:02}.json';put(dest/name,value)
   figures.append({'call_id':f['call_id'],'run_id':run['runId'],'file':name,'result':f['result'],'digest_verified':True})
  elif f['tool_name']=='render_chart_figure':
   blob=api(f'/sessions/{session}/runs/{quote(run["runId"],safe="")}/chart-renders/{quote(f["call_id"],safe="")}/content')
   assert hashlib.sha256(blob).hexdigest()==f['result']['image_sha256']
   name=f'render-{len(renders)+1:02}.png';(dest/name).write_bytes(blob)
   renders.append({'call_id':f['call_id'],'run_id':run['runId'],'file':name,'result':f['result'],'png_sha256_verified':True})
 attempts=rows('SELECT attempt_id,request_id,status,response_record_id,failure_code,http_status,usage_json,attempt_sequence FROM run_provider_attempts WHERE run_id=? ORDER BY run_attempt_sequence',(run['runId'],))
 usage={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0};missing=[]
 for a in attempts:
  u=json.loads(a['usage_json']) if a['usage_json'] else byid.get(a['response_record_id'],{}).get('usage')
  a.pop('usage_json');a['usage']=u
  if not u:missing.append(a['attempt_id']);continue
  for k in usage:
   if isinstance(u.get(k),int):usage[k]+=u[k]
   else:missing.append(a['attempt_id']+':'+k)
 put(dest/'provider-attempts.json',attempts)
 ops=rows('SELECT operation_id,status,failure_code FROM session_context_compaction_operations WHERE target_run_id=?',(run['runId'],))
 put(dest/'tool-overview.json',overview)
 evidence={'turn':turn,'run_id':run['runId'],'session_id':session,'status':run['status'],'terminal_code':run.get('terminalCode'),'wall_seconds':round(elapsed,3),'timed_out':timedout,'final_answer':'final-answer.txt','final_answer_committed':bool(final),'figures':figures,'renders':renders,'provider_attempt_count':len(attempts),'internal_retry_count':sum(a['attempt_sequence']>1 for a in attempts),'usage':usage,'usage_complete':not missing,'usage_missing_attempt_refs':missing,'compaction_operations':ops,'delivery_selection':'judge must select from actual final answer and all committed candidates; no automatic best-of selection'}
 put(dest/'evidence.json',evidence)
 return evidence

def run_task(tid,source,timeout,calibration=False):
 taskdir=OUT/('calibration' if calibration else 'tasks')/tid
 if (taskdir/'execution.json').exists() and read(taskdir/'execution.json').get('execution_status')=='completed':
  emit('already_completed',task_id=tid);return read(taskdir/'execution.json')
 turns=read(source/'agent-input/conversation.json')
 taskdir.mkdir(parents=True,exist_ok=True)
 created=api('/sessions','POST',{'name':f'E2E30 {BATCH} {tid}'})
 session=created['session']['id'];uploaded={};execution={'task_id':tid,'batch_id':BATCH,'session_id':session,'execution_status':'running','started_at':now(),'turns':[],'protocol_anomalies':[]}
 put(taskdir/'execution.json',execution)
 for t in turns:
  attach=[]
  for name in t['attachments']:
   p=source/'agent-input'/name
   if name not in uploaded:
    uploaded[name]=api(f'/sessions/{session}/attachments?filename={quote(name)}','POST',data=p.read_bytes(),headers={'Content-Type':'image/png'})['attachment']['id']
   attach.append(uploaded[name])
  req={'text':t['text'],'attachmentIds':attach,'providerId':'deepseek'}
  put(taskdir/f'turn-{t["turn"]:02}'/'submitted-input.json',{'text':t['text'],'attachment_sha256':[sha(source/'agent-input'/n) for n in t['attachments']],'providerId':'deepseek'})
  started=time.monotonic();created=api(f'/sessions/{session}/runs','POST',req,headers={'Idempotency-Key':uuid.uuid4().hex});run=created['run'];runid=run['runId']
  execution['active_run_id']=runid;put(taskdir/'execution.json',execution)
  emit('turn_started',task_id=tid,turn=t['turn'],run_id=runid)
  last=0;timedout=False
  while run['status']=='running':
   time.sleep(2)
   history=api(f'/sessions/{session}/runs/{runid}/history?afterSequence=0');run=history['run'];elapsed=time.monotonic()-started
   if elapsed-last>=30:
    last=elapsed;emit('turn_running',task_id=tid,turn=t['turn'],seconds=round(elapsed),status=run['status'])
   if elapsed>timeout and not timedout:
    timedout=True;api(f'/sessions/{session}/runs/{runid}/stop','POST',{});emit('timeout_stop_requested',task_id=tid,turn=t['turn'])
   if timedout and elapsed>timeout+180:raise RuntimeError(f'{tid}: stop not converged; refusing overlapping next task')
  evidence=export_turn(taskdir,session,run,t['turn'],time.monotonic()-started,timedout)
  execution['turns'].append(evidence);execution.pop('active_run_id',None);put(taskdir/'execution.json',execution)
  emit('turn_completed',task_id=tid,turn=t['turn'],status=run['status'],seconds=evidence['wall_seconds'],renders=len(evidence['renders']),tokens=evidence['usage']['total_tokens'])
 execution.update(execution_status='completed',completed_at=now());put(taskdir/'execution.json',execution)
 emit('task_completed',task_id=tid,turns=len(turns))
 return execution

load_dotenv(REPO/'.env',override=False)
for rel,h in read(DATASET/'checksums.json')['files'].items():assert sha(DATASET/rel)==h,f'Frozen material drift: {rel}'
assert ProviderSettings.from_env().profiles[ProviderId.DEEPSEEK].availability().available
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
BASE=f'http://127.0.0.1:{port}/api/v1'
env=os.environ.copy();env.update(FIGURA_DATA_DIR=str(RUNTIME),FIGURA_GATEWAY_PORT=str(port),FIGURA_WEB_ORIGINS='http://127.0.0.1:1421,http://localhost:1421')
log=(OUT/'gateway.log').open('ab',buffering=0)
proc=subprocess.Popen([sys.executable,'-m','figura.gateway'],cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
put(OUT/'driver-state.json',{'pid':os.getpid(),'gateway_pid':proc.pid,'port':port,'status':'calibrating','runtime_dir':str(RUNTIME.relative_to(REPO))})
try:
 for _ in range(40):
  if proc.poll() is not None:raise RuntimeError('Evaluation Gateway exited; see gateway.log')
  try:health=api('/health');break
  except requests.RequestException:time.sleep(1)
 else:raise RuntimeError('Gateway health timeout')
 emit('gateway_ready',port=port,provider='deepseek',model='deepseek-flash')
 put(OUT/'health.json',health)
 results=[]
 for tid in ('K01','K02','K03'):results.append(run_task(tid,DATASET/'calibration'/tid,1200,True))
 durations=[t['wall_seconds'] for r in results for t in r['turns']]
 if any(t['timed_out'] for r in results for t in r['turns']):raise RuntimeError('Calibration timed out; cannot freeze formal budget')
 budget=max(600,math.ceil(3*max(durations)/60)*60)
 put(OUT/'calibration-complete.json',{'completed_at':now(),'durations':durations,'per_turn_timeout_seconds':budget,'status':'awaiting_judge_calibration'})
 emit('calibration_execution_complete',budget=budget)
 while not (OUT/'formal-start.json').exists():time.sleep(2)
 batch=read(OUT/'batch.json');assert batch['judge']['calibration_completed'];assert batch['execution']['per_turn_timeout_seconds']==budget
 put(OUT/'driver-state.json',{'pid':os.getpid(),'gateway_pid':proc.pid,'port':port,'status':'formal_running','runtime_dir':str(RUNTIME.relative_to(REPO))})
 for t in read(DATASET/'manifest.json')['tasks']:
  run_task(t['task_id'],DATASET/'tasks'/t['task_id'],budget)
 put(OUT/'execution-complete.json',{'completed_at':now(),'tasks':30,'turns':50,'status':'awaiting_judgement_and_review'})
 emit('all_formal_tasks_executed',tasks=30,turns=50)
except BaseException as e:
 put(OUT/'driver-error.json',{'at':now(),'type':type(e).__name__,'message':str(e)[:600]})
 emit('driver_error',type=type(e).__name__,message=str(e)[:300]);raise
finally:
 if proc.poll() is None:
  proc.terminate()
  try:proc.wait(timeout=20)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
 log.close()
