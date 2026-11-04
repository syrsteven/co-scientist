"""Offline fixture page/API; restart and GET cannot generate or recover."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKGROUND_CLIENT = runpy.run_path(str(Path(__file__).with_name("test_background_http.py")))[
    "CLIENT"
]


def start(tmp_path):
    code = r"""
import runpy,sys
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server
from co_scientist_next.background_ops import DevelopmentReadingAdapter
from co_scientist_next.generation_ops import DevelopmentGenerationAdapter
transport=runpy.run_path(sys.argv[2])['FixtureTransport']()
with Store(sys.argv[1]) as s:
 server=make_server(s,development_test=True,public_literature=True,literature_transport=transport,reading_adapter=DevelopmentReadingAdapter(),generation_adapter=DevelopmentGenerationAdapter())
 print('http://127.0.0.1:'+str(server.server_port),flush=True)
 server.serve_forever()
"""
    p = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(tmp_path / "generation-http.sqlite"),
            str(ROOT / "tests/next/test_literature_acquisition.py"),
        ],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = p.stdout.readline().strip()
    assert url.startswith("http://127.0.0.1:"), p.stderr.read()
    return p, url


CLIENT = r"""
import json,sys,urllib.request,urllib.error
url=sys.argv[1];saved=json.loads(sys.argv[2]);run=saved['run']
def api(path,data=None):
 req=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
path='/api/generation?run_id='+run
if len(sys.argv)>3:
 assert api(path)==saved['generation']
 assert api('/api/run?id='+run)['run']['status']=='awaiting_candidate_ethics'
 print('Restart and repeated GET: same persisted candidates, no new sends')
else:
 with urllib.request.urlopen(url+'/generation.js') as r:assert b'showGeneration' in r.read()
 data=api(path);assert data['can_submit'] and not data['actions']
 r=data['ready_records'][0]
 for i,mode in enumerate(['DIRECT','ASSUMPTION_STRUCTURED']):
  request={'candidate_id':'http-candidate-'+str(i),'mode':mode,'seed_id':r['seed_id'],'packet_ref':r['packet_ref'],'readiness_ref':r['readiness_ref']}
  ref='http-generation-'+str(i)
  api('/api/generation',{'run_id':run,'request_id':ref,'request':request})
  data=api('/api/generation/execute',{'request_id':ref})
  assert data['actions'][-1]['result']['generation_status']=='generated'
  assert api('/api/generation/execute',{'request_id':ref})==data
  attempt=data['actions'][-1]['attempts'][0]['id']
  raw=api('/api/generation/attempt?attempt_id='+attempt)
  assert json.loads(raw['request'])['operation']=='P08'
 for _ in range(3):assert api(path)==data
 try:api('/api/generation',{'run_id':run,'request_id':'rewrite-identity','request':request})
 except urllib.error.HTTPError as e:assert e.code==400
 else:raise AssertionError('Candidate identity was reused')
 # A saved but unexecuted action must stay unexecuted over restart/GET.
 pending={**request,'candidate_id':'http-pending-identity'}
 api('/api/generation',{'run_id':run,'request_id':'http-pending-generation','request':pending})
 data=api(path);assert data['actions'][-1]['task_status']=='ready' and data['actions'][-1]['attempts']==[]
 print(json.dumps({'run':run,'generation':data}))
"""


def test_generation_page_api_persistence_and_restart_without_resend(tmp_path):
    p, url = start(tmp_path)
    try:
        response = subprocess.run(
            [sys.executable, "-c", BACKGROUND_CLIENT, url],
            capture_output=True,
            text=True,
            check=True,
            timeout=40,
        )
        saved = json.loads(response.stdout)
        response = subprocess.run(
            [sys.executable, "-c", CLIENT, url, json.dumps(saved)],
            capture_output=True,
            text=True,
            check=True,
            timeout=40,
        )
        saved = json.loads(response.stdout)
    finally:
        p.terminate()
        p.wait(timeout=10)
    p, url = start(tmp_path)
    try:
        # Pending action stays ready: no automatic execution on server restart.
        replay = CLIENT.replace("=='awaiting_candidate_ethics'", "=='ready'")
        response = subprocess.run(
            [sys.executable, "-c", replay, url, json.dumps(saved), "read-only"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        assert "no new sends" in response.stdout
    finally:
        p.terminate()
        p.wait(timeout=10)
