/* Same-origin authenticated adapter. No provider calls or scientific computation. */
(() => {
  "use strict";
  const $=s=>document.querySelector(s), M=window.CoScientistMonitor;
  const escape=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  let csrf="", currentRun=null, projectId=null, draftId=null, latest=null, source=null, lastSequence=-1, loading=false;
  let catalog={projects:[],drafts:[],runs:[]};
  const notify=text=>{const t=$("#toast");t.textContent=text;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),5000);};
  async function api(path,method="GET",data){
    const response=await fetch("/api/v1"+path,{method,credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:data===undefined?undefined:JSON.stringify(data)});
    const value=await response.json();
    if(!response.ok)throw new Error(JSON.stringify(value));
    return value;
  }
  const safely=fn=>async event=>{event?.preventDefault();try{await fn(event);}catch(error){notify(error.message);}};
  document.addEventListener("change",event=>{
    if(event.target.id!=="trace-files"||!event.target.files.length)return;
    currentRun=null;source?.close();lastSequence=-1;
    history.replaceState(null,"",location.pathname+"#monitor");
  },true);
  function capture(selector,event,fn){document.addEventListener(event,e=>{const node=e.target.closest(selector);if(!node)return;e.preventDefault();e.stopImmediatePropagation();safely(fn)(e);},true);}
  function form(){return {project_id:projectId,goal:{title:$("#wb-title").value.trim(),goal:$("#wb-goal").value.trim(),
    required_causal_chain:$("#wb-chain").value.split(/\n/).map(x=>x.trim()).filter(Boolean),required_outputs:$("#wb-outputs").value.split(/\n/).map(x=>x.trim()).filter(Boolean)},
    run_config:{template_id:"continuous-g3-r2-default",generation_model:$("#wb-model-generation").value,review_evolution_model:$("#wb-model-review").value,
      root_slots:Number($("#wb-roots").value),reproduction_transitions:Number($("#wb-generations").value),reproduction_slots_per_transition:Number($("#wb-offspring").value),
      risk_ceiling_usd:String(Number($("#wb-budget").value)),wall_minutes:Number($("#wb-time").value)},
    mode:$("#wb-type").value,constraints_note:$("#wb-constraints").value};}
  async function preflight(){
    const result=await api("/config/preflight","POST",form());
    $("#wb-preflight-list").textContent=`原生预检 PASS · ${result.configuration_hash}\n保守规划 $${result.conservative_reservation_usd} / 风险上限 $${result.user_risk_ceiling_usd}。未检查账户权限，没有付费调用。`;
    return result;
  }
  function renderProjects(){
    if(document.body.dataset.activePage!=="projects")return;
    const query=$("#wb-project-search").value.toLowerCase();
    const cards=[...catalog.runs.map(x=>({id:x.id,title:x.title,kind:x.mode,label:"打开原生运行",action:"run"})),
      ...catalog.drafts.map(x=>({id:x.id,title:x.goal.title,kind:"服务器草稿",label:"继续编辑",action:"draft"})),
      ...catalog.projects.map(x=>({id:x.id,title:x.title,kind:"服务器项目",label:"在此项目创建任务",action:"project"}))];
    $("#wb-project-list").innerHTML=cards.filter(x=>(x.title+" "+x.id).toLowerCase().includes(query)).map(x=>`<article class="wb-project-card"><h3>${escape(x.title)}</h3><span>${escape(x.kind)}</span><code>${escape(x.id)}</code><button type="button" class="btn primary" data-server-action="${x.action}" data-key="${escape(x.id)}">${escape(x.label)}</button></article>`).join("")+`<article class="wb-project-card demo"><h3>DEMO · 合成 UI 演示</h3><p>不属于服务器 Run 列表，不是实际科研结果。</p><button type="button" class="btn secondary" id="backend-demo">查看演示</button></article>`;
    $("#wb-total-projects").textContent=catalog.projects.length;$("#wb-drafts-count").textContent=catalog.drafts.length;$("#wb-imports-count").textContent=catalog.runs.length;
  }
  async function refreshCatalog(){
    [catalog.projects,catalog.drafts,catalog.runs]=await Promise.all([api("/projects"),api("/drafts"),api("/runs")]);renderProjects();
  }
  function fillDraft(d){
    projectId=d.project_id;draftId=d.id;location.hash="#create";
    $("#wb-title").value=d.goal.title;$("#wb-goal").value=d.goal.goal;$("#wb-chain").value=d.goal.required_causal_chain.join("\n");$("#wb-outputs").value=d.goal.required_outputs.join("\n");$("#wb-constraints").value=d.constraints_note;
    $("input[name=wb-config-mode][value=custom]").checked=true;$("input[name=wb-config-mode][value=custom]").dispatchEvent(new Event("change",{bubbles:true}));
    const c=d.run_config;for(const [id,key] of [["wb-model-generation","generation_model"],["wb-model-review","review_evolution_model"],["wb-roots","root_slots"],["wb-generations","reproduction_transitions"],["wb-offspring","reproduction_slots_per_transition"],["wb-budget","risk_ceiling_usd"],["wb-time","wall_minutes"]])$("#"+id).value=c[key];
    $("#wb-type").value=d.mode;
  }
  async function saveDraft(){
    if(!projectId){projectId=(await api("/projects","POST",{title:$("#wb-title").value||"未命名研究"})).id;}
    const d=await api(draftId?"/drafts/"+draftId:"/drafts",draftId?"PATCH":"POST",form());draftId=d.id;
    $("#wb-form-status").textContent="已保存服务器草稿 "+d.id;await refreshCatalog();notify("草稿已保存到本地后端数据库");
  }
  async function settings(){
    const s=await api("/settings/status");
    for(const [id,key] of [["#wb-openai-state","openai_configured"],["#wb-deepseek-state","deepseek_configured"],["#wb-pubmed-state","pubmed_email_configured"]])$(id).textContent=s[key]?"后端内存已配置 · 未验证":"未配置";
    $("#wb-settings-summary").textContent="后端进程内存保存；重启需重新输入，不验证账户权限";
    $("#wb-config-credential-status").textContent=`OpenAI ${s.openai_configured?"已配置":"未配置"} · DeepSeek ${s.deepseek_configured?"已配置":"未配置"} · PubMed ${s.pubmed_email_configured?"已配置":"未配置"}`;
  }
  capture("#wb-settings-form","submit",async()=>{
    // Read only to make authenticated PUT; clear even on validation/network error.
    try{
      for(const [id,p] of [["wb-secret-openai","openai"],["wb-secret-deepseek","deepseek"]]){
        const input=$("#"+id);if(input.value.trim())await api("/settings/credentials/"+p,"PUT",{key:input.value.trim()});
      }
      const email=$("#wb-pubmed-email").value.trim();if(email)await api("/settings/pubmed","PUT",{email});
      await settings();notify("已保存到后端内存，未向模型或 PubMed 发出请求");
    }finally{for(const id of ["wb-secret-openai","wb-secret-deepseek"]){$("#"+id).value="";$("#"+id).type="password";}}
  });
  capture("#wb-settings-clear","click",async()=>{await api("/settings/credentials/openai","DELETE");await api("/settings/credentials/deepseek","DELETE");await api("/settings/pubmed","DELETE");$("#wb-pubmed-email").value="";await settings();});
  capture("#wb-save-draft","click",saveDraft);
  capture("#wb-run-check","click",async()=>{await preflight();notify("原生离线预检通过");});
  function showApproval(){
    for(const id of ["backend-confirm","backend-pricing","backend-unknown"])$("#"+id).checked=false;
    $("#backend-approval-info").textContent=`Run ${currentRun}\n${latest.mode}\n保守规划 $${latest.limits.conservative_usd}\n风险上限 $${latest.limits.risk_ceiling_usd}\nLIVE 还要求明确确认价格/权限和可能重复计费风险。`;
    $("#backend-approval").showModal();
  }
  capture("#backend-create","click",async()=>{
    await saveDraft();const pf=await preflight();const run=await api("/runs","POST",{preflight_id:pf.preflight_id});
    currentRun=run.id;latest=await api(`/runs/${currentRun}/status`);showApproval();await refreshCatalog();
  });
  capture("#backend-open-approval","click",async()=>{
    if(!currentRun)throw new Error("请选择服务器 Run");
    latest=await api(`/runs/${currentRun}/status`);
    if(latest.state!=="prepared")throw new Error("当前不是待启动 Run；非终态中断请使用原生恢复");
    if(latest.authorized){await api(`/runs/${currentRun}/start`,"POST");await attach(currentRun);}else showApproval();
  });
  capture("#backend-cancel","click",async()=>{$("#backend-approval").close();await attach(currentRun);});
  capture("#backend-approve","click",async()=>{
    if(!$("#backend-confirm").checked)throw new Error("必须明确接受此 Run 的费用风险上限");
    if(latest.mode==="LIVE_SINGLE_DISPATCH"&&(!$("#backend-pricing").checked||!$("#backend-unknown").checked))throw new Error("LIVE 必须分别确认价格/权限和 unknown-delivery 风险");
    await api(`/runs/${currentRun}/authorize`,"POST",{confirm:true,accept_usd:latest.limits.risk_ceiling_usd,confirm_pricing:$("#backend-pricing").checked,accept_unknown_risk:$("#backend-unknown").checked});
    $("#backend-approval").close();await api(`/runs/${currentRun}/start`,"POST");await attach(currentRun);
  });
  capture("[data-server-action]","click",async e=>{
    const b=e.target.closest("[data-server-action]");
    if(b.dataset.serverAction==="run")await attach(b.dataset.key);
    if(b.dataset.serverAction==="draft")fillDraft(catalog.drafts.find(x=>x.id===b.dataset.key));
    if(b.dataset.serverAction==="project"){projectId=b.dataset.key;draftId=null;location.hash="#create";}
  });
  capture("#backend-demo","click",()=>{currentRun=null;source?.close();history.replaceState(null,"",location.pathname+"#monitor");$("#btn-back-demo").click();location.hash="#monitor";});
  capture("#backend-stop","click",async()=>{if(!currentRun)throw new Error("请选择服务器 Run");if(!confirm("终止后为 PARTIAL，不是暂停，不能继续原科学流程。确认？"))return;await api(`/runs/${currentRun}/stop`,"POST");notify("已请求原生终止，当前有界调用完成后关闭");});
  capture("#backend-reconnect","click",async()=>{if(!currentRun)throw new Error("请选择服务器 Run");await update();connect();});
  capture("#backend-resume","click",async()=>{if(!currentRun)throw new Error("请选择服务器 Run");if(!confirm("恢复将继续原 Run 执行，可能发出付费 API 请求。确认已检查故障、原始响应及授权？"))return;await api(`/runs/${currentRun}/resume`,"POST",{confirm_execution:true});connect();await update();});
  capture("#backend-export","click",async()=>{if(!currentRun)throw new Error("请选择服务器 Run");const x=await api(`/runs/${currentRun}/exports`,"POST");const a=document.createElement("a");a.href=`/api/v1/runs/${currentRun}/exports/${x.export_id}`;a.download="native-trace.zip";a.click();notify("原生五项 Trace，非前端阅读报告");});
  function connect(){source?.close();source=new EventSource(`/api/v1/runs/${currentRun}/stream?after=${Math.max(0,lastSequence)}`);
    source.addEventListener("run.event",()=>update());source.addEventListener("boundary",()=>{source.close();update();});}
  async function attach(id){currentRun=id;lastSequence=-1;history.replaceState(null,"",`?run=${encodeURIComponent(id)}#monitor`);location.hash="#monitor";await update();connect();}
  async function update(){
    if(loading||!currentRun)return;loading=true;
    try{
      const id=currentRun;latest=await api(`/runs/${id}/status`);
      if((latest.events??0)!==lastSequence){
        const packet=await api(`/runs/${id}/monitor?after=${Math.max(0,lastSequence)}`);
        if(id!==currentRun)return;
        M.loadEvents(packet,latest);lastSequence=packet.source_sequence;
      }
      $("#board-refresh-label").textContent=`${latest.state} · ${latest.job.state} · ${latest.events??0} events`;
      $("#backend-open-approval").disabled=latest.state!=="prepared";
      $("#backend-stop").disabled=["prepared","initializing","completed","completed_partial","failed","cancelled"].includes(latest.state);
      $("#backend-resume").disabled=["prepared","initializing","completed","completed_partial","failed","cancelled"].includes(latest.state)||latest.job.alive;
      const accounting=latest.accounting??{};
      $("#phase-hint").textContent=`估算 $${accounting.settled?.cost_usd??"0"} · 活动预留 $${accounting.actively_reserved?.cost_usd??"0"} · 风险上限 $${latest.limits.risk_ceiling_usd}；完整账务见原生 Trace`;
      if(document.body.dataset.activePage==="results"){
        $("#wb-results-source").textContent=`原生 ${latest.mode} · ${latest.state}；不是 DEMO。科学有效性仍需独立验证。`;
      }
    }catch(e){if(!e.message.includes("SNAPSHOT_BUSY"))notify(e.message);}finally{loading=false;}
  }
  window.addEventListener("hashchange",()=>{queueMicrotask(()=>{renderProjects();settings().catch(()=>{});if(currentRun)update();});});
  window.addEventListener("co-scientist-monitor-update",()=>{renderProjects();if(currentRun&&document.body.dataset.activePage==="results")$("#wb-results-source").textContent=`服务器原生 Run ${currentRun}，非导入文件、非 DEMO。`;});
  $("#wb-project-search").addEventListener("input",renderProjects);
  window.WorkbenchBackend={settings,renderProjects};
  async function boot(){
    csrf=(await api("/session")).csrf_token;
    await Promise.all([refreshCatalog(),settings(),api("/health")]);
    $(".connection").textContent="已连接 127.0.0.1 Python 后端";
    $("#wb-save-native-file").textContent="保存当前文件视图";
    for(const [selector,text] of [
      ["#page-settings .subtitle","凭据由本地后端进程内存处理；重启服务需重新提供。"],
      ["#page-settings .tag-demo","本地服务 · 账户未验证"],
      ["#page-settings .wb-block-head p","安全保存设置，不执行模型权限或付费探测"],
      ["#page-settings .wb-settings-facts>div:first-child span","127.0.0.1 Python 服务 · 已连接"],
      ["#page-create .subtitle","研究目标 → 冻结配置 → 原生预检 → 逐 Run 授权 → 后台执行"],
      ["#page-create .tag-demo","本地 Runner · 须逐 Run 授权"],
      ["#wb-save-draft","保存服务器草稿"]])$(selector).textContent=text;
    document.querySelectorAll(".wb-info").forEach(n=>{if(n.textContent.includes("未连接")||n.textContent.includes("当前仅用于交互演示")||n.textContent.includes("尚未获得执行授权"))n.textContent="本地 Python 服务 · Mock 无需凭据；LIVE 默认关闭，必须逐 Run 授权。凭据只保存在后端进程内存。";});
    const id=new URLSearchParams(location.search).get("run");if(id)await attach(id);
    setInterval(()=>{if(currentRun)update();},2500);
  }
  boot().catch(e=>notify("后端连接失败："+e.message));
})();
