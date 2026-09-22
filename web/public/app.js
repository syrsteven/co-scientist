import { stages, label, escape as e, arr, fmt, short, role, stageState, taskDisplayState, costSummary, normalize, admission, ranked, parents, parseFolder, callApplied, workerStatus, allowedControl, feedbackUsage } from "./model.js";
import { createSettings } from "./settings.js";
import { createRetry } from "./retry.js";
import { createScientistFeedback } from "./scientist.js";

const $ = id => document.getElementById(id);
const state = { data:null, runs:[], id:null, view:"overview", epoch:null, search:"", filter:"all", selected:null, generation:0, loading:false };
const requestedView=new URL(location.href).searchParams.get("view");
if(["overview","hypotheses","evidence","tournament","tasks","events","costs","settings"].includes(requestedView))state.view=requestedView;
const settings = createSettings({getRun:()=>state.data,notify:message=>toast(message),isActive:()=>state.view==="settings",onPreferences:()=>sourceStatus()});
const retryUI=createRetry({getRun:()=>state.data,getId:()=>state.id,notify:message=>toast(message),refresh:id=>loadRun(id)});
const scientistUI=createScientistFeedback({getRun:()=>state.data,getId:()=>state.id,notify:message=>toast(message),refresh:id=>loadRun(id)});
const chip = (text,tone="") => `<span class="chip ${e(tone)}">${e(text)}</span>`;
const tone = value => ["pass","passed","succeeded","completed","applied","domain_result_applied","decisive"].includes(value)?"pass":/failed|reject|invalid|needs_attention/.test(value)?"reject":["needs_more_evidence","not_assessed","inconclusive","needs_tiebreaker","blocked"].includes(value)?"warning":"partial";
const inspect = (type,id) => `data-inspect="${e(type)}" data-id="${e(id)}"`;
const empty = text => `<div class="empty">${e(text)}</div>`;
const section = (title,body,extra="") => `<section class="card"><div class="card-head"><h2>${e(title)}</h2>${extra}</div><div class="card-body">${body}</div></section>`;
const detail = (title,body) => `<section class="detail-section"><h3>${e(title)}</h3>${body}</section>`;
const list = values => arr(values).length ? `<ul>${values.map(v=>`<li>${e(typeof v==="object"?JSON.stringify(v):v)}</li>`).join("")}</ul>` : `<p class="muted">未记录</p>`;
const raw = (title,obj) => `<details class="raw"><summary>${e(title)}</summary><pre>${e(JSON.stringify(obj,null,2))}</pre></details>`;
const kv = obj => `<dl class="detail-kv">${Object.entries(obj).map(([k,v])=>`<dt>${e(k)}</dt><dd>${e(v ?? "—")}</dd>`).join("")}</dl>`;
const date = value => value ? new Date(value).toLocaleString("zh-CN",{hour12:false}) : "未记录时间";
const hyp = id => state.data.hypotheses.find(h=>h.hypothesis_id===id);
const name = id => hyp(id)?.title || id;
const shortId = id => String(id || "").match(/^H\d+/)?.[0] || short(id,22);
const currentEpoch = () => state.epoch || Object.keys(state.data.ratings)[0];
const sources = () => arr(state.data.literature.source_documents);
const taskCalls = id => state.data.external_calls.filter(c=>c.task_id===id);
const costsFor = calls => state.data.costs.filter(c=>calls.some(x=>x.external_call_id===c.external_call_id));
const query = value => JSON.stringify(value).toLowerCase().includes(state.search.toLowerCase());
const runReason = d => ["running","created"].includes(d.manifest.final_state)?null:d.manifest.stop_reason || d.events.filter(ev=>/RunNeedsAttention|RunFailed|RunPaused|RunCancelled/.test(ev.event_type)).at(-1)?.payload.reason;
let toastTimer;
function toast(text) { $("toast").textContent=text; $("toast").classList.remove("hidden"); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$("toast").classList.add("hidden"),5000); }

function sourceStatus(error=false) {
  const source=state.data?._source;
  const prefs=settings.getPreferences();
  $("sourceLabel").textContent=error ? "连接中断 · 显示上次快照" : state.view==="settings"?"编辑设置 · 轮询暂停":source?.kind==="database" ? `数据库监控 · ${prefs.autoRefresh?`每 ${prefs.pollSeconds} 秒刷新`:"手动刷新"}` : "历史快照 · 不自动更新";
  document.querySelector(".status-dot").classList.toggle("offline",error || source?.kind!=="database");
}
function renderHeader() {
  const d=state.data,m=d.manifest,c=costSummary(d.costs);
  $("runName").textContent=m.run_id; $("runName").title=m.run_id;
  $("runState").textContent=label(m.final_state); $("runState").className=`state-pill state-${m.final_state}`;
  $("sequence").textContent=`SEQ ${m.current_sequence ?? d.events.at(-1)?.sequence ?? 0} · ${m.providers?.llm || "未指定模型"}`;
  $("goalTitle").textContent="研究驾驶舱";
  let goal=$("goalDescription");
  if(!goal) { goal=document.createElement("p"); goal.id="goalDescription"; goal.className="goal-description"; $("goalTitle").after(goal); }
  goal.textContent=m.goal?.title || m.run_id;
  const admitted=d.hypotheses.filter(h=>admission(d,h,currentEpoch())).length;
  $("metrics").innerHTML=[
    ["候选假设",fmt(d.hypotheses.length),`${admitted} 个获准进入当前竞技场`],
    ["评审产物",fmt(d.reviews.length),`${d.reviews.filter(r=>hyp(r.hypothesis_id)).length} 候选 + ${d.reviews.filter(r=>!hyp(r.hypothesis_id)).length} 固定 Anchor`],
    ["对比比赛",fmt(d.matches.length),`${d.matches.filter(m=>m.rating_updated).length} 场更新 rating`],
    ["外部调用",fmt(d.external_calls.length),`${fmt(c.input+c.output)} tokens · 已记账`],
    ["已定价费用",c.unpriced?"未定价":d.costs.length?`$${c.usd.toFixed(4)}`:"暂无账目", c.unpriced?`另有 ${c.unpriced} 笔未定价 · 已定价 $${c.usd.toFixed(4)}`:`已记录 $${c.usd.toFixed(4)} USD`],
  ].map(([title,value,note])=>`<div class="metric"><small>${e(title)}</small><strong>${e(value)}</strong><span>${e(note)}</span></div>`).join("");
  sourceStatus();
}

