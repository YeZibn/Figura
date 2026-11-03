from pathlib import Path
from datetime import datetime
import json,hashlib,subprocess,importlib.metadata
from dotenv import load_dotenv
from figura.providers.config import ProviderSettings
from figura.providers.models import ProviderId
REPO=Path(__file__).resolve().parents[2];DATA=REPO/'evaluation/e2e-30-v1';OUT=REPO/'evaluation/e2e-30-runs/20261102-正式首测-01'
def j(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(p):
 h=hashlib.sha256()
 for f in sorted(p.rglob('*')):
  if f.is_file() and f.suffix in ('.py','.md','.json'):h.update(str(f.relative_to(p)).encode());h.update(f.read_bytes())
 return h.hexdigest()
load_dotenv(REPO/'.env');profile=ProviderSettings.from_env().profiles[ProviderId.DEEPSEEK]
for t,expected in [('K01','pass'),('K02','fail'),('K03','fail')]:
 v=j(OUT/'judge-calibration'/t/'mock-verdict.json');assert v['content_verdict']==expected and v['png_viewed']
for t in ('K01','K02','K03'):
 v=j(OUT/'calibration'/t/'verdict.json');assert v['verdict'] in ('pass','fail'),(t,v['verdict']);assert v['judge']['actual_png_viewed']
batch=j(DATA/'templates/batch.json');cal=j(OUT/'calibration-complete.json')
batch.update(batch_id=OUT.name,status='formal_running',started_at=datetime.now().astimezone().isoformat(),dataset_checksums_sha256=sha(DATA/'checksums.json'),manifest_sha256=sha(DATA/'manifest.json'))
batch['code'].update(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),dirty_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--binary','HEAD'],cwd=REPO)).hexdigest(),source_sha256=tree(REPO/'src/figura'),prompt_sha256=tree(REPO/'src/figura/agent/prompting/assets'),tool_registry_version='figura-web-v11',dependency_versions={k:importlib.metadata.version(k) for k in ('matplotlib','numpy','requests','jsonschema')})
batch['execution'].update(provider='deepseek',model='deepseek-flash',context_capacity_tokens=profile.context_window_tokens,per_turn_timeout_seconds=cal['per_turn_timeout_seconds'],calibration_durations_seconds=cal['durations'],sampling_parameters={'thinking_mode':profile.thinking_mode,'reasoning_effort':profile.reasoning_effort,'max_completion_tokens':profile.max_completion_tokens},uncontrolled_parameters=['Provider 模型服务端更新和随机采样；当前生产接口未固定 seed/temperature'])
batch['judge'].update(model='gpt-6.1-sol',prompt_sha256=sha(DATA/'judge/prompt.md'),calibration_completed=True)
batch['harness']={'scripts':{str(p.relative_to(REPO)):sha(p) for p in sorted((REPO/'evaluation/e2e-30-execution').glob('*.py'))},'codex_cli_version':subprocess.check_output(['codex','--version'],text=True).strip(),'isolation':'fresh ephemeral read-only Codex invocation per task; images and JSON supplied explicitly'}
batch['notes']=['全部正式输入与评分规则均沿用已准备 v1 文件，完整摘要校验通过。','正式运行前校准修复了证据包 mock-only 来源标记误混入真实校准包；首次K01判定保留于 initial-mixed-provenance-packet，未改答案或评分规则。','K02/K03 真实校准任务内容通过与人工错误夹具失败是两套独立证据，不混作主成绩。']
(OUT/'batch.json').write_text(json.dumps(batch,ensure_ascii=False,indent=2)+'\n')
(OUT/'formal-start.json').write_text(json.dumps({'authorized_by':'user: 没问题开始吧','calibration_verified':True,'at':batch['started_at']},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'batch_id':OUT.name,'provider':'deepseek','model':'deepseek-flash','judge':'gpt-6.1-sol','timeout':cal['per_turn_timeout_seconds'],'formal_started':True},ensure_ascii=False))
