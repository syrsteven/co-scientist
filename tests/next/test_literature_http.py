"""Loopback HTTP persistence with explicitly INVENTED response fixtures."""

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
fixture=runpy.run_path(sys.argv[2])['FixtureTransport']()
with Store(sys.argv[1]) as store:
 server=make_server(store,port=0,development_test=True,public_literature=True,literature_transport=fixture)
 print('http://127.0.0.1:'+str(server.server_port),flush=True)
 server.serve_forever()
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(tmp_path / "http.sqlite"),
            str(ROOT / "tests/next/test_literature_acquisition.py"),
        ],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = process.stdout.readline().strip()
    assert url.startswith("http://127.0.0.1:"), process.stderr.read()
    return process, url


CLIENT = r"""
import sys,json,urllib.request,hashlib,base64
url=sys.argv[1]
def api(path,data=None):
 req=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
if len(sys.argv)>2:
 saved=json.loads(sys.argv[2]); run=saved['run']
 assert api('/api/literature?run_id='+run)==saved['history']
 assert api('/api/run?id='+run)['run']['status']=='literature_acquired_unread'
 print('Restart GET preserved all HTTP acquisition facts without resending')
else:
 assert api('/api/config')['public_literature_enabled']
 b=api('/api/brief',{'name':'OFFLINE HTTP fixture','brief':{'question':'Keep Goal'}})
 run=api('/api/runs',{'revision_id':b['revision_id'],'policy':{'id':'test-only','version':'1','text':'Explicit test policy'}})['run_id']
 api('/api/execute',{'run_id':run})
 payload={'run_id':run,'request_id':'http-query-01','request':{'kind':'search','query':'manual concept'}}
 first=api('/api/literature',payload)
 assert first[0]['result']['details']['transport']=='injected_test_transport'
 assert api('/api/literature',payload)==first
 history=api('/api/literature',{'run_id':run,'request_id':'http-fetch-01','request':{'kind':'fetch','source_ref':'epmc:MED:999001','desired_access':'abstract'}})
 assert history[-1]['result']['acquisition']['access']=='abstract'
 for _ in range(3):assert api('/api/literature?run_id='+run)==history
 attempt=api('/api/literature/response?attempt_id='+history[-1]['attempts'][0]['id'])
 response=attempt['response']; assert hashlib.sha256(base64.b64decode(response['body_base64'])).hexdigest()==response['sha256']
 assert api('/api/run?id='+run)['fixed_brief']['question']=='Keep Goal'
 print(json.dumps({'run':run,'history':history}))
"""


def test_http_acquisition_duplicate_submission_and_restart(tmp_path):
    process, url = start(tmp_path)
    try:
        result = subprocess.run(
            [sys.executable, "-c", CLIENT, url],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        )
        saved = json.loads(result.stdout)
    finally:
        process.terminate()
        process.wait(timeout=10)
    process, url = start(tmp_path)
    try:
        result = subprocess.run(
            [sys.executable, "-c", CLIENT, url, json.dumps(saved)],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert "without resending" in result.stdout
    finally:
        process.terminate()
        process.wait(timeout=10)
