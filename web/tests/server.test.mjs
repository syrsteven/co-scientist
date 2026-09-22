import test from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { request } from "node:http";
import { createCockpitServer } from "../server.mjs";

test("local read-only HTTP contract, data sources and safety boundaries",async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-test-"));
  await fs.mkdir(join(root,".co-scientist-test"));
  await fs.writeFile(join(root,".co-scientist-test/co-scientist.db"),"");
  await fs.mkdir(join(root,"demo-export"));
  await fs.writeFile(join(root,"demo-export/manifest.json"),JSON.stringify({run_id:"demo",final_state:"completed",api_key:"do-not-display"}));
  await fs.writeFile(join(root,"demo-export/events.jsonl"),'{"sequence":1}\n');
  const server=createCockpitServer({repoRoot:root,dataDir:null,bridge:async(_db,command)=>command==="list"?[{runId:"live",state:"running"}]:{manifest:{run_id:"live",current_sequence:2},api_key:"do-not-display"}});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(async()=>{await new Promise(resolve=>server.close(resolve));await fs.rm(root,{recursive:true,force:true});});
  const url=`http://127.0.0.1:${server.address().port}`;
  const catalog=await (await fetch(`${url}/api/runs`)).json();
  assert.equal(catalog.runs.length,2);
  assert.equal(catalog.runs.some(r=>r.database),false);
  for(const run of catalog.runs){
    const response=await fetch(`${url}/api/runs/${encodeURIComponent(run.id)}/snapshot`);
    assert.equal(response.status,200);
    const data=await response.json();assert.equal(data._source.kind,run.kind);
    assert.equal(JSON.stringify(data).includes("do-not-display"),false);
  }
  assert.equal((await fetch(`${url}/api/runs`,{method:"POST"})).status,405);
  assert.equal((await fetch(`${url}/api/runs`,{headers:{origin:"https://evil.example"}})).status,403);
  // fetch normalizes Host; raw http.request tests the actual rebinding boundary.
  const hostStatus=await new Promise((resolve,reject)=>{
    const req=request(`${url}/api/runs`,{headers:{host:"evil.example"}},res=>{res.resume();resolve(res.statusCode);});
    req.on("error",reject);req.end();
  });
  assert.equal(hostStatus,403);
  assert.equal((await fetch(`${url}/api/runs/${encodeURIComponent("../private")}/snapshot`)).status,404);
  assert.equal((await fetch(`${url}/%2e%2e/.env`)).status,404);
  assert.equal((await fetch(`${url}/server.mjs`)).status,404);
  const page=await fetch(url);assert.equal(page.status,200);
  assert.match(page.headers.get("content-security-policy"),/frame-ancestors 'none'/);
});

test("missing Python surfaces a warning but exports remain browsable",async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-offline-"));
  await fs.mkdir(join(root,".co-scientist-test"));
  await fs.writeFile(join(root,".co-scientist-test/co-scientist.db"),"");
  const server=createCockpitServer({repoRoot:root,dataDir:null,bridge:async()=>{throw new Error("secret internal path");}});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(async()=>{await new Promise(resolve=>server.close(resolve));await fs.rm(root,{recursive:true,force:true});});
  const response=await fetch(`http://127.0.0.1:${server.address().port}/api/runs`);
  const catalog=await response.json();assert.equal(catalog.warnings.length,1);
  assert.equal(JSON.stringify(catalog).includes("secret internal path"),false);
});

test("settings writes require same-origin JSON; runs remain read-only",async t=>{
  const calls=[];
  const server=createCockpitServer({settingsBridge:async(command,payload)=>{
    calls.push({command,payload});return command==="catalog"?{templates:[]}:{ok:true,run_started:false};
  }});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const url=`http://127.0.0.1:${server.address().port}`;
  const headers={origin:url,"content-type":"application/json"};
  assert.equal((await fetch(`${url}/api/settings`)).status,200);
  assert.equal((await fetch(`${url}/api/settings/save`,{method:"POST",headers,body:JSON.stringify({name:"中文研究配置"})})).status,200);
  assert.equal(calls.at(-1).payload.name,"中文研究配置");
  assert.equal(calls.at(-1).command,"save");
  assert.equal((await fetch(`${url}/api/settings/save`,{method:"POST",body:"{}"})).status,403);
  assert.equal((await fetch(`${url}/api/settings/save`,{method:"POST",headers:{origin:url,"content-type":"text/plain"},body:"{}"})).status,415);
  assert.equal((await fetch(`${url}/api/settings/save`,{method:"POST",headers,body:"bad"})).status,400);
  assert.equal((await fetch(`${url}/api/settings/save`,{method:"POST",headers,body:JSON.stringify({x:"x".repeat(270000)})})).status,413);
  assert.equal((await fetch(`${url}/api/runs`,{method:"POST",headers,body:"{}"})).status,405);
  assert.equal(calls.length,2);
});
test("control is same-origin, catalog-bound, database-only, and forwards optimistic sequence",async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-control-"));
  await fs.mkdir(join(root,".co-scientist-test"));
  await fs.writeFile(join(root,".co-scientist-test/co-scientist.db"),"");
  await fs.mkdir(join(root,"demo-export"));
  await fs.writeFile(join(root,"demo-export/manifest.json"),JSON.stringify({run_id:"demo"}));
  const calls=[];
  const server=createCockpitServer({repoRoot:root,dataDir:null,
    bridge:async()=>[{runId:"live",state:"running"}],
    controlBridge:async(database,runId,payload)=>{calls.push({database,runId,payload});return {ok:true,status:200,worker_started:false};}});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  t.after(async()=>{await new Promise(resolve=>server.close(resolve));await fs.rm(root,{recursive:true,force:true});});
  const url=`http://127.0.0.1:${server.address().port}`;
  const path=`${url}/api/runs/${encodeURIComponent("db:.co-scientist-test:live")}/control`;
  const payload={action:"pause",expected_sequence:12,confirmed:true};
  const opts={method:"POST",headers:{origin:url,"content-type":"application/json"},body:JSON.stringify(payload)};
  assert.equal((await fetch(path,{method:"POST",body:opts.body})).status,403);
  assert.equal((await fetch(`${url}/api/runs/export:demo-export/control`,opts)).status,409);
  assert.equal((await fetch(`${url}/api/runs/missing/control`,opts)).status,404);
  assert.equal((await fetch(path,opts)).status,200);
  assert.equal(calls.length,1);assert.equal(calls[0].runId,"live");assert.deepEqual(calls[0].payload,payload);
  assert.equal(calls[0].database,join(root,".co-scientist-test/co-scientist.db"));
});
