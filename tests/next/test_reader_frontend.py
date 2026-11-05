"""Pure frontend mappings against frozen records; Node DOM harness, no browser/provider."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src/co_scientist_next/frontend/workbench.js"
NODE = shutil.which("node")


def node_check(code, data=None):
    if not NODE:
        pytest.skip("Node unavailable; frontend mapping check not run")
    result = subprocess.run(
        [NODE, "-e", code, str(JS)],
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


BOOT = """const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(process.argv[1],'utf8');
const context={module:{exports:{}}};vm.createContext(context);
vm.runInContext(src.slice(0,src.indexOf('const readerTabs')),context);
const F=context.module.exports;
"""


def test_review_states_do_not_turn_technical_failure_or_fixture_into_real_pass():
    node_check(
        BOOT
        + """
assert.equal(F.status(), '尚未执行');
const completed={result:{review_status:'completed',artifact:{decision_per_approved_policy:'pass'}},config:{execution_mode:'development_fixture'}};
assert.equal(F.status(completed),'已通过本次限定用途筛查');
assert.equal(F.execution(completed),'开发替身（非真实模型）');
assert.equal(F.execution({...completed,config:{execution_mode:'real_model'}}),'真实模型');
assert.equal(F.status({...completed,result:{review_status:'invalid_output',artifact:{decision_per_approved_policy:'pass'}}}),'invalid_output');
assert.equal(F.status({task_status:'blocked'}),'发送结果不确定，禁止普通重发');
assert.equal(F.status({result:{review_status:'completed',artifact:{disposition:'proceed_to_R1'}}}),'初审允许进入 R1，科学正确性尚未确认');
"""
    )


def test_review_and_annotation_filters_preserve_run_candidate_and_content_version():
    node_check(
        BOOT
        + """
const g={request_id:'gen',run_id:'run',candidate_id:'c'};
const valid={generation_ref:'gen',run_id:'run',binding:{candidate_id:'c'},operation:'P10'};
assert.equal(F.boundReviews(g,[valid,{...valid,run_id:'other'},{...valid,generation_ref:'sibling'},{...valid,binding:{candidate_id:'sibling'}},{...valid,binding:{run_id:'wrong'}},{...valid,input:{fixed_candidate:{title:'tampered'}}}]).length,1);
const t={run_id:'run',kind:'candidate',ref:'c',sha256:'version1'};
const n={run_id:'run',target_kind:'candidate',target_ref:'c',target_sha256:'version1'};
assert.equal(F.annotations([n,{...n,run_id:'sibling'},{...n,target_sha256:'version2'}],t).length,1);
"""
    )


def test_history_decode_retains_scientific_fields_usage_and_real_review_counts():
    # Synthetic unit fixture; actual ALS counts are separately browser-verified.
    node_check(
        BOOT
        + """
const candidate={candidate_id:'c',scoped_claim:'original statement',limitations:['original limit'],extra_field:'must survive'};
const result={candidate};
const e={run:{id:'run'},results:[{task_id:'g',output:JSON.stringify(result)}],generation_actions:[{task_id:'g',request_id:'gen',candidate_id:'c',request:'{}',input:'{}',binding:'{}',config:'{"execution_mode":"real_model"}'}],candidate_review_actions:[],attempts:[{task_id:'g',usage:null}],human_annotations:[]};
const h=F.historical(e);assert.equal(h.generations[0].result.candidate.extra_field,'must survive');assert.equal(h.generations[0].attempts[0].usage,null);assert.equal(e.results[0].output,JSON.stringify(result));
assert.equal(F.access({access:'abstract',cropped:false}),'摘要');
assert.ok(F.access({access:'full_text',cropped:true}).includes('选定片段'));
"""
    )


def test_specialized_components_preserve_full_fields_and_readonly_notes():
    node_check("""const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(process.argv[1],'utf8');
