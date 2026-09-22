// Direct request-handler tests: no port binding, sockets, model calls or user data.
import test from "node:test";
import assert from "node:assert/strict";
import {Readable} from "node:stream";
import {promises as fs} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {createCockpitServer} from "../server.mjs";

function dispatch(server,path,{method="GET",body="",headers={}}={}){
  return new Promise((resolve,reject)=>{
    const req=Readable.from([Buffer.from(body)]);
    Object.assign(req,{method,url:path,headers:{host:"localhost:4173",...headers}});
    const res={status:200,headers:{},setHeader(k,v){this.headers[k]=v;},writeHead(status,headers){this.status=status;Object.assign(this.headers,headers);},
      end(value){try{resolve({status:this.status,headers:this.headers,data:JSON.parse(String(value))});}catch(error){reject(error);}}};
    server.emit("request",req,res);
  });
}

test("control routing is catalog-bound and same-origin without starting a server",async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-routing-"));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.mkdir(join(root,".co-scientist-test"));
  await fs.writeFile(join(root,".co-scientist-test/co-scientist.db"),"");
  await fs.mkdir(join(root,"demo-export"));
  await fs.writeFile(join(root,"demo-export/manifest.json"),'{"run_id":"demo"}');
  const calls=[];
  const server=createCockpitServer({repoRoot:root,dataDir:null,
    bridge:async(_db,command)=>command==="list"?[{runId:"live",state:"running"}]:{manifest:{run_id:"live"}},
    controlBridge:async(db,runId,payload)=>{calls.push({db,runId,payload});return {ok:false,status:409,error:"stale"};}});
  const path="/api/runs/db%3A.co-scientist-test%3Alive/control";
  const payload={action:"pause",expected_sequence:7,confirmed:true};
  const opts={method:"POST",body:JSON.stringify(payload),headers:{origin:"http://localhost:4173","content-type":"application/json"}};
  assert.equal((await dispatch(server,path,{...opts,headers:{"content-type":"application/json"}})).status,403);
  assert.equal((await dispatch(server,path,{...opts,headers:{...opts.headers,origin:"https://evil.example"}})).status,403);
  assert.equal((await dispatch(server,path,{...opts,headers:{...opts.headers,"content-type":"text/plain"}})).status,415);
  assert.equal((await dispatch(server,path,{...opts,body:"bad"})).status,400);
  assert.equal((await dispatch(server,path,{...opts,body:'"'+"x".repeat(270000)+'"'})).status,413);
  assert.equal((await dispatch(server,"/api/runs/export%3Ademo-export/control",opts)).status,409);
  assert.equal((await dispatch(server,"/api/runs/missing/control",opts)).status,404);
  assert.equal(calls.length,0);
  assert.equal((await dispatch(server,path,opts)).status,409);
  assert.equal(calls.length,1);assert.equal(calls[0].runId,"live");assert.deepEqual(calls[0].payload,payload);
  assert.equal(calls[0].db,join(root,".co-scientist-test/co-scientist.db"));
  assert.equal((await dispatch(server,"/api/runs/db%3A.co-scientist-test%3Alive/snapshot")).data._source.controlAvailable,true);
  assert.equal((await dispatch(server,"/api/runs/export%3Ademo-export/snapshot")).data._source.controlAvailable,false);
});

test("retry and raw routes are catalog-bound, same-origin, and unavailable on exports",async t=>{
  const root=await fs.mkdtemp(join(tmpdir(),"cockpit-retry-routing-"));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.mkdir(join(root,".co-scientist-test"));
  await fs.writeFile(join(root,".co-scientist-test/co-scientist.db"),"");
  await fs.mkdir(join(root,"demo-export"));
  await fs.writeFile(join(root,"demo-export/manifest.json"),'{"run_id":"demo"}');
  const calls=[];
  const server=createCockpitServer({repoRoot:root,dataDir:null,
    bridge:async(_db,command)=>command==="list"?[{runId:"live"}]:{manifest:{run_id:"live"}},
    retryBridge:async(db,run,command,payload)=>{calls.push({db,run,command,payload});return {ok:true,status:200,worker_started:false};}});
  const prefix="/api/runs/db%3A.co-scientist-test%3Alive",path=`${prefix}/retry-output`;
  const payload={external_call_id:"call:1",expected_sequence:4,confirmed:true};
  const opts={method:"POST",headers:{origin:"http://localhost:4173","content-type":"application/json"},body:JSON.stringify(payload)};
  assert.equal((await dispatch(server,path,{...opts,headers:{"content-type":"application/json"}})).status,403);
  assert.equal((await dispatch(server,path,{...opts,headers:{...opts.headers,origin:"https://evil.example"}})).status,403);
  assert.equal((await dispatch(server,path,{...opts,headers:{...opts.headers,"content-type":"text/plain"}})).status,415);
  assert.equal((await dispatch(server,path,{...opts,body:"bad"})).status,400);
  assert.equal((await dispatch(server,path,{...opts,body:'"'+"x".repeat(270000)+'"'})).status,413);
  for(const suffix of ["retry-output","scientist-feedback","calls/call%3A1/raw"]){
    const options=suffix.endsWith("/raw")?{}:opts;
    assert.equal((await dispatch(server,`/api/runs/export%3Ademo-export/${suffix}`,options)).status,409);
    assert.equal((await dispatch(server,`/api/runs/missing/${suffix}`,options)).status,404);
  }
  assert.equal(calls.length,0);
  assert.equal((await dispatch(server,path,opts)).status,200);
  assert.equal((await dispatch(server,`${prefix}/calls/call%3A1/raw`)).status,200);
  assert.deepEqual(calls.map(c=>c.command),["retry","raw"]);
  assert.equal(calls[0].db,join(root,".co-scientist-test/co-scientist.db"));
  assert.deepEqual(calls[0].payload,payload);
  assert.equal(calls[1].payload.external_call_id,"call:1");
  assert.equal((await dispatch(server,`${prefix}/scientist-feedback`,{...opts,headers:{"content-type":"application/json"}})).status,403);
  assert.equal((await dispatch(server,`${prefix}/scientist-feedback`,opts)).status,200);
  assert.equal(calls[2].command,"scientist-feedback");
  const data=(await dispatch(server,`${prefix}/snapshot`)).data;
  assert.equal(data._source.outputRetryAvailable,true);assert.equal(data._source.rawAvailable,true);
  assert.equal(data._source.scientistFeedbackAvailable,true);
});
