"""Loopback-only fixture preview/confirm/refresh; never actual model execution."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = r"""
import json,runpy,sys
h=runpy.run_path(sys.argv[2])
from co_scientist_next.workspace import make_server
with h['Store'](sys.argv[1]) as s:
 if not s.rows('SELECT id FROM runs'):
  run,bg,a,request=h['source_fixture'](s)
 else:
  a=s.one("SELECT * FROM generation_actions WHERE request_id='offline-original-direct'")
  old=json.loads(a['request']);run=a['run_id']
  attempts=s.rows('SELECT id FROM attempts WHERE task_id=? ORDER BY ordinal',(a['task_id'],))
  request={'source_task_id':a['task_id'],'source_attempt_ids':[p['id'] for p in attempts],'seed_id':old['seed_id'],'packet_ref':old['packet_ref'],'readiness_ref':old['readiness_ref'],'request_id':'offline-migrated-direct','candidate_id':'planned-p08-direct-responses'}
 server=make_server(s,development_test=True,generation_adapter=h['OpenAIResponses'](h['CONFIG']))
 print(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'run':run,'request':request,'acks':h['ACK']}),flush=True)
 server.serve_forever()
"""
CLIENT = r"""
import json,sys,urllib.request,urllib.error
v=json.loads(sys.argv[1]);url=v['url'];base='/api/generation';run=v['run'];request=v['request']
def api(path,data=None):
 req=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
def snapshot():return api(base+'?run_id='+run)
if sys.argv[2]=='first':
 original=snapshot();assert len(original['actions'])==1
 p=api(base+'/migration/preview',{'run_id':run,'request':request})
 assert snapshot()==original
 data={'run_id':run,'request':request,'preview_hash':p['preview_hash'],'acknowledgements':v['acks']}
 try:api(base+'/migration/confirm',{**data,'acknowledgements':{}})
 except urllib.error.HTTPError as e:assert e.code==400
 else:raise AssertionError('Implicit migration accepted')
 created=api(base+'/migration/confirm',data)
 assert api(base+'/migration/confirm',data)==created
saved=snapshot();old,new=saved['actions']
assert old['task_status']=='blocked' and all(p['status']=='uncertain' for p in old['attempts'])
assert new['task_status']=='ready' and not new['attempts'] and not new['result']
assert new['migration']['source_task_id']==old['task_id'] and not new['migration']['execution_authorization']
for _ in range(3):assert snapshot()==saved
try:api(base+'/execute',{'request_id':request['request_id']})
except urllib.error.HTTPError as e:assert e.code==400
else:raise AssertionError('Migration used as paid authorization')
assert snapshot()==saved
with urllib.request.urlopen(url+'/generation.js') as response:
 js=response.read().decode();assert '仅创建一个关联任务' in js and '模型尚未运行' in js
print('OFFLINE migration API: preview read-only; one successor; no send on confirm/refresh/restart')
"""


def test_migration_preview_confirmation_persistence_and_no_execute(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for stage in ("first", "restart"):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SERVER,
                str(tmp_path / "migration-http.sqlite"),
                str(ROOT / "tests/next/test_generation_migration.py"),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = process.stdout.readline().strip()
            assert line, process.stderr.read()
            value = json.loads(line)
            completed = subprocess.run(
                [sys.executable, "-c", CLIENT, json.dumps(value), stage],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=35,
            )
            assert "no send" in completed.stdout
        finally:
            process.terminate()
            process.wait(timeout=10)