function toolbar(options=[]) {
  return `<div class="toolbar"><label class="search"><span aria-hidden="true">⌕</span><input id="viewSearch" type="search" placeholder="搜索当前视图…" aria-label="搜索当前视图" value="${e(state.search)}"></label>${options.length?`<select id="viewFilter" aria-label="筛选当前视图">${options.map(([v,t])=>`<option value="${e(v)}" ${v===state.filter?"selected":""}>${e(t)}</option>`).join("")}</select>`:""}</div>`;
}
function rankingRows() {
  const rows=ranked(state.data,currentEpoch());
  return rows.length ? `<div class="rank-list">${rows.map(([id,rating],i)=>`<button class="rank-row" ${inspect("hypothesis",id)}><span class="rank-number">${String(i+1).padStart(2,"0")}</span><span class="truncate" title="${e(name(id))}">${e(shortId(id))} · ${e(name(id))}</span><span class="rating-bar"><span style="width:${Math.max(3,Math.min(100,(rating-1000)/4))}%"></span></span><span class="rating">${Number(rating).toFixed(1)}</span></button>`).join("")}</div>` : empty("尚无准入候选的排名。审查尚未通过不等于系统故障。");
}
function budgetView() {
  const d=state.data,b=d.manifest.profile?.budget||{}, c=costSummary(d.costs);
  return `<div class="budget-stack">${[["调用",d.external_calls.length,b.max_model_calls],["假设",d.hypotheses.length,b.max_hypotheses],["比赛",d.matches.length,b.max_matches],["输入 Tokens",c.input,b.max_input_tokens],["输出 Tokens",c.output,b.max_output_tokens]].map(([t,v,max])=>`<div class="budget-line"><div><span>${e(t)}</span><strong>${fmt(v)} / ${max==null?"未限额":fmt(max)}</strong></div>${max!=null?`<div class="bar"><i style="width:${Math.min(100,max ? v/max*100 : 100)}%"></i></div>`:""}</div>`).join("")}</div><p class="muted">已观测数量 / 配置上限；在途预留与实际执行以 Supervisor 账本为准。</p><button class="text-button" ${inspect("budget","")}>查看预算、停止条件与证据 →</button>`;
}
function overview() {
  const d=state.data,active=d.tasks.filter(t=>!["succeeded","failed","cancelled"].includes(t.state));
  const feedback=feedbackUsage(d,currentEpoch());
  const meta=d.events.filter(ev=>ev.event_type==="MetaReviewCompleted" && !ev.payload.literature_operation && ev.payload.overview).at(-1);
  const intervention=d.tasks.some(t=>t.payload?.inputs?.test_intervention);
  return `<div class="notice">研究辅助 · 模型生成的假设和排名尚未构成实验验证。${intervention?" 本次包含显式测试调度。":""}</div>
    ${section("Supervisor / Orchestrator",`<div class="supervisor"><div><span class="eyebrow">CONTROL PLANE</span><h3>${e(runReason(d)?label(runReason(d)):active.length?`${active.length} 个任务待处理`:label(d.manifest.final_state))}</h3><p>解析计划 · 任务调度 · 预算分配 · 状态迁移 · 停止与最终汇总</p></div><button class="quiet-button" ${inspect("run","")}>计划与运行详情 →</button></div>
    <div class="pipeline">${stages.map(([id,title,en])=>{const tasks=d.tasks.filter(t=>role(t)===id),s=stageState(tasks,d.external_calls);return `<button class="phase" ${inspect("stage",id)}><span class="phase-index">${en}</span><strong>${title}</strong><small>${tasks.filter(t=>t.state==="succeeded").length} / ${tasks.length} 任务执行成功</small><span class="stage-status ${s.tone}">${s.text}</span></button>`;}).join("")}</div>
    <div class="flow-note"><span>↳ Evolution 子代 → 重新初审 / 策略评审 → 新颖性 / 相似度检查 → 准入 → 新一轮比赛</span><small>上方是职责分区，不是一次性线性进度；所有后继任务由 Supervisor 创建。</small></div>`,chip("只读观测","partial"))}
    ${controlPanel()}
    <div class="section-grid">${section("当前候选排名",rankingRows(),`<small>${e(currentEpoch()||"无 epoch")} · 排除固定 anchors</small>`)}${section("计算预算",budgetView())}</div>
    ${meta?section("研究综合反馈",`<p class="summary-text">${e(short(meta.payload.overview,700))}</p><div class="card-actions">${chip(`${arr(meta.payload.coverage_gaps).length} 项证据缺口`,"warning")}<button class="text-button" ${inspect("event",meta.sequence)}>查看完整反馈与产物 →</button></div>`):""}
    ${feedback.latest?section("反馈闭环追踪",`<p>已记录 ${feedback.rounds} 轮科学反馈。最新版本 ${e(feedback.latest.payload.feedback_version)} 已带入 ${feedback.scheduled} 个后续任务，其中 ${feedback.completed} 个执行成功。</p><p class="muted">${feedback.evolution.length?"已由 Supervisor 创建反馈驱动的 Evolution；子代仍需独立重审。":"此反馈尚未驱动 Evolution，可能受轮次、预算或停止策略限制。"} 传入反馈不证明建议已被采纳或科学质量得到提升。</p><button class="text-button" ${inspect("event",feedback.latest.sequence)}>查看来源、反馈 hash 与完整内容 →</button>`,chip("可追溯输入","partial")):""}
    ${d.manifest?.final_state==="needs_attention"&&feedback.latest&&feedback.latest.payload.safety_direction_check!=="clear"?section("研究者核查入口",`<p>综合反馈将安全方向判为 ${e(feedback.latest.payload.safety_direction_check)}。请分别检查具体安全疑问、初审安全记录、完整评审和文献证据缺口；尚未验证的机制本身不等于不安全。</p><p class="muted">核查后可在上方提交署名意见，申请独立复评。意见不会直接覆盖判定。若要更改研究目标或协议，请另存新配置。</p><button class="text-button" ${inspect("event",feedback.latest.sequence)}>核查完整反馈 →</button><button class="text-button" data-view="hypotheses">查看候选及评审 →</button>`,chip("需要人工核查","warning")):""}
    ${section(active.length?"待处理任务":"最近事件", active.length ? taskRows(active.slice(0,8)) : eventRows(d.events.slice(-5).reverse()),`<button class="text-button" data-view="tasks">所有任务 →</button>`)}
    <div class="infra">共享基础设施 <span>Literature search</span><span>Tools / Models</span><span>Context memory</span><span>Provenance store</span><span>Event / Cost log</span></div>`;
}

