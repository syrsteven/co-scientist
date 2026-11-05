"""Loopback, isolated imported-real-candidate fixture. No real model or DB access."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = r"""
import sys,json
from pathlib import Path
from co_scientist_next.review_fixture import create_fixture
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server
from co_scientist_next.candidate_review_ops import DevelopmentReviewAdapter
p=Path(sys.argv[1])
if not p.exists():metadata=create_fixture(p,sys.argv[2])
with Store(p) as s:
 server=make_server(s,development_test=True,review_adapter=DevelopmentReviewAdapter(),development_review=True)
 run=s.one('SELECT id FROM runs')['id']
 print(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'run':run}),flush=True)
 server.serve_forever()
"""
CLIENT = r"""
import sys,json,urllib.request,urllib.error
v=json.loads(sys.argv[1]);base=v['url'];run=v['run']
def api(path,data=None):
 req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
path='/api/candidate-review?run_id='+run
if sys.argv[2]=='first':
 from co_scientist_next.candidate_review_ops import DEVELOPMENT_POLICY,DEVELOPMENT_DECISIONS,DEVELOPMENT_R0_POLICY
 ref='planned-p08-responses-migration-single'
 request={'operation':'P09','generation_ref':ref,'intended_use':'OFFLINE conceptual engineering','policy':DEVELOPMENT_POLICY,'decision_policy':DEVELOPMENT_DECISIONS}
 api('/api/candidate-review',{'run_id':run,'request_id':'offline-http-review09','request':request})
 api('/api/candidate-review/execute',{'request_id':'offline-http-review09'})
 api('/api/candidate-review',{'run_id':run,'request_id':'offline-http-review10','request':{'operation':'P10','generation_ref':ref,'ethics_ref':'offline-http-review09','policy':DEVELOPMENT_R0_POLICY}})
 api('/api/candidate-review/execute',{'request_id':'offline-http-review10'})
saved=api(path)
assert len(saved['actions'])==2 and all(a['result']['development'] for a in saved['actions'])
assert saved['actions'][1]['result']['artifact']['disposition']=='proceed_to_R1'
for _ in range(3):assert api(path)==saved
assert api('/api/run?id='+run)['run']['status']=='awaiting_r1'
with urllib.request.urlopen(base+'/candidate-review.js') as r:assert '下一步 R1 核查'.encode() in r.read()
for a in saved['actions']:
 raw=api('/api/candidate-review/attempt?attempt_id='+a['attempts'][0]['id'])
 assert json.loads(raw['request'])['operation']==a['operation']
api('/api/candidate-review/execute',{'request_id':'offline-http-review09'})
assert api(path)==saved
print('OFFLINE P09/P10 create/execute/replay/GET/restart persisted; no automatic sends')
"""


def test_review_page_api_restart_and_readonly_refresh(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for stage in ("first", "restart"):
        server = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SERVER,
                str(tmp_path / "fixture.sqlite"),
                str(ROOT / "docs/trials/p08-direct-responses-real"),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = server.stdout.readline().strip()
            assert line, server.stderr.read()
            result = subprocess.run(
                [sys.executable, "-c", CLIENT, line, stage],
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=45,
            )
            assert "no automatic sends" in result.stdout
        finally:
            server.terminate()
            server.wait(timeout=10)
