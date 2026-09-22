import test from "node:test";
import assert from "node:assert/strict";
import { costSummary, stageState, taskDisplayState, role, admission, ranked, parents, escape, parseFolder, callApplied, feedbackUsage, allowedOutputRetry } from "../public/model.js";

test("invalid current output is not shown as active; old failures do not hide retries",()=>{
  const task={task_id:"t",state:"running",attempt:1};
  const calls=[{task_id:"t",external_call_id:"bad",attempt:1,state:"validation_failed"}];
  assert.equal(taskDisplayState(task,calls),"validation_failed");
  assert.equal(stageState([task],calls).text,"输出校验失败 · 待人工处理");
  assert.equal(taskDisplayState({...task,state:"pending"},calls),"pending");
  assert.equal(taskDisplayState({...task,attempt:2},calls),"running");
  assert.equal(taskDisplayState({...task,attempt:undefined},calls),"running");
  assert.equal(taskDisplayState({...task,task_id:"other"},calls),"running");
  assert.equal(taskDisplayState(task,[]),"running");
  assert.equal(task.state,"running");
});

test("output retry is explicit-capability, live-only and sequence-bound",()=>{
  const live={_source:{kind:"database",outputRetryAvailable:true},manifest:{execution_contract_version:3,final_state:"needs_attention",current_sequence:4},
    output_retry:{eligible:true,expected_sequence:4,external_call_id:"call-1"}};
  assert.equal(allowedOutputRetry(live),true);
  for(const kind of ["folder","local-export"])assert.equal(allowedOutputRetry({...live,_source:{kind,outputRetryAvailable:true}}),false);
  assert.equal(allowedOutputRetry({...live,_source:{kind:"database"}}),false);
  assert.equal(allowedOutputRetry({...live,output_retry:{...live.output_retry,eligible:false}}),false);
  assert.equal(allowedOutputRetry({...live,output_retry:{...live.output_retry,expected_sequence:3}}),false);
  assert.equal(allowedOutputRetry({...live,manifest:{...live.manifest,final_state:"completed"}}),false);
});

test("feedback tracking distinguishes literature, epochs, passed inputs and completed consumers",()=>{
  const data={events:[{event_type:"MetaReviewCompleted",payload:{literature_operation:"summary"}},
    {event_type:"ResearchFeedbackRecorded",payload:{feedback_id:"f-old",epoch_id:"old"}},
    {event_type:"ResearchFeedbackRecorded",payload:{feedback_id:"f1",epoch_id:"e1"}}],
    tasks:[{state:"pending",payload:{skill_id:"evolution",inputs:{research_feedback:{feedback_id:"f1"}}}},
      {state:"succeeded",payload:{skill_id:"ranking",inputs:{research_feedback:{feedback_id:"f1"}}}},
      {state:"succeeded",payload:{inputs:{research_feedback:{feedback_id:"f-old"}}}}]};
  const usage=feedbackUsage(data,"e1");
  assert.equal(usage.rounds,1);assert.equal(usage.scheduled,2);assert.equal(usage.completed,1);
  assert.equal(usage.evolution.length,1);assert.equal(feedbackUsage({events:[],tasks:[]}).scheduled,0);
});

test("applied filter uses the persisted ExternalCall state",()=>{
  assert.equal(callApplied({state:"domain_result_applied"}),true);
  assert.equal(callApplied({state:"started"}),false);
});

test("unpriced zero is unknown, not free; measured tokens remain",()=>{
  assert.deepEqual(costSummary([{input_tokens:10,output_tokens:20,cost_usd:"0",pricing_version:"unpriced"}]),{input:10,output:20,usd:0,unpriced:1});
  assert.equal(costSummary([{cost_usd:"0",pricing_version:"frozen-v1"}]).unpriced,0);
});
test("pending and absent work never appear completed",()=>{
  assert.equal(stageState([]).text,"尚未调度");
  assert.equal(stageState([{state:"succeeded"},{state:"queued"}]).tone,"partial");
  assert.equal(stageState([{state:"failed"}]).tone,"reject");
});
test("literature is not counted as a meta-review LLM task",()=>{
  assert.equal(role({intent_type:"run_literature_summary",payload:{skill_id:"meta_review"}}),"literature");
});
test("review pass does not grant admission; content and epoch must match",()=>{
  const d={manifest:{admission_evidence:[{hypothesis_id:"H1",epoch_id:"e1",evidence:{content_hash:"x"}}]}};
  assert.equal(admission(d,{hypothesis_id:"H1",content_hash:"x"},"e2"),undefined);
  assert.equal(admission(d,{hypothesis_id:"H1",content_hash:"y"},"e1"),undefined);
  assert.ok(admission(d,{hypothesis_id:"H1",content_hash:"x"},"e1"));
});
test("rankings exclude anchors and cannot mix epochs",()=>{
  const d={hypotheses:[{hypothesis_id:"H1"}],ratings:{e1:{H1:1200,anchor:1500},e2:{H1:900}}};
  assert.deepEqual(ranked(d,"e1"),[["H1",1200]]);
  assert.deepEqual(ranked(d,"e2"),[["H1",900]]);
});
test("lineage resolves content IDs, not hypothesis ID guesses",()=>{
  const h={hypothesis_id:"H1",content_id:"content-a"};
  assert.equal(parents({hypotheses:[h]},{parent_content_ids:["content-a"]})[0].hypothesis,h);
});
test("untrusted model output is escaped",()=>assert.equal(escape('<img src="x" onerror="alert(1)">'),"&lt;img src=&quot;x&quot; onerror=&quot;alert(1)&quot;&gt;"));
test("folder parser supports empty exports and rejects missing or corrupt manifest",()=>{
  assert.deepEqual(parseFolder([["manifest.json",'{"run_id":"x"}']]).hypotheses,[]);
  assert.throws(()=>parseFolder([])); assert.throws(()=>parseFolder([["manifest.json","broken"]]));
});
import { workerStatus, allowedControl } from "../public/model.js";

test("worker health uses heartbeat and lease, never the run's running label",()=>{
  const now=Date.parse("2026-09-17T12:00:00Z");
  const task={state:"running",worker_id:"w",heartbeat_at:"2026-09-17T11:59:30Z",lease_expires_at:"2026-09-17T12:04:00Z"};
  assert.equal(workerStatus([task],now).fresh,1);
  assert.equal(workerStatus([task],now+300000).fresh,0);
  assert.equal(workerStatus([{...task,state:"succeeded"}],now).fresh,0);
  assert.equal(workerStatus([{state:"running"}],now).fresh,0);
});
test("controls are limited to current database runs and safe lifecycle states",()=>{
  const data={_source:{kind:"database",controlAvailable:true},manifest:{execution_contract_version:3,final_state:"running"}};
  assert.equal(allowedControl(data,"pause"),true);assert.equal(allowedControl(data,"resume"),false);
  data.manifest.final_state="needs_attention";assert.equal(allowedControl(data,"resume"),false);
  data.manifest.final_state="completed";assert.equal(allowedControl(data,"stop"),false);
  data.manifest.final_state="running";data._source.kind="folder";assert.equal(allowedControl(data,"pause"),false);
});
