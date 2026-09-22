import test from "node:test";
import assert from "node:assert/strict";
import {groups,preferences,setPath,getPath,switchProvider,fromRun,errorsByGroup,listedModels,modelReference,priceNumber} from "../public/settings-model.js";

test("settings have seven sections grouped by purpose",()=>{
  assert.equal(groups.length,7);assert.equal(new Set(groups.map(g=>g[0])).size,7);
  assert.equal(groups.at(-1)[3],"本地工作台");
});
test("strict Ranking is explicit, preserved in copies and removed for other providers",()=>{
  for(const protocol of ["deepseek-strict-tool-v1","deepseek-strict-tool-v2"]){
  const profile={providers:{llm:"deepseek"},ranking_output_protocol:protocol,budget:{max_matches:12}};
  const copied=fromRun({manifest:{run_id:"strict",goal:{title:"x"},profile}});
  assert.equal(copied.profile.ranking_output_protocol,profile.ranking_output_protocol);
  const next=switchProvider(copied,"qwen",[{id:"qwen",profile:{providers:{llm:"qwen"},replay_resources:null}}],{});
  assert.equal(next.profile.ranking_output_protocol,undefined);
  assert.equal(profile.ranking_output_protocol,protocol);
  }
  const legacy=fromRun({manifest:{run_id:"old",goal:{title:"x"},profile:{providers:{llm:"deepseek"}}}});
  assert.equal(legacy.profile.ranking_output_protocol,undefined);
  assert.deepEqual(errorsByGroup([{field:"profile.ranking_output_protocol"}]),{ranking:1});
});
test("view preferences have bounded intervals and do not affect profiles",()=>{
  assert.deepEqual(preferences({pollSeconds:0,density:"invalid",autoRefresh:false}),{pollSeconds:5,density:"comfortable",autoRefresh:false});
});
test("nested controls preserve null versus zero and prevent prototype writes",()=>{
  const d={profile:{budget:{max_matches:10}}};setPath(d,"profile.budget.max_matches",null);
  assert.equal(getPath(d,"profile.budget.max_matches"),null);
  setPath(d,"profile.budget.max_matches",0);assert.equal(getPath(d,"profile.budget.max_matches"),0);
  assert.throws(()=>setPath(d,"__proto__.polluted",true));assert.equal({}.polluted,undefined);
});
test("copying frozen run configuration never edits its source",()=>{
  const run={manifest:{run_id:"demo",goal:{title:"title"},profile:{budget:{max_matches:12}},provider_configuration:{model:"m"}}};
  const d=fromRun(run);d.profile.budget.max_matches=50;
  assert.equal(run.manifest.profile.budget.max_matches,12);
});
test("provider switch preserves research and budget but strips provider-specific options",()=>{
  const d={goal:{title:"x"},model:"old",profile:{budget:{max_matches:12},providers:{llm:"deepseek",deepseek_generation:{}},evolution:{max_rounds:1}}};
  const next=switchProvider(d,"openai",[{id:"openai",profile:{providers:{llm:"openai",literature:"pubmed"},replay_resources:null}}],{model:"example-model"});
  assert.equal(next.model,"example-model");assert.equal(next.profile.providers.deepseek_generation,undefined);
  assert.equal(next.profile.budget.max_matches,12);assert.equal(d.profile.providers.llm,"deepseek");
});
test("Replay to real enables template scientific protocol; old real copies are not silently upgraded",()=>{
  const templates=[{id:"openai",profile:{providers:{llm:"openai",literature:"pubmed"},replay_resources:null,
    scientific_context:true,research_protocol_version:"research-v1",literature_content:"abstracts",literature_sort:"relevance"}},
    {id:"replay",profile:{providers:{llm:"replay",literature:"replay_pubmed"},replay_resources:{llm_responses:"fixture"}}}];
  const replay={goal:{title:"my goal"},profile:{providers:{llm:"replay"},budget:{max_matches:12},scientific_context:false,evolution:{max_rounds:0}}};
  const real=switchProvider(replay,"openai",templates,{model:"m"});
  assert.equal(real.profile.research_protocol_version,"research-v1");
  assert.equal(real.profile.scientific_context,true);assert.equal(real.profile.literature_content,"abstracts");
  assert.deepEqual(real.goal,replay.goal);assert.deepEqual(real.profile.budget,replay.profile.budget);
  const back=switchProvider(real,"replay",templates);
  assert.equal(back.profile.research_protocol_version,null);assert.equal(back.profile.scientific_context,false);
  const legacy=structuredClone(real);delete legacy.profile.research_protocol_version;
  assert.equal(switchProvider(legacy,"openai",templates).profile.research_protocol_version,undefined);
  assert.deepEqual(errorsByGroup([{field:"profile.research_protocol_version"}]),{review:1});
});
test("validation summaries point to the correct menu group",()=>{
  assert.deepEqual(errorsByGroup([{field:"profile.budget.max_matches"},{field:"model"},{field:"goal.title"},{field:"profile.meta_review.max_rounds"}]),{budget:1,model:1,goal:1,review:1});
});
test("model references are provider scoped; custom models are not assigned invented prices",()=>{
  const catalog={models:[{provider:"deepseek",id:"flash"},{provider:"openai",id:"flash"}]};
  assert.equal(listedModels(catalog,"deepseek").length,1);
  assert.equal(modelReference(catalog,"qwen","flash"),null);
  assert.equal(modelReference(catalog,"deepseek","custom"),null);
  assert.equal(priceNumber(null),"未列出");assert.equal(priceNumber(0),"0");
  assert.equal(priceNumber(.003),"0.003");
});
