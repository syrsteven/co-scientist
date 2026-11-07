"use strict";
// Read-only presentation mapping. No scientific text is rewritten or inferred.
const ReaderFacts = (() => {
  const parse = value => typeof value === "string" ? JSON.parse(value) : value;
  const canonical = value => JSON.stringify(value, (_, v) => v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])) : v);
  function boundReviews(generation, reviews) {
    return reviews.filter(a => a.generation_ref === generation.request_id &&
      (!a.run_id || a.run_id === generation.run_id) &&
      (!a.binding?.run_id || a.binding.run_id === generation.run_id) &&
      (!a.binding?.generation_ref || a.binding.generation_ref === generation.request_id) &&
      (!a.input?.fixed_candidate || canonical(a.input.fixed_candidate) === canonical(generation.result?.candidate)) &&
      (!a.binding?.candidate_id || a.binding.candidate_id === generation.candidate_id) &&
      (!a.result?.artifact?.candidate_id || a.result.artifact.candidate_id === generation.candidate_id));
  }
  function latest(actions, operation) {
    return [...actions].reverse().find(a => a.operation === operation);
  }
  function verdict(action) {
    return action?.result?.review_status === "completed" ? action.result.artifact : null;
  }
  function status(action) {
    const value = verdict(action);
    if (value?.decision_per_approved_policy === "pass") return "已通过本次限定用途筛查";
    if (value?.decision_per_approved_policy === "reject") return "本次用途筛查拒绝（reject）";
    if (value?.decision_per_approved_policy === "incomplete") return "筛查信息不足，暂不推进（incomplete）";
    if (value?.disposition === "proceed_to_R1") return "初审允许进入 R1，科学正确性尚未确认";
    if (value?.disposition === "blocked") return "R0 明确阻断，原候选保留";
    return {ready:"未提交／已保存待执行", running:"执行中，结果尚未保存", waiting_remote:"远端等待，已有任务 ID", blocked:"发送结果不确定，禁止普通重发", failed:"技术失败，不是科学结论"}[action?.task_status] || action?.result?.review_status || "尚未执行";
  }
  function execution(action) {
    const mode = action?.result?.execution_mode || action?.config?.execution_mode;
    return mode === "real_model" ? "真实模型" : mode === "development_fixture" ? "开发替身（非真实模型）" : "执行方式见原始记录";
  }
  function access(view) {
    const label = {abstract:"摘要",full_text:"可访问全文",metadata:"仅元数据",supplement:"补充材料"}[view.access] || view.access;
    return (view.cropped ? "已取得文本的选定片段 · " : "") + label;
  }
  function evidenceKind(status) {
    if (status === "source_report" || status?.includes("source_observation")) return "候选转述的来源报告";
    if (status?.includes("author")) return "作者解释（候选转述）";
    if (status?.includes("conjecture") || status?.includes("hypothes") || status?.includes("proposed")) return "新猜想 · 待检验";
    return "候选中的陈述 · 性质见原文";
  }
  function historical(exported) {
    const results = new Map(exported.results.map(r => [r.task_id, parse(r.output)]));
    const decode = a => {
      const n = {...a, result:results.get(a.task_id)};
      for (const k of ["request","input","config","binding"]) if (n[k]) n[k] = parse(n[k]);
      n.attempts = exported.attempts.filter(p => p.task_id === a.task_id);
      return n;
    };
    return {run:exported.run, generations:exported.generation_actions.map(decode).filter(a=>a.result?.candidate), reviews:exported.candidate_review_actions.map(decode), annotations:exported.human_annotations||[]};
  }
  function annotations(records, target) {
    return records.filter(n=>n.run_id === target.run_id && n.target_kind === target.kind && n.target_ref === target.ref && n.target_sha256 === target.sha256);
  }
  return {boundReviews,latest,verdict,status,execution,access,evidenceKind,historical,annotations};
})();
if (typeof module !== "undefined") module.exports = ReaderFacts;

