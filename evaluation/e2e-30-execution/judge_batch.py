"""Independent Codex CLI judge calls for the user-authorized evaluation."""
from __future__ import annotations
import json,os,shutil,subprocess,sys,time
from pathlib import Path
from jsonschema import Draft202012Validator

REPO=Path(__file__).resolve().parents[2]
DATASET=REPO/'evaluation/e2e-30-v1'
BATCH=sys.argv[1];MODE=sys.argv[2];TID=sys.argv[3] if len(sys.argv)>3 else None
OUT=REPO/'evaluation/e2e-30-runs'/BATCH
MODEL='gpt-6.1-sol'
def read(p):return json.loads(p.read_text())
def put(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(tid,prompt,images,output):
 output.parent.mkdir(parents=True,exist_ok=True)
 packet=Path('/private/tmp')/('figura-e2e30-judge-'+BATCH)/MODE/tid
 packet.mkdir(parents=True,exist_ok=True)
 args=['codex','exec','--ephemeral','--ignore-user-config','--sandbox','read-only','--skip-git-repo-check','--cd',str(packet),'--model',MODEL,'--json','--output-last-message',str(output)]
 for i,p in enumerate(images):
  q=packet/f'image-{i+1:02}.png';shutil.copyfile(p,q);args+=['--image',str(q)]
 args+=['-']
 (output.parent/(output.stem+'-prompt.txt')).write_text(prompt)
 with (output.parent/(output.stem+'-events.jsonl')).open('w') as stdout,(output.parent/(output.stem+'-stderr.log')).open('w') as stderr:
  started=time.monotonic();p=subprocess.run(args,input=prompt,text=True,stdout=stdout,stderr=stderr,timeout=1200)
 if p.returncode:raise RuntimeError(f'Codex judge exit={p.returncode}; inspect {output.stem}-stderr.log')
 text=output.read_text().strip()
 if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
 obj=json.loads(text);put(output,obj)
 put(output.with_name(output.stem+'-invocation.json'),{'model':MODEL,'wall_seconds':round(time.monotonic()-started,3),'context':'new ephemeral Codex invocation','mode':MODE,'task_id':tid,'attached_images':[str(p.relative_to(REPO)) for p in images]})
 print(json.dumps({'task_id':tid,'mode':MODE,'verdict':obj.get('verdict',obj.get('content_verdict'))},ensure_ascii=False),flush=True)
 return obj

if MODE=='mock-calibration':
 ids=[TID] if TID else ['K01','K02','K03']
 for tid in ids:
  src=DATASET/'calibration'/tid;gold=read(src/'judge-only/answer-key.json');mock=src/'judge-only/mock-evidence'
  content={p.name:(read(p) if p.suffix=='.json' else p.read_text()) for p in mock.iterdir() if p.suffix in ('.json','.txt') and p.name!='provenance.json'}
  imgs=sorted(mock.glob('*.png'))
  if not imgs:imgs=[src/'agent-input/chart.png']
  prompt='你是独立 Codex 内容评判官。这是正式集外的人工构造校准夹具，不是真实 Run，不检查 durable commit；只检查内容正确性。夹具标签尚未提供。请实际查看附图、对照固定用户要求与参考答案，找出系列归属错误或非目标数据破坏。不能修复输出，不能上网或读取本题之外文件，不使用任何工具。只返回JSON：task_id、content_verdict(pass或fail)、critical_errors(字符串数组)、png_viewed(布尔)、reason(简短证据)。\n用户对话：'+json.dumps(read(src/'agent-input/conversation.json'),ensure_ascii=False)+'\n参考答案：'+json.dumps(gold,ensure_ascii=False)+'\n人工实际输出内容：'+json.dumps(content,ensure_ascii=False)+'\n图片按顺序：'+json.dumps([p.name for p in imgs],ensure_ascii=False)
  obj=call(tid,prompt,imgs,OUT/'judge-calibration'/tid/'mock-verdict.json')
  expected=read(src/'judge-only/expected-calibration.json')['content_verdict']
  assert obj['content_verdict']==expected and obj['png_viewed'],(tid,obj,expected)
else:
 calibration=MODE=='real-calibration'
 ids=[TID] if TID else [f'{c}{i:02}' for c in 'ABC' for i in range(1,11)]
 for tid in ids:
  source=DATASET/('calibration' if calibration else 'tasks')/tid
  actual=OUT/('calibration' if calibration else 'tasks')/tid
  execution=read(actual/'execution.json');assert execution['execution_status']=='completed'
  output=actual/('review-independent.json' if MODE=='review' else 'verdict.json')
  if output.exists():continue
  packet={'task_id':tid,'batch_id':BATCH,'conversation':read(source/'agent-input/conversation.json'),'answer_key':read(source/'judge-only/answer-key.json'),'execution':execution,'turn_evidence':[]}
  if calibration:
   marker=packet['answer_key'].pop('fixture_mode',None)
   packet['reference_packet_note']={'removed_mock_fixture_marker':marker,'scope':'该标记只描述单独的人工 mock-evidence；本包 actual execution 来自真实 Gateway Run，并非人工夹具。仅规范化来源标记，未修改答案或评分项。'}
  images=[]
  if (source/'agent-input/chart.png').exists():images.append(source/'agent-input/chart.png')
  for turn in execution['turns']:
   d=actual/f'turn-{turn["turn"]:02}'
   entry={'turn':turn['turn'],'evidence':read(d/'evidence.json'),'answer':(d/'final-answer.txt').read_text(),'tool_overview':read(d/'tool-overview.json'),'figures':{p.name:read(p) for p in sorted(d.glob('figure-*.json'))}}
   packet['turn_evidence'].append(entry)
   images+=sorted(d.glob('render-*.png'))
  if tid=='B08':packet['visual_reference_note']=(source/'judge-only/reference-visual-note.md').read_text()
  packet['image_order']=[str(p.relative_to(REPO)) for p in images]
  prompt=(DATASET/'judge/prompt.md').read_text()+'\n\n执行协议：\n'+(DATASET/'protocol.md').read_text()+'\n\n输出JSON结构（严格遵守；覆盖每个check ID；model='+MODEL+'）：\n'+(DATASET/'judge/verdict.schema.json').read_text()+'\n\n以下为本题唯一的冻结判分数据与实际证据：\n'+json.dumps(packet,ensure_ascii=False)+'\n\n全部实际图片已按 image_order 附上。不要读取其他任务或参考 PNG，不需要调用工具，不修复内容，只进行独立判分。'
  obj=call(tid,prompt,images,output)
  Draft202012Validator(read(DATASET/'judge/verdict.schema.json')).validate(obj)
  assert obj['task_id']==tid and obj['batch_id']==BATCH
  assert sorted(c['id'] for c in obj['checks'])==sorted(c['id'] for c in packet['answer_key']['checks'])