function controlPanel() {
  const d=state.data,live=d._source?.kind==="database",status=workerStatus(d.tasks.map(t=>({...t,state:taskDisplayState(t,d.external_calls)})));
  return section("运行监控与人工干预",`<p class="summary-text">${e(live?status.text:"这是历史快照，不能推断当前 Worker 状态或执行控制。")}</p>
    ${live&&!d._source.controlAvailable?'<p class="notice">当前 HTTP 服务尚未启用控制接口；请重启网页服务后刷新。监控仍可使用。</p>':""}
    <p class="muted">${live?`快照 ${e(date(d._source.loadedAt))}。` : ""}角色卡片 → 任务 → 输入、调用、结果、领域事件。按设置周期刷新；不是模型 token 流式输出。</p>
    <div class="card-actions">${[["pause","暂停调度"],["resume","继续调度"],["stop","请求收尾"]].map(([a,title])=>`<button class="quiet-button" data-control="${a}" ${allowedControl(d,a)?"":"disabled"}>${title}</button>`).join("")}
      <button class="text-button" data-view="settings">调整下一次研究目标 / 模型 →</button></div>
    <p class="muted">暂停不取消已发给供应商的请求；继续仅恢复运行状态，不启动 Worker。请求收尾保留已有成果，需要 Worker 完成 finalization。修改目标请在设置载入当前运行副本并另存新配置。</p>
    ${retryUI.panel()}
    ${scientistUI.panel()}
    <details><summary>人工评审与自有假设：当前能力边界</summary><p>当前支持针对科学 Meta-review 阻断提交署名意见并申请独立复评；暂不支持直接导入自有假设、修改冻结计划或手工指定判定。意见是否被采用，以复评产物和后继事件为准。</p></details>`,chip(live?"显式确认后写入":"只读快照",live?"warning":"partial"));
}
let controlBusy=false;
async function runControl(action) {
  if(controlBusy||!allowedControl(state.data,action))return;
  const id=state.id,runId=state.data.manifest.run_id,sequence=state.data.manifest.current_sequence;
  const explanation={pause:"暂停后不再领取新任务；已发出的请求仍可能完成和计费。",
    resume:"仅恢复调度状态；如果原 CLI 已退出，需要另行启动 Worker。",
    stop:"停止扩展研究并请求收尾；保留已有产物，需 Worker 完成。此操作不等于暂停。"}[action];
  if(!window.confirm(`${runId}\n当前序号：${sequence}\n${explanation}\n确认执行？`))return;
  controlBusy=true;
  try {
    const response=await fetch(`/api/runs/${encodeURIComponent(id)}/control`,{method:"POST",
      headers:{"content-type":"application/json"},body:JSON.stringify({action,expected_sequence:sequence,confirmed:true})});
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.error||`HTTP ${response.status}`);
    toast(result.message);
    if(state.id===id){await loadRun(id);inspector("run","",false);
      $("inspectorBody").insertAdjacentHTML("afterbegin",detail("如 Worker 已退出，在已配置 API 的终端继续",`<p>网页未启动进程。${action==="pause"?"先点击继续调度，或请求收尾。":""}只有确认原 Worker 已退出后，才执行：</p><pre>${e(result.worker_command)}</pre>`));}
  } catch(error){toast(error.message);if(state.id===id)await loadRun(id);}
  finally {controlBusy=false;}
}
function hypothesisView() {
  const d=state.data,filtered=d.hypotheses.filter(h=>query(h)&&(state.filter==="all"||(state.filter==="admitted"?admission(d,h,currentEpoch()):parents(d,h).length)));
  const evolved=d.hypotheses.filter(h=>parents(d,h).length);
  return toolbar([["all","全部候选"],["admitted","当前 epoch 已准入"],["children","Evolution 子代"]])+
    (evolved.length?section("假设血缘 · 内容不可变",`<div class="lineage">${evolved.map(h=>`<div class="lineage-row"><div>${parents(d,h).map(p=>`<button class="lineage-node" ${p.hypothesis?inspect("hypothesis",p.hypothesis.hypothesis_id):""}>${e(p.hypothesis?shortId(p.hypothesis.hypothesis_id):p.id)}</button>`).join("")}</div><span class="lineage-arrow">→</span><button class="lineage-node child" ${inspect("hypothesis",h.hypothesis_id)}>${e(shortId(h.hypothesis_id))}<small>${admission(d,h,currentEpoch())?"独立审查后准入":"未获准入"}</small></button><p>${e(h.title)}</p></div>`).join("")}</div><p class="muted">子代不覆盖父假设，不继承父代 rating；连线来自 parent_content_ids。</p>`):"")+
    `<div class="hypothesis-grid">${filtered.map(h=>{const a=admission(d,h,currentEpoch()),r=d.reviews.filter(r=>r.hypothesis_id===h.hypothesis_id);return `<button class="hypothesis-card" ${inspect("hypothesis",h.hypothesis_id)}><header><span class="mono">${e(shortId(h.hypothesis_id))}</span>${chip(a?"已准入":"未准入",a?"pass":"warning")}</header><h3>${e(h.title)}</h3><p>${e(h.claim)}</p><div class="parent-line">${r.length} 份评审 · ${parents(d,h).length?"Evolution 子代":"初始生成"}${d.ratings[currentEpoch()]?.[h.hypothesis_id]!=null?` · Elo ${d.ratings[currentEpoch()][h.hypothesis_id].toFixed(1)}`:""}</div></button>`;}).join("") || empty("没有匹配的假设")}</div>`;
}
function reviewRows(reviews) {
  return `<div class="review-list">${reviews.map(r=>`<button class="review-row" ${inspect("review",r.review_id)}><strong>${e(shortId(r.hypothesis_id))}${!hyp(r.hypothesis_id)?'<small class="block">固定 Anchor</small>':""}</strong><small>${e(label(r.stage))}</small><small class="truncate">${e(r.critical_flaws?.[0]||"未记录 critical flaw；以准入证据为准")}</small>${chip(label(r.recommendation),tone(r.recommendation))}</button>`).join("") || empty("暂无评审")}</div>`;
}
function evidenceView() {
  const d=state.data;
  return toolbar([["all","全部评审阶段"],["initial_review","初审"],["full_review","完整评审"]])+
    section("Reflection · 评审结论",reviewRows(d.reviews.filter(r=>query(r)&&(state.filter==="all"||r.stage===state.filter))),chip(`${d.reviews.length} 份产物`))+
    section("Literature · 证据库",`<div class="evidence-list">${sources().filter(query).map(s=>`<button class="evidence-row" ${inspect("source",s.source_id)}><span class="mono">${e(s.canonical_id||s.source_id)}</span><span>${e(s.title)}<small class="block">${e(s.publication_date||"日期未记录")}</small></span>${chip(label(s.content_level),s.content_level==="abstract"?"partial":"warning")}</button>`).join("")||empty("没有检索到可展示的文献记录")}</div><p class="muted">题录 ≠ 摘要 ≠ 全文；被检索或被引用不意味着支持模型主张。</p>`, `<button class="text-button" ${inspect("literature","")}>查询与访问问题 →</button>`)+
    section("Novelty · 文献新颖性",`<div class="review-list">${d.novelty_assessments.filter(query).map(n=>`<button class="review-row" ${inspect("novelty",n.assessment_id)}><strong>${e(shortId(n.hypothesis_id))}</strong><span>${e(label(n.verdict))}</span><small>${arr(n.evidence_ids).length} 条引用</small><span>→</span></button>`).join("")||empty("暂无新颖性评估")}</div>`);
}
function tournamentView() {
  const d=state.data,epoch=currentEpoch(),matches=d.matches.filter(m=>m.epoch_id===epoch);
  return `<div class="toolbar"><label>竞技场 <select id="epochSelect">${d.tournament_epochs.map(ep=>`<option ${ep.epoch_id===epoch?"selected":""} value="${e(ep.epoch_id)}">${e(ep.epoch_id)} · Plan v${e(ep.research_plan_version)}</option>`).join("")}</select></label><button class="text-button" ${inspect("epoch",epoch)}>查看冻结比较规则 →</button></div>
    <div class="notice">Elo 仅在同一 epoch 内可比，是相对偏好，不是正确率。初始 rating 是准入后的起点，不是准入阈值。</div>
    ${section("候选 Elo",rankingRows())}
    ${section("比赛记录",`<div class="matches">${matches.map(m=>`<button class="match-card" ${inspect("match",m.match_id)}><div><span class="mono">#${e(m.sequence)}</span> ${chip(label(m.decision),tone(m.decision))}<small>${m.rating_updated?"Elo 已更新":"Elo 不更新"}</small></div><div class="match-row"><span class="${m.winner_id===m.left_id?"winner":""}">${e(shortId(m.left_id))}</span><span class="versus">VS</span><span class="${m.winner_id===m.right_id?"winner":""}">${e(shortId(m.right_id))}</span></div><small>${e(m.match_id)} · 查看判定依据 →</small></button>`).join("")||empty("尚无比赛记录")}</div>`)}
    <div class="section-grid">${section("固定 Anchor",`<div class="review-list">${Object.entries(d.ratings[epoch]||{}).filter(([id])=>!hyp(id)).map(([id,r])=>`<div class="anchor-row"><span>${e(id)}</span><strong>${r.toFixed(1)}</strong></div>`).join("")||empty("未记录 anchor rating")}</div>`)}${section("Proximity · 候选相似度",`<div class="review-list">${d.proximity.map((p,i)=>`<button class="anchor-row text-row" ${inspect("proximity",i)}><span>${e(shortId(p.left_id))} ↔ ${e(shortId(p.right_id))}</span><span>相似度 ${e(p.similarity)} · 重复概率 ${e(p.duplicate_likelihood)}</span></button>`).join("")||empty("暂无相似度记录")}</div><p class="muted">这里比较候选之间的相似度；不替代文献新颖性评审。</p>`)}</div>`;
}
function taskRows(tasks) {
  return `<div class="task-list">${tasks.map(t=>{const calls=taskCalls(t.task_id),status=taskDisplayState(t,calls);return `<button class="task-row" ${inspect("task",t.task_id)}><span class="role-icon">${e((stages.find(s=>s[0]===role(t))?.[2]||"T").slice(0,2))}</span><span><strong>${e(label(t.intent_type.replace(/^run_/,"")))}</strong><small class="block truncate">${e(t.task_id)}</small></span>${t.payload?.inputs?.test_intervention?chip("测试调度","warning"):""}<span class="task-meta">${calls.length} 次调用 · attempt ${t.attempt}/${t.max_attempts}</span>${chip(label(status),tone(status))}</button>`;}).join("")||empty("暂无匹配任务")}</div>`;
}
function tasksView() {
  const d=state.data;
  const counts=stages.map(([id,title])=>[id,title]);
  return toolbar([["all","全部角色"],...counts])+section("任务队列与产物",taskRows(d.tasks.filter(t=>query(t)&&(state.filter==="all"||role(t)===state.filter)).sort((a,b)=>{
    const seq=t=>d.events.find(ev=>ev.event_type==="TaskEnqueued"&&ev.payload.task_id===t.task_id)?.sequence||0; return seq(a)-seq(b);
  })),chip("点击任务查看输入 → 调用 → 输出"));
}
function eventRows(events) {
  return `<div class="event-list">${events.map(ev=>`<button class="event-row" ${inspect("event",ev.sequence)}><span class="event-seq">#${e(ev.sequence)}</span><span>${e(ev.event_type)}<small class="block">${e(date(ev.occurred_at))}</small></span><small class="truncate">${e(ev.payload.hypothesis_id||ev.payload.task_id||ev.payload.reason||ev.payload.match_id||ev.causation_id||"运行事件")}</small></button>`).join("")||empty("暂无匹配事件")}</div>`;
}
function eventsView() {
  return toolbar([["all","全部事件"],["science","科学产物"],["lifecycle","运行与停止"],["tasks","任务与调用"]])+eventRows(state.data.events.filter(ev=>query(ev)&&(state.filter==="all"||({science:/Hypothesis|Review|Proximity|Match|Novelty|Tournament|Cluster/,lifecycle:/Run|Finalization|Stop|Convergence/,tasks:/Task|ExternalCall|Cost|Budget/}[state.filter]?.test(ev.event_type)))).reverse());
}
function costsView() {
  const d=state.data,c=costSummary(d.costs);
  return `<div class="notice">费用来自持久化账本，不推测供应商价格。未定价账目的 0 不能解释为免费；尚未返回 usage 的在途调用不计入 token 总数。</div>`+
    section("Token 使用",`<div class="token-split"><div><small>INPUT</small><strong>${fmt(c.input)}</strong></div><div><small>OUTPUT</small><strong>${fmt(c.output)}</strong></div><div><small>UNPRICED</small><strong>${fmt(c.unpriced)} 笔</strong></div></div>`)+toolbar([["all","全部调用"],["applied","已应用"],["pending","未应用 / 在途 / 失败"]])+
    section("外部调用账本",`<div class="call-list">${d.external_calls.filter(call=>query(call)&&(state.filter==="all"||(state.filter==="applied"?callApplied(call):!callApplied(call)))).map(call=>{const cost=costSummary(costsFor([call]));return `<button class="task-row" ${inspect("call",call.external_call_id)}><span><strong>${e(call.provider)} / ${e(call.model_or_tool)}</strong><small class="block truncate">${e(call.task_id)}</small></span><span class="task-meta">${fmt(cost.input+cost.output)} tokens</span>${chip(label(call.state),tone(call.state))}</button>`;}).join("")||empty("暂无匹配调用")}</div>`);
}
function renderView() {
  document.querySelectorAll("nav [data-view]").forEach(b=>{b.classList.toggle("active",b.dataset.view===state.view);b.setAttribute("aria-current",b.dataset.view===state.view?"page":"false");});
  document.body.classList.toggle("settings-mode",state.view==="settings");
  sourceStatus();
  if(state.view==="settings"){
    state.selected=null;$("inspector").classList.add("closed");
    $("goalTitle").textContent="设置";
    if($("goalDescription"))$("goalDescription").textContent="配置下一次研究运行 · 已有运行参数保持冻结";
    settings.mount($("viewRoot"));return;
  }
  if(!state.data){$("viewRoot").innerHTML=empty("暂无运行数据。可在设置页编辑并保存新运行配置。");return;}
  renderHeader();
  $("viewRoot").innerHTML=({overview,hypotheses:hypothesisView,evidence:evidenceView,tournament:tournamentView,tasks:tasksView,events:eventsView,costs:costsView}[state.view]||overview)();
}

