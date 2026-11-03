from pathlib import Path
from datetime import datetime
from collections import Counter
import json,math,statistics,sys
REPO=Path(__file__).resolve().parents[2];BATCH=sys.argv[1];OUT=REPO/'evaluation/e2e-30-runs'/BATCH
def j(p):return json.loads(p.read_text())
def put(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def ci(s,n):
 z=1.959963984540054;p=s/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
 return [round(100*(c-h),2),round(100*(c+h),2)]
executions={p.parent.name:j(p) for p in sorted((OUT/'tasks').glob('*/execution.json'))}
verdicts={p.parent.name:j(p) for p in sorted((OUT/'tasks').glob('*/verdict.json'))}
final={v['task_id']:v for v in j(OUT/'final-status.json')} if (OUT/'final-status.json').exists() else {}
counts={};pending=[];rows=[];turns=[];tokens=[]
for c in 'ABC':
 current=[]
 for i in range(1,11):
  tid=f'{c}{i:02}';v=verdicts.get(tid);e=executions.get(tid)
  resolved=final.get(tid,{}).get('final_verdict');status=resolved if resolved else 'pending'
  if status=='pending':pending.append(tid)
  current.append(status)
  if e and e['execution_status']=='completed':
   wall=sum(t['wall_seconds'] for t in e['turns']);usage=sum(t['usage']['total_tokens'] for t in e['turns']);tokens.append(usage);turns+=e['turns']
  else:wall=usage=None
  reason=v['primary_failure'] if v else None
  critical=sum(x['status']=='pass' for x in v['checks']) if v else None
  rows.append({'task_id':tid,'final':status,'initial':v['verdict'] if v else 'not_judged','primary_failure':reason,'critical_passed':critical,'critical_total':len(v['checks']) if v else None,'wall_seconds':wall,'provider_total_tokens':usage,'usage_complete':all(t['usage_complete'] for t in e['turns']) if e else False,'evidence':f'tasks/{tid}/execution.json','judgement':f'tasks/{tid}/verdict.json','review':final.get(tid,{}).get('review')})
 count=Counter(current);s=count['pass'];counts[c]={'planned':10,'passed':s,'failed':count['fail'],'pending':count['pending'],'success_rate_percent':s*10 if not count['pending'] else None,'wilson_95_percent':ci(s,10) if not count['pending'] else None}
s=sum(v['passed'] for v in counts.values());f=sum(v['failed'] for v in counts.values());fully_resolved=not pending and len(verdicts)==30 and (OUT/'review-complete.json').exists()
judge_usage=Counter();judge_calls=0
for p in OUT.rglob('*-events.jsonl'):
 if not any(part in ('calibration','judge-calibration','initial-mixed-provenance-packet') for part in p.relative_to(OUT).parts):
  for line in p.read_text().splitlines():
   try:event=json.loads(line)
   except ValueError:continue
   if event.get('type')=='turn.completed':judge_usage.update({k:v for k,v in event.get('usage',{}).items() if isinstance(v,int)});judge_calls+=1
summary={'batch_id':BATCH,'updated_at':datetime.now().astimezone().isoformat(),'status':'complete' if fully_resolved else 'incomplete','formal_tasks':30,'executions_completed':sum(e['execution_status']=='completed' for e in executions.values()),'initial_judgements':len(verdicts),'categories':counts,'total':{'passed':s,'failed':f,'pending':len(pending),'success_rate_percent':round(s/30*100,2) if fully_resolved else None,'wilson_95_percent':ci(s,30) if fully_resolved else None},'pending_tasks':pending,'formal_provider_usage':{'total_tokens':sum(tokens),'completed_turns':len(turns),'attempts':sum(t['provider_attempt_count'] for t in turns),'internal_retries':sum(t['internal_retry_count'] for t in turns),'missing_usage_turns':sum(not t['usage_complete'] for t in turns)},'judge_usage':{'calls_with_usage':judge_calls,**dict(judge_usage)},'rows':rows}
put(OUT/'summary.json',summary)
lines=['# Figura E2E-30 正式首测报告','',f'批次：{BATCH}；状态：{summary["status"]}。', '', '只有完整执行、评分及复核后才报告完整成功率。校准任务不计入分母。','', '| 类别 | 计划 | 成功 | 失败 | 未裁定 | 成功率 | 95% Wilson CI |','|---|---:|---:|---:|---:|---|---|']
for c,label in [('A','图表分析'),('B','图表构建'),('C','多轮修改')]:
 v=counts[c];lines.append(f'| {label} | 10 | {v["passed"]} | {v["failed"]} | {v["pending"]} | {str(v["success_rate_percent"])+"%" if v["success_rate_percent"] is not None else "待完成"} | {v["wilson_95_percent"] or "待完成"} |')
lines+=['',f'整体：成功 {s}，失败 {f}，未裁定 {len(pending)}；'+(f'成功率 {summary["total"]["success_rate_percent"]}%，95% CI {summary["total"]["wilson_95_percent"]}。' if fully_resolved else '完整成功率尚未形成。'),'', '| 任务 | 最终结论 | 初评 | 首要原因 | 关键项（初评） | 耗时/秒 | Provider Token | 复核 |','|---|---|---|---|---|---:|---:|---|']
for r in rows:lines.append(f'| [{r["task_id"]}](tasks/{r["task_id"]}/execution.json) | {r["final"]} | {r["initial"]} | {r["primary_failure"] or "—"} | {r["critical_passed"]}/{r["critical_total"]} | {r["wall_seconds"]} | {r["provider_total_tokens"]} | {r["review"] or "—"} |')
lines+=['','## 资源和范围','',f'已完成正式轮次 {len(turns)}；Provider 总 Token {sum(tokens)}；内部重试 {summary["formal_provider_usage"]["internal_retries"]}。Token 包含所有可获得 usage 的物理 attempt，缺失 usage 的轮次为 {summary["formal_provider_usage"]["missing_usage_turns"]}。Codex judge 用量另存 summary.json，不与 Figura 用量合并。','', '条件：deepseek-flash，当前生产上下文配置 200,000 tokens、thinking 开启；Codex gpt-6.1-sol 按题独立上下文评判。正式单轮超时 600 秒。详见 batch.json。','', '本结果属于固定30题（各类10题）的单次执行；不是生产分布、开放域准确率或浏览器 UI 全流程结果。4张真实来源图均来自 OWID，另有6张合成分析图。参考图片与实际产物严格区分。','', '复核覆盖全部初评失败/待复核任务，加各类通过任务20%向上取整的固定随机样本。完整选择及分歧见 review-selection.json / final-status.json。']
if tokens:lines+=['',f'任务 Provider Token 中位数 {statistics.median(tokens)}，范围 {min(tokens)}—{max(tokens)}。']
walls=[r['wall_seconds'] for r in rows if r['wall_seconds'] is not None]
if walls:lines+=['',f'任务执行耗时中位数 {statistics.median(walls):.2f} 秒，范围 {min(walls):.2f}—{max(walls):.2f} 秒。']
(OUT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:summary[k] for k in ('status','executions_completed','initial_judgements','total')},ensure_ascii=False))
