// Real HTTP -> Python bridge -> Supervisor -> temporary SQLite; replay only.
import test from "node:test";
import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {promisify} from "node:util";
import {promises as fs, existsSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {createCockpitServer} from "../server.mjs";

const execute=promisify(execFile);
const repo=fileURLToPath(new URL("../../",import.meta.url));
const python=process.env.CO_SCIENTIST_PYTHON||join(repo,".venv/bin/python");

test("scientist feedback HTTP bridge records opinion and queues one review without calls",{
  skip:!existsSync(python),timeout:60000,
},async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"scientist-http-"));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await execute(python,["-c",`import asyncio,sys,pytest
from pathlib import Path
from tests.unit.runtime.test_feedback_loop import setup_loop
from co_scientist.runtime.core_runner import CoreRunner
async def main():
    root=Path(sys.argv[1])
    with pytest.MonkeyPatch.context() as monkey:
        config,env,_=setup_loop(root,monkey,safety="insufficient_evidence")
        runner=CoreRunner(data_dir=root/"data",environment=env)
        try:
            assert str((await runner.execute(config=config,run_id="human-http")).state)=="needs_attention"
        finally:
            await runner.aclose()
asyncio.run(main())`,root],{cwd:repo,timeout:30000});
  const server=createCockpitServer({repoRoot:root,dataDir:"data",python});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const url=`http://127.0.0.1:${server.address().port}`;
  const catalog=await (await fetch(`${url}/api/runs`)).json();
  const endpoint=`${url}/api/runs/${encodeURIComponent(catalog.runs[0].id)}`;
  const get=async()=>await (await fetch(`${endpoint}/snapshot`)).json();
  const before=await get();
  const feedback=before.events.find(e=>e.event_type==="ResearchFeedbackRecorded");
  const payload={feedback_id:feedback.payload.feedback_id,expected_run_sequence:before.manifest.current_sequence,
    actor:"Test researcher",note:"Please inspect initial safety coverage.",confirmed:true};
  const post=async extra=>fetch(`${endpoint}/scientist-feedback`,{method:"POST",headers:{origin:url,"content-type":"application/json"},body:JSON.stringify({...payload,...extra})});
  assert.equal((await post({run_id:"injected"})).status,422);
  const response=await post({});assert.equal(response.status,200);
  assert.equal((await response.json()).worker_started,false);
  assert.equal((await post({})).status,409);
  const after=await get();
  assert.deepEqual(after.external_calls,before.external_calls);
  assert.deepEqual(after.costs,before.costs);
  assert.equal(after.manifest.final_state,"running");
  assert.equal(after.events.filter(e=>e.event_type==="ScientistFeedbackRecorded").length,1);
  assert.deepEqual(after.events.find(e=>e.sequence===feedback.sequence),feedback);
});
const setup=`
import asyncio, json, sys
from pathlib import Path
from tests.core_preview_support import write_core_preview_inputs
from co_scientist.application.config import resolve_run_config
from co_scientist.runtime.core_runner import CoreRunner
async def main():
    root = Path(sys.argv[1])
    goal, profile, environment = write_core_preview_inputs(root, novelty_verdict="novel")
    config = resolve_run_config(goal_file=goal, profile_file=profile, provider="replay", environment=environment)
    runner = CoreRunner(data_dir=root / ".co-scientist-http-test", environment=environment)
    try:
        result = await runner.execute(config=config)
        print(json.dumps(result.model_dump(mode="json")))
    finally:
        await runner.aclose()
        runner.uow.engine.dispose()
asyncio.run(main())
`;
const finalize=`
import asyncio, json, sys
from pathlib import Path
from co_scientist.runtime.core_runner import CoreRunner
async def main():
    runner = CoreRunner(data_dir=Path(sys.argv[1]), environment={})
    try:
        assert runner.uow.run_manifest(sys.argv[2])["providers"]["llm"] == "replay"
        result = await runner.resume(run_id=sys.argv[2])
        print(json.dumps(result.model_dump(mode="json")))
    finally:
        await runner.aclose()
        runner.uow.engine.dispose()
asyncio.run(main())
`;

