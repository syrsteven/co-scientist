"""Real loopback page/API persistence, INVENTED literature and model fixtures."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def start(tmp_path):
    code = r"""
import sys,runpy
from co_scientist_next.store import Store
from co_scientist_next.workspace import make_server
from co_scientist_next.background_ops import DevelopmentReadingAdapter
fixture=runpy.run_path(sys.argv[2])['FixtureTransport']()
with Store(sys.argv[1]) as store:
 server=make_server(store,port=0,development_test=True,public_literature=True,literature_transport=fixture,reading_adapter=DevelopmentReadingAdapter())
 print('http://127.0.0.1:'+str(server.server_port),flush=True)
 server.serve_forever()
"""
    p = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(tmp_path / "background-http.sqlite"),
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
import json,sys,urllib.request
url=sys.argv[1]
def api(path,data=None):
 req=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
if len(sys.argv)>2:
 saved=json.loads(sys.argv[2]);data=api('/api/background?run_id='+saved['run'])
 assert data==saved['data'];print('Restart: saved background, views, seed and model attempts identical; GET only')
else:
 with urllib.request.urlopen(url+'/background.js') as r:assert b'showBackground' in r.read()
 brief=api('/api/brief',{'name':'OFFLINE HTTP background test','brief':{'question':'Goal unknown'}})
 run=api('/api/runs',{'revision_id':brief['revision_id'],'policy':{'id':'test','version':'1','text':'Explicit fixture policy'}})['run_id'];api('/api/execute',{'run_id':run})
 api('/api/literature',{'run_id':run,'request_id':'http-search','request':{'kind':'search','query':'manual concept'}})
 lit=api('/api/literature',{'run_id':run,'request_id':'http-fetch','request':{'kind':'fetch','source_ref':'epmc:MED:999001','desired_access':'abstract'}})
 view=api('/api/material-views',{'run_id':run,'acquisition_task_id':lit[-1]['task_id']})
 def op(ref,operation,request):
  response=api('/api/background',{'run_id':run,'request_id':ref,'operation':operation,'request':request})
  assert response['request_id']==ref
  return api('/api/background/execute',{'request_id':ref})
 op('http-reading','P04',{'view_id':view['id']})
 op('http-orientation','P05',{})
 data=op('http-open-seed','P06_OPEN',{'orientation_ref':'http-orientation','count':1})
 seed=data['seeds'][0]['id']
 op('http-seed-packet','P05',{'seed_id':seed})
 data=op('http-readiness','P07',{'seed_id':seed,'packet_ref':'http-seed-packet','requested_specificity':'conceptual conjecture'})
 assert data['actions'][-1]['result']['artifact']['decision']=='ready'
 assert data['reading_count_saved']==1 and data['current_model_config']['execution_mode']=='development_fixture'
 assert data['current_prompt_versions']['P04']=='w1-l2-p04-bound-view-v3'
 assert data['actions'][0]['prompt_version']=='w1-l2-p04-bound-view-v3'
 assert api('/api/background/execute',{'request_id':'http-readiness'})==data
 for _ in range(3):assert api('/api/background?run_id='+run)==data
 assert api('/api/run?id='+run)['run']['status']=='awaiting_generation'
 print(json.dumps({'run':run,'data':data}))
"""


def test_background_api_saved_page_and_restart(tmp_path):
    p, url = start(tmp_path)
    try:
        response = subprocess.run(
            [sys.executable, "-c", CLIENT, url],
            check=True,
            capture_output=True,
            text=True,
            timeout=40,
        )
        saved = json.loads(response.stdout)
    finally:
        p.terminate()
        p.wait(timeout=10)
    p, url = start(tmp_path)
    try:
        response = subprocess.run(
            [sys.executable, "-c", CLIENT, url, json.dumps(saved)],
            check=True,
            capture_output=True,
            text=True,
            timeout=40,
        )
        assert "GET only" in response.stdout
    finally:
        p.terminate()
        p.wait(timeout=10)
