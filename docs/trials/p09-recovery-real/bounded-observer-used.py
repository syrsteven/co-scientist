"""User-authorized bounded operator: GET saved ID only, never submits or retries."""
import json,sqlite3,subprocess,sys,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/private/tmp/co-scientist-p09-recovery');DB=Path('/private/tmp/co-scientist-candidate-review-trial/runs/candidate-review.sqlite')
PYTHON='/Users/lemintea/anaconda3/envs/coscientist/bin/python'
STAGE=sys.argv[1];assert STAGE in ('P09','P10')
RID={'P09':'p09-real-nonprod-single-v1','P10':'p10-real-nonprod-single-v1'}[STAGE]
OUT=Path('/private/tmp/p09-recovery-ops');OUT.mkdir(exist_ok=True)
def state():
 with sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True) as c:
  c.row_factory=sqlite3.Row
  action=dict(c.execute('SELECT * FROM candidate_review_actions WHERE request_id=?',(RID,)).fetchone())
  jobs=[dict(r) for r in c.execute('SELECT * FROM remote_generations WHERE task_id=?',(action['task_id'],))]
  attempts=[dict(r) for r in c.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY started_at,ordinal',(action['task_id'],))]
  results=[dict(r) for r in c.execute('SELECT * FROM results WHERE task_id=?',(action['task_id'],))]
 return action,jobs,attempts,results
start_mono=time.monotonic();action,jobs,attempts,results=state()
submits=[a for a in attempts if a['call_key']=='responses.submit'];latest_submit=submits[-1]
age=max(0,time.time()-datetime.fromisoformat(latest_submit['started_at']).timestamp())
deadline=start_mono+max(0,1200-age)
log={'stage':STAGE,'request_id':RID,'task_id':action['task_id'],'submission_attempt_id':latest_submit['id'],'window_seconds':1200,'max_queries':60,'minimum_interval_seconds':15,'events':[],'operator_sends_POST':False}
def save(reason):
 log['stop_reason']=reason;log['elapsed_operator_seconds']=time.monotonic()-start_mono
 (OUT/(STAGE+'.observation.json')).write_text(json.dumps(log,indent=2)+'\n')
 print(json.dumps({'stage':STAGE,'stop_reason':reason,'events':len(log['events'])}),flush=True)
while True:
 action,jobs,attempts,results=state()
 if not jobs:save('No saved response ID; stop without query or POST');break
 job=jobs[0];log.setdefault('response_id',job['response_id']);assert log['response_id']==job['response_id']
 if job['status'] not in ('queued','in_progress','unknown'):
  log['terminal_status']=job['status'];log['saved_result']=json.loads(results[0]['output']) if results else None
  save('Terminal response; no further query');break
 queries=[a for a in attempts if a['target'].endswith('/retrieve')]
 if queries and queries[-1]['status']!='succeeded':save('Prior query failed/interrupted; stop');break
 if len(queries)>=60:save('Query limit reached; retain ID');break
 last=queries[-1] if queries else latest_submit
 last_end=datetime.fromisoformat(last['finished_at'] or last['started_at']).timestamp()
 delay=max(0,15-(time.time()-last_end))
 if time.monotonic()+delay>=deadline:save('Observation window ended; retain ID, no cancellation or resubmission');break
 if delay:time.sleep(delay)
 if time.monotonic()>=deadline:save('Observation window ended; retain ID');break
 before=time.monotonic();utc=datetime.now(timezone.utc).isoformat()
 command=[PYTHON,'-m','co_scientist_next.review_trial','query-'+STAGE.lower(),'--db',str(DB),'--package','docs/preparations/candidate-review-real-trial/package','--credential-env','OPENAI_API_KEY','--authorize-same-id-query']
 result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=False)
 (OUT/(STAGE+f'.query-{len(queries)+1}.json')).write_text(result.stdout)
 event={'query':len(queries)+1,'started_at':utc,'ended_at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-before,'exit_code':result.returncode,'response_id':job['response_id']}
 log['events'].append(event);save('Observing saved ID')
 if result.returncode:save('Query command failed; stop');break
