"""Check the same failures against HEAD plus the user's pre-existing test edits."""
import io, os, re, subprocess, sys, tarfile, tempfile
from pathlib import Path
root=Path.cwd(); report=root/'evaluation/multimodal-tool-results'
failed=re.findall(r'^FAILED (\S+)', (report/'all-tests.txt').read_text(), re.MULTILINE)
with tempfile.TemporaryDirectory(prefix='figura-baseline-') as temporary:
    baseline=Path(temporary)
    archive=subprocess.run(['git','archive','HEAD'],check=True,capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream: stream.extractall(baseline,filter='data')
    for name in ['test_evaluation_workbench.py','test_real_chart_diagnostic.py','test_trace.py']:
        (baseline/'tests'/name).write_bytes((root/'tests'/name).read_bytes())
    environment=dict(os.environ); environment['PYTHONPATH']=str(baseline/'src')
    result=subprocess.run([sys.executable,'-m','pytest','-q','--tb=short',*failed],cwd=baseline,env=environment,text=True,capture_output=True)
    output=result.stdout+'\n'+result.stderr
    (report/'baseline-failures.txt').write_text(output)
    baseline_failed=re.findall(r'^FAILED (\S+)',output,re.MULTILINE)
    print({'current_failures':len(failed),'baseline_failures':len(baseline_failed),
           'same_failures':set(failed)==set(baseline_failed),'exit_code':result.returncode})