// Minimal DOM is solely a unit harness; browser acceptance is separately run through CUA.
class E{constructor(tag,text){this.tag=tag;this.textContent=text||'';this.children=[];this.dataset={};this.hidden=false;this.attrs={};this.classList={add:()=>{}};this.isConnected=true;} append(...n){this.children.push(...n);} replaceChildren(...n){this.children=n;} insertBefore(n,b){this.children.splice(this.children.indexOf(b),0,n);} setAttribute(k,v){this.attrs[k]=v;} scrollIntoView(){} }
const n=(tag,text)=>new E(tag,text);
const ctx={module:{exports:{}},wbNode:n,wbButton:(text,fn)=>{const e=n('button',text);e.onclick=fn;return e;},folded:(label,v)=>{const e=n('details',label);e.append(n('pre',JSON.stringify(v)));return e;},wbSource:()=>{},api:()=>{throw Error('Read-only must not call annotations API')},state:{busy:false},console};
vm.createContext(ctx);vm.runInContext(src.slice(0,src.indexOf('// Live data only.')),ctx);
const c={candidate_id:'c',title:'Title',scoped_claim:'CONDITIONAL CLAIM',biological_context:'CONTEXT',mechanism_steps:[{relation:'STEP ORIGINAL',status:'new_conjecture'}],evidence_anchors:[{reported_basis:'ANCHOR ORIGINAL',epistemic_status:'source_report'}],assumption_ledger:[{assumption:'PREMISE ORIGINAL',context_transfer:'TRANSFER',possible_check:'CHECK'}],competing_explanations:['COMPETING'],predictions:[{claim_prediction:'PREDICTION',alternative_prediction:'ALTERNATIVE',comparison:'COMPARISON',readout:'READOUT'}],falsification_conditions:['FALSIFICATION'],validation_concept:{setting:'SETTING',controls:'CONTROLS',comparison:'PLAN COMPARISON',intervention_and_measurement:'INTERVENTION'},nearest_prior_work_scope:'SCOPE',limitations:['LIMIT'],proposed_new_links:['NEW BRIDGE'],other_field:'EXTRA'};
const generation={request_id:'g',run_id:'r',candidate_id:'c',result:{candidate:c},config:{execution_mode:'real_model'},attempts:[]};
const review={generation_ref:'g',run_id:'r',operation:'P10',request:{policy:{id:'test',version:'1',mode:'development'}},task_status:'succeeded',result:{review_status:'completed',artifact:{disposition:'proceed_to_R1',blocking_defects:[],scientific_unknowns:['U1','U2','U3','U4','U5','U6'],required_R1_checks:['R1','R2','R3','R4','R5','R6','R7','R8'],limitations:['REVIEW LIMIT']}}};
const root=n('article');ctx.readerCandidate(root,c,[],{generation,runId:'r',reviews:[review],readOnly:true});
function text(e){return e.textContent+' '+e.children.map(text).join(' ')}
const out=text(root);
for(const v of ['CONDITIONAL CLAIM','CONTEXT','STEP ORIGINAL','ANCHOR ORIGINAL','PREMISE ORIGINAL','COMPETING','PREDICTION','ALTERNATIVE','FALSIFICATION','CONTROLS','SCOPE','LIMIT','EXTRA','科学未知 · 6 项','后续 R1 核查事项 · 8 项']) assert.ok(out.includes(v),v);
function all(e){return [e,...e.children.flatMap(all)]}
const tabs=all(root).filter(e=>e.attrs.role==='tab');assert.equal(tabs.length,4);tabs[2].onclick();assert.equal(tabs[2].attrs['aria-selected'],'true');tabs[3].onclick();
assert.ok(text(root).includes('不能在此持久化意见'));assert.ok(!all(root).some(e=>e.tag==='form'));
assert.deepEqual(c.assumption_ledger[0].assumption,'PREMISE ORIGINAL');
ctx.state.run={run:{id:'r'}};ctx.api=async()=>({targets:[],records:[]});const absent=n('div');
ctx.readerNotes(absent,{readOnly:false,runId:'r'},'material_view','frozen-only').then(()=>{assert.ok(text(absent).includes('没有后端支持的 material_view'));assert.ok(!all(absent).some(e=>e.tag==='form'));}).catch(e=>{console.error(e);process.exitCode=1});
""")


def test_http_conflict_and_connection_loss_never_retry_provider_actions():
    app = ROOT / "src/co_scientist_next/frontend/app.js"
    code = """const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1].replace('workbench.js','app.js'),'utf8');
let sends=0;
const ctx={fetch:async()=>{sends++;return {ok:false,status:409,json:async()=>({error:'busy'})}}};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('async function action(')),ctx);
(async()=>{try{await ctx.api('/api/generation/execute',{request_id:'fixed'});throw Error('Must reject')}catch(e){assert.equal(e.status,409);assert.ok(e.message.includes('不是模型执行失败'));}assert.equal(sends,1);
ctx.fetch=async()=>{sends++;throw TypeError('OFFLINE connection lost')};try{await ctx.api('/api/generation/execute',{request_id:'fixed'})}catch(e){assert.ok(e.message.includes('OFFLINE'))}assert.equal(sends,2);})().catch(e=>{console.error(e);process.exitCode=1});
"""
    assert app.exists()
    node_check(code)