"use strict";
const readerTabs = new Map();
const readerDrafts = new Map();
function readerText(parent, label, text) {
  if (text == null || text === "") return;
  const section = wbNode("section", undefined, "reading-field");
  if (label) section.append(wbNode("h4", label));
  if (Array.isArray(text)) {
    const list = wbNode("ul");
    for (const item of text) list.append(wbNode("li", typeof item === "string" ? item : JSON.stringify(item, null, 2)));
    section.append(list);
  } else section.append(wbNode("p", typeof text === "string" ? text : JSON.stringify(text, null, 2)));
  parent.append(section);
}
function readerSection(parent, title, intro) {
  const node = wbNode("section", undefined, "scientific-section");
  node.append(wbNode("h3", title));
  if (intro) node.append(wbNode("p", intro, "muted"));
  parent.append(node);
  return node;
}
function readerSources(parent, refs, views, ctx) {
  for (const ref of [...new Set(refs || [])]) {
    const view = views.find(v=>v.id === ref || v.source_ref === ref);
    if (view) parent.append(wbButton(view.source_ref+" · "+ReaderFacts.access(view),()=>wbSource(view,ctx),"source-link"));
    else parent.append(wbNode("p","保存的来源引用尚无可见原文："+ref,"muted"));
  }
}
function readerMechanisms(parent, c, views, ctx) {
  const section = readerSection(parent,"机制步骤","保留候选原始顺序及措辞；来源观察和新猜想分别标记，相邻步骤不表示已证实因果。");
  const list = wbNode("ol",undefined,"mechanism-list");
  for (const step of c.mechanism_steps || []) {
    const item = wbNode("li");
    item.append(wbNode("span",ReaderFacts.evidenceKind(step.status || step.epistemic_status),"epistemic-tag"));
    readerText(item,null,step.relation || step.description || step.step);
    const links = wbNode("details"); links.append(wbNode("summary","原始环节与实际来源关联"));
    readerSources(links,step.source_view_refs,views,ctx); links.append(folded("完整原始环节",step));
    item.append(links); list.append(item);
  }
  section.append(list);
  readerText(section,"候选提出的新因果桥接（未证实）",c.proposed_new_links);
}
function readerPredictions(parent,c) {
  const section = readerSection(parent,"可区分预测","以下问题、比较和测量均取自已保存字段，未添加实验参数。");
  for (const [i,p] of (c.predictions || []).entries()) {
    const card = wbNode("article",undefined,"prediction-card");
    card.append(wbNode("h4","预测 "+(i+1)));
    readerText(card,"待区分的科学问题／竞争解释",p.discriminates_against);
    if (!p.discriminates_against) card.append(wbNode("p","该记录未单列问题标题；比较以下两种预期。","muted"));
    readerText(card,"候选预测",p.claim_prediction);
    readerText(card,"竞争解释的预测",p.alternative_prediction);
    readerText(card,"比较方式",p.comparison);
    readerText(card,"测量指标",p.readout);
    card.append(folded("原始预测字段",p));section.append(card);
  }
}
function readerScience(parent,c,views,ctx) {
  readerText(readerSection(parent,"适用研究情境"),null,c.biological_context);
  readerMechanisms(parent,c,views,ctx);
  const assumptions = readerSection(parent,"必要前提与跨情境假设","前提未确证不等于事实错误；不从缺少直接证据推导确定性阻断。");
  for (const [i,a] of (c.assumption_ledger||[]).entries()) {
    const card = wbNode("article",undefined,"assumption-card");card.append(wbNode("h4","必要前提 "+(i+1)));
    readerText(card,null,a.assumption);readerText(card,"情境迁移边界",a.context_transfer);readerText(card,"候选提出的可能核对",a.possible_check);
    readerSources(card,a.source_view_refs,views,ctx);assumptions.append(card);
  }
  readerText(readerSection(parent,"竞争解释"),null,c.competing_explanations);
  readerPredictions(parent,c);
  readerText(readerSection(parent,"证伪条件","忠实保留候选对有效干预、测量能力及统计解释的限制；不将统计不显著自动解释为证伪。"),null,c.falsification_conditions);
  const plan = readerSection(parent,"验证构想 · 非实验执行许可");
  for (const [key,label] of [["setting","研究情境"],["comparison","比较方式"],["intervention_and_measurement","干预与测量"],["controls","必要控制"]]) readerText(plan,label,c.validation_concept?.[key]);
  readerText(readerSection(parent,"近邻研究范围"),null,c.nearest_prior_work_scope);
  readerText(readerSection(parent,"候选原始限制"),null,c.limitations);
}
function readerEvidence(parent,c,views,ctx) {
  parent.append(wbNode("p","候选的证据转述、保存的模型阅读卡与原文分区展示。合法引用不代表证据已核实，未直接支持的新桥接不是已有事实。","reading-notice"));
  const cards = (ctx.generation?.input?.actual_frozen_seed_background_packet?.retained_contexts||[]).flatMap(r=>r.finding_cards||[]);
  for (const [i,a] of (c.evidence_anchors||[]).entries()) {
    const card = wbNode("article",undefined,"evidence-card");
    card.append(wbNode("span",ReaderFacts.evidenceKind(a.epistemic_status),"epistemic-tag"),wbNode("h3","证据锚点 "+(i+1)));
    readerText(card,"候选所报告的来源内容及关系",a.reported_basis);
    const view = views.find(v=>v.id===a.source_view_ref);
    if (view) {
      card.append(wbNode("p",view.source_ref+" · "+ReaderFacts.access(view)+" · 字符 "+view.character_range.join("–"),"access-badge"));
      readerText(card,"材料选择与访问限制",[view.selection_reason,view.access_limitations].filter(Boolean));
      readerSources(card,[view.id],views,ctx);
    } else card.append(wbNode("p","此锚点未绑定可见原文，不能补造来源支持。","muted"));
    const finding = cards.find(f=>f.id===a.finding_ref);
    if (finding) {
      const d=wbNode("details");d.append(wbNode("summary","对应模型阅读卡 · 不是原始来源"));
      readerText(d,"实际研究情境（保存的模型解读）",finding.biological_context);
      readerText(d,"干预／对照",finding.intervention_comparator);
      readerText(d,"实测终点",finding.endpoint);
      readerText(d,"来源观察的模型转述",finding.reported_observation);
      readerText(d,"作者解释的模型转述",finding.author_interpretation);
      readerText(d,"模型摘录的引文 · 需对照原文",finding.supporting_quote);
      readerText(d,"阴性结果",finding.negative_findings);
      readerText(d,"未建立事项",finding.not_established);
      d.append(folded("完整原始阅读卡",finding));card.append(d);
    }
    card.append(folded("完整原始锚点",a));parent.append(card);
  }
  readerText(readerSection(parent,"新机制桥接 · 不作为来源已有证据"),null,c.proposed_new_links);
  const sourceList=readerSection(parent,"实际可见文献与材料范围");
  for (const view of views) {
    const d=wbNode("article",undefined,"source-card");d.append(wbNode("h4",view.source_ref),wbNode("p",ReaderFacts.access(view)+" · "+view.representation));
    readerText(d,"定位与未阅读范围",[view.locator,"字符 "+view.character_range.join("–")+" / "+view.original_characters,"未读范围："+JSON.stringify(view.not_read_ranges||[])]);
    readerText(d,"访问限制",view.access_limitations);readerSources(d,[view.id],views,ctx);sourceList.append(d);
  }
}
function readerReview(parent,action,operation,ctx) {
  const heading=operation==="P09"?"Candidate Ethics · 候选限定用途筛查":"R0 · 初步科学检查";
  const section=readerSection(parent,heading);
  section.append(wbNode("p",ReaderFacts.status(action),"review-verdict"));
  if (!action) {section.append(wbNode("p","尚无该候选对应的已保存审查记录。"));return;}
  const value=ReaderFacts.verdict(action);const policy=action.request.policy;
  section.append(wbNode("p",ReaderFacts.execution(action)+" · "+(policy?.mode==="development"?"非生产政策":"政策模式："+(policy?.mode||"未配置")),"mode"));
  readerText(section,"正式结果与执行状态",[value?.decision_per_approved_policy||value?.disposition||"未形成完成决定",action.task_status||action.result?.review_status]);
  readerText(section,"政策版本",policy?policy.id+"@"+policy.version:"未配置");
  if (operation==="P09") {
    readerText(section,"本次实际用途",action.request.intended_use);
    readerText(section,"审查理由",value?.rationale);readerText(section,"具体风险",value?.specific_risks);
    readerText(section,"限制与缺少信息",value?.limitations_or_missing_context);
    section.append(wbNode("p","限定用途 pass 不等于组织伦理批准、实验执行许可或科学验证；不能继承 Goal Ethics 的开发结果。","reading-notice"));
  } else {
    readerText(section,"Goal 对齐",value?.goal_alignment);
    const defects=readerSection(section,"达到 R0 阻断标准的缺陷");
    if (value && !value.blocking_defects?.length) defects.append(wbNode("p","无达到本次 R0 阻断标准的缺陷；这不是全面事实核验。"));
    for (const defect of value?.blocking_defects||[]) {
      readerText(defects,"具体问题",defect.defect);readerText(defects,"候选片段",defect.candidate_span);readerText(defects,"为何属于不可缺少的核心前提",defect.why_indispensable);
      const basis=defect.actual_visible_basis;
      if(basis){readerText(defects,"实际原文引文",basis.quote);readerText(defects,"原文位置与访问范围",["字符 "+basis.start+"–"+basis.end,basis.access]);readerText(defects,"审查记录中的可靠性理由",basis.reliability_reason);readerSources(defects,[basis.source_view_ref],action.input?.actual_visible_source_views||[],ctx);}
      defects.append(folded("完整阻断依据",defect));
    }
    const unknowns=readerSection(section,"科学未知 · "+(value ? value.scientific_unknowns.length+" 项" : "尚无完成记录"));readerText(unknowns,null,value?.scientific_unknowns);
    const checks=readerSection(section,"后续 R1 核查事项 · "+(value ? value.required_R1_checks.length+" 项" : "尚无完成记录"),"保留每条正式核查原文；尚未执行 R1，不代表这些问题已有答案。");readerText(checks,null,value?.required_R1_checks);
    readerText(section,"适用范围及审查限制",value?.limitations);
    section.append(wbNode("p","R1 尚未执行，新系统相应能力尚未实现。没有 R1 执行按钮。","reading-notice"));
  }
  if (action.error || action.result?.parse_error) readerText(section,"执行问题（非科学结论）",action.result?.parse_error||action.error.message);
  section.append(folded("完整原始正式审查记录",action));
}
function readerSummary(parent,c,ctx,reviews) {
  parent.append(wbNode("span",ctx.readOnly?"历史真实研究 · 只读":"保存的候选 · 科学未验证","eyebrow"),wbNode("h2",c.title),wbNode("p",c.scoped_claim,"scoped-claim"));
  const stages=wbNode("div",undefined,"candidate-stages");
  stages.append(wbNode("p","候选生成：已生成并保存 · "+ReaderFacts.execution(ctx.generation)));
  for (const [op,label] of [["P09","Candidate Ethics"],["P10","R0"]]) {const a=ReaderFacts.latest(reviews,op);stages.append(wbNode("p",label+"："+ReaderFacts.status(a)+(a?" · "+ReaderFacts.execution(a)+" · "+(a.request.policy?.mode==="development"?"非生产政策":"政策范围见记录"):"")));}
  stages.append(wbNode("p","science_validated=false · 未获科学准入"));parent.append(stages);
  const overview=wbNode("details",undefined,"mechanism-overview");overview.open=true;overview.append(wbNode("summary","机制关系 · 条件性待检验猜想"));
  readerText(overview,null,c.proposed_new_links?.length?c.proposed_new_links:(c.mechanism_steps||[]).map(s=>s.relation));parent.append(overview);
  const premises=wbNode("div",undefined,"premise-summary");
  readerText(premises,"关键必要前提（候选原文）",c.assumption_ledger?.[0]?.assumption);
  const r0=ReaderFacts.verdict(ReaderFacts.latest(reviews,"P10"));
  readerText(premises,"当前首项科学未知（完整列表见科学审查）",r0?.scientific_unknowns?.[0]);parent.append(premises);
  const next=ReaderFacts.verdict(ReaderFacts.latest(reviews,"P09"));
  parent.append(wbNode("p",r0?.disposition==="proceed_to_R1"?"下一步：等待 R1 能力；本工作台不执行 R1。":r0?.disposition==="blocked"?"当前边界：R0 已阻断，原文保留；不自动修复。":next?.decision_per_approved_policy==="pass"?"下一步：可在科学审查标签查看并显式执行既有 R0 操作。":"下一步：查看科学审查；无有效 Candidate Ethics pass 时不能建立 R0。","reading-notice"));
}
function readerNoteRecords(root,records) {
  root.replaceChildren();
  for (const n of records) {
    const article=wbNode("article",undefined,"human-note");article.append(wbNode("span","独立人工意见 · "+n.created_at,"eyebrow"));
    for (const [key,value] of Object.entries(n.observations||{})) readerText(article,key,value);
    readerText(article,"个人意见",n.note);article.append(folded("对象及内容版本绑定",n));root.append(article);
  }
  if (!records.length) root.append(wbNode("p","此内容版本尚无独立人工意见。","muted"));
}
async function readerNotes(root,ctx,kind,ref) {
  root.replaceChildren(wbNode("p","读取已保存的独立人工意见……","muted"));
  if (ctx.readOnly) {root.replaceChildren(wbNode("p","这是独立只读历史来源，不能在此持久化意见；没有保存、修复或执行按钮。","reading-notice"));const list=wbNode("div");readerNoteRecords(list,(ctx.annotations||[]).filter(n=>n.target_kind===kind&&n.target_ref===ref));root.append(list);return;}
  const runId=ctx.runId;
  try {
    const data=await api('/api/annotations?run_id='+encodeURIComponent(runId));
    if (!root.isConnected || state.run?.run.id!==runId) return;
    root.replaceChildren();
    const target=data.targets.find(t=>t.kind===kind&&t.ref===ref);
    if (!target) {root.append(wbNode("p","此来源仅存在于冻结模型输入中，没有后端支持的 material_view 注释目标，无法在这里持久化意见。","reading-notice"));return;}
    const binding={...target,run_id:runId};const draftKey=[runId,kind,ref,target.sha256].join(":");
    const fields=kind==="candidate"?['证据忠实性','机制价值','可检验性','主要问题']:kind==="run"?['检索相关性','重要遗漏','研究过程问题']:['实验情境是否保留','阴性结果是否保留','作者措辞是否忠实'];
    const draft=readerDrafts.get(draftKey)||{};
    const form=wbNode("form",undefined,"inline-assessment");
    form.append(wbNode("p","自动绑定当前"+(kind==="candidate"?"候选":kind==="run"?"研究":"原文视图")+"及内容版本。意见不会改写科学结果，也不会自动进入模型输入。","muted"));
    const inputs={};
    for (const name of [...fields,'个人意见']) {const label=wbNode("label",name);const input=wbNode("textarea");input.rows=2;input.value=draft[name]||"";input.oninput=()=>{const d=readerDrafts.get(draftKey)||{};d[name]=input.value;readerDrafts.set(draftKey,d);};label.append(input);form.append(label);inputs[name]=input;}
    const save=wbNode("button","保存当前对象的独立判断","primary");save.type="submit";save.disabled=state.busy;form.append(save);
    const message=wbNode("p",state.busy?"本机写操作执行中；可继续阅读，待完成后保存意见。":"","muted");message.classList.add("assessment-status");form.append(message);
    const list=wbNode("div");readerNoteRecords(list,ReaderFacts.annotations(data.records,binding));
    form.onsubmit=e=>{e.preventDefault();action(async()=>{
      if (state.run?.run.id!==runId) throw new Error("运行已切换，请回到对应研究再保存意见。");
      const observations=Object.fromEntries(fields.map(name=>[name,inputs[name].value]));
      await api('/api/annotations',{run_id:runId,target_kind:kind,target_ref:ref,target_sha256:target.sha256,category:kind==="candidate"?'generation':kind==="run"?'retrieval':'reading',observations,note:inputs['个人意见'].value});
      readerDrafts.delete(draftKey);message.textContent="已保存独立人工意见；原始科学内容和正式审查结果保持不变。";
      await readerNotes(root,ctx,kind,ref);
    });};
    root.append(form,list);
  } catch(e) {if(root.isConnected)root.replaceChildren(wbNode("p",e.message,"reading-notice"));}
}
function readerCandidate(parent,c,views,ctx) {
  const reviews=ReaderFacts.boundReviews(ctx.generation,ctx.reviews||[]);
  const key=[ctx.readOnly?"history":"live",ctx.runId,c.candidate_id].join(":");
  parent.replaceChildren();parent.classList.add("candidate-reader");
  readerSummary(parent,c,ctx,reviews);
  const nav=wbNode("div",undefined,"candidate-tabs");nav.setAttribute("role","tablist");nav.setAttribute("aria-label","当前候选科学阅读");
  const body=wbNode("div",undefined,"candidate-tab-body");
  const buttons=[];const panes=[];
  function select(name) {
    readerTabs.set(key,name);
    buttons.forEach(b=>{const active=b.dataset.tab===name;b.setAttribute("aria-selected",String(active));b.tabIndex=active?0:-1;});
    panes.forEach(p=>p.hidden=p.dataset.tab!==name);
    if (name==="assessment") readerNotes(panes.find(p=>p.dataset.tab===name),ctx,"candidate",c.candidate_id);
  }
  for (const [name,label,render] of [
    ['science','科学内容',p=>readerScience(p,c,views,ctx)],
    ['evidence','证据与来源',p=>readerEvidence(p,c,views,ctx)],
    ['review','科学审查',p=>{readerReview(p,ReaderFacts.latest(reviews,'P09'),'P09',ctx);readerReview(p,ReaderFacts.latest(reviews,'P10'),'P10',ctx);if(!ctx.readOnly){const host=wbNode('div',undefined,'candidate-review-controls');host.dataset.candidateId=c.candidate_id;p.append(host);}}],
    ['assessment','我的评估',()=>{}],
  ]) {
    const button=wbButton(label,()=>select(name));button.dataset.tab=name;button.setAttribute("role","tab");button.setAttribute("aria-controls",key+":"+name);button.id=key+":tab:"+name;
    button.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const i=buttons.indexOf(button);const n=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[n].click();buttons[n].focus();}};
    const pane=wbNode("section");pane.dataset.tab=name;pane.id=key+":"+name;pane.setAttribute("role","tabpanel");pane.setAttribute("aria-labelledby",button.id);render(pane);nav.append(button);buttons.push(button);body.append(pane);panes.push(pane);
  }
  parent.append(nav,body);
  const judge=wbButton(ctx.readOnly?"查看独立人工意见（只读）":"记录我的判断",()=>{select('assessment');body.scrollIntoView({block:'start',behavior:'smooth'});},"reader-judge");parent.insertBefore(judge,nav);
  const raw=folded("完整原始记录：候选、冻结输入、模型请求／响应与用量",{candidate:c,generation:ctx.generation,reviews});raw.classList.add('reader-raw');
  if (!ctx.readOnly) for (const a of [ctx.generation,...reviews]) for (const attempt of a.attempts||[]) {
    const button=wbButton("读取保存的"+(a.operation||'P08')+"请求／原始响应",async()=>{try{const path=a.operation?'/api/candidate-review/attempt':'/api/generation/attempt';const result=await api(path+'?attempt_id='+encodeURIComponent(attempt.id));raw.append(folded('已保存的完整调用事实',result));}catch(e){wbError(e);}});raw.append(button);
  }
  parent.append(raw);select(readerTabs.get(key)||'science');
}