function outputPreview(c) {
  const p=c.agent_result?.payload;
  if(!p)return `<p class="muted">尚未产生通过校验的 AgentResult。</p>`;
  const children=arr(p.hypotheses).concat(arr(p.children));
  if(children.length)return `<p>${children.length} 个候选内容</p><div class="review-list">${children.map(h=>hyp(h.hypothesis_id)?`<button class="text-row" ${inspect("hypothesis",h.hypothesis_id)}>${e(h.title||h.hypothesis_id)} →</button>`:`<p>${e(h.title||h.hypothesis_id)} · 尚未应用到领域</p>`).join("")}</div>`;
  if(p.review_id)return `${chip(label(p.recommendation),tone(p.recommendation))}<p>${arr(p.critical_flaws).length} 项关键缺陷 · ${arr(p.evidence_ids).length} 条引用</p><button class="text-button" ${inspect("review",p.review_id)}>查看评审依据 →</button>`;
  if(p.match_id)return `<p>${e(label(p.decision_status))} · ${e(shortId(p.left_id))} vs ${e(shortId(p.right_id))}</p><button class="text-button" ${inspect("match",p.match_id)}>查看比赛产物 →</button>`;
  if(p.overview)return `<p>${e(p.overview)}</p>`;
  if(p.rationale)return `<p>${e(p.rationale)}</p>`;
  return `<p>结构化产物已记录，请展开完整字段。</p>`;
}

