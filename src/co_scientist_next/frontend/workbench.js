"use strict";
// Live data only. User-supplied embedded records execute solely inside the history sandbox.
const wb = {view:"home", subpanel:"acquisition", candidate:null, run:null, targets:[], refresh:0};
const wbTitles = {home:"我的研究",overview:"研究概览",brief:"研究简报",candidates:"候选与科学阅读",literature:"文献与背景",reviews:"Candidate Ethics／R0",activity:"运行实况与研究过程",notes:"人工评估与个人笔记",settings:"设置",history:"历史演示"};
const wbKeys = {epistemic_status:"信息性质",reported_basis:"来源报告",source_view_ref:"原文视图",finding_ref:"已保存阅读引用",assumption:"必要假设",why_needed:"作用",test_or_limit:"检验与限制",claim_prediction:"候选预测",alternative_prediction:"竞争解释预期",discriminates_against:"所区分的竞争解释",description:"说明",relation:"关系",step:"机制步骤",interpretation:"解释",observation:"观察",source_refs:"来源",context:"实验情境",prediction:"预测",rationale:"理由"};
function wbNode(tag,text,cls) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function wbShow(view) {wb.view=view;document.querySelectorAll('main>.view').forEach(n=>n.hidden=n.id!=='wb-'+view);document.querySelectorAll('[data-nav]').forEach(n=>n.classList.toggle('active',n.dataset.nav===view));el('wb-title').textContent=(state.project&&view!=='home'?el('name').value+' · ':'')+wbTitles[view];wbRender();window.scrollTo({top:0,behavior:'instant'});}
function wbButton(text,fn,cls) {const b=wbNode('button',text,cls);b.type='button';b.onclick=fn;return b;}
function wbAny(parent,value,views=[]) {
 if(value==null){parent.append(wbNode('p','未提供','muted'));return;}
 if(Array.isArray(value)){for(const item of value){const n=wbNode('div',undefined,'scientific-item');wbAny(n,item,views);parent.append(n);}if(!value.length)parent.append(wbNode('p','无新增记录','muted'));return;}
 if(typeof value==='object'){const dl=document.createElement('dl');for(const [k,v] of Object.entries(value)){dl.append(wbNode('dt',wbKeys[k]||k));const dd=document.createElement('dd');if(['finding_ref','source_view_ref','source_view_refs'].includes(k))dd.append(folded('技术引用与版本',v));else wbAny(dd,v,views);if(k==='source_view_ref'){const source=views.find(x=>x.id===v);if(source)dd.append(wbButton('打开实际原文与位置',()=>wbSource(source),'source-link'));}dl.append(dd);}parent.append(dl);return;}
 parent.append(wbNode('p',String(value)));
}
function wbSource(view) {el('wb-source-title').textContent=view.source_ref;el('wb-source-meta').textContent=(view.cropped?'已取得文本的片段 · ':'')+view.access+' · 字符 '+view.character_range.join('–')+' / '+view.original_characters+'；'+view.access_limitations+'；原文未改写，图像/补充未查看。';el('wb-source-text').textContent=view.text;el('wb-source-dialog').showModal();}
function wbCandidate(parent,c,views) {
 parent.replaceChildren(wbNode('span','SAVED HYPOTHESIS · 科学未验证','eyebrow'),wbNode('h2',c.title));
 for(const [label,value] of [['科学主张',c.scoped_claim],['适用情境',c.biological_context],['机制链：来源、解释与新猜想',c.mechanism_steps],['证据锚点（候选引用，未代表证据已核实）',c.evidence_anchors],['必要假设',c.assumption_ledger],['竞争解释',c.competing_explanations],['可区分的预测',c.predictions],['证伪条件',c.falsification_conditions],['概念验证方案（非执行授权）',c.validation_concept],['近邻研究范围',c.nearest_prior_work_scope],['限制',c.limitations]]){const section=wbNode('section',undefined,'scientific-section');section.append(wbNode('h3',label));wbAny(section,value,views);parent.append(section);}
 const sources=wbNode('div',undefined,'source-list');for(const view of views)sources.append(wbButton(view.source_ref+' · '+(view.cropped?'片段':view.access),()=>wbSource(view),'source-link'));parent.append(wbNode('h3','本候选实际使用的来源'),sources,folded('不可变候选原始 JSON（页面分组不改措辞）',c));
}
function wbCandidates() {
 const actions=state.run&&generationData?.actions||[];
 const generated=actions.filter(a=>a.result?.candidate);
 if(!generated.some(a=>a.candidate_id===wb.candidate))wb.candidate=generated[0]?.candidate_id||null;
 const list=el('wb-candidate-index');list.replaceChildren();
 for(const a of generated){const b=wbButton(a.result.candidate.title+' · '+a.request.mode,()=>{wb.candidate=a.candidate_id;wbCandidates();},'candidate-choice'+(a.candidate_id===wb.candidate?' selected':''));list.append(b);}
 const selected=generated.find(a=>a.candidate_id===wb.candidate);
 const reader=el('wb-scientific-reader');if(selected){wbCandidate(reader,selected.result.candidate,selected.input.actual_frozen_seed_background_packet.source_views);reader.prepend(wbNode('p',selected.config.execution_mode==='development_fixture'?'OFFLINE 开发替身结果，不是真实模型能力。':'保存的真实模型输出；科学未验证。','mode'));}else reader.replaceChildren(wbNode('h2','等待已保存的候选'),wbNode('p','先完成资料准备并选择ready方向，再由你点击生成。这里不会显示占位候选。','muted'));
 const reviewRoot=el('wb-review-records');
 const previousPanels=[...reviewRoot.querySelectorAll('.candidate-review')];const existing=[];
 for(const a of actions){const card=[...document.querySelectorAll('#generation-records .candidate-card')].find(n=>n.dataset.candidateId===a.candidate_id);const panel=card?.querySelector('.candidate-review');if(panel){panel.dataset.candidateId=a.candidate_id;existing.push(panel);}}
 for(const panel of previousPanels){if(actions.some(a=>a.candidate_id===panel.dataset.candidateId)&&!existing.some(p=>p.dataset.candidateId===panel.dataset.candidateId))existing.push(panel);}
 reviewRoot.replaceChildren();
 if(generated.length){const label=wbNode('label','选择已保存候选');const select=document.createElement('select');select.id='wb-review-candidate';for(const a of generated){const o=wbNode('option',a.result.candidate.title+' · '+a.request.mode);o.value=a.candidate_id;select.append(o);}select.value=wb.candidate;select.onchange=()=>{wb.candidate=select.value;wbCandidates();};label.append(select);reviewRoot.append(label);}
 else reviewRoot.append(wbNode('p','没有已保存候选，不能执行候选伦理或R0。','muted'));
 const seen=new Set();for(const panel of existing){if(seen.has(panel.dataset.candidateId))continue;seen.add(panel.dataset.candidateId);panel.hidden=panel.dataset.candidateId!==wb.candidate;reviewRoot.append(panel);}
}
async function wbHome() {
 const token=++wb.refresh;const projectsList=await api('/api/projects');
 const projectsData=await Promise.all(projectsList.map(p=>api('/api/project?id='+encodeURIComponent(p.id))));if(token!==wb.refresh)return;
 const root=el('wb-studies');root.replaceChildren();
 for(const data of projectsData){const card=wbButton('',async()=>{await action(async()=>{await project(data.project.id);if(data.runs.length)await showRun(data.runs[0].id);});wbShow(data.runs.length?'overview':'brief');},'study-card');card.append(wbNode('span',data.runs.length+' 个固定运行','badge'),wbNode('h3',data.project.name),wbNode('p',data.revisions[0]?.content.question||'尚无简报'));root.append(card);}
 if(!projectsData.length)root.append(wbNode('p','当前阶段测试库为空。点击“新建研究”开始自己的问题。','muted'));
}
function wbSettings() {
 const cfg=state.config;if(!cfg)return;const root=el('wb-settings-content');root.replaceChildren(wbNode('p','本机服务已连接：'+location.origin+'。供应商连通性不在页面查看时自动探测。'));
 const grid=wbNode('div',undefined,'configuration');
 const goal=wbNode('div',undefined,'panel');goal.append(wbNode('h3','目标制备与目标筛查'),wbNode('p',cfg.development_test?'仅确定性开发替身；创建运行前必须显式选择，不代表真实伦理审查。':'未配置，无默认替身。'));grid.append(goal);
 for(const [name,key,role] of [['背景阅读与准备','reading_model','reading'],['候选生成','generation_model','generation'],['候选伦理／R0','review_model','review']]){const model=cfg[key]||{};const panel=wbNode('div',undefined,'panel');panel.append(wbNode('h3',name),wbNode('p',model.execution_mode==='development_fixture'?'OFFLINE 确定性开发替身':model.execution_mode==='real_model'?'真实适配器配置；只有显式操作才发送':'未配置，不回退替身'),wbNode('p',(model.model||'无模型')+' · '+(model.api_mode||model.endpoint||'无API')),wbNode('p','凭据：'+(model.credential_configured?'后端可用':'未配置')+'；发送权限：'+(cfg.module_authorization?.[role]?'仅用户点击操作':'未授权')),folded('固定参数与容量（不会自动降低或裁剪）',model));grid.append(panel);}
 root.append(grid,wbNode('div','公共文献服务：'+(cfg.public_literature_enabled?(cfg.literature_execution_mode==='offline_fixture'?'OFFLINE 响应夹具':'Europe PMC，显式检索与获取'):'未启用'),'panel'),wbNode('div','政策：没有生产默认政策或默认通过。当前候选审查'+(cfg.review_development_policy_allowed?'可显式采用非生产模板；development是政策范围，不等同于替身。':'须自行显式配置政策。')+' 真实模型响应也不使政策自动成为生产政策。','panel'));
}
function wbOverview() {
 const root=el('wb-overview-summary');root.replaceChildren();if(!state.run){root.append(wbNode('div','请选择已保存运行，或保存简报后创建固定运行。','panel'));return;}
 root.append(wbNode('div',(labels[state.run.run.status]||state.run.run.status)+' · 刷新只读，执行须由你发起。','panel'));
 const metrics=wbNode('div',undefined,'metrics');for(const [label,count] of [['已保存候选',generationData?.actions.filter(a=>a.result?.candidate).length||0],['阅读记录',backgroundData?.reading_count_saved||0],['研究方向',backgroundData?.seeds.length||0]]){const item=wbNode('div',undefined,'metric');item.append(wbNode('strong',String(count)),wbNode('span',label));metrics.append(item);}root.append(metrics);
 const actions=wbNode('div',undefined,'toolbar');for(const [label,view] of [['检索与材料','literature'],['候选与生成','candidates'],['独立人工评估','notes']])actions.append(wbButton(label,()=>wbShow(view)));root.append(actions);
}
function wbActivity() {
 const root=el('wb-activity-content');root.replaceChildren();if(!state.run){root.append(wbNode('p','没有选择固定运行。'));return;}
 root.append(wbNode('div','当前：'+(labels[state.run.run.status]||state.run.run.status)+'；不代表科研完成。','panel'));
 for(const task of state.run.tasks){const row=wbNode('div',undefined,'process-row');const stage=task.module.startsWith('background.')?backgroundTaskLabels[task.module.split('.').at(-1)]||'背景准备':task.module.startsWith('literature.')?'检索与材料':task.module.startsWith('generation.')?'候选生成':task.module.startsWith('candidate_review.')?'独立候选审查':task.module.includes('prepare')?'目标制备':'目标前置';row.append(wbNode('h3',stage),wbNode('p',({ready:'未提交 / 已保存待执行',running:'运行事实尚未收尾；刷新不恢复',waiting_remote:'远端等待（只查询已保存ID）',succeeded:'已完成',failed:'技术失败',blocked:'发送结果不确定；停止，不普通重发'}[task.status]||task.status)));if(task.error){let err;try{err=JSON.parse(task.error)}catch{err={message:'查看持久错误记录'}}row.append(wbNode('p',err.message||err.type));}row.append(folded('技术ID、任务输入和状态',task));root.append(row);}
 root.append(folded('完整用量记录（未知保持未知；远端GET为重复观测，不相加）',state.run.usage));
}
function wbCounts() {
 const history=state.run&&literatureData||[];const returned=history.filter(a=>a.request.kind==='search').flatMap(a=>a.result?.acquisition?.items||[]);const unique=new Set(returned.map(s=>s.source_ref));const material=backgroundData?.materials||[];const read=new Set((backgroundData?.actions||[]).filter(a=>a.operation==='P04'&&a.result?.background_status==='saved').map(a=>a.request.view_id));const root=el('wb-literature-counts');root.replaceChildren();for(const [label,n] of [['已执行查询页',history.filter(a=>a.request.kind==='search'&&a.result).length],['本地返回记录',returned.length],['去重来源标识',unique.size],['取得材料记录',material.length],['已阅读视图',read.size]]){const item=wbNode('div',undefined,'metric');item.append(wbNode('strong',String(n)),wbNode('span',label));root.append(item);}root.append(wbNode('p','来源标识不是独立研究数；视图不是全文篇数，取得材料不等于已阅读。','muted'));
}
const wbRubrics={retrieval:['检索相关性','重要遗漏与覆盖限制'],reading:['实验情境是否保留','阴性结果是否保留','作者措辞是否忠实'],generation:['证据忠实性','机制价值','可检验性','主要问题'],note:[]};
function wbRubric() {const root=el('wb-note-rubric');root.replaceChildren();for(const name of wbRubrics[el('wb-note-category').value]){const label=wbNode('label',name);const t=document.createElement('textarea');t.rows=2;t.dataset.rubric=name;label.append(t);root.append(label);}}
async function wbNotes() {
 const run=state.run?.run.id;const root=el('wb-note-list');if(!run){el('wb-note-form').hidden=true;root.replaceChildren(wbNode('p','先保存简报并创建固定运行，再绑定材料或候选记录意见。'));return;}
 const data=await api('/api/annotations?run_id='+encodeURIComponent(run));if(state.run?.run.id!==run)return;el('wb-note-form').hidden=false;wb.targets=data.targets;
 bgOptions('wb-note-target',data.targets.map(t=>({...t,id:t.kind+':'+t.ref})),t=>t.label+' · '+({run:'研究整体',candidate:'候选',material_view:'原文视图'}[t.kind]));
 root.replaceChildren();for(const n of data.records){const card=wbNode('article',undefined,'panel');card.append(wbNode('span','独立人工意见 · '+n.created_at,'eyebrow'),wbNode('h3',wb.targets.find(t=>t.ref===n.target_ref)?.label||'已保存内容版本'));wbAny(card,n.observations);card.append(wbNode('h3','个人意见'),wbNode('p',n.note),folded('绑定的Run、对象及内容版本',n));root.append(card);}if(!data.records.length)root.append(wbNode('p','尚无人工意见。意见只保存在独立后端记录。','muted'));
}
function wbRender() {document.querySelectorAll("[data-nav],#refresh").forEach(b=>b.disabled=false);if(!state.config)return;if(wb.run!==state.run?.run.id){wb.run=state.run?.run.id;wb.candidate=null;}el('wb-title').textContent=(state.project&&wb.view!=='home'?el('name').value+' · ':'')+wbTitles[wb.view];el('wb-export').disabled=!state.run;el('wb-open-history').disabled=!state.config.history_available;wbOverview();wbCandidates();wbSettings();wbActivity();wbCounts();el('wb-acquisition').hidden=wb.subpanel!=='acquisition';el('wb-background').hidden=wb.subpanel!=='background';if(wb.view==='home')wbHome().catch(wbError);if(wb.view==='notes')wbNotes().catch(wbError);}
function wbError(e) {el('notice').textContent=e.message;}
document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.subpanel)wb.subpanel=b.dataset.subpanel;wbShow(b.dataset.nav);});
document.querySelectorAll('[data-new-study]').forEach(b=>b.onclick=()=>{reset();wbShow('brief');});
el('new-project').onclick=()=>{reset();wbShow('brief');};
el('goal-test-choice').onchange=updateActions;
el('wb-close-source').onclick=()=>el('wb-source-dialog').close();
el('wb-note-category').onchange=wbRubric;wbRubric();
el('wb-note-form').onsubmit=e=>{e.preventDefault();action(async()=>{const target=wb.targets.find(t=>t.kind+':'+t.ref===el('wb-note-target').value);if(!target)throw new Error('请选择本运行已保存的对象');const observations={};el('wb-note-rubric').querySelectorAll('textarea').forEach(t=>{observations[t.dataset.rubric]=t.value;});await api('/api/annotations',{run_id:state.run.run.id,target_kind:target.kind,target_ref:target.ref,target_sha256:target.sha256,category:el('wb-note-category').value,observations,note:el('wb-note-text').value});el('wb-note-text').value='';el('wb-note-rubric').querySelectorAll('textarea').forEach(t=>{t.value='';});await wbNotes();el('notice').textContent='独立人工意见已保存；没有修改或发送模型输入。';});};
el('wb-export').onclick=()=>action(async()=>{const data=await api('/api/export?run_id='+encodeURIComponent(state.run.run.id));const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='co-scientist-run-'+state.run.run.id+'.json';a.click();URL.revokeObjectURL(url);});
el('wb-open-demo').onclick=()=>{const f=el('wb-demo-frame');if(!f.getAttribute('src'))f.src='/history.html';f.hidden=false;el('wb-history-records').replaceChildren();};
el('wb-open-history').onclick=()=>action(async()=>{const data=await api('/api/history');el('wb-demo-frame').hidden=true;const root=el('wb-history-records');root.replaceChildren(wbNode('div','历史ALS只读记录，所有内容来自后端只读数据库；不写入当前研究，也不提供执行按钮。','mode'));if(!data.export){root.append(wbNode('p','没有历史记录'));return;}const exported=data.export;for(const a of exported.generation_actions){const result=exported.results.find(r=>r.task_id===a.task_id);const candidate=result&&JSON.parse(result.output).candidate;if(!candidate)continue;const panel=wbNode('article',undefined,'panel');wbCandidate(panel,candidate,JSON.parse(a.input).actual_frozen_seed_background_packet.source_views);root.append(panel);}for(const a of exported.candidate_review_actions){const r=exported.results.find(x=>x.task_id===a.task_id);if(r){const result=JSON.parse(r.output);const panel=wbNode('article',undefined,'panel');panel.append(wbNode('h2','历史 '+a.operation+' · '+(result.artifact?.decision_per_approved_policy||result.artifact?.disposition||result.review_status)));wbAny(panel,result.artifact);root.append(panel);}}root.append(folded('历史只读完整原始记录',exported));});
document.addEventListener('workspace-change',wbRender);
// Technical IDs/versions remain available without taking over the primary workflow.
for(const id of ['background-prompt','generation-prompt']){const node=el(id);if(node){const d=document.createElement('details');d.append(wbNode('summary','高级：当前Prompt版本与执行边界'));node.before(d);d.append(node);}}
wbShow('home');
