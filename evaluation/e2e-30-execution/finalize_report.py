from pathlib import Path
from datetime import datetime
from collections import Counter
import hashlib,json,subprocess,sys,zipfile
REPO=Path(__file__).resolve().parents[2];BATCH=sys.argv[1];OUT=REPO/'evaluation/e2e-30-runs'/BATCH
def j(p):return json.loads(p.read_text())
def put(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert (OUT/'review-complete.json').exists(),'review still running'
states=j(OUT/'final-status.json')
for s in states:
 if s['requires_adjudication']:
  p=OUT/'adjudications'/f'{s["task_id"]}.json';assert p.exists(),s['task_id']
  a=j(p);assert a['resolved'] and a['rubric_changed'] is False and a['figura_rerun'] is False
  s.update(final_verdict=a['final_verdict'],requires_adjudication=False,adjudication=str(p.relative_to(OUT)))
assert len(states)==30 and all(s['final_verdict'] in ('pass','fail') for s in states)
put(OUT/'final-status.json',states)
subprocess.run([sys.executable,str(REPO/'evaluation/e2e-30-execution/validate_evidence.py'),BATCH],check=True)
subprocess.run([sys.executable,str(REPO/'evaluation/e2e-30-execution/summarize.py'),BATCH],check=True)
summary=j(OUT/'summary.json');assert summary['status']=='complete'
for row in summary['rows']:
 row['initial_primary_failure']=row['primary_failure']
 row['initial_critical_passed']=row['critical_passed']
 state=next(s for s in states if s['task_id']==row['task_id'])
 row['final_decision_ref']=state.get('adjudication','final-status.json')
 if row['final']=='pass':row['primary_failure']=None
 if state.get('adjudication'):
  decisive=j(OUT/'tasks'/row['task_id']/'review-independent.json')
  row['critical_passed']=sum(c['status']=='pass' for c in decisive['checks'])
put(OUT/'summary.json',summary)
batch=j(OUT/'batch.json')
if not (OUT/'batch-at-start.json').exists():put(OUT/'batch-at-start.json',batch)
batch.update(status='complete',completed_at=datetime.now().astimezone().isoformat());put(OUT/'batch.json',batch)
reviewed=[s for s in states if s['selected_for_review']]
review_meta={'reviewed':len(reviewed),'initial_review_same_task_verdict':sum(s['initial']==s['review'] for s in reviewed),'resolved_by_frozen_rule':[s['task_id'] for s in states if s.get('adjudication')],'not_a_judge_accuracy_estimate':True,'same_model_independent_contexts':True}
put(OUT/'review-summary.json',review_meta)
failures=[]
for s in states:
 if s['final_verdict']=='fail':
  v=j(OUT/'tasks'/s['task_id']/'verdict.json')
  failures.append({'task_id':s['task_id'],'primary_failure':v['primary_failure'],'failed_checks':[c for c in v['checks'] if c['status']=='fail'],'initial_verdict':f'tasks/{s["task_id"]}/verdict.json','review_verdict':f'tasks/{s["task_id"]}/review-independent.json'})
put(OUT/'failures.json',failures)
supp=['','## 失败证据与复核裁决','']
for f in failures:
 supp.append(f'- **{f["task_id"]}**（{f["primary_failure"]}）：'+'；'.join(c['reason'] for c in f['failed_checks'])+f' [初评]({f["initial_verdict"]}) / [复核]({f["review_verdict"]})。')
supp+=['',f'独立复核 {len(reviewed)} 题，其中 {review_meta["initial_review_same_task_verdict"]} 题任务结论一致。C06 的注释争议按冻结的空 note 等义例外裁决通过，[裁决记录](adjudications/C06.json)。原始初评与独立复核文件均保留；报告表格的“初评首要原因”和“关键项（初评）”不代表裁决后的最终结论。','', '初评和复核均为 Codex gpt-6.1-sol 的新独立上下文，未向复核者提供初评标签。这是同一模型下的复核一致性，不是人工标注的 judge 准确率。未为评分重跑任何正式 Figura 任务，未修改输入、标准答案、Prompt、工具或在线代码。']
# Optional diagnostic: how many modifications succeeded conditional on a clean baseline.
base_pass=[];conditional_pass=[]
for s in states:
 if not s['task_id'].startswith('C'):continue
 v=j(OUT/'tasks'/s['task_id']/'verdict.json')
 first=[c for c in v['checks'] if c['id'].startswith('T1-')]
 if first and all(c['status']=='pass' for c in first):
  base_pass.append(s['task_id'])
  if s['final_verdict']=='pass':conditional_pass.append(s['task_id'])
supp+=['',f'修改类补充诊断：首轮基线关键项通过 {len(base_pass)}/10；在这些基线任务中，最终完整任务通过 {len(conditional_pass)}/{len(base_pass)}。这项条件统计不替代修改类主指标。']
ops=[op for p in (OUT/'tasks').glob('*/execution.json') for t in j(p)['turns'] for op in t['compaction_operations']]
supp+=['',f'正式运行记录的压缩操作数：{len(ops)}。因此本批次不形成“压缩后正确性”的单独结论。','', '原始运行输入已逐字核对，30个Session、50个Run互不重复，43份实际Figure/PNG摘要匹配。详见 [证据校验](evidence-validation.json)。评测专用Gateway已退出，端口已释放；原有用户会话目录未用于本批次。']
report=OUT/'report.md';text=report.read_text().replace('首要原因 | 关键项（初评）','初评首要原因 | 关键项（初评）');report.write_text(text+'\n'.join(supp)+'\n')
put(OUT/'completed-harness-snapshot.json',{'scripts':{str(p.relative_to(REPO)):sha(p) for p in sorted((REPO/'evaluation/e2e-30-execution').glob('*.py'))},'note':'执行与判分脚本的冻结摘要仍见batch-at-start；其后添加的调度/汇总/校验脚本仅消费已有证据。'})
payload=[p for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ('result-checksums.json','gateway.log') and not p.name.endswith('-stderr.log')]
put(OUT/'result-checksums.json',{'algorithm':'sha256','files':{str(p.relative_to(OUT)):sha(p) for p in payload}})
archive=OUT.parent/(BATCH+'-results.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
 for p in payload+[OUT/'result-checksums.json']:z.write(p,str(Path(BATCH)/p.relative_to(OUT)))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print(json.dumps({'status':'complete','total':summary['total'],'categories':summary['categories'],'reviews':review_meta,'provider_usage':summary['formal_provider_usage'],'result_archive':str(archive),'archive_bytes':archive.stat().st_size},ensure_ascii=False))