function inspector(type,id,focus=true) {
  const d=state.data; if(!d)return;
  let title="运行说明",body="";
  if(type==="run") {
    title="Research Plan / Supervisor";
    body=detail("研究目标",`<p>${e(d.manifest.goal?.goal||d.manifest.goal?.title)}</p>`)+detail("运行状态",kv({Run:d.manifest.run_id,状态:label(d.manifest.final_state),停止或暂停原因:label(runReason(d)),收尾状态:d.manifest.finalization_state,状态路径:arr(d.manifest.state_history).join(" → "),数据来源:d._source?.kind,快照时间:date(d._source?.loadedAt)}))+detail("必需因果链",list(d.manifest.goal?.required_causal_chain))+detail("所需产物",list(d.manifest.goal?.required_outputs))+raw("冻结 profile / 审查策略",d.manifest.profile)+raw("完整运行 manifest",d.manifest);
  } else if(type==="stage") {
    const stage=stages.find(s=>s[0]===id);if(!stage)return;title=stage[1];
    body=detail(stage[2],`<p>${e(stage[3])}</p>`)+detail("本阶段任务",taskRows(d.tasks.filter(t=>role(t)===id)))+detail("如何阅读",`<p>点击任务查看真实输入、外部调用、结构化产物与领域事件。任务成功仅表示执行成功，不代表科学主张已获验证。</p>`);
  } else if(type==="hypothesis") {
    const h=hyp(id);if(!h)return;title=`${shortId(id)} · 假设详情`;
    const projection=d.hypothesis_projections.find(p=>p.hypothesis_id===id),a=admission(d,h,currentEpoch());
    body=detail(h.title,`<p>${e(h.claim)}</p>`)+detail("当前准入",`${chip(a?"已准入":"未准入",a?"pass":"warning")}<p>依据当前 epoch 的持久化准入证据，不由单份评审的 pass 推断。</p>`)+detail("机制链",`<ol class="causal-chain">${arr(h.mechanism_chain).map(step=>`<li>${e(typeof step==="object"?JSON.stringify(step):step)}</li>`).join("")}</ol>`)+detail("可检验预测 / 实验",list(h.predictions))+detail("证伪条件",list(h.falsifiers))+detail("关键假定",list(h.assumptions))+detail("内容来源",kv({content_id:h.content_id,内容哈希:h.content_hash,创建事件:`#${h.created_sequence}`,父内容:arr(h.parent_content_ids).join(", ")||"无"}))+detail("评审记录",reviewRows(d.reviews.filter(r=>r.hypothesis_id===id)))+raw("准入证据",a||{status:"未记录准入"})+raw("状态投影 / cluster / rating",projection)+raw("不可变科学内容",h);
  } else if(type==="review") {
    const r=d.reviews.find(r=>r.review_id===id);if(!r)return;title=`${shortId(r.hypothesis_id)} · ${label(r.stage)}`;
    const event=d.events.find(ev=>ev.event_type==="ReviewCompleted"&&ev.payload.review_id===id);
    body=detail("模型建议",chip(label(r.recommendation),tone(r.recommendation)))+detail("关键缺陷",list(r.critical_flaws))+detail("评审维度",kv(r.dimension_scores||{}))+detail("引用证据",sourceLinks(r.evidence_ids))+raw("完整评审与 provenance",event?.payload||r);
  } else if(type==="source") {
    const s=sources().find(s=>s.source_id===id);if(!s)return;title="文献证据";
    const pmid=String(s.canonical_id||"").match(/^PMID:(\d+)$/)?.[1];
    body=detail(s.title,kv({来源:s.canonical_id,时间:s.publication_date,内容级别:label(s.content_level),作者:arr(s.authors).join(", ")}))+detail("已获取的摘要",`<p>${e(s.abstract||"未获取摘要。题录不能用于验证文中具体机制。")}</p>`)+(pmid?`<a class="external-link" href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener noreferrer">在 PubMed 查看 ↗</a>`:"")+detail("引用此来源的评审",reviewRows(d.reviews.filter(r=>arr(r.evidence_ids).includes(id))))+raw("检索与原始产物引用",s);
  } else if(type==="task") {
    const t=d.tasks.find(t=>t.task_id===id);if(!t)return;title="任务输入与产物";const calls=taskCalls(id);
    body=detail("执行状态",kv({任务:t.task_id,角色:role(t),当前执行:label(taskDisplayState(t,calls)),持久化任务状态:label(t.state),尝试:`${t.attempt} / ${t.max_attempts}`,创建者:d.events.find(ev=>ev.event_type==="TaskEnqueued"&&ev.payload.task_id===id)?.payload.created_by||"未记录",测试介入:t.payload?.inputs?.test_intervention?"是":"未记录"}))+detail("外部调用",`<div class="review-list">${calls.map(c=>`<button class="text-row" ${inspect("call",c.external_call_id)}>${e(c.model_or_tool)} · ${e(label(c.state))} →</button>`).join("")||"<p>无外部调用记录</p>"}</div>`)+raw("任务输入快照",t.payload)+calls.map(c=>detail("结构化产物",outputPreview(c)+raw(`${c.model_or_tool} · AgentResult`,c.agent_result?.payload||c.validated_payload||{status:"尚未产生通过校验的结果"}))).join("")+raw("领域事件",d.events.filter(ev=>ev.payload.source_task_id===id||ev.payload.task_id===id))+raw("租约与任务记录",t);
  } else if(type==="call") {
    const c=d.external_calls.find(c=>c.external_call_id===id);if(!c)return;title="外部调用追踪";const cost=costSummary(costsFor([c]));
    body=detail("持久化状态",kv({供应商:c.provider,模型:c.model_or_tool,状态:label(c.state),输入tokens:cost.input,输出tokens:cost.output,费用:cost.unpriced?"未定价":`$${cost.usd.toFixed(4)}`,领域应用序号:c.applied_domain_sequence}))+detail("Raw-first 生命周期",`<p>planned → started → raw response persisted → validated → AgentResult submitted → domain result applied</p><p>下方是原始产物引用与哈希，不是原始响应正文，也不表示本页面重新验证过哈希。</p>`)+raw("原始响应 provenance",c.raw_artifact_ref)+raw("已校验的结构化结果",c.agent_result?.payload||c.validated_payload)+raw("调用、usage 与执行上下文",c);
    if(d._source?.rawAvailable&&c.raw_artifact_ref)body+=`<button class="quiet-button" data-raw-call="${e(id)}">查看原始响应正文（校验哈希）</button>`;
  } else if(type==="match") {
    const m=d.matches.find(m=>m.match_id===id);if(!m)return;title="比赛判定与 Elo";const event=d.events.find(ev=>ev.event_type==="MatchEvaluated"&&ev.payload.match_id===id);
    body=detail("参与者",kv({左侧:name(m.left_id),右侧:name(m.right_id),结果:label(m.decision),胜者:m.winner_id?name(m.winner_id):"无",Elo更新:m.rating_updated?"是":"否",epoch:m.epoch_id}))+detail("维度理由",Object.entries(event?.payload.dimension_reasons||{}).map(([k,v])=>`<h4>${e(k)}</h4><p>${e(v)}</p>`).join(""))+raw("Rating before / after",{before:m.ratings_before,after:m.ratings_after})+raw("完整判定与冻结规则",event?.payload||m);
  } else if(type==="event") {
    const ev=d.events.find(ev=>ev.sequence===Number(id));if(!ev)return;title=`#${ev.sequence} · ${ev.event_type}`;
    body=detail("事件 provenance",kv({时间:date(ev.occurred_at),causation_id:ev.causation_id,correlation_id:ev.correlation_id}));
    if(ev.payload.overview)body+=detail("综合反馈",`<p>${e(ev.payload.overview)}</p>`)+detail("证据缺口",list(ev.payload.coverage_gaps))+detail("系统反馈",list(ev.payload.system_feedback));
    if(ev.event_type==="ScientistFeedbackRecorded")body+=detail("研究者意见（自报署名）",`<p>${e(ev.payload.actor)}</p><p style="white-space:pre-wrap">${e(ev.payload.note)}</p>`)+detail("绑定的原反馈",kv({feedback_id:ev.payload.source_feedback_id,feedback_hash:ev.payload.source_feedback_hash,epoch:ev.payload.epoch_id}));
    body+=raw("完整领域产物 / payload",ev.payload);
  } else if(type==="budget") {
    title="停止策略与预算";const checkpoint=d.convergence_checkpoints.at(-1);
    body=detail("实际停止",kv({原因:label(runReason(d)),状态:label(d.manifest.final_state),finalization:d.manifest.finalization_state}))+detail("最近收敛证据",kv({"top-k 稳定":checkpoint?.top_k_stable,"cluster diversity":checkpoint?.cluster_diversity_satisfied,"novelty plateau":checkpoint?.novelty_plateau,"Elo plateau（辅助）":checkpoint?.elo_plateau,"固定 anchor 对比数":checkpoint?.anchor_comparison_ids?.length}))+raw("冻结停止策略",d.manifest.profile?.stop)+raw("冻结预算",d.manifest.profile?.budget)+raw("预算预留与结算记录",d.budget_reservations)+raw("停止决策",d.stop_decisions)+raw("收敛 checkpoint",checkpoint);
  } else if(type==="epoch") { title="TournamentEpoch";body=detail("可比性边界",`<p>计划版本、评价规则、ranking prompt、judge profile 与 rating policy 冻结在此 epoch；不将不同 epoch 的分数放在同一排名里。</p>`)+raw("冻结竞技场定义",d.tournament_epochs.find(ep=>ep.epoch_id===id));
  } else if(type==="novelty") {const n=d.novelty_assessments.find(n=>n.assessment_id===id);if(!n)return;title="文献新颖性评估";body=detail("独立评估对象",kv({假设:n.hypothesis_id,结论:label(n.verdict)}))+detail("相关文献",sourceLinks(n.evidence_ids))+raw("NoveltyAssessment",n);
  } else if(type==="literature") {title="文献检索记录";body=detail("实际查询",list(d.literature.pubmed_queries))+detail("访问问题",list(d.literature.access_issues))+raw("查询截止与内容级别",d.literature);
  } else if(type==="proximity") {const p=d.proximity[Number(id)];if(!p)return;title="候选相似度";body=raw("ProximityEdge",p)+raw("对应领域产物",d.events.filter(ev=>ev.event_type==="ProximityAssessed"&&JSON.stringify(ev.payload).includes(p.left_id)&&JSON.stringify(ev.payload).includes(p.right_id)).map(ev=>ev.payload));
  }
  state.selected={type,id}; $("inspectorTitle").textContent=title; $("inspectorBody").innerHTML=body;
  $("inspector").classList.remove("closed"); if(focus) {$("inspector").scrollTop=0; $("closeInspector").focus({preventScroll:true});}
}
function sourceLinks(ids) {return `<div class="source-links">${arr(ids).map(id=>sources().some(s=>s.source_id===id)?`<button class="text-button" ${inspect("source",id)}>${e(id)} ↗</button>`:`<span class="muted">${e(id)} · 来源记录缺失</span>`).join("")||"未列出证据引用"}</div>`;}

