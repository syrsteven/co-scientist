"""Loopback-only page/API persistence using explicitly OFFLINE remote responses."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = r"""
import json,runpy,sys,urllib.request
from co_scientist_next.store import Store
from co_scientist_next.responses_model import OpenAIResponses
from co_scientist_next.generation import GenerationService
from co_scientist_next.workspace import make_server
h=runpy.run_path(sys.argv[2]); w=h['Wire']([h['envelope'](),TimeoutError('OFFLINE query disconnect'),h['envelope']('in_progress')])
urllib.request.build_opener=lambda *_:w
class OfflineResponses(OpenAIResponses):
 execution_mode='development_fixture'
with Store(sys.argv[1]) as s:
 a=OfflineResponses(h['CONFIG'],h['SECRET'],authorized=True)
 g=GenerationService(s,a)
 if not s.rows('SELECT id FROM runs'):
  run,_,req=h['H']['prepared'](s);g.submit(run,'offline-remote-http',req)
 else:run=s.one('SELECT run_id FROM generation_actions')['run_id']
 server=make_server(s,development_test=True,generation_adapter=a)
 print(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'run':run}),flush=True)
 server.serve_forever()
"""
CLIENT = r"""
import json,sys,urllib.request
v=json.loads(sys.argv[1]);url=v['url'];path='/api/generation?run_id='+v['run']
def api(path,data=None):
 req=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
req={'request_id':'offline-remote-http'}
if sys.argv[2]=='initial':
 a=api('/api/generation/execute',req)['actions'][0]
 assert a['remote']['status']=='queued' and len(a['attempts'])==1
 a=api('/api/generation/query',req)['actions'][0]
 assert a['remote']['latest_query']['outcome']=='query_failed' and len(a['attempts'])==2
else:
 a=api(path)['actions'][0]
 assert a['task_status']=='waiting_remote' and a['remote']['response_id']=='resp_OFFLINE1'
 assert a['remote']['latest_query']['outcome']=='query_failed' and len(a['attempts'])==2
for _ in range(3):
 a=api(path)['actions'][0]
 assert len(a['attempts'])==2 and a['result'] is None
with urllib.request.urlopen(url+'/generation.js') as r:
 js=r.read().decode();assert '/api/generation/query' in js and '提交结果不确定' in js and '已等待' in js
print('OFFLINE page API: saved ID/query error survive refresh/restart; no create or query on GET')
"""


def test_remote_page_query_persistence_and_restart(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for step in ("initial", "restart"):
        p = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SERVER,
                str(tmp_path / "page.sqlite"),
                str(ROOT / "tests/next/test_responses_background.py"),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = p.stdout.readline().strip()
            assert line, p.stderr.read()
            data = json.loads(line)
            result = subprocess.run(
                [sys.executable, "-c", CLIENT, json.dumps(data), step],
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            assert "no create or query on GET" in result.stdout
        finally:
            p.terminate()
            p.wait(timeout=10)
