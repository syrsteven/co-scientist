"""V6 local HTTP boundaries; no provider sends, no keys loaded."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_role_configs_coexist_opt_in_annotations_export_and_history(tmp_path):
    # An historical database is created once, then consumed strictly read-only.
    import hashlib

    from co_scientist_next.store import Store

    history = tmp_path / "history.sqlite"
    with Store(history) as s:
        p = s.create_project("Historical")
        b = s.revise_brief(p, {"question": "Historical immutable question"})
        s.create_run(b, ["OFFLINE"], policy_ref="OFFLINE")
    before = hashlib.sha256(history.read_bytes()).hexdigest()
    command = [
        sys.executable,
        "-m",
        "co_scientist_next.workspace",
        "--db",
        str(tmp_path / "stage.sqlite"),
        "--port",
        "0",
        "--development-test",
        "--require-goal-test-opt-in",
        "--responsive",
        "--history-db",
        str(history),
        "--reading-model-config",
        "docs/workbench/reading-model.json",
        "--generation-responses-config",
        "docs/workbench/responses-model.json",
        "--review-responses-config",
        "docs/workbench/responses-model.json",
        "--allow-development-review-policy",
    ]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    env.pop("OPENAI_API_KEY", None)
    process = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        url = process.stdout.readline().split(" | ")[0].strip()
        assert url.startswith("http://127.0.0.1:"), process.stderr.read()
        client = r"""
import json,sys,urllib.request,urllib.error
url=sys.argv[1]
def api(path,data=None):
 req=urllib.request.Request(url+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
c=api('/api/config')
assert c['goal_test_opt_in_required']
for key in ['reading_model','generation_model','review_model']:
 assert c[key]['model']=='gpt-6.1-sol'
 assert not c[key]['credential_configured']
assert 'api_key' not in json.dumps(c)
b=api('/api/brief',{'name':'Arbitrary new question','brief':{'question':'Why do salt conditions alter roots?'}})
try:
 api('/api/runs',{'revision_id':b['revision_id'],'policy':c['example_policy']})
 raise AssertionError('Missing explicit test choice must fail')
except urllib.error.HTTPError as e:assert e.code==400
r=api('/api/runs',{'revision_id':b['revision_id'],'policy':c['example_policy'],'goal_test_mode':'deterministic_development'})['run_id']
t=api('/api/annotations?run_id='+r)['targets'][0]
a=api('/api/annotations',{'submission_id':'http-assessment-single','run_id':r,'target_kind':t['kind'],'target_ref':t['ref'],'target_sha256':t['sha256'],'category':'note','note':'Independent human opinion','observations':{}})
assert api('/api/export?run_id='+r)['human_annotations'][0]['note']=='Independent human opinion'
for _ in range(3):
 assert api('/api/run?id='+r)['usage']['input_tokens']['unknown_attempts']==0
 assert api('/api/history')['read_only'] is True
with urllib.request.urlopen(url+'/history.html') as res:
 assert "connect-src 'none'" in res.headers['Content-Security-Policy']
with urllib.request.urlopen(url+'/') as res:
 text=res.read().decode();assert 'allow-scripts allow-downloads' in text;assert 'allow-same-origin' not in text
print(r)
"""
        result = subprocess.run(
            [sys.executable, "-c", client, url],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    finally:
        process.terminate()
        process.wait(timeout=10)
    # Another process reads persisted annotations after a full server restart.
    process = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        url = process.stdout.readline().split(" | ")[0].strip()
        run_id = result.stdout.strip()
        check = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys,urllib.request; d=json.load(urllib.request.urlopen(sys.argv[1])); assert d['human_annotations'][0]['note']=='Independent human opinion'; assert d['attempts']==[]",
                url + "/api/export?run_id=" + run_id,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert check.returncode == 0, check.stderr
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert hashlib.sha256(history.read_bytes()).hexdigest() == before


def test_responsive_get_does_not_wait_for_model_or_send_again(tmp_path):
    # Socket work remains in subprocess, preserving the suite's parent socket guard.
    code = r"""
import json,sys,threading,time,urllib.request
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server
from co_scientist_next.goal import DEVELOPMENT_POLICY
with Store(sys.argv[1],http_threads=True) as store:
 server=make_server(store,development_test=True,responsive=True)
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 url='http://127.0.0.1:'+str(server.server_port)
 def api(path,data=None):
  req=urllib.request.Request(url+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)
 b=api('/api/brief',{'name':'OFFLINE','brief':{'question':'An arbitrary question'}})
 r=api('/api/runs',{'revision_id':b['revision_id'],'policy':DEVELOPMENT_POLICY})['run_id']
 # Hold a real Goal operation inside its adapter until after GET returns.
 from co_scientist_next.goal import DevelopmentAdapter
 entered=threading.Event();release=threading.Event()
 original=DevelopmentAdapter.__call__
 def slow(self,request):
  entered.set();assert release.wait(5);return original(self,request)
 DevelopmentAdapter.__call__=slow
 errors=[]
 def execute():
  try:api('/api/execute',{'run_id':r})
  except Exception as exc:errors.append(type(exc).__name__)
 worker=threading.Thread(target=execute);worker.start();assert entered.wait(5)
 start=time.monotonic()
 assert api('/api/run?id='+r)['run']['status']=='running'
 assert time.monotonic()-start<2
 assert worker.is_alive()
 import urllib.error
 try:
  api('/api/execute',{'run_id':r})
  raise AssertionError('Concurrent writer must be rejected')
 except urllib.error.HTTPError as e:assert e.code==409
 release.set();worker.join(5);assert not errors
 assert api('/api/run?id='+r)['run']['status']=='awaiting_background'
 server.shutdown();server.server_close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "responsive.sqlite")],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