async function request(url) { const response=await fetch(url);if(!response.ok)throw new Error((await response.json()).error||`HTTP ${response.status}`);return response.json(); }
async function inventory() {
  const result=await request("/api/runs"); state.runs=result.runs;
  $("runMenu").innerHTML=state.runs.map(r=>`<button class="run-option" role="option" aria-selected="${r.id===state.id}" data-run="${e(r.id)}"><strong>${e(r.runId)}</strong><small>${e(label(r.state))} · ${r.kind==="database"?"数据库监控":"导出快照"} · ${e(r.location)}</small></button>`).join("")||"暂无本地运行";
  if(result.warnings?.length)toast(result.warnings.join(" "));
}
async function loadRun(id,quiet=false) {
  const generation=++state.generation;const changed=state.id!==id;state.id=id;state.loading=true;
  $("refreshButton").disabled=true;
  if(changed){state.selected=null;state.search="";state.filter="all";state.epoch=null;if(state.view!=="settings")$("viewRoot").innerHTML=empty("正在读取一致性快照…");$("inspector").classList.add("closed");}
  try {
    const data=normalize(await request(`/api/runs/${encodeURIComponent(id)}/snapshot`));
    if(generation!==state.generation)return;
    const fingerprint=d=>JSON.stringify([d?.manifest.current_sequence,d?.tasks.map(t=>[t.state,t.attempt,t.heartbeat_at,t.lease_expires_at]),d?.external_calls.map(c=>c.state),d?.costs, d?workerStatus(d.tasks).fresh:0]);
    const redraw=changed||!quiet||state.view==="overview"||fingerprint(state.data)!==fingerprint(data);
    state.data=data;
    if(!quiet){const url=new URL(location.href);url.searchParams.set("run",id);history.replaceState(null,"",url);}
    if(!data.tournament_epochs.some(ep=>ep.epoch_id===state.epoch))state.epoch=data.tournament_epochs.at(-1)?.epoch_id;
    if(redraw&&state.view!=="settings"){renderHeader();renderView();if(state.selected)inspector(state.selected.type,state.selected.id,false);}
    if(state.view==="settings"){$("runName").textContent=data.manifest.run_id;$("runName").title=data.manifest.run_id;}
    sourceStatus();
  } catch(error) {
    if(generation!==state.generation)return;
    sourceStatus(true); if(!quiet)toast(error.message);
    if(changed||!state.data){state.data=null;$("runName").textContent="加载失败";$("metrics").innerHTML="";$("viewRoot").innerHTML=empty(`${error.message} 可重新载入或选择导出目录。`);}
  } finally {if(generation===state.generation){state.loading=false;$("refreshButton").disabled=false;}}
}
document.addEventListener("click",event=>{
  const b=event.target.closest("[data-inspect],[data-view],[data-run],[data-control]");if(!b)return;
  if(b.dataset.control){void runControl(b.dataset.control);return;}
  if(b.dataset.inspect)inspector(b.dataset.inspect,b.dataset.id);
  if(b.dataset.view){state.view=b.dataset.view;state.search="";state.filter="all";
    const url=new URL(location.href);url.searchParams.set("view",state.view);history.replaceState(null,"",url);renderView();}
  if(b.dataset.run){$("runMenu").classList.add("hidden");$("runSwitcher").setAttribute("aria-expanded","false");loadRun(b.dataset.run);}
});
document.addEventListener("input",event=>{if(event.target.id==="viewSearch"){const position=event.target.selectionStart;state.search=event.target.value;renderView();$("viewSearch").focus();try{$("viewSearch").setSelectionRange(position,position);}catch{ /* search inputs vary by browser */ }}});
document.addEventListener("change",event=>{if(event.target.id==="viewFilter"){state.filter=event.target.value;renderView();}if(event.target.id==="epochSelect"){state.epoch=event.target.value;renderHeader();renderView();}});
document.addEventListener("keydown",event=>{if(event.key==="Escape"){$("inspector").classList.add("closed");$("runMenu").classList.add("hidden");state.selected=null;}});
$("closeInspector").onclick=()=>{$("inspector").classList.add("closed");state.selected=null;};
$("runSwitcher").onclick=async()=>{const opening=$("runMenu").classList.contains("hidden");$("runMenu").classList.toggle("hidden");$("runSwitcher").setAttribute("aria-expanded",String(opening));if(opening)try{await inventory();}catch(error){toast(error.message);}};
$("refreshButton").onclick=()=>state.id?loadRun(state.id):toast("离线快照不会自动更新，请重新选择导出目录。");
$("openFolderButton").onclick=()=>$("folderInput").click();
$("folderInput").onchange=async event=>{
  const names=new Set(["manifest","hypotheses","hypothesis_projections","reviews","novelty_assessments","proximity","matches","ratings","tasks","costs","convergence_checkpoints","stop_decisions","literature","external_calls","tournament_epochs","budget_reservations","full_workflow_check"].map(n=>`${n}.json`).concat("events.jsonl"));
  try {
    const files=[...event.target.files].filter(f=>f.webkitRelativePath.split("/").length===2&&names.has(f.name));
    if(files.reduce((n,f)=>n+f.size,0)>64*1024*1024)throw new Error("目录快照超过 64 MB，请使用本地服务器读取。");
    const data=parseFolder(await Promise.all(files.map(async f=>[f.name,await f.text()])));
    ++state.generation;state.loading=false;state.id=null;state.data=data;state.epoch=data.tournament_epochs.at(-1)?.epoch_id;state.selected=null;state.search="";state.filter="all";
    const url=new URL(location.href);url.searchParams.delete("run");history.replaceState(null,"",url);
    data._source={kind:"folder",loadedAt:new Date().toISOString()};renderHeader();renderView();$("refreshButton").disabled=false;inspector("run","",false);toast("目录已在浏览器本地读取，未上传任何文件。");
  } catch(error){toast(`无法载入：${error.message}`);}finally{event.target.value="";}
};
// Additional navigation stays in the same read-only shell.
document.querySelector("nav").insertAdjacentHTML("beforeend",`<button class="nav-item" data-view="tasks"><span>☷</span>任务与产物</button><button class="nav-item" data-view="costs"><span>◴</span>模型与成本</button><button class="nav-item" data-view="settings"><span>⚙</span>设置</button>`);
$("viewRoot").innerHTML=empty("正在发现本地运行…");
try {await inventory();if(state.runs.length){const requested=new URL(location.href).searchParams.get("run");await loadRun(state.runs.find(r=>r.id===requested)?.id||state.runs[0].id);}else{$("runName").textContent="尚无运行";$("viewRoot").innerHTML=empty("未发现运行。先用 CLI 运行案例，或选择一个包含 manifest.json 的导出目录。");}}
catch(error){$("runName").textContent="未连接";$("viewRoot").innerHTML=empty(`${error.message} 请确认本地服务已启动，也可直接载入导出目录。`);sourceStatus(true);}
if(state.view==="settings")renderView();
let lastPoll=Date.now();
setInterval(()=>{const prefs=settings.getPreferences();if(Date.now()-lastPoll<prefs.pollSeconds*1000)return;
  if(!document.hidden&&!state.loading&&!retryUI.isOpen()&&!scientistUI.isOpen()&&state.view!=="settings"&&prefs.autoRefresh&&state.id&&state.data?._source?.kind==="database"){lastPoll=Date.now();loadRun(state.id,true);}},1000);
