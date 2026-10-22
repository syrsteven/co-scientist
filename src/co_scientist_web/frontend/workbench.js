/* Research Workbench 0.4 - five-page, offline-only UI.
 * Projects/drafts are client-local. No backend dispatch, paid calls or scientific mutation.
 */
(() => {
  "use strict";
  const $ = (selector,root=document) => root.querySelector(selector);
  const $$ = (selector,root=document) => [...root.querySelectorAll(selector)];
  const M = window.CoScientistMonitor;
  const STORE = "co-scientist-research-workbench-v03-drafts";
  const pages = ["projects","create","monitor","results","settings"];
  const pageNames = {projects:"研究项目",create:"创建任务",monitor:"运行监控",results:"结果中心",settings:"设置"};
  const defaults = {generationModel:"gpt-6.1-sol",reviewModel:"deepseek-flash",generations:3,roots:4,offspring:2,budget:60,time:120};
  const htmlEscape = v => String(v??"").replace(/[&<>"']/g,x=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]));
  const clean = (v,n=180) => {const s=String(v??"").replace(/\s+/g," ").trim();return s.length>n?s.slice(0,n-1)+"…":s;};
  const fmt = n => Number.isFinite(Number(n))?Number(n).toFixed(2):"—";
  const nameOf = id => {const c=(M.snapshot()?.candidates??[]).find(x=>x.id===id);return c?.title??id;};
  function notify(msg){const node=$("#toast");node.textContent=msg;node.classList.add("show");clearTimeout(notify.t);notify.t=setTimeout(()=>node.classList.remove("show"),3200);}
  function download(name,content,mime){const blob=new Blob([content],{type:mime}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
  function readStored(){try{const o=JSON.parse(localStorage.getItem(STORE)||"[]");return Array.isArray(o)?o.filter(x=>x&&typeof x==="object"&&!x.secret):[];}catch{return []}}
  function writeStored(){try{localStorage.setItem(STORE,JSON.stringify(projects));return true;}catch{notify("浏览器不支持本地保存；可下载任务草稿 JSON");return false}}
  let projects=readStored(),currentDraftId=null,step=0,resultsSearch="",selectedResult=null,resultsTab="hypothesis",compare=new Set(),currentPage="projects";
  let lastImportedRun=null;
  // Secrets are intentionally in-memory only. Never write them to storage,
  // drafts, logs, URL parameters, exports, DOM attributes or outbound requests.
  const sessionCredentials={openai:"",deepseek:""};
  const sessionProfile={pubmedEmail:"",researcherName:""};
  const validContactEmail = value => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) && value.length<=254;
  function renderCredentialStatus(){
    if(window.WorkbenchBackend){window.WorkbenchBackend.settings().catch(()=>{});return;}
    const openai=Boolean(sessionCredentials.openai),deepseek=Boolean(sessionCredentials.deepseek),email=Boolean(sessionProfile.pubmedEmail);
    const showState=(id,ok)=>{const el=$(id);el.textContent=ok?"本次会话已填写 · 未验证":"未填写";el.classList.toggle("filled",ok)};
    showState("#wb-openai-state",openai);showState("#wb-deepseek-state",deepseek);showState("#wb-pubmed-state",email);
    $("#wb-settings-summary").textContent=`已填写 ${[openai,deepseek,email].filter(Boolean).length}/3 项 · 无后端验证`;
    const mode=$("#wb-type").value;
    $("#wb-config-credential-status").textContent=mode==="MOCK_ONLY"
      ?"Mock 不要求凭据；真实运行需 OpenAI、DeepSeek 与 PubMed 联系邮箱"
      :`OpenAI ${openai?"已填写":"未填写"} · DeepSeek ${deepseek?"已填写":"未填写"} · PubMed ${email?"已填写":"未填写"}（未验证）`;
  }
  function clearUnsavedSecrets(){
    for(const id of ["wb-secret-openai","wb-secret-deepseek"]){const el=$("#"+id);el.value="";el.type="password";const btn=$(`[data-toggle-secret="${id}"]`);if(btn){btn.textContent="显示";btn.setAttribute("aria-label", "显示 " +(id.includes("openai")?"OpenAI":"DeepSeek")+" API Key");}}
  }
  $("#wb-settings-form").addEventListener("submit",event=>{
    event.preventDefault();
    const email=$("#wb-pubmed-email").value.trim(),displayName=$("#wb-researcher-name").value.trim();
    if(email&&!validContactEmail(email)){notify("请输入正确的 PubMed 联系邮箱格式");$("#wb-pubmed-email").focus();return;}
    const openai=$("#wb-secret-openai").value.trim(),deepseek=$("#wb-secret-deepseek").value.trim();
    if(openai)sessionCredentials.openai=openai;
    if(deepseek)sessionCredentials.deepseek=deepseek;
    sessionProfile.pubmedEmail=email;sessionProfile.researcherName=displayName;
    clearUnsavedSecrets();renderCredentialStatus();notify("设置已保存到当前标签页内存；未联网、未验证密钥");
  });
  $("#wb-settings-clear").addEventListener("click",()=>{
    sessionCredentials.openai="";sessionCredentials.deepseek="";
    sessionProfile.pubmedEmail="";sessionProfile.researcherName="";
    $("#wb-pubmed-email").value="";$("#wb-researcher-name").value="";
    clearUnsavedSecrets();renderCredentialStatus();notify("本次会话内的 API Key 和联系信息已清除");
  });
  $$('[data-toggle-secret]').forEach(btn=>btn.addEventListener("click",()=>{
    const el=document.getElementById(btn.dataset.toggleSecret),visible=el.type==="password";
    el.type=visible?"text":"password";btn.textContent=visible?"隐藏":"显示";
    btn.setAttribute("aria-label",(visible?"隐藏 ":"显示 ")+(el.id.includes("openai")?"OpenAI":"DeepSeek")+" API Key");
  }));
  // No automatic checking against external providers in the offline prototype.
  window.addEventListener("pagehide",()=>{
    sessionCredentials.openai="";sessionCredentials.deepseek="";
    sessionProfile.pubmedEmail="";sessionProfile.researcherName="";
    clearUnsavedSecrets();
    $("#wb-pubmed-email").value="";$("#wb-researcher-name").value="";
  });
  window.addEventListener("pageshow",renderCredentialStatus);


  function setPage(requested){
    const route=pages.includes(requested)?requested:"projects";
    const previousPage=currentPage;
    currentPage=route;
    document.body.dataset.activePage=route;
    $$('[data-page]').forEach(node=>node.classList.toggle("hidden",node.dataset.page!==route));
    $$("[data-nav]").forEach(node=>{const active=node.dataset.nav===route;node.classList.toggle("active",active);node.setAttribute("aria-current",active?"page":"false")});
    $("#wb-crumb").textContent=pageNames[route];
    const topControls=route==="monitor"||route==="results";
    $("#btn-import").classList.toggle("hidden",!topControls);
    $("#btn-export").classList.toggle("hidden",route!=="monitor");
    if(previousPage==="settings"&&route!=="settings")clearUnsavedSecrets();
    if(route!=="monitor") M.pause();
    if(route==="create"||route==="settings")renderCredentialStatus();
    if(route==="projects")renderProjects();
    if(route==="create")renderWizard();
    if(route==="results")renderResults();
    window.scrollTo?.({top:0,behavior:"instant"});
  }
  function go(page){if(!pages.includes(page))return; if(location.hash!=="#"+page)location.hash=page;setPage(page)}
  window.addEventListener("hashchange",()=>setPage(location.hash.slice(1)));
  $$("[data-nav]").forEach(b=>b.addEventListener("click",()=>go(b.dataset.nav)));
  $$("[data-go]").forEach(b=>b.addEventListener("click",()=>{if(b.dataset.go==="create")resetCreate();go(b.dataset.go)}));

  function demoProject(){return {id:"synthetic-demo-g3",title:"RPE Mitochondrial Stress",goal:"线粒体应激后 RPE 恢复与持续退变的候选机制研究。",kind:"demo",runId:window.MONITOR_FIXTURE?.runId,generations:3,updatedAt:"示例研究"};}
  function importedProject(){const n=M.imported();if(!n)return null;return {id:"imported-"+n.runId,title:n.study,goal:"本次浏览器会话内导入的 Native Trace；所有候选与事件来自用户所选文件。",kind:"native",runId:n.runId,generations:n.maxGenerations,updatedAt:lastImportedRun??"刚刚导入"};}
  function renderProjects(){
    if(window.WorkbenchBackend){window.WorkbenchBackend.renderProjects();return;}
    const p=[demoProject(),...(importedProject()?[importedProject()]:[]),...projects.map(x=>({...x,kind:"draft"}))];
    const q=$("#wb-project-search").value.trim().toLowerCase();
    const shown=p.filter(x=>(String(x.title??"")+" "+String(x.goal??"")).toLowerCase().includes(q));
    $("#wb-total-projects").textContent=p.length;
    $("#wb-drafts-count").textContent=projects.length;
    $("#wb-imports-count").textContent=importedProject()?"1":"0";
    $("#wb-project-list").innerHTML=shown.map(x=>{
      const state=x.kind==="demo"?"模拟演示":x.kind==="native"?"Native Trace":"本地草稿";
      const primary=x.kind==="draft"?"继续编辑":x.kind==="demo"?"打开模拟监控":"打开导入的监控";
      const secondary=x.kind==="draft"?"下载草稿 JSON":"查看结果中心";
      return `<article class="wb-project-card ${x.kind}"><div class="wb-card-heading"><h3>${htmlEscape(x.title||"未命名研究")}</h3><span class="wb-state-pill ${x.kind}">${state}</span></div>
        <p class="wb-card-desc">${htmlEscape(clean(x.goal||"尚未填写研究目标",250))}</p>
        <div class="wb-card-meta"><span>${htmlEscape(x.runId??x.id??"local")}</span><span>·</span><span>G0→G${htmlEscape(x.config?.generations??x.generations??3)}</span><span>·</span><span>${htmlEscape(x.updatedAt||"刚刚更新")}</span></div>
        <div class="wb-card-actions"><button type="button" class="btn primary compact" data-project-primary="${htmlEscape(x.id)}" data-kind="${x.kind}">${primary} →</button><button type="button" class="btn secondary compact" data-project-secondary="${htmlEscape(x.id)}" data-kind="${x.kind}">${secondary}</button>${x.kind==="draft"?`<button type="button" class="btn secondary compact" data-project-delete="${htmlEscape(x.id)}">删除</button>`:""}</div></article>`;
    }).join("")||'<div class="board-empty">没有匹配的研究。请清除搜索条件或新建科研任务。</div>';
  }
  $("#wb-project-search").addEventListener("input",renderProjects);
  $("#wb-project-import").addEventListener("click",()=>$("#trace-files").click());
  $("#wb-project-list").addEventListener("click",event=>{
    const primary=event.target.closest("[data-project-primary]");
    if(primary){
      if(primary.dataset.kind==="draft"){loadDraft(primary.dataset.projectPrimary);go("create")}else{if(primary.dataset.kind==="demo" && M.sourceMode()!=="fixture"){$("#btn-back-demo").click()}go("monitor")}
      return;
    }
    const secondary=event.target.closest("[data-project-secondary]");
    if(secondary){
      if(secondary.dataset.kind==="draft")downloadDraft(secondary.dataset.projectSecondary);
      else{if(secondary.dataset.kind==="demo"&&M.sourceMode()!=="fixture")$("#btn-back-demo").click();go("results")}
      return;
    }
    const remove=event.target.closest("[data-project-delete]");
    if(remove){const project=projects.find(x=>x.id===remove.dataset.projectDelete);if(!project)return;if(!confirm("确定删除本地草稿「"+project.title+"」？此操作只影响浏览器中保存的草稿。"))return;projects=projects.filter(x=>x.id!==project.id);if(currentDraftId===project.id)currentDraftId=null;writeStored();renderProjects();notify("已删除本地草稿");}
  });

  const fieldIds={title:"wb-title",goal:"wb-goal",chain:"wb-chain",outputs:"wb-outputs",constraints:"wb-constraints",generationModel:"wb-model-generation",reviewModel:"wb-model-review",generations:"wb-generations",roots:"wb-roots",offspring:"wb-offspring",budget:"wb-budget",time:"wb-time",runMode:"wb-type"};
  function textValue(id){return $("#"+fieldIds[id]).value.trim()}
  function intValue(id){return Number($("#"+fieldIds[id]).value)}
  function configMode(){return $("input[name=wb-config-mode]:checked").value}
  function collectForm(){
    const config={generationModel:textValue("generationModel"),reviewModel:textValue("reviewModel"),generations:intValue("generations"),roots:intValue("roots"),offspring:intValue("offspring"),budget:intValue("budget"),time:intValue("time")};
    return {title:textValue("title"),goal:textValue("goal"),required_causal_chain:textValue("chain").split(/\r?\n/).map(x=>x.trim()).filter(Boolean),required_outputs:textValue("outputs").split(/\r?\n/).map(x=>x.trim()).filter(Boolean),constraints:textValue("constraints"),configMode:configMode(),config,runMode:$("#wb-type").value};
  }
  function resetCreate(){
    currentDraftId=null;$("#wb-run-form").reset();
    $("#wb-model-generation").value=defaults.generationModel;$("#wb-model-review").value=defaults.reviewModel;
    $("#wb-generations").value=defaults.generations;$("#wb-roots").value=defaults.roots;
    $("#wb-offspring").value=defaults.offspring;$("#wb-budget").value=defaults.budget;$("#wb-time").value=defaults.time;
    $("#wb-type").value="MOCK_ONLY";step=0;updateConfigMode();renderWizard();
  }
  function loadDraft(id){
    const x=projects.find(a=>a.id===id);if(!x)return;
    currentDraftId=id;$("#wb-title").value=x.title??"";$("#wb-goal").value=x.goal??"";
    $("#wb-chain").value=(x.required_causal_chain??[]).join("\n");$("#wb-outputs").value=(x.required_outputs??[]).join("\n");
    $("#wb-constraints").value=x.constraints??"";
    $("input[name=wb-config-mode][value='"+(x.configMode==="custom"?"custom":"default")+"']").checked=true;
    for(const key of Object.keys(defaults))$("#"+fieldIds[key]).value=String(x.config?.[key]??defaults[key]);
    $("#wb-type").value=x.runMode??"MOCK_ONLY";step=0;updateConfigMode();renderWizard();
    $("#wb-form-status").textContent="已载入本地草稿";
  }
  function updateConfigMode(){
    const isDefault=configMode()==="default";
    $$('[data-config]').forEach(x=>{x.disabled=isDefault});
    if(isDefault){for(const key of Object.keys(defaults))$("#"+fieldIds[key]).value=String(defaults[key]);}
    renderConfigPreview();
  }
  function checkLocal(form){
    const errors=[];
    if(form.title.length<3||form.title.length>150)errors.push("研究标题需包含 3–150 个字符");
    if(form.goal.length<15)errors.push("研究目标至少填写 15 个字符");
    if(form.required_causal_chain.length===0)errors.push("至少填写一项必要因果链");
    if(form.required_outputs.length===0)errors.push("至少填写一项期望输出");
    const c=form.config;
    if(!c.generationModel||!c.reviewModel)errors.push("必须指定模型名称");
    for(const [key,min,max] of [["generations",0,10],["roots",1,20],["offspring",1,10],["time",1,1440]])if(!Number.isInteger(c[key])||c[key]<min||c[key]>max)errors.push(key+" 必须为 "+min+"–"+max+" 的整数");
    if(!Number.isFinite(c.budget)||c.budget<=0||c.budget>10000)errors.push("预算上限必须处于 (0, 10000] USD");
    return errors;
  }
  function renderConfigPreview(){
    const d=collectForm(),c=d.config,count=Number.isFinite(c.generations*c.offspring+c.roots)?c.generations*c.offspring+c.roots:"—";
    const fixed=d.configMode==="default" || Object.keys(defaults).every(k=>c[k]===defaults[k]);
    $("#wb-config-preview").innerHTML=`<span>研究范围 <strong>G0 → G${htmlEscape(c.generations)}</strong></span><span>计划候选槽位 <strong>${htmlEscape(count)}</strong></span><span>风险上限 <strong>$${htmlEscape(c.budget)}</strong></span><span>模式 <strong>${d.configMode==="default"?"DEFAULT":"CUSTOM"}</strong></span><span>模型适配 <strong>${fixed?"G3 默认":"待验证，禁止启动"}</strong></span><span>后端验证 <strong>以原生预检为准</strong></span>`;
  }
  function renderPreflight(){
    if(window.WorkbenchBackend){$("#wb-preflight-list").textContent="点击“重新检查输入”执行原生离线预检。自定义组合未验证前不能创建 Run；账户权限不会自动探测。";return;}
    const form=collectForm(),errors=checkLocal(form);
    const credentialsReady=Boolean(sessionCredentials.openai&&sessionCredentials.deepseek&&validContactEmail(sessionProfile.pubmedEmail));
    const providerInfo=form.runMode==="MOCK_ONLY"
      ?"Mock 无需 OpenAI / DeepSeek Key 或 PubMed 邮箱。"
      :credentialsReady?"三个必要字段已在本次标签页填写；仍需服务端验证权限与可用性。":"缺少部分 OpenAI / DeepSeek API Key 或有效 PubMed 邮箱；可到“设置”补充。";
    const checks=[
      {state:errors.length?"fail":"ok",name:"前端填写内容",detail:errors.length?errors.join("；"):"科研问题和基本参数已通过页面字段校验。"},
      {state:"wait",name:"模型和任务代数执行兼容性",detail:"需要 Config Builder 进行模型能力、Schema、Ranking、演化代数与冻结身份检查。"},
      {state:"wait",name:"Token、调用上限与预算规划",detail:"必须由后端根据模型定价与角色调用上限计算，不使用页面中的估计值作为授权依据。"},
      {state:"wait",name:"资源及 Provider 凭据",detail:providerInfo+" 连接 Runner 后仍需检查 Tokenizer、账户权限和模型能力。"},
      {state:"wait",name:"可派发的最终预检",detail:"本原型没有真实服务端连接，无法签署授权或启动 Mock/真实 Run。"},
    ];
    $("#wb-preflight-list").innerHTML=checks.map(c=>`<div class="wb-check ${c.state}"><div class="wb-check-symbol">${c.state==="ok"?"✓":c.state==="fail"?"!":"·"}</div><div><strong>${c.name} · ${c.state==="ok"?"页面检查通过":c.state==="fail"?"需要修改":"待连接"}</strong><p>${htmlEscape(c.detail)}</p></div></div>`).join("");
  }
  function renderConfirm(){
    const d=collectForm(),c=d.config;
    const fields=[["研究标题",d.title||"未填写"],["运行计划",`G0→G${c.generations} · ${c.roots}+${c.offspring}×${c.generations} 槽位`],
      ["Generation 模型",c.generationModel],["评价 / 演化模型",c.reviewModel],["预算风险上限","$"+c.budget],["时间上限",c.time+" 分钟"],
      ["运行模式",d.runMode==="MOCK_ONLY"?"Mock 合成测试":"真实模型 / PubMed"],["凭据状态",d.runMode==="MOCK_ONLY"?"无需密钥":"由后端进程内存设置检查，未验证账户权限"],["后端授权状态",window.WorkbenchBackend?"冻结新 Run 后必须明确逐 Run 授权":"未连接 · 未授权"]];
    $("#wb-confirm-summary").innerHTML=fields.map(([k,v])=>`<div class="wb-confirm-cell"><span>${htmlEscape(k)}</span><strong>${htmlEscape(v)}</strong></div>`).join("");
  }
  function renderWizard(){
    $$("[data-wizard]").forEach(x=>x.classList.toggle("hidden",Number(x.dataset.wizard)!==step));
    $$("[data-step]").forEach(x=>{x.classList.toggle("on",Number(x.dataset.step)===step);x.setAttribute("aria-current",Number(x.dataset.step)===step?"step":"false")});
    $("#wb-step-back").disabled=step===0;
    $("#wb-step-next").classList.toggle("hidden",step===3);
    $("#wb-step-next").textContent=step===2?"确认配置 →":"下一步 →";
    renderConfigPreview();renderCredentialStatus();renderPreflight();renderConfirm();
  }
  function nextStep(){
    const d=collectForm();
    if(step===0){const errors=checkLocal(d).filter(x=>x.includes("标题")||x.includes("研究目标")||x.includes("因果链")||x.includes("期望输出"));if(errors.length){notify("请完善研究目标："+errors[0]);return;}}
    if(step===1){const errors=checkLocal(d).filter(x=>!x.includes("标题")&&!x.includes("研究目标")&&!x.includes("因果链")&&!x.includes("期望输出"));if(errors.length){notify("运行参数存在问题："+errors[0]);return;}}
    if(step<3){step++;renderWizard();}
  }
  function saveDraft(){
    const d=collectForm(),now=new Date().toLocaleString("zh-CN",{hour12:false});
    if(!currentDraftId)currentDraftId="draft-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2,7);
    const draft={...d,id:currentDraftId,updatedAt:now};
    projects=projects.filter(p=>p.id!==draft.id);projects.unshift(draft);const ok=writeStored();
    $("#wb-form-status").textContent=(ok?"已保存于当前浏览器 · ":"未能保存 · ")+now;
    notify(ok?"草稿已保存到本地研究项目":"浏览器保存失败；请下载草稿 JSON");
    return draft;
  }
  function plannedDraft(id=null){
    const d=id?projects.find(p=>p.id===id):collectForm();if(!d)return null;
    return {format:"co-scientist-web-task-draft-v0.4",notice:"NOT_AUTHORIZED_NOT_BACKEND_VALIDATED_NO_RUN_CREATED",baseline_commit:"21213ed0d7863547aff5c081e75bfb0c4f875ec6",research_goal:{title:d.title,goal:d.goal,required_causal_chain:d.required_causal_chain,required_outputs:d.required_outputs},
      optional_constraints_note:d.constraints,config_mode:d.configMode,requested_configuration:d.config,requested_mode:d.runMode,validation_status:"LOCAL_INPUT_ONLY",saved_at:new Date().toISOString()};
  }
  function downloadDraft(id=null){const d=plannedDraft(id);if(!d)return notify("找不到本地草稿");download("co-scientist-task-draft.json",JSON.stringify(d,null,2),"application/json");notify("已下载任务配置草稿（非真实 Run）");}
  $$("input[name=wb-config-mode]").forEach(n=>n.addEventListener("change",()=>{updateConfigMode();$("#wb-form-status").textContent="当前配置有未保存更改"}));
  $$("#wb-run-form input,#wb-run-form textarea,#wb-run-form select").forEach(x=>{
    const dirty=()=>{$("#wb-form-status").textContent="当前配置有未保存更改";renderConfigPreview();renderCredentialStatus();};
    x.addEventListener("input",dirty);x.addEventListener("change",dirty);
  });
  $("#wb-run-form").addEventListener("submit",event=>event.preventDefault());
  $("#wb-step-back").addEventListener("click",()=>{step=Math.max(0,step-1);renderWizard()});
  $("#wb-step-next").addEventListener("click",nextStep);
  $$("[data-step]").forEach(x=>x.addEventListener("click",()=>{step=Number(x.dataset.step);renderWizard()}));
  $("#wb-run-check").addEventListener("click",()=>{renderPreflight();notify("仅完成本地输入字段检查；后端预检仍未连接")});
  $("#wb-save-draft").addEventListener("click",saveDraft);
  $("#wb-download-plan").addEventListener("click",()=>downloadDraft());

  function viewAndRows(){const v=M.snapshot(),rows=M.candidates();return {v,rows};}
  function resultsRow(c,n){
    const checked=compare.has(c.id)?"checked":"";
    return `<div class="wb-result-row ${selectedResult===c.id?"selected":""}" data-result-id="${htmlEscape(c.id)}" role="button" tabindex="0" aria-label="查看候选 ${htmlEscape(c.title)}">
      <input type="checkbox" aria-label="选中进行比较 ${htmlEscape(c.title)}" data-compare="${htmlEscape(c.id)}" ${checked}>
      <div><div class="wb-result-row-title">${htmlEscape(n?"#"+n+" · ":"待评 · ")}${htmlEscape(c.title)}</div><div class="wb-result-row-sub">${htmlEscape(clean(c.summary||c.claim,165))}</div><div class="wb-result-row-meta">G${htmlEscape(c.g)} · ${htmlEscape(c.operator??"root")} · ${htmlEscape(c.matches??0)} 次有效比较</div></div>
      <div class="wb-result-row-score">${c.score?"μ "+fmt(c.score.mu):"—"}<small>${c.score?"σ "+fmt(c.score.sigma):"尚未评分"}</small></div>
    </div>`;
  }
  const detailTabs=[["hypothesis","完整假设"],["evidence","文献证据"],["reflection","Reflection"],["ranking","Ranking"],["evolution","演化"],["raw","完整 JSON"]];
  function renderResults(){
    const {v,rows}=viewAndRows();if(!v)return;
    const candidates=rows.all;
    const filtered=candidates.filter(c=>(c.title+" "+c.summary+" "+c.claim).toLowerCase().includes(resultsSearch.toLowerCase()));
    if(!candidates.some(c=>c.id===selectedResult))selectedResult=candidates[0]?.id??null;
    const isNative=v.kind==="native";
    $("#wb-results-source").innerHTML=isNative?'<strong>原生数据 · 本地导入</strong><span>显示用户导入的 Native Trace；尚未连接在线后台。输入文件可能含敏感科学资料，请谨慎分享。</span>':'<strong>合成演示 · 非科研结果</strong><span>这是一组用于界面交互测试的虚构候选和模型评分。可通过“导入真实 Trace”切换至原生数据。</span>';
    const formal=v.final?.execution_result==="COMPLETE"&&v.final?.selection_result==="FINAL_WINNER"&&v.final?.terminal_barrier_complete===true;
    const metrics=[["已产生候选",v.candidateTotal,"截至当前回放位置"],["达到比较要求",v.eligible,"至少两次有效比较"],["有效比较",v.matches,"已观察到的比较事件"]];
    $("#wb-results-metrics").innerHTML=metrics.map(([name,value,desc])=>`<div class="wb-summary"><span>${name}</span><strong>${htmlEscape(value)}</strong><small>${desc}</small></div>`).join("");
    const selected=formal?candidates.find(c=>c.id===v.final.winner_id):rows.ranked[0];
    $("#wb-results-summary").innerHTML=`<div class="wb-result-kind">${formal?(isNative?"FINAL SELECTION · NATIVE TRACE":"FINAL SELECTION · SYNTHETIC DEMO"):"CURRENT BEST-SO-FAR · NOT FINAL WINNER"}</div>
      <h2>${htmlEscape(selected?.title??"尚无足够比较数据")}</h2><p>${htmlEscape(selected?.claim??"等待产生候选或完成有效比较。")}</p>
      <div class="wb-result-footer"><span>Run: ${htmlEscape(v.runId)}</span><span>G${htmlEscape(v.g)} / G${htmlEscape(v.maxGenerations)}</span><span>μ ${selected?.score?fmt(selected.score.mu):"—"} · σ ${selected?.score?fmt(selected.score.sigma):"—"}</span><span>${formal?"COMPLETE / FINAL_WINNER":"临时榜单，不是正式获胜者"}</span></div>`;
    $("#wb-results-rows").innerHTML=filtered.map(c=>resultsRow(c,rows.ranked.findIndex(r=>r.id===c.id)+1||null)).join("")||'<div class="board-empty">没有匹配的候选。请清空搜索或调整回放位置。</div>';
    const tabbar=$("#wb-results-tabs");tabbar.innerHTML=detailTabs.map(([k,title])=>`<button type="button" data-r-tab="${k}" class="${k===resultsTab?"on":""}">${title}</button>`).join("");
    const c=candidates.find(c=>c.id===selectedResult);
    $("#wb-results-detail-badge").textContent=c?`G${c.g} · ${c.operator??"root"}`:"无候选";
    $("#wb-results-detail").innerHTML=c?`<div class="wb-detail-top"><span>${htmlEscape(c.id)}</span><h3>${htmlEscape(c.title)}</h3><p>${htmlEscape(c.claim||c.summary)}</p></div>`+M.detailHTML(c.id,resultsTab):'<div class="board-empty">从左侧选择候选查看完整信息。</div>';
    const canCompare=compare.size===2 && [...compare].every(id=>candidates.some(c=>c.id===id));
    $("#wb-compare-panel").classList.toggle("hidden",!canCompare);
    if(canCompare){
      const both=[...compare].map(id=>candidates.find(c=>c.id===id));
      $("#wb-compare-content").innerHTML=both.map(c=>`<div class="wb-compare-card"><h3>${htmlEscape(c.title)}</h3><p>G${c.g} · ${htmlEscape(c.operator)} · μ ${fmt(c.score?.mu)} / σ ${fmt(c.score?.sigma)} · ${c.matches} 次有效比较</p><strong>科学主张</strong><p>${htmlEscape(c.claim)}</p><strong>机制链</strong><p>${htmlEscape((c.mechanism_chain??[]).join(" → ")||"未记录")}</p><strong>关键预测</strong><p>${htmlEscape((c.predictions??[]).join("\n")||"未记录")}</p><strong>证伪条件</strong><p>${htmlEscape((c.falsifiers??[]).join("\n")||"未记录")}</p></div>`).join("");
    }
    const files=M.nativeRawTexts?.()??{};
    const sel=$("#wb-native-file"),old=sel.value;
    sel.innerHTML=Object.keys(files).length?Object.keys(files).map(k=>`<option value="${htmlEscape(k)}">${htmlEscape(k)}</option>`).join(""):'<option value="">尚未导入原生文件</option>';
    if(files[old])sel.value=old;
    $("#wb-save-native-file").disabled=!Object.keys(files).length;
  }
  $("#wb-jump-last").addEventListener("click",()=>{M.showFinal();renderResults();notify("已定位到已加载数据的最后事件边界")});
  $("#wb-results-search").addEventListener("input",e=>{resultsSearch=e.target.value;renderResults()});
  $("#wb-results-rows").addEventListener("click",e=>{
    const check=e.target.closest("[data-compare]");if(check){const id=check.dataset.compare;
      if(compare.has(id))compare.delete(id);else if(compare.size<2)compare.add(id);else{notify("最多选择两条候选比较");check.checked=false;return}
      renderResults();return;}
    const row=e.target.closest("[data-result-id]");if(row){selectedResult=row.dataset.resultId;resultsTab="hypothesis";renderResults();}
  });
  $("#wb-results-rows").addEventListener("keydown",e=>{if(e.key!=="Enter"||e.target.matches("input"))return;const row=e.target.closest("[data-result-id]");if(row){selectedResult=row.dataset.resultId;renderResults()}});
  $("#wb-results-tabs").addEventListener("click",e=>{const b=e.target.closest("[data-r-tab]");if(b){resultsTab=b.dataset.rTab;renderResults()}});
  $("#wb-clear-compare").addEventListener("click",()=>{compare.clear();renderResults()});
  function report(){
    const {v,rows}=viewAndRows();if(!v)return "";
    const final=v.final?.execution_result==="COMPLETE"&&v.final?.selection_result==="FINAL_WINNER"&&v.final?.terminal_barrier_complete===true;
    return [`# Co-Scientist 结果阅读报告`,"",`数据来源：${v.kind==="synthetic"?"SYNTHETIC DEMO, NOT SCIENTIFIC EVIDENCE":"IMPORTED NATIVE TRACE"}`,
      `Run：${v.runId}`,`执行状态：${v.state}`,`当前回放：G${v.g}/G${v.maxGenerations}`,`正式终局结果：${final?"COMPLETE / FINAL_WINNER":"无（仅当前回放的临时结果）"}`,"",
      "## 候选排行（当前回放）","",...rows.all.flatMap((c,i)=>[`${i+1}. ${c.title} (G${c.g}; μ=${fmt(c.score?.mu)}, σ=${fmt(c.score?.sigma)}, 有效比较=${c.matches})`,c.claim??c.summary??"","**机制链**："+(c.mechanism_chain??[]).join(" → "),"**预测**："+(c.predictions??[]).join("；"),"**证伪**："+(c.falsifiers??[]).join("；"),""]),
      "---","注：本报告为前端阅读视图；不是官方五项原生 Trace，不意味着科学机制得到实验验证。"].join("\n");
  }
  $("#wb-export-md").addEventListener("click",()=>{download("co-scientist-reading-report.md",report(),"text/markdown;charset=utf-8");notify("已导出阅读报告，非官方 Trace")});
  $("#wb-export-json").addEventListener("click",()=>{const {v,rows}=viewAndRows();const content={version:"workbench-results-view-v0.3",origin:v.kind,run_id:v.runId,scientific_evidence:false,notice:"FRONTEND VIEW ONLY; NOT AN AUTHORITATIVE NATIVE TRACE",frame_state:v.state,ranked:rows.ranked.map(c=>({...c})),pending:rows.pending.map(c=>({...c})),final:v.final};download("co-scientist-results-view.json",JSON.stringify(content,null,2),"application/json");notify("已导出当前候选视图 JSON")});
  $("#wb-save-native-file").addEventListener("click",()=>{const name=$("#wb-native-file").value,src=M.nativeRawTexts?.()??{};if(!src[name])return notify("尚未导入此原生文件");download(name,src[name],name.endsWith(".json")?"application/json":"text/markdown;charset=utf-8");notify("已保存本次导入的原生文件："+name)});
  window.addEventListener("co-scientist-monitor-update",()=>{
    if(M.sourceMode()==="native")lastImportedRun=lastImportedRun??new Date().toLocaleString("zh-CN");
    if(currentPage==="results")renderResults();
    if(currentPage==="projects")renderProjects();
  });
  resetCreate();
  setPage(location.hash.replace(/^#/,"")||"projects");
})();