"use strict";
// Live data only. User-supplied embedded records execute solely inside the history sandbox.
const wb = {view:"home", subpanel:"acquisition", candidate:null, run:null, targets:[], refresh:0, history:null, historyCandidate:null};
const wbTitles = {home:"我的研究",overview:"研究概览",brief:"研究简报",candidates:"候选假说",literature:"文献与背景",reviews:"Candidate Ethics／R0",activity:"研究过程",notes:"人工评估与个人笔记",settings:"设置",history:"历史演示"};

function wbNode(tag,text,cls) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function wbShow(view) {wb.view=view;document.querySelectorAll('main>.view').forEach(n=>n.hidden=n.id!=='wb-'+view);document.querySelectorAll('[data-nav]').forEach(n=>n.classList.toggle('active',n.dataset.nav===view));el('wb-title').textContent=(state.project&&view!=='home'?el('name').value+' · ':'')+wbTitles[view];wbRender();window.scrollTo({top:0,behavior:'instant'});}
function wbButton(text,fn,cls) {const b=wbNode('button',text,cls);b.type='button';b.dataset.readOnly='true';b.onclick=fn;return b;}
function wbSource(view,ctx={readOnly:true}) {
  el('wb-source-title').textContent=view.source_ref;
  el('wb-source-meta').textContent=ReaderFacts.access(view)+' · 字符 '+view.character_range.join('–')+' / '+view.original_characters+'；'+view.access_limitations+'；原文未改写，图像/补充未查看。';
  el('wb-source-text').textContent=view.text;
  const extra=el('wb-source-annotations');extra.replaceChildren();
  if(view.source_citation && /^https?:\/\//.test(view.source_citation)){const link=wbNode('a','原始来源入口');link.href=view.source_citation;link.target='_blank';link.rel='noopener noreferrer';extra.append(link);}
  if(ctx.readOnly)extra.append(wbNode('p','独立只读来源；不能在此保存意见。','reading-notice'));
  else extra.append(wbButton('记录来源问题',()=>{const host=wbNode('div');extra.replaceChildren(host);readerNotes(host,ctx,'material_view',view.id);}));
  el('wb-source-dialog').showModal();
}
function wbCandidate(parent,c,views,ctx) {readerCandidate(parent,c,views,ctx);}
function wbCandidates() {
 const actions=state.run&&generationData?.actions||[];
 const generated=actions.filter(a=>a.result?.candidate);
 if(!generated.some(a=>a.candidate_id===wb.candidate))wb.candidate=generated[0]?.candidate_id||null;
 const list=el('wb-candidate-index');list.replaceChildren();
 for(const a of generated){const b=wbButton(a.result.candidate.title+' · '+a.request.mode,()=>{wb.candidate=a.candidate_id;wbCandidates();},'candidate-choice'+(a.candidate_id===wb.candidate?' selected':''));list.append(b);}
 const selected=generated.find(a=>a.candidate_id===wb.candidate);
 const previousPanels=[...document.querySelectorAll('#wb-review-records .candidate-review,#wb-scientific-reader .candidate-review')];
 const reader=el('wb-scientific-reader');
 const ctx=selected?{generation:selected,runId:state.run.run.id,reviews:candidateReviewData?.actions||[],readOnly:false}:null;
 if(selected)wbCandidate(reader,selected.result.candidate,selected.input.actual_frozen_seed_background_packet.source_views,ctx);
 else reader.replaceChildren(wbNode('h2','等待已保存的候选'),wbNode('p','先完成资料准备并选择ready方向，再由你点击生成。这里不会显示占位候选。','muted'));
 const reviewRoot=el('wb-review-records');
 reviewRoot.replaceChildren();
 if(generated.length){const label=wbNode('label','选择已保存候选');const select=document.createElement('select');select.id='wb-review-candidate';for(const a of generated){const o=wbNode('option',a.result.candidate.title+' · '+a.request.mode);o.value=a.candidate_id;select.append(o);}select.value=wb.candidate;select.onchange=()=>{wb.candidate=select.value;wbCandidates();};label.append(select);reviewRoot.append(label,wbButton('打开当前候选的科学审查',()=>{readerTabs.set(['live',state.run.run.id,wb.candidate].join(':'),'review');wbShow('candidates');}));}
 else reviewRoot.append(wbNode('p','没有已保存候选，不能执行候选伦理或R0。','muted'));
 for(const a of actions){
   const card=[...document.querySelectorAll('#generation-records .candidate-card')].find(n=>n.dataset.candidateId===a.candidate_id);
   const panel=card?.querySelector('.candidate-review')||previousPanels.find(n=>n.dataset.candidateId===a.candidate_id);
   if(!panel)continue;panel.dataset.candidateId=a.candidate_id;
   // Controls are kept separate from the scientist-facing saved result and never auto-run.
   const advanced=wbNode('details');advanced.className='review-execution-controls';advanced.append(wbNode('summary','显式操作、远端查询与高级政策设置'),panel);
   panel.hidden=false;
   if(a.candidate_id===wb.candidate){reader.querySelector('.candidate-review-controls')?.append(advanced);}
   else {advanced.hidden=true;reviewRoot.append(advanced);}
 }

}
async function wbHome() {
 const token=++wb.refresh;const projectsList=await api('/api/projects');
 const projectsData=await Promise.all(projectsList.map(p=>api('/api/project?id='+encodeURIComponent(p.id))));if(token!==wb.refresh)return;
 const root=el('wb-studies');root.replaceChildren();
 for(const data of projectsData){const card=wbButton('',async()=>{await action(async()=>{await project(data.project.id);if(data.runs.length)await showRun(data.runs[0].id);});if(wb.view==='home')wbShow(data.runs.length?'overview':'brief');},'study-card');card.append(wbNode('span',data.runs.length+' 个固定运行','badge'),wbNode('h3',data.project.name),wbNode('p',data.revisions[0]?.content.question||'尚无简报'));root.append(card);}
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
 const root=el('wb-overview-summary');root.replaceChildren();if(!state.run){root.append(wbNode('div','请选择已保存运行，或保存简报后创建固定运行。','panel'),wbButton('查看／编辑研究简报',()=>wbShow('brief')));return;}
 root.append(wbNode('div',(labels[state.run.run.status]||state.run.run.status)+' · 刷新只读，执行须由你发起。','panel'));
 const actions=wbNode('div',undefined,'toolbar');for(const [label,view] of [['查看／编辑研究简报','brief'],['检索与材料','literature'],['独立人工评估汇总','notes'],['候选审查汇总','reviews']])actions.append(wbButton(label,()=>wbShow(view)));root.append(actions);
 const latest=readerSection(root,'最新研究内容');
 const background=[...(backgroundData?.actions||[])].reverse().find(a=>a.operation==='P05'&&a.result?.artifact);
 if(background)readerText(latest,'已保存背景综合 · 非独立事实核验',background.result.artifact.overview);
 else latest.append(wbNode('p','尚无已保存背景综合。','muted'));
 const generated=(generationData?.actions||[]).filter(a=>a.result?.candidate);
 if(generated.length){const a=generated.at(-1);readerText(latest,'最近候选：'+a.result.candidate.title,a.result.candidate.scoped_claim);}
 const candidates=readerSection(root,'候选摘要','按保存记录列出，不计算得分、排序或推荐 Winner。');
 for(const a of generated){const card=wbNode('article',undefined,'overview-candidate');card.append(wbButton(a.result.candidate.title,()=>{wb.candidate=a.candidate_id;wbShow('candidates');},'candidate-title'));readerText(card,null,a.result.candidate.scoped_claim);const reviews=ReaderFacts.boundReviews(a,candidateReviewData?.actions||[]);for(const [op,label] of [['P09','Candidate Ethics'],['P10','R0']]){const a=ReaderFacts.latest(reviews,op);card.append(wbNode('p',label+'：'+ReaderFacts.status(a)+(a?' · '+ReaderFacts.execution(a):'')));};candidates.append(card);}
 if(!generated.length)candidates.append(wbNode('p','当前 Run 尚无候选；不会显示其他研究或历史演示结果。','muted'));
 const progress=readerSection(root,'当前进展与待解决问题');
 const done=[...state.run.tasks].reverse().find(t=>t.status==='succeeded');if(done)progress.append(wbNode('p','最近完成：'+wbTaskName(done.module)));
 if(state.run.run.status==='awaiting_r1')progress.append(wbNode('p','等待 R1 能力，尚未执行；新系统未实现 M03/R1/Ranking/Evolution。'));
 for(const a of generated){const r0=ReaderFacts.verdict(ReaderFacts.latest(ReaderFacts.boundReviews(a,candidateReviewData?.actions||[]),'P10'));if(r0){readerText(progress,'科学未知（原始记录）',r0.scientific_unknowns);readerText(progress,'待 R1 核查（尚未执行）',r0.required_R1_checks);}}
 const abnormal=state.run.tasks.filter(t=>['failed','blocked','waiting_remote','running'].includes(t.status));for(const t of abnormal)progress.append(wbNode('p',wbTaskName(t.module)+'：'+({failed:'技术失败，查看保存错误；不改判科学否定。',blocked:'发送结果不确定，停止普通重发。',waiting_remote:'已有远端 ID，只有显式同 ID 查询。',running:'执行结果尚未收尾，刷新仅读取本地状态。'}[t.status])));
 if(abnormal.length)progress.append(wbButton('查看持久化过程与允许操作',()=>wbShow('activity')));
}
function wbTaskName(module) {return module.startsWith('background.')?backgroundTaskLabels[module.split('.').at(-1)]||'背景准备':module.startsWith('literature.')?'检索与材料':module.startsWith('generation.')?'候选生成':module.startsWith('candidate_review.')?'独立候选审查':module.includes('prepare')?'目标制备':'目标前置';}
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
 root.replaceChildren();for(const n of data.records){const card=wbNode('article',undefined,'panel');card.append(wbNode('span','独立人工意见 · '+n.created_at,'eyebrow'),wbNode('h3',wb.targets.find(t=>t.ref===n.target_ref)?.label||'已保存内容版本'));for(const [key,value] of Object.entries(n.observations))readerText(card,key,value);card.append(wbNode('h3','个人意见'),wbNode('p',n.note),folded('绑定的Run、对象及内容版本',n));root.append(card);}if(!data.records.length)root.append(wbNode('p','尚无人工意见。意见只保存在独立后端记录。','muted'));
}
function wbRender() {document.querySelectorAll('.inline-assessment button[type="submit"]').forEach(b=>b.disabled=state.busy);if(!state.busy)document.querySelectorAll(".assessment-status").forEach(n=>{if(n.textContent.startsWith("本机写操作"))n.textContent="当前可保存；意见与科学结果独立。";});document.querySelectorAll("[data-nav],#refresh").forEach(b=>b.disabled=false);if(!state.config)return;if(wb.run!==state.run?.run.id){wb.run=state.run?.run.id;wb.candidate=null;}el('wb-title').textContent=(state.project&&wb.view!=='home'?el('name').value+' · ':'')+wbTitles[wb.view];el('wb-export').disabled=!state.run;el('wb-open-history').disabled=!state.config.history_available;wbOverview();wbCandidates();wbRunStatus();wbSettings();wbActivity();wbCounts();el('wb-acquisition').hidden=wb.subpanel!=='acquisition';el('wb-background').hidden=wb.subpanel!=='background';if(wb.view==='home')wbHome().catch(wbError);if(wb.view==='notes')wbNotes().catch(wbError);}
function wbError(e) {el('notice').textContent=e.message;}
document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.subpanel)wb.subpanel=b.dataset.subpanel;wbShow(b.dataset.nav);});
document.querySelectorAll('[data-new-study]').forEach(b=>b.onclick=()=>{reset();wbShow('brief');});
el('new-project').onclick=()=>{reset();wbShow('brief');};
el('goal-test-choice').onchange=updateActions;
el('wb-close-source').onclick=()=>el('wb-source-dialog').close();
el('wb-note-category').onchange=wbRubric;wbRubric();
el('wb-note-form').onsubmit=e=>{e.preventDefault();action(async()=>{const target=wb.targets.find(t=>t.kind+':'+t.ref===el('wb-note-target').value);if(!target)throw new Error('请选择本运行已保存的对象');const observations={};el('wb-note-rubric').querySelectorAll('textarea').forEach(t=>{observations[t.dataset.rubric]=t.value;});await api('/api/annotations',{run_id:state.run.run.id,target_kind:target.kind,target_ref:target.ref,target_sha256:target.sha256,category:el('wb-note-category').value,observations,note:el('wb-note-text').value});el('wb-note-text').value='';el('wb-note-rubric').querySelectorAll('textarea').forEach(t=>{t.value='';});await wbNotes();el('notice').textContent='独立人工意见已保存；没有修改或发送模型输入。';});};
el('wb-export').onclick=()=>action(async()=>{const data=await api('/api/export?run_id='+encodeURIComponent(state.run.run.id));const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='co-scientist-run-'+state.run.run.id+'.json';a.click();URL.revokeObjectURL(url);});
el('wb-open-demo').onclick=()=>{wb.history=null;wbRunStatus();const f=el('wb-demo-frame');if(!f.getAttribute('src'))f.src='/history.html';f.hidden=false;el('wb-history-records').replaceChildren();};
function wbHistorical() {
 const data=wb.history;wbRunStatus();const root=el('wb-history-records');root.replaceChildren(wbNode('div','历史 ALS · 后端只读保存记录；不写当前研究，不执行或查询供应商。','mode'));
 if(!data?.export){root.append(wbNode('p','没有历史记录'));return;}
 const history=ReaderFacts.historical(data.export);if(!history.generations.some(a=>a.candidate_id===wb.historyCandidate))wb.historyCandidate=history.generations[0]?.candidate_id;
 const intro=readerSection(root,'历史研究概览');readerText(intro,'当前阶段',labels[history.run.status]||history.run.status);
 for(const a of history.generations)intro.append(wbButton(a.result.candidate.title,()=>{wb.historyCandidate=a.candidate_id;wbHistorical();},'candidate-choice'));
 const a=history.generations.find(a=>a.candidate_id===wb.historyCandidate);
 if(a){const host=wbNode('article',undefined,'panel');root.append(host);readerCandidate(host,a.result.candidate,a.input.actual_frozen_seed_background_packet.source_views,{generation:a,reviews:history.reviews,runId:history.run.id,annotations:history.annotations,readOnly:true});}
 root.append(folded('历史只读完整原始记录',data.export));
}
el('wb-open-history').onclick=async()=>{try{wb.history=await api('/api/history');el('wb-demo-frame').hidden=true;wbHistorical();}catch(e){wbError(e);}};
function wbRunStatus() {
 const root=el('wb-run-status');if(wb.view==='history'&&wb.history?.export){root.textContent='只读历史运行：'+(labels[wb.history.export.run.status]||wb.history.export.run.status)+' · 不写入当前研究、不执行或查询供应商。';return;}if(!state.run){root.textContent='未选择固定运行 · 查看与导航不发送请求';return;}
 const last=state.run.tasks.at(-1);root.textContent=(labels[state.run.run.status]||state.run.run.status)+' · '+({running:'执行中，刷新只读取本地状态；断连不自动重发。',waiting_remote:'远端等待，需显式查询已保存 ID。',blocked:'发送结果不确定，无普通重发。',failed:'技术失败，不代表科学结论。'}[last?.status]||'仅展示保存事实；不代表科学验证。');
}

document.addEventListener('workspace-change',wbRender);
// Technical IDs/versions remain available without taking over the primary workflow.
for(const id of ['background-prompt','generation-prompt']){const node=el(id);if(node){const d=document.createElement('details');d.append(wbNode('summary','高级：当前Prompt版本与执行边界'));node.before(d);d.append(node);}}
wbShow('home');
