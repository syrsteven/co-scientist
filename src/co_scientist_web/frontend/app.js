
/* Co-Scientist native-trace-aware offline monitor.
   No network calls, no provider dispatch, no claim that read models are connected. */
(() => {
  "use strict";
  const $ = (s,root=document) => root.querySelector(s);
  const $$ = (s,root=document) => Array.from(root.querySelectorAll(s));
  const escapeHtml = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const num = v => Number.isFinite(Number(v)) ? Number(v) : null;
  const two = n => Number.isFinite(Number(n)) ? Number(n).toFixed(2) : "—";
  const short = (s,n=98) => {const t=String(s??"").trim();return t.length>n?t.slice(0,n).trimEnd()+"…":t};
  const cleanSentence = t => {
    const s = String(t??"").replace(/\s+/g," ").trim();
    const x = s.match(/^.{20,175}?[。！？.!?](?:\s|$)/);
    return short(x?x[0]:s,130)||"尚无可显示的原文概要";
  };
  const minClock = t => {t=Math.max(0,Math.floor(Number(t)||0));return String(Math.floor(t/60)).padStart(2,"0")+":"+String(t%60).padStart(2,"0")};
  const F = window.MONITOR_FIXTURE;
  const state = {mode:"fixture",frame:9,filter:"ranked",query:"",generation:"all",
    selected:null,tab:"hypothesis",playing:false,timer:null,rawOpen:false,native:null,modal:false};
  let cachedView = null;
  let nativePayloads = null;
  let nativeRawTexts = null;
  let backendStatus = null;

  function sourceData(){return state.mode==="fixture"?F:state.native}
  function frames(){return state.mode==="fixture"?F.steps:state.native.frames}
  function frame(){return frames()[state.frame]}
  function stopPlayback(){if(state.timer)clearInterval(state.timer);state.timer=null;state.playing=false;$("#play-icon").textContent="▶";$("#btn-play").title="播放回放"}
  function notify(t){const node=$("#toast");node.textContent=t;node.classList.add("show");clearTimeout(notify.t);notify.t=setTimeout(()=>node.classList.remove("show"),3000)}

  function makeNativeCandidate(x,i) {
    const id=String(x.hypothesis_id??x.id??"candidate-"+i);
    return {id,title:x.title??id,g:num(x.generation_index??x.generation)??0,
      summary:cleanSentence(x.claim??x.hypothesis??""),claim:x.claim??x.hypothesis??"",
      mechanism_chain:x.mechanism_chain??[],assumptions:x.assumptions??[],predictions:x.predictions??[],
      falsifiers:x.falsifiers??[],parents:x.scientific_parent_ids??[],operator:x.generation_strategy??(x.scientific_parent_ids?.length===2?"crossover":x.scientific_parent_ids?.length===1?"mutation":"root"),
      created_sequence:num(x.created_sequence),rating:x.rating??null,
      ethics:x.ethics??[],reflection:x.reflection??[], evidence:[],raw:x,source:"native-export"};
  }

  function importNative(payloads) {
    const cs = payloads["candidates.json"];
    if(!Array.isArray(cs))throw new Error("必须选择有效的 candidates.json（JSON 数组）。");
    const timeline=payloads["run-timeline.json"]&&typeof payloads["run-timeline.json"]==="object"?payloads["run-timeline.json"]:null;
    const ranks=Array.isArray(payloads["ranking-history.json"])?payloads["ranking-history.json"]:[];
    const tree=payloads["evolution-tree.json"]&&typeof payloads["evolution-tree.json"]==="object"?payloads["evolution-tree.json"]:null;
    if(timeline&&tree&&timeline.run_id&&tree.run_id&&timeline.run_id!==tree.run_id)throw new Error("不同 Run 的 Trace 不可混合导入。");
    const events=Array.isArray(timeline?.events)?timeline.events.slice().sort((a,b)=>Number(a.sequence)-Number(b.sequence)):[];
    const nativeCandidates=cs.map(makeNativeCandidate).filter(c=>c.id);
    for(const c of nativeCandidates){
      const plan=tree?.reproduction?.find(p=>(p.children??[]).includes(c.id));
      c.operator=plan?.decision?.operator??(c.raw.generation_index===0&&c.raw.generation_source_sequence!=null?"root":"unrecorded");
    }
    const frames=[{seq:0,label:"Run 初始化",g:0,summary:"初始事件边界。"}];
    const keyTypes=new Set(["HypothesisContentCreated","MatchEvaluated","BayesianRatingProjected",
      "BaselineGenerationCompletedV1","BaselineReproductionPlannedV1","IdeationFinalSelectionV1",
      "RunNeedsAttention","RunPaused","RunResumed","RunStopped","RunCompleted",
      "CandidateEthicsRecordedV1","BaselineReflectionRecordedV1"]);
    const labels={"HypothesisContentCreated":"新候选已创建","MatchEvaluated":"配对比较完成",
      "BayesianRatingProjected":"TrueSkill 更新","BaselineGenerationCompletedV1":"本代评价完成",
      "BaselineReproductionPlannedV1":"演化计划建立","IdeationFinalSelectionV1":"终局选择",
      "RunNeedsAttention":"运行需要关注","RunPaused":"任务暂停","RunResumed":"继续运行",
      "RunStopped":"运行停止","RunCompleted":"运行完成",
      "CandidateEthicsRecordedV1":"Ethics 检查","BaselineReflectionRecordedV1":"Reflection 完成"};
    if(events.length) {
      for(const e of events){
        if(!keyTypes.has(e.event_type))continue;
        const payload=e.payload??{};
        const associated=nativeCandidates.find(c=>c.id===payload.hypothesis_id);
        let g=num(payload.generation??associated?.g);
        if(g===null)g=frames[frames.length-1].g;
        frames.push({seq:e.sequence,label:labels[e.event_type]??e.event_type,g,
          summary:(associated?.title??payload.hypothesis_id??payload.match_id??payload.slot_id??e.event_type),
          event_type:e.event_type,occurred_at:e.occurred_at});
      }
      if(frames[frames.length-1]?.seq!==events[events.length-1].sequence){
        const e=events[events.length-1];frames.push({seq:e.sequence,label:"最新事件边界",summary:e.event_type,g:frames[frames.length-1].g})
      }
    } else {
      frames.length=0;
      frames.push({seq:Infinity,label:"导入的终局候选快照",g:Math.max(0,...nativeCandidates.map(x=>x.g)),summary:"未提供事件时间线，仅能查看当前导入候选评分。"});
    }
    const manifest=timeline?.manifest??{};
    const science=manifest?.effective_execution_config?.performance?.baseline?.scientific?.search
      ??manifest?.effective_execution_config?.scientific?.search??{};
    const rootSlots=num(science.root_slots)??4;
    const childSlots=num(science.reproduction_slots_per_transition)??2;
    const gens=num(science.reproduction_transitions)??Math.max(3,...nativeCandidates.map(c=>c.g));
    const final=timeline?.final_selection??tree?.final_selection??null;
    return {version:"native-trace-import",runId:timeline?.run_id??tree?.run_id??"unknown-native-run",
      study:manifest?.goal?.title??manifest?.goal?.goal?.slice(0,35)??"导入研究",
      maxGenerations:gens,totalSlots:rootSlots+childSlots*gens,
      candidates:nativeCandidates,cById:Object.fromEntries(nativeCandidates.map(c=>[c.id,c])),
      timeline,events,tree,ranking:ranks,frames,final,
      importedFiles:Object.keys(payloads),snapshotOnly:events.length===0};
  }

  function latestRating(history,step,defaultRating){
    const r=(history??[]).filter(x=>x[0]<=step).at(-1);
    if(r)return {mu:r[1],sigma:r[2]};
    return defaultRating??null;
  }

  function fixtureView(){
    const step=state.frame,stamp=F.steps[step];
    const candidates=F.candidates.filter(c=>c.appear<=step).map(c=>{
      const matched=F.matches.filter(m=>m.step<=step&&(m.a===c.id||m.b===c.id));
      const rating=latestRating(F.ratings[c.id],step,matched.length?{mu:25,sigma:8.3333}:null);
      return {...c,score:rating,matches:matched.length,ranked:matched.length>=2&&!!rating}
    });
    const active=F.matches.filter(m=>m.step<=step);
    const complete=stamp.status==="Completed";
    return {kind:"synthetic",runId:F.runId,study:F.study,maxGenerations:F.maxGenerations,totalSlots:F.totalSlots,
      g:stamp.g,state:stamp.status,gLabel:stamp.label,subtitle:stamp.summary,
      elapsed:stamp.minute,span:950,spent:stamp.cost,spentNote:"模拟费用 · 非实际账单",
      candidateTotal:candidates.length,eligible:candidates.filter(x=>x.ranked).length,
      matches:active.length,calls:stamp.calls,retries:stamp.retry??0,
      candidates,ranking:active.map((m,i)=>({match_id:"synthetic-"+(i+1),left_id:m.a,right_id:m.b,
        winner_id:m.winner,status:"VALID_DECISIVE",reason:m.note,step:m.step})),
      final:complete?{winner_id:F.finalWinner,selection_result:"FINAL_WINNER",
        execution_result:"COMPLETE",terminal_barrier_complete:true}:null,
      activity:F.steps.slice(0,step+1).map((s,i)=>({id:i,label:s.label,summary:s.summary,alert:!!s.alert,
        time:minClock(s.minute),sequence:i+1, raw:F.timelineRaw[i]})).reverse(),
      timeText:minClock(stamp.minute)+" / "+minClock(950)};
  }

  function nativeView(){
    const N=state.native,info=N.frames[state.frame],seq=info.seq;
    const cut=N.events.filter(e=>e.sequence<=seq);
    const hasTimeline=N.events.length>0;
    const ratingMap=new Map(),matchMap=new Map();
    for(const e of cut){
      const p=e.payload??{};
      if(e.event_type==="InitialRatingAssigned"||e.event_type==="BayesianRatingProjected"){
        if(p.hypothesis_id&&num(p.mu)!==null&&num(p.sigma)!==null)ratingMap.set(p.hypothesis_id,{mu:num(p.mu),sigma:num(p.sigma)});
      }
      if(e.event_type==="MatchEvaluated"&&p.left_id&&p.right_id){
        matchMap.set(p.left_id,(matchMap.get(p.left_id)??0)+1);
        matchMap.set(p.right_id,(matchMap.get(p.right_id)??0)+1);
      }
    }
    const candidates=N.candidates.filter(c=>!hasTimeline||c.created_sequence==null||c.created_sequence<=seq).map(c=>{
      const latest=state.frame===N.frames.length-1;
      const score=latest&&c.rating?{mu:num(c.rating.mu),sigma:num(c.rating.sigma)}:hasTimeline?(ratingMap.get(c.id)??null):null;
      const matches=latest?(num(c.rating?.decisive_matches)??0):(matchMap.get(c.id)??0);
      return {...c,score,matches,ranked:score!==null&&matches>=2};
    });
    const matched=cut.filter(e=>e.event_type==="MatchEvaluated").length;
    const isLast=state.frame===N.frames.length-1;
    const final=N.final&&isLast?N.final:(cut.findLast(e=>e.event_type==="IdeationFinalSelectionV1")?.payload??null);
    const complete=final?.execution_result==="COMPLETE"&&final?.selection_result==="FINAL_WINNER"&&final?.terminal_barrier_complete===true;
    const explicitState=isLast?(N.timeline?.execution_state??"Snapshot"):"Historical";
    let costs=0;let hasCost=false;
    for(const x of N.timeline?.cost_entries??[]){const c=num(x.cost_usd);if(c!==null){costs+=c;hasCost=true}}
    const calls=(N.timeline?.calls??[]).length;
    const failures=(N.timeline?.failure_diagnostics??[]).length;
    const idx=candidates.reduce((s,c)=>Math.max(s,c.g),0);
    const activity=cut.filter(e=>e.event_type!=="TaskEnqueued"&&e.event_type!=="TaskCompleted"&&e.event_type!=="TaskLeased").slice(-9).reverse().map(e=>{
      const candidate=N.cById[e.payload?.hypothesis_id];
      return {sequence:e.sequence,label:e.event_type,summary:candidate?.title??e.payload?.task_id??e.payload?.slot_id??e.payload?.match_id??"原生事件",
        time:e.occurred_at?new Date(e.occurred_at).toLocaleTimeString("zh-CN",{hour12:false}):"—",
        raw:e,alert:/Failure|Rejected|NeedsAttention|Invalid/.test(e.event_type)};
    });
    const started=N.events[0]?.occurred_at,last=info.occurred_at;
    let elapsed=null;
    if(started&&last){const n=Date.parse(last)-Date.parse(started);if(Number.isFinite(n))elapsed=n/1000}
    return {kind:"native",runId:N.runId,study:N.study,maxGenerations:N.maxGenerations,totalSlots:N.totalSlots,
      g:info.g??idx,state:explicitState,gLabel:info.label,subtitle:info.summary,
      elapsed,span:N.timeline?.event_span_seconds??null,
      spent:hasCost?costs:null,spentNote:"导出记录总额 · 非账单或当前时间点费用",
      candidateTotal:candidates.length,eligible:candidates.filter(c=>c.ranked).length,
      matches:matched,calls,retries:failures,
      candidates,ranking:N.ranking,final:complete?final:(final??null),isFormal:complete,activity,
      timeText:elapsed===null?"event "+info.seq:minClock(elapsed)+(N.timeline?.event_span_seconds?(" / "+minClock(N.timeline.event_span_seconds)):"")};
  }

  function currentView(){return state.mode==="fixture"?fixtureView():nativeView()}
  function sortedRows(view){
    const ranked=view.candidates.filter(c=>c.ranked).sort((a,b)=>{
      const delta=(b.score?.mu??0)-(a.score?.mu??0);
      return delta||a.id.localeCompare(b.id);
    });
    const pending=view.candidates.filter(c=>!c.ranked).sort((a,b)=>a.g-b.g||a.id.localeCompare(b.id));
    return {ranked,pending,all:[...ranked,...pending]};
  }

  function syncSelection(view,rows){
    if(!view.candidates.some(c=>c.id===state.selected))
      state.selected=rows.ranked[0]?.id??rows.pending[0]?.id??null;
  }

  function render(){
    const v=currentView(); cachedView=v;const rows=sortedRows(v);
    syncSelection(v,rows);
    const mode=state.mode==="fixture"?"SIMULATED DEMO":backendStatus?`${backendStatus.mode} · NATIVE RUN`:"IMPORTED NATIVE TRACE";
    $("#mode-badge").textContent=mode;$("#mode-badge").className="tag "+(state.mode==="fixture"?"tag-demo":"tag-native");
    $("#source-notice").innerHTML=state.mode==="fixture"?
      "<strong>演示数据</strong><span>所有候选内容、分数与事件均为合成示例，不是实际科研结果。可在右上角导入原生 JSON Trace。</span>":
      "<strong>原生数据导入</strong><span>正在本机浏览器中读取导出文件；榜单按导入事件重建，未连接实时 API。所有文件仅在本地处理。</span>";
    $("#side-study").textContent=short(v.study,80);$("#side-runid").textContent=v.runId;
    $("#side-scope").textContent="G0 → G"+v.maxGenerations;
    $("#side-runtime").textContent=state.mode==="fixture"?"DEMO / OFFLINE":"TRACE / READ ONLY";
    $("#side-mode").textContent=state.mode==="fixture"?"演示回放 · 离线":"原生 Trace · 离线";
    $("#origin-label").textContent=state.mode==="fixture"?"未连接真实 Runner":"已导入原生文件，未连接 Runner";
    $("#footer-source").textContent="数据源："+(state.mode==="fixture"?"SYNTHETIC FIXTURE":"NATIVE TRACE (LOCAL)");
    $("#subtitle").textContent=state.mode==="fixture"?
      "按时间线回放候选生成、实时排序与假设演化；点击候选查看完整科研内容。":
      "当前为原生 Trace 的本地历史回放；实时运行仍需连接 Web API。";
    const formal=v.final?.execution_result==="COMPLETE"&&v.final?.selection_result==="FINAL_WINNER"&&v.final?.terminal_barrier_complete===true;
    $("#run-state").innerHTML=formal?'<span class="run-state-dot"></span>已完成 · Final Winner':
      v.state==="Completed"?'<span class="run-state-dot"></span>演示完成':state.mode==="fixture"?
      '<span class="run-state-dot"></span>演示回放中':'<span class="run-state-dot"></span>'+escapeHtml(v.state==="Historical"?"历史事件回放":v.state);
    $("#stat-generation").innerHTML="G"+escapeHtml(v.g)+" <em>/ G"+escapeHtml(v.maxGenerations)+"</em>";
    $("#stat-stage").textContent=v.gLabel;
    $("#stat-candidates").innerHTML=escapeHtml(v.candidateTotal)+" <em>/ "+escapeHtml(v.totalSlots)+"</em>";
    $("#stat-eligible").textContent=v.eligible+" 个达到最低有效比较要求";
    $("#stat-matches").textContent=v.matches;
    $("#stat-updates").textContent=state.mode==="fixture"?"模拟有效比较次数":"原生 MatchEvaluated 事件数";
    $("#stat-cost").textContent=v.spent===null?"—":"$"+Number(v.spent).toFixed(3);
    $("#stat-cost-note").textContent=v.spentNote;
    $("#phase-time").textContent=v.timeText;
    $("#scrub-label").textContent=(state.frame+1)+" / "+frames().length+" · "+short(v.gLabel,35);
    $("#frame-slider").max=frames().length-1;$("#frame-slider").value=state.frame;
    $("#board-refresh-label").textContent=state.mode==="fixture"?"模拟事件驱动":"本地事件序列";
    $("#n-ranked").textContent=rows.ranked.length;
    $("#n-pending").textContent=rows.pending.length;
    $("#n-all").textContent=rows.all.length;
    renderPhase(v);renderBoard(v,rows);renderInspector(v);renderLineage(v);renderActivity(v);
    if(backendStatus&&state.mode==="native"){
      $("#source-notice").textContent=`原生 RunService · ${backendStatus.mode} · ${backendStatus.state}；Mock 是合成证据，不是科研结论。`;
      $("#origin-label").textContent="已连接本地 Python Runner";
      $("#side-mode").textContent="原生事件 / SSE";
      $("#side-runtime").textContent=backendStatus.mode;
      $("#subtitle").textContent="当前榜单来自原生已提交事件与 TrueSkill 投影；历史回放不改变科学状态。";
      $("#stat-cost-note").textContent="原生费用估算，非账单；reservation 另见状态";
      $("#footer-source").textContent="本地 Python / native trace";
    }
    if(state.modal)renderModal(v);
    window.dispatchEvent(new CustomEvent("co-scientist-monitor-update",{detail:{runId:v.runId,kind:v.kind,state:v.state}}));
  }

  function renderPhase(v){
    const phases=[];
    for(let g=0;g<=Math.min(v.maxGenerations,9);g++){
      let status=g<v.g?"done":g===v.g?"current":"waiting";
      if(g===v.g&&v.final?.execution_result==="COMPLETE")status="done";
      const count=v.candidates.filter(c=>c.g===g).length;
      phases.push(`<button type="button" class="phase-box ${status}" data-g="${g}" title="跳转至 G${g}">
        <span class="number">${status==="done"?"✓":"G"+g}</span><span><span class="phase-name">G${g}</span>
        <span class="phase-description">${count} 条可见候选 · ${status==="waiting"?"尚未开始":status==="done"?"已完成":"当前代际"}</span></span></button>`);
    }
    const rail=$("#phase-rail");rail.style.gridTemplateColumns="repeat("+phases.length+",minmax(0,1fr))";
    rail.innerHTML=phases.join("");
  }

  function renderBoard(v,rows){
    let chosen=rows[state.filter]??rows.ranked;
    if(state.query){const q=state.query.toLowerCase();chosen=chosen.filter(c=>(c.id+" "+c.title+" "+c.summary+" "+c.claim).toLowerCase().includes(q))}
    if(state.generation!=="all")chosen=chosen.filter(c=>String(c.g)===state.generation);
    const rankedIndices=new Map(rows.ranked.map((x,i)=>[x.id,i+1]));
    const html=chosen.map(c=>{
      const rank=rankedIndices.get(c.id);
      const smallStat=rank?"已排名":"评估中";
      const eName=c.operator==="root"?"ROOT":(c.operator??"").toUpperCase();
      const isFormal=v.final?.execution_result==="COMPLETE"&&v.final?.selection_result==="FINAL_WINNER"&&v.final?.terminal_barrier_complete;
      const isWinner=isFormal&&v.final.winner_id===c.id;
      return `<button type="button" class="candidate-row ${c.id===state.selected?"selected":""}" data-id="${escapeHtml(c.id)}">
         <span class="candidate-main"><span class="rank ${rank&&rank<=3?"top":""} ${!rank?"unrated":""}">${rank?"#"+rank:"待评"}</span>
           <span class="candidate-text">
             <span class="candidate-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}${isWinner?' <span class="detail-pill green">WINNER</span>':""}</span>
             <span class="candidate-description">${escapeHtml(cleanSentence(c.summary||c.claim))}</span>
             <span class="candidate-tags"><span class="tag-g">G${escapeHtml(c.g)}</span>${escapeHtml(eName)} <span>·</span> ${smallStat}</span>
           </span></span>
         <span class="candidate-score">${c.score?"μ "+two(c.score.mu):'<span class="pending-score">未评估</span>'}<span>${c.score?"σ "+two(c.score.sigma):"等待初始评分"}</span></span>
         <span class="candidate-matches">${c.matches}<span class="match-check ${rank?"good":""}">${rank?"已达标":"未达标"}</span></span>
       </button>`;
    }).join("");
    $("#candidate-list").innerHTML=html||`<div class="board-empty">${state.filter==="pending"?"当前没有等待评价的候选。":"当前阶段没有符合条件的候选。"}<br>可调整筛选条件或移动回放时间线。</div>`;
    $$('.segmented button').forEach(b=>b.classList.toggle("selected",b.dataset.filter===state.filter));
    $("#board-footnote").textContent=rows.ranked.length?"μ 高不等于实验验证 · σ 反映模型排名不确定性":"等待完成有效比较后显示正式排序";
  }

  function renderInspector(v){
    const c=v.candidates.find(c=>c.id===state.selected);
    if(!c){$("#inspector-content").innerHTML='<div class="board-empty">当前尚无候选。播放时间线或导入 Trace 开始查看。</div>';return}
    $("#inspector-content").innerHTML=renderDetail(c,v);
  }

  function detailHero(c,v) {
    const winner=v.final?.winner_id===c.id&&v.final?.execution_result==="COMPLETE"&&v.final?.selection_result==="FINAL_WINNER"&&v.final?.terminal_barrier_complete===true;
    return `<div class="inspector-hero">
      <div class="detail-eyebrow">G${escapeHtml(c.g)} · ${escapeHtml(c.operator==="root"?"ROOT":c.operator?.toUpperCase())} ${winner?'· FINAL WINNER':""}</div>
      <h3>${escapeHtml(c.title)}</h3>
      <p class="summary">${escapeHtml(c.claim||c.summary)}</p>
      <div class="inspector-score-row">
        <div class="inspector-score"><span>Posterior μ</span><strong>${c.score?two(c.score.mu):"—"}</strong></div>
        <div class="inspector-score"><span>Uncertainty σ</span><strong>${c.score?two(c.score.sigma):"—"}</strong></div>
        <div class="inspector-score"><span>有效比较</span><strong class="sub">${escapeHtml(c.matches)}</strong></div>
      </div></div>`;
  }
  function listSection(title,content,ordered=false){
    if(!Array.isArray(content)||!content.length)return `<div class="detail-section"><h4>${escapeHtml(title)}</h4><div class="detail-muted">暂无已记录数据。</div></div>`;
    const t=ordered?"ol":"ul";
    return `<div class="detail-section"><h4>${escapeHtml(title)}</h4><${t}>${content.map(x=>`<li>${escapeHtml(typeof x==="string"?x:JSON.stringify(x,null,2))}</li>`).join("")}</${t}></div>`;
  }
  function rawSection(name,payload){
    return `<div class="detail-section"><h4>${escapeHtml(name)}</h4><pre class="rawjson">${escapeHtml(JSON.stringify(payload,null,2))}</pre></div>`;
  }
  function detailBody(c,v){
    if(state.tab==="hypothesis"){
      return `<div class="detail-section"><h4>核心科学假设 / Claim</h4><p>${escapeHtml(c.claim||"无原始 Claim。")}</p></div>`+
        listSection("机制链 / Mechanism",c.mechanism_chain,true)+listSection("前提假设 / Assumptions",c.assumptions,true)+
        listSection("可检验预测 / Predictions",c.predictions,true)+listSection("证伪条件 / Falsifiers",c.falsifiers,true);
    }
    if(state.tab==="evidence"){
      return c.source==="synthetic-fixture"?`<div class="detail-muted">演示数据不包含真实文献引用，不伪造 PMID、支持度或证据覆盖。</div>`:
        `<div class="detail-muted">以下为此 Run 的原生检索、Source Review、冻结 Grounding 和 Generation 事实，保留各 root/binding 身份；不代表所有来源支持当前候选的每条主张。请按 source_set_hash、父代及原始 Artifact 核对，不推断证据支持。</div>`+
        rawSection("Run 级来源与冻结输入（原生事实）",c.raw?.source_and_generation_records??[])+
        rawSection("候选 Ethics 审查记录",c.ethics??[]);
    }
    if(state.tab==="reflection"){
      if(c.source==="synthetic-fixture")return listSection("模拟 Reflection 意见",c.reflection);
      return (c.reflection?.length?c.reflection.map((x,i)=>rawSection("Reflection "+(i+1),x)).join(""):`<div class="detail-muted">当前候选尚无 Reflection 记录。</div>`) +
        (c.ethics?.length?rawSection("Candidate Ethics 原始记录",c.ethics):"");
    }
    if(state.tab==="ranking"){
      const assoc=(v.ranking??[]).filter(m=>m.a===c.id||m.b===c.id||m.left_id===c.id||m.right_id===c.id);
      if(!assoc.length)return `<div class="detail-muted">当前尚无属于此候选的有效 Ranking 记录。</div>`;
      return assoc.slice().reverse().map((m,i)=>{
        const left=m.left_id??m.a,right=m.right_id??m.b;const other=left===c.id?right:left;
        return `<div class="detail-section"><h4>配对 ${assoc.length-i} · ${escapeHtml(other)}</h4>
          <p>${escapeHtml(m.reason??m.original_validated_decision??m.status??"原生排序记录")}</p>
          <p class="detail-mono">Match ID: ${escapeHtml(m.match_id??"—")} · ${escapeHtml(m.status??"")}</p>
          ${c.source==="native-export"?`<details><summary class="detail-mono">原始对比数据</summary><pre class="rawjson">${escapeHtml(JSON.stringify(m,null,2))}</pre></details>`:""}
        </div>`;
      }).join("");
    }
    if(state.tab==="evolution"){
      const parentlist=c.parents?.length?
        c.parents.map(id=>`<button class="parent-link" type="button" data-parent="${escapeHtml(id)}">${escapeHtml(v.candidates.find(x=>x.id===id)?.title??id)} ↗</button>`).join(""):
        `<div class="detail-muted">G0 初始候选，无科学父代。</div>`;
      return `<div class="detail-section"><h4>演化方式</h4><span class="detail-pill">${escapeHtml(c.operator==="root"?"独立生成":c.operator)}</span></div>
        <div class="detail-section"><h4>科学父代</h4>${parentlist}</div>
        <div class="detail-muted">完整演化计划、UCB 父代抽样、父代贡献和 Reflection 输入可在原生 evolution-tree.json 中审阅。</div>`+
        (state.mode==="native"&&state.native?.tree?.reproduction?
          rawSection("关联的演化计划（原始）",state.native.tree.reproduction.filter(e=>(e.children??[]).includes(c.id)).slice(0,3)):"");
    }
    return rawSection("候选原生结构化记录",c.raw??c);
  }

  const tabs=[["hypothesis","完整假设"],["evidence","证据"],["reflection","Reflection"],["ranking","Ranking"],["evolution","演化"],["raw","原文 JSON"]];
  function renderDetail(c,v){
    return detailHero(c,v)+`<div class="inspector-tabs" role="tablist">${tabs.map(([k,t])=>`<button type="button" role="tab" class="detail-tab ${state.tab===k?"active":""}" data-tab="${k}">${t}</button>`).join("")}</div>`+
      `<div class="inspector-body">${detailBody(c,v)}<button type="button" class="detail-action" data-copy="${escapeHtml(c.id)}">复制当前候选 JSON</button></div>`;
  }
  function renderModal(v){
    const c=v.candidates.find(x=>x.id===state.selected);
    if(!c)return;
    $("#modal-title").textContent="完整候选 · G"+c.g;
    $("#modal-content").innerHTML=renderDetail(c,v);
  }

  function renderLineage(v){
    const svg=$("#lineage"),candidates=v.candidates.filter(c=>c.g>=0&&c.g<=v.maxGenerations);
    const byGen=Object.groupBy?Object.groupBy(candidates,c=>c.g):candidates.reduce((r,c)=>{(r[c.g]??=[]).push(c);return r},{});
    const groups=Object.keys(byGen);
    const maxCnt=Math.max(1,...Object.values(byGen).map(a=>a.length));
    const width=Math.max(920,(Math.min(v.maxGenerations,7)+1)*228+14);
    const height=Math.max(220,maxCnt*47+62);
    svg.setAttribute("viewBox",`0 0 ${width} ${height}`);
    const pos={};
    for(let g=0;g<=v.maxGenerations&&g<=7;g++){
      const a=byGen[g]??[];a.forEach((c,i)=>{pos[c.id]={x:24+g*224,y:38+i*47}})}
    let html="";
    for(let g=0;g<=v.maxGenerations&&g<=7;g++){
      html+=`<text class="lineage-label" x="${31+g*224}" y="20">GENERATION G${g}</text>`;
      html+=`<line x1="${16+g*224}" x2="${16+g*224}" y1="28" y2="${height-12}" stroke="#edf1f7"/>`;
    }
    for(const c of candidates)for(const id of c.parents??[]){
      const p=pos[id],child=pos[c.id];if(!p||!child)continue;
      const x1=p.x+181,y1=p.y+16,x2=child.x,y2=child.y+16;
      html+=`<path class="lineage-edge ${c.operator==="mutation"?"mutation":""}" d="M ${x1} ${y1} C ${x1+20} ${y1}, ${x2-18} ${y2}, ${x2} ${y2}"/>`;
    }
    for(const c of candidates){
      const pt=pos[c.id];if(!pt)continue;
      html+=`<g class="lineage-node ${c.id===state.selected?"selected":""} ${c.g===0?"root":""}" tabindex="0" role="button" data-id="${escapeHtml(c.id)}" aria-label="查看${escapeHtml(c.title)}">
        <rect x="${pt.x}" y="${pt.y}" width="181" height="34" rx="6"/>
        <text x="${pt.x+10}" y="${pt.y+14}">${escapeHtml(short(c.title,24))}</text>
        <text class="small" x="${pt.x+10}" y="${pt.y+27}">${escapeHtml(c.operator?.toUpperCase()??"ROOT")}${c.id===state.selected?" · SELECTED":""}</text></g>`;
    }
    svg.innerHTML=html;
  }

  function renderActivity(v){
    $("#activity-feed").innerHTML=v.activity.slice(0,5).map(a=>`<div class="activity-row">
      <span class="activity-mark ${a.alert?"alert":a.label==="最终选择"?"success":""}"></span>
      <div class="activity-text"><strong>${escapeHtml(short(a.label,62))}</strong><p>${escapeHtml(short(a.summary,145))}</p></div>
      <time>${escapeHtml(a.time??a.sequence)}</time></div>`).join("")||'<div class="board-empty">暂无执行事件。</div>';
    const raws=(v.activity??[]).slice(0,8).map(x=>x.raw??x);
    $("#raw-feed").innerHTML=`<pre>${escapeHtml(JSON.stringify(raws,null,2))}</pre>`;
    $("#raw-feed").classList.toggle("hidden",!state.rawOpen);
    $("#toggle-raw").textContent=state.rawOpen?"隐藏原始事件":"显示原始事件";
  }

  function choose(id){
    if(!cachedView?.candidates?.some(c=>c.id===id))return;
    state.selected=id;state.tab="hypothesis";render();
  }
  function goto(index){
    stopPlayback();state.frame=Math.min(frames().length-1,Math.max(0,index));render();
  }
  function play(){
    if(state.playing){stopPlayback();return}
    if(state.frame===frames().length-1)state.frame=0;
    state.playing=true;$("#play-icon").textContent="❚❚";$("#btn-play").title="暂停回放";
    const speed=Number($("#play-speed").value);
    state.timer=setInterval(()=>{
      if(state.frame>=frames().length-1){stopPlayback();return}
      state.frame++;render();if(state.frame>=frames().length-1)stopPlayback();
    },speed);
    render();
  }
  function download(name,content,type){
    const blob=new Blob([content],{type});
    const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);
  }

  $("#btn-play").addEventListener("click",play);
  $("#btn-prev").addEventListener("click",()=>goto(state.frame-1));
  $("#btn-next").addEventListener("click",()=>goto(state.frame+1));
  $("#frame-slider").addEventListener("input",e=>goto(Number(e.target.value)));
  $("#play-speed").addEventListener("change",()=>{if(state.playing){stopPlayback();play()}});
  $("#btn-back-demo").addEventListener("click",()=>{
    backendStatus=null;
    stopPlayback();state.mode="fixture";state.native=null;nativePayloads=null;nativeRawTexts=null;state.frame=9;state.filter="ranked";state.query="";
    state.generation="all";state.tab="hypothesis";state.selected=null;$("#search-input").value="";$("#gen-filter").value="all";render();notify("已切换至合成演示数据");
  });
  $("#btn-import").addEventListener("click",()=>$("#trace-files").click());
  $("#trace-files").addEventListener("change",async e=>{
    backendStatus=null;
    const files=[...e.target.files];if(!files.length)return;
    try{
      const payloads={};
      const rawTexts={};
      for(const file of files){
        if(file.size>24_000_000)throw new Error(file.name+" 大于 24MB，当前原型拒绝导入。");
        if(!/^(candidates|run-timeline|ranking-history|evolution-tree|ideation-report)\.(json|md)$/.test(file.name))continue;
        const txt=await file.text();rawTexts[file.name]=txt;payloads[file.name]=file.name.endsWith(".json")?JSON.parse(txt):txt;
      }
      const imported=importNative(payloads);
      nativePayloads=payloads;nativeRawTexts=rawTexts;state.native=imported;state.mode="native";stopPlayback();state.frame=state.native.frames.length-1;
      state.selected=null;state.tab="hypothesis";
      state.filter=state.native.candidates.some(c=>Number(c.rating?.decisive_matches??0)>=2)?"ranked":"all";
      state.query="";$("#search-input").value="";
      state.generation="all";$("#gen-filter").value="all";render();
      notify("已在本机导入 "+Object.keys(payloads).length+" 个原生文件；可回放排名历史");
    }catch(err){notify("导入失败："+String(err.message??err));console.error(err)}
    e.target.value="";
  });
  $("#btn-export").addEventListener("click",()=>{
    const v=cachedView;
    const safe = {format:"co-scientist-monitor-view-v2",notice:"Snapshot of UI; not native scientific trace",source:v.kind,
      run_id:v.runId,step:state.frame,state:v.state,generation:v.g,counts:{candidate:v.candidateTotal,eligible:v.eligible,matches:v.matches},
      candidates:v.candidates.map(c=>({id:c.id,g:c.g,title:c.title,claim:c.claim,mechanism_chain:c.mechanism_chain,
        assumptions:c.assumptions,predictions:c.predictions,falsifiers:c.falsifiers,scientific_parent_ids:c.parents,
        operator:c.operator,score:c.score,valid_decisive:c.matches})),final_selection:v.final};
    download("co-scientist-monitor-view.json",JSON.stringify(safe,null,2),"application/json");
    notify("已导出当前页面快照（非原生完整 Trace）");
  });
  $$('.segmented button').forEach(b=>b.addEventListener("click",()=>{state.filter=b.dataset.filter;render()}));
  $("#search-input").addEventListener("input",e=>{state.query=e.target.value.trim();render()});
  $("#gen-filter").addEventListener("change",e=>{state.generation=e.target.value;render()});
  $("#toggle-raw").addEventListener("click",()=>{state.rawOpen=!state.rawOpen;renderActivity(cachedView)});
  $("#candidate-list").addEventListener("click",e=>{
    const b=e.target.closest("[data-id]");if(b)choose(b.dataset.id);
  });
  $("#lineage").addEventListener("click",e=>{const g=e.target.closest("[data-id]");if(g)choose(g.dataset.id)});
  $("#lineage").addEventListener("keydown",e=>{if(e.key==="Enter"){const g=e.target.closest("[data-id]");if(g)choose(g.dataset.id)}});
  $("#phase-rail").addEventListener("click",e=>{
    const b=e.target.closest("[data-g]");if(!b)return;const g=Number(b.dataset.g);
    const ind=frames().findIndex(f=>f.g===g);
    goto(ind>=0?ind:state.frame);
  });
  function delegatedDetailClick(e){
    const tab=e.target.closest("[data-tab]");
    if(tab){state.tab=tab.dataset.tab;render();return}
    const parent=e.target.closest("[data-parent]");
    if(parent){choose(parent.dataset.parent);return}
    const copy=e.target.closest("[data-copy]");
    if(copy){
      const c=cachedView.candidates.find(x=>x.id===copy.dataset.copy);
      const value=JSON.stringify(c?.raw??c,null,2);
      const fallback=()=>{const t=document.createElement("textarea");t.value=value;document.body.append(t);t.select();document.execCommand("copy");t.remove();notify("已复制候选 JSON")};
      if(navigator.clipboard?.writeText)navigator.clipboard.writeText(value).then(()=>notify("已复制候选 JSON"),fallback);
      else fallback();
    }
  }
  $("#inspector-content").addEventListener("click",delegatedDetailClick);
  $("#modal-content").addEventListener("click",delegatedDetailClick);
  $("#btn-expand").addEventListener("click",()=>{
    if(!state.selected){notify("请先选择一条候选");return}
    state.modal=true;$("#modal-backdrop").classList.remove("hidden");renderModal(cachedView);
  });
  $("#close-modal").addEventListener("click",()=>{state.modal=false;$("#modal-backdrop").classList.add("hidden")});
  $("#modal-backdrop").addEventListener("click",e=>{if(e.target.id==="modal-backdrop"){$("#close-modal").click()}});
  document.addEventListener("keydown",e=>{if(e.key==="Escape"&&state.modal)$("#close-modal").click()});
  window.CoScientistMonitor = {
    loadBackend:(payloads,status)=>{
      backendStatus=status;nativePayloads=payloads;
      nativeRawTexts=Object.fromEntries(Object.entries(payloads).map(([k,v])=>[k,typeof v==="string"?v:JSON.stringify(v,null,2)]));
      state.native=importNative(payloads);
      const types=new Set(["RootReviewPlannedV1","RootRetrievalOutcomeRecordedV2","RootRetrievalReusedV2","RootSourceReviewRecordedV1","RootGroundingFrozenV1","GroundedGenerationRecordedV1"]);
      const related=state.native.events.filter(e=>types.has(e.event_type));
      for(const c of state.native.candidates)c.raw={...c.raw,source_and_generation_records:related};
      state.mode="native";stopPlayback();state.frame=state.native.frames.length-1;render();
    },
    snapshot:()=>cachedView,
    candidates:()=>sortedRows(cachedView),
    showFinal:()=>goto(frames().length-1),
    pause:()=>stopPlayback(),
    select:(id)=>choose(id),
    detailHTML:(id,tab="hypothesis")=>{
      const c=cachedView?.candidates.find(x=>x.id===id);
      if(!c)return "";
      const prev=state.tab;state.tab=tab;
      const html=detailBody(c,cachedView);state.tab=prev;return html;
    },
    nativePayloads:()=>nativePayloads,
    nativeRawTexts:()=>nativeRawTexts,
    imported:()=>state.native,
    sourceMode:()=>state.mode,
  };
  render();
})();