test("real bridges persist lifecycle controls and never launch a worker",{
  skip:!existsSync(python)?"Install the project Python environment to run bridge integration":false,
  timeout:60000,
},async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-real-bridge-"));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const prepared=JSON.parse((await execute(python,["-c",setup,root],{cwd:repo,timeout:30000})).stdout);
  assert.equal(prepared.state,"running");
  const server=createCockpitServer({repoRoot:root,dataDir:null,python});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const url=`http://127.0.0.1:${server.address().port}`;
  const catalog=await (await fetch(`${url}/api/runs`)).json();
  assert.equal(catalog.runs.length,1);
  const endpoint=`${url}/api/runs/${encodeURIComponent(catalog.runs[0].id)}`;
  const get=async()=>{
    const response=await fetch(`${endpoint}/snapshot`);assert.equal(response.status,200);
    return response.json();
  };
  const post=async payload=>{
    const response=await fetch(`${endpoint}/control`,{method:"POST",
      headers:{origin:url,"content-type":"application/json"},body:JSON.stringify(payload)});
    return {status:response.status,data:await response.json()};
  };
  const before=await get();
  assert.equal(before._source.controlAvailable,true);
  let sequence=before.manifest.current_sequence;
  const calls=before.external_calls.length;
  assert.equal((await post({action:"pause",confirmed:true,expected_sequence:sequence,run_id:"injected"})).status,422);
  for(const [action,state] of [["pause","paused"],["resume","running"],["stop","stopping"]]){
    const result=await post({action,confirmed:true,expected_sequence:sequence});
    assert.equal(result.status,200,JSON.stringify(result.data));
    assert.equal(result.data.worker_started,false);
    const current=await get();
    assert.equal(current.manifest.final_state,state);
    assert.equal(current.external_calls.length,calls);
    assert.ok(current.manifest.current_sequence>sequence);
    const stale=await post({action,confirmed:true,expected_sequence:sequence});
    assert.equal(stale.status,409);
    assert.equal((await get()).manifest.current_sequence,current.manifest.current_sequence);
    sequence=current.manifest.current_sequence;
  }
  // An explicit replay Worker invocation, not the HTTP command, finishes the run.
  const completed=JSON.parse((await execute(python,["-c",finalize,
    join(root,".co-scientist-http-test"),prepared.run_id],{cwd:repo,timeout:30000})).stdout);
  assert.equal(completed.state,"completed");
  const after=await get();
  assert.equal(after.external_calls.length,calls);
  assert.deepEqual(after.events.filter(ev=>["RunPausing","RunPaused","RunResumed","RunStopping","FinalizationCompleted","RunCompleted"].includes(ev.event_type)).map(ev=>ev.event_type),
    ["RunPausing","RunPaused","RunResumed","RunStopping","FinalizationCompleted","RunCompleted"]);
  assert.equal((await post({action:"resume",confirmed:true,expected_sequence:after.manifest.current_sequence})).status,409);
});

test("real HTTP retry/raw bridges preserve failed response and cost, no Worker",{
  skip:!existsSync(python),timeout:60000,
},async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-retry-http-"));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await execute(python,["-c",`import asyncio,sys
from pathlib import Path
from tests.scenario.test_explicit_output_retry import create_failed_run
asyncio.run(create_failed_run(Path(sys.argv[1])))`,root],{cwd:repo,timeout:30000});
  const server=createCockpitServer({repoRoot:root,dataDir:"data",python});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const url=`http://127.0.0.1:${server.address().port}`;
  const catalog=await (await fetch(`${url}/api/runs`)).json();
  const endpoint=`${url}/api/runs/${encodeURIComponent(catalog.runs[0].id)}`;
  const get=async()=>{const res=await fetch(`${endpoint}/snapshot`);assert.equal(res.status,200);return res.json();};
  const before=await get(),p=before.output_retry;
  assert.equal(p.eligible,true);
  const raw=await (await fetch(`${endpoint}/calls/${encodeURIComponent(p.external_call_id)}/raw`)).json();
  assert.equal(raw.integrity_verified,true);assert.equal(raw.text,'{"schema_version": 1, "hypotheses": [');
  const post=async extra=>{
    const res=await fetch(`${endpoint}/retry-output`,{method:"POST",headers:{origin:url,"content-type":"application/json"},
      body:JSON.stringify({external_call_id:p.external_call_id,expected_sequence:p.expected_sequence,confirmed:true,...extra})});
    return {status:res.status,data:await res.json()};
  };
  assert.equal((await post({confirmed:false})).status,422);
  assert.equal((await post({database:"injected"})).status,422);
  assert.equal((await post({expected_sequence:p.expected_sequence-1})).status,409);
  const result=await post({});assert.equal(result.status,200,JSON.stringify(result.data));
  assert.equal(result.data.worker_started,false);assert.equal(result.data.authorized_attempt,2);
  const after=await get();assert.equal(after.manifest.final_state,"running");
  assert.deepEqual(after.external_calls,before.external_calls);assert.deepEqual(after.costs,before.costs);
  assert.equal(after.output_retry,null);assert.equal((await post({})).status,409);
  assert.deepEqual(after.events.slice(-3).map(e=>e.event_type),["TaskOutputRetryRequested","TaskRequeued","RunResumed"]);
});
