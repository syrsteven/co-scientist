"""Real local HTTP acceptance in child processes; parent suite remains socket-denied."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def start_server(tmp_path):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "co_scientist_next.workspace",
            "--db",
            str(tmp_path / "http.sqlite"),
            "--port",
            "0",
            "--development-test",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = process.stdout.readline().split(" | ")[0].strip()
    assert url.startswith("http://127.0.0.1:"), process.stderr.read()
    return process, url


CLIENT = r"""
import json,sys,urllib.request,urllib.error
url=sys.argv[1]
def api(path,data=None):
 request=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,
  headers={'Content-Type':'application/json'},method='POST' if data is not None else 'GET')
 with urllib.request.urlopen(request,timeout=10) as r:return json.load(r)
assert api('/api/config')['development_test'] is True
saved=api('/api/brief',{'name':'HTTP真实持久化','brief':{'question':'原始问题','hard_constraints':['保留条件'],'preferences':[],'background':'用户背景'}})
policy={'id':'explicit-test','version':'1','text':'Explicit policy; no implicit default.'}
run=api('/api/runs',{'revision_id':saved['revision_id'],'policy':policy})['run_id']
ready=api('/api/run?id='+run)
assert ready['run']['status']=='ready'
assert ready['usage']['input_tokens']['unknown_attempts']==0
snapshot=api('/api/execute',{'run_id':run})
assert snapshot['run']['status']=='awaiting_background'
assert len(snapshot['tasks'])==2
before=snapshot['usage']
for i in range(3):assert api('/api/run?id='+run)['usage']==before
api('/api/brief',{'project_id':saved['project_id'],'previous_revision_id':saved['revision_id'],
 'brief':{'question':'新草稿问题','hard_constraints':[]}})
assert api('/api/run?id='+run)['fixed_brief']['question']=='原始问题'
try:
 req=urllib.request.Request(url+'/api/runs',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://external.invalid'},method='POST')
 urllib.request.urlopen(req,timeout=10)
 raise AssertionError('Cross-origin write should fail')
except urllib.error.HTTPError as e:assert e.code==400
print(json.dumps({'run_id':run,'usage':before}))
"""


def test_page_api_persistence_readonly_get_and_restart(tmp_path):
    process, url = start_server(tmp_path)
    try:
        result = subprocess.run(
            [sys.executable, "-c", CLIENT, url],
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        saved = json.loads(result.stdout)
    finally:
        process.terminate()
        process.wait(timeout=10)
    process, url = start_server(tmp_path)
    try:
        code = "import json,sys,urllib.request;v=json.load(urllib.request.urlopen(sys.argv[1]));assert v['run']['status']=='awaiting_background';assert v['fixed_brief']['question']=='原始问题';print(json.dumps(v['usage']))"
        result = subprocess.run(
            [sys.executable, "-c", code, url + "/api/run?id=" + saved["run_id"]],
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        assert json.loads(result.stdout) == saved["usage"]
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_restart_and_get_do_not_recover_unfinished_goal_without_explicit_post(tmp_path):
    code = r"""
import json,os,sys
import co_scientist_next.goal as goal
from co_scientist_next.store import Store
with Store(sys.argv[1]) as store:
 p=store.create_project('Unfinished goal');b=store.revise_brief(p,{'question':'原始研究问题'})
 service=goal.GoalSlice(store,goal.DevelopmentAdapter(),development_test=True)
 run=service.create_run(b,goal.DEVELOPMENT_POLICY)
 print(run,flush=True)
 goal.parse_prepare_v3=lambda *args:os._exit(78)
 service.execute(run)
"""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    crash = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "http.sqlite")],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert crash.returncode == 78, crash.stderr
    run_id = crash.stdout.strip()
    process, url = start_server(tmp_path)
    try:
        client = r"""
import json,sys,urllib.request
url,run=sys.argv[1:]
for _ in range(3):
 with urllib.request.urlopen(url+'/api/run?id='+run) as r:value=json.load(r)
 assert value['run']['status']=='running'
 assert value['usage']['input_tokens']['unknown_attempts']==1
req=urllib.request.Request(url+'/api/execute',data=json.dumps({'run_id':run,'recover':True}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as r:value=json.load(r)
assert value['run']['status']=='awaiting_background'
assert value['usage']['input_tokens']['unknown_attempts']==2
print('GET did not recover or send; explicit POST recovered and replayed')
"""
        result = subprocess.run(
            [sys.executable, "-c", client, url, run_id],
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        assert "explicit POST" in result.stdout
    finally:
        process.terminate()
        process.wait(timeout=10)
