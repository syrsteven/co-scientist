import {escape as e} from "./model.js";
import {groups,preferences,clone,getPath,setPath,fromTemplate,switchProvider,fromRun,errorsByGroup,dirtyFingerprint,listedModels,modelReference,priceNumber} from "./settings-model.js";

const providerNames={deepseek:"DeepSeek",openai:"OpenAI",qwen:"Qwen",gemini:"Gemini",claude:"Claude",replay:"Replay · 离线回放"};
const preferenceKey="co-scientist.interface.v1";
const frozen=label=>`<span class="setting-locked">固定 · ${e(label)}</span>`;

export function createSettings({getRun,notify,isActive,onPreferences}) {
  let catalog=null,draft=null,group="goal",modified=false,busy=false,errors=[],warnings=[],saved=null;
  let checked=null,choice="run",replacePending=false,root=null,loading=false,loadError="";
  let prefs=preferences();
  try{prefs=preferences(JSON.parse(localStorage.getItem(preferenceKey)||"{}"));}catch{/* Storage is optional. */}
  document.documentElement.dataset.density=prefs.density;

  const value=path=>getPath(draft,path);
  function field(path,title,{type="text",hint="",options,min,max,step=1,nullable=false,disabled=false,rows=4}={}) {
    const v=value(path),id=`setting-${path.replaceAll(".","-")}`;
    const error=errors.find(x=>x.field===path);
    const described=`${id}-hint${error?` ${id}-error`:""}`;
    const attrs=`id="${id}" data-field="${e(path)}" aria-describedby="${described}" ${error?'aria-invalid="true"':""} ${disabled?"disabled":""}`;
    let control;
    if(type==="checkbox")control=`<input ${attrs} type="checkbox" ${v?"checked":""}><span class="switch-track" aria-hidden="true"></span>`;
    else if(type==="textarea")control=`<textarea ${attrs} rows="${rows}" data-lines="${Array.isArray(v)}">${e(Array.isArray(v)?v.join("\n"):v)}</textarea>`;
    else if(options)control=`<select ${attrs}>${options.map(([val,text])=>`<option value="${e(val)}" ${String(v??"")===val?"selected":""}>${e(text)}</option>`).join("")}</select>`;
    else control=`<input ${attrs} type="${type}" value="${e(v??"")}" ${min!==undefined?`min="${min}"`:""} ${max!==undefined?`max="${max}"`:""} ${type==="number"?`step="${step}"`:""} ${nullable&&v==null?"disabled":""} autocomplete="off">`;
    return `<div class="setting-field ${type==="checkbox"?"switch-field":""} ${error?"field-invalid":""}"><label for="${id}">${e(title)}</label>${control}${nullable?`<label class="unlimited"><input type="checkbox" data-unlimited="${e(path)}" ${v==null?"checked":""}> 不设上限</label>`:""}<small id="${id}-hint">${e(hint)}</small>${error?`<span id="${id}-error" class="field-error">${e(error.message)}</span>`:""}</div>`;
  }
  const panel=(title,subtitle,body)=>`<section class="settings-panel"><header><h3>${e(title)}</h3><p>${e(subtitle)}</p></header><div class="settings-fields">${body}</div></section>`;
  function goalPanel(){return panel("把研究问题写清楚","这些内容将进入新运行的冻结 ResearchPlan。",
    field("goal.title","研究标题",{hint:"一句话界定研究对象与核心问题。"})+
    field("goal.goal","研究目标",{type:"textarea",rows:6,hint:"说明要解释的机制、需要区分的竞争性解释，以及实验可检验性要求。"})+
    field("goal.required_causal_chain","必须覆盖的因果链",{type:"textarea",hint:"每行一个环节，按因果顺序排列。不是关键词检索框。"})+
    field("goal.required_outputs","必须产出的内容",{type:"textarea",hint:"每行一项，例如：最早因果决定因素、证伪条件、区分实验。"}));}
  function priceCard(){
    const reference=modelReference(catalog.model_catalog,draft.profile.providers.llm,draft.model);
    if(!reference)return `<p class="setting-note">当前自定义型号没有已核验报价；不代表免费。请查询供应商账户，不会自动替换已有模型 ID。</p>`;
    return `<div class="price-reference"><strong>${e(reference.name)} · ${e(reference.currency)} / 每百万 tokens</strong>
      <div class="price-scroll"><table><thead><tr><th>计费条件</th><th>输入</th><th>缓存命中输入</th><th>输出</th></tr></thead><tbody>${reference.rates.map(r=>`<tr><td>${e(r.condition)}</td><td>${priceNumber(r.input)}</td><td>${priceNumber(r.cached_input)}</td><td>${priceNumber(r.output)}</td></tr>`).join("")}</tbody></table></div>
      <p>${e(reference.note)}</p><small>${e(reference.availability)}。核验：${e(reference.verified_at)} · <a href="${e(reference.source)}" target="_blank" rel="noreferrer">官方报价 ↗</a></small></div>`;
  }
  function modelPicker(provider,info){
    const models=listedModels(catalog.model_catalog,provider),listed=models.some(m=>m.id===draft.model&&m.selectable);
    return `<div class="setting-field"><label for="modelCatalogChoice">选择模型</label><select id="modelCatalogChoice"><option value="" ${!listed?"selected":""}>自定义 / 保留当前型号</option>${models.map(m=>`<option value="${e(m.id)}" ${m.id===draft.model&&m.selectable?"selected":""} ${m.selectable?"":"disabled"}>${e(m.name)} · ${e(m.id)}${m.selectable?"":" · 适配待验证"}</option>`).join("")}</select><small>按供应商列出已核验的公开型号，不代表你的账户全部可用。不会自动升级冻结运行。</small></div>`+
      field("model","模型 ID",{hint:`也可直接填写精确快照型号；启动命令通过 ${info?.model_env} 传入。选择模型本身不产生费用。`})+
      `<div id="modelPriceReference">${priceCard()}</div><p class="setting-note">${e(catalog.model_catalog?.disclaimer||"暂无报价目录")} 报价是${e(catalog.model_catalog?.verified_at||"未知日期")}快照，价格可能变化。Qwen为当前北京endpoint人民币报价；不与美元直接比较或相加。</p>`;
  }
  function modelPanel(){
    const provider=draft.profile.providers.llm,info=catalog.providers.find(p=>p.id===provider);
    return (provider!=="replay"&&!draft.profile.scientific_context?'<div class="notice">研究输入警告：此配置未开启科学上下文，下游可能只收到 ID/哈希。请先到文献检索开启科学上下文，再进行真实研究或模型比较。</div>':"")+panel("模型连接","一个 Run 冻结一个模型；切换供应商不会修改研究目标和计算预算。",
      field("profile.providers.llm","模型供应商",{options:Object.entries(providerNames)})+
      (provider!=="replay"?modelPicker(provider,info):`<p class="setting-note">使用仓库内固定响应。不需要 API key，不代表模型重新推理。</p>`)+
      (info?`<div class="credential-status"><span class="${info.key_configured?"pass":"warning"}">${info.key_configured?"服务进程检测到密钥":"服务进程未检测到密钥"}</span><code>${e(info.key_env)}</code><small>仅检测是否存在，不读取到浏览器。CLI 终端环境可能与网页服务不同；这是环境检查，不是连通性验证。</small></div>`:""))+
      (provider==="deepseek"?panel("DeepSeek 生成参数","这些参数由当前 adapter 实际使用；供应商是否支持仍取决于具体模型。",
        field("profile.providers.deepseek_generation.max_tokens","单次输出 token 上限",{type:"number",min:1,max:384000,hint:"与整轮运行的 token 预算不同。过低可能导致 JSON 被截断。"})+
        field("profile.providers.deepseek_generation.thinking","思考模式",{options:[["enabled","启用"],["disabled","关闭"]]})+
        field("profile.providers.deepseek_generation.reasoning_effort","思考强度",{options:[["low","Low"],["high","High"],["max","Max"]],disabled:draft.profile.providers.deepseek_generation?.thinking==="disabled",hint:"关闭思考时不发送此参数。"})+
        field("profile.providers.deepseek_generation.timeout_seconds","单次请求超时（秒）",{type:"number",min:1,max:1800,hint:"本地等待超时不保证供应商停止计费。"})):
      panel("当前适配能力","未接入的参数不会提供虚假开关。",`<div class="setting-note">${frozen("adapter 默认生成参数")}<p>温度、其他供应商的输出参数、角色级多模型合作与自动路由暂未开放。</p></div>`));
  }
  function literaturePanel(){const replay=draft.profile.providers.llm==="replay";return panel("文献来源与上下文","文献检索为模型提供来源，不代表证据已经验证。",
    `<div class="setting-note">来源 ${frozen(replay?"Replay PubMed":"PubMed")}</div>`+
    field("profile.scientific_context","向 Agent 提供科学上下文",{type:"checkbox",disabled:replay,hint:"带入目标、假设内容和已有文献。真实研究的摘要模式及 Evolution 依赖此项。"})+
    field("profile.literature_content","获取的文献内容",{options:[["metadata","仅题录"],["abstracts","题录 + 可获取摘要"]],disabled:replay,hint:"摘要不是全文；缺失摘要不会由模型补写。"})+
    field("profile.literature_sort","PubMed 排序方式",{options:[["","默认"],["relevance","相关性"],["pub_date","发表时间"]],disabled:replay})+
    field("profile.literature_search_queries","检索表达式与回退顺序",{type:"textarea",rows:6,disabled:replay,hint:"每行一条 PubMed 查询，最多 5 条、不可重复。按顺序在空结果时回退；留空使用运行器默认查询。"}));}
  function reviewPanel(){
    const full=draft.profile.review_policy.required_before_admission.includes("full_review");
    return panel("科研指令协议","只用于新运行；旧运行的提示词与评分契约保持冻结。",
      field("profile.research_protocol_version","科学指令与评价标准",{options:[["research-v1","Research v1 · 六角色科学指令 + 内容绑定评审 + Ranking 标准"],["","Legacy · 保留历史任务输入"]],disabled:draft.profile.providers.llm==="replay",hint:"Research v1 需要开启科学上下文；保存后通过新配置启动，不会升级旧 Run。"})+
      `<p class="setting-note">${draft.profile.research_protocol_version?"评价维度：目标对齐、因果明确性、证据、新颖性、区分实验、稳健性与安全。协议纳入 epoch 评价规则，不代表论文性能已复现。":"此副本保留旧协议。升级新配置时请显式选择 Research v1；历史 Replay 保持 Legacy。"}</p>`)+
      panel("准入审查","任务执行成功不等于假设通过审查；演化子代需要独立重新准入。",
      `<div class="setting-note">初审与安全审查 ${frozen("始终必需")}</div>
      <div class="setting-field switch-field"><label for="fullReview">准入前要求完整评审</label><input id="fullReview" data-special="full-review" type="checkbox" ${full?"checked":""}><span class="switch-track" aria-hidden="true"></span><small>当前文献新颖性评估在完整评审中生成。</small></div>`+
      field("profile.literature_novelty_required","要求文献新颖性证据",{type:"checkbox",hint:"开启时必须保留完整评审。关闭会降低准入门槛，系统会提示。"})+
      field("profile.duplicate_likelihood_threshold","重复假设判定阈值",{type:"number",min:0,max:1,step:0.05,hint:"范围 0–1。低阈值更容易判为重复；Proximity 不代替文献新颖性评审。"}))+
      panel("有界 Evolution","在当前调度策略需要改进候选时触发，不保证每次运行都发生。",
        field("profile.evolution.max_rounds","最多演化轮次",{type:"number",min:0,max:10,disabled:draft.profile.providers.llm==="replay",hint:"修复和 Meta-review 反馈驱动共用此上限。0 表示关闭；内置 trace 无演化响应。"})+
        field("profile.evolution.max_children_per_round","每轮最多子假设",{type:"number",min:1,max:10,hint:"不会绕过审查，也不会覆盖父假设或继承父代 Elo。"}))+
      panel("Meta-review 反馈闭环","由 Supervisor 在未收敛的比赛 checkpoint 后调度；预算和人工停止优先。",
        field("profile.meta_review.contract_version","反馈判定协议",{options:[["meta-review-loop-v1","原版 v1"],["meta-review-loop-v2","v2 · 区分证据缺口与安全判定"]],hint:"v2提供初审安全与准入上下文，仅适用于新运行；不会改判历史反馈。"})+
        field("profile.meta_review.max_rounds","最多科学总结轮次",{type:"number",min:0,max:10,disabled:draft.profile.providers.llm==="replay",hint:"0 关闭。启用需要 Research v1、允许演化以及有限调用/比赛预算；旧副本不自动开启。"})+
        field("profile.meta_review.match_interval","总结之间至少新增比赛数",{type:"number",min:1,max:100,disabled:draft.profile.providers.llm==="replay",hint:"首次需完成初始比赛批次；不会按秒数反复调用。"})+
        field("profile.meta_review.max_children_per_round","每次反馈最多生成子假设",{type:"number",min:1,max:5,disabled:draft.profile.providers.llm==="replay",hint:"同时受演化与总预算限制；反馈不是准入许可，安全方向不明确时交研究者处理。"}))+
      panel("条件评审策略","配置保留这些触发规则，但当前默认调度未完整实现自动触发。",`<div class="setting-note">${frozen("只读预留")}<p>Deep verification / Observation / Simulation / Recurrent review 不作为所有候选的强制步骤；此版不提供自动触发开关。</p><details><summary>查看冻结触发规则</summary><pre>${e(JSON.stringify(draft.profile.review_policy.trigger_rules,null,2))}</pre></details></div>`);
  }
  function rankingPanel(){return panel("TournamentEpoch","每个新运行使用独立竞技场；修改计划不能沿用旧 Elo。",
    `<div class="locked-grid"><span>比较模式 ${frozen("research")}</span><span>Rating policy ${frozen("elo-32-v1")}</span><span>初始 rating ${frozen("1200，准入后赋值")}</span><span>固定 anchors ${frozen("2 个晶状体基线")}</span></div><p class="setting-note">新研究领域需要实现匹配的 anchor 集。不能通过改参数名称改变评分算法。</p>`)+
    panel("Ranking 输出协议","仅改变新运行的结果传输方式，不改变科学评判标准。",
      field("profile.ranking_output_protocol","结构化输出约束",{options:[["","标准 JSON · 保留现有行为"],["deepseek-strict-tool-v1","DeepSeek Strict Tool v1 · Beta"],["deepseek-strict-tool-v2","DeepSeek Strict Tool v2 · 扁平理由 / 仅离线验证"]],disabled:draft.profile.providers.llm!=="deepseek"||draft.profile.research_protocol_version!=="research-v1",hint:"需要 DeepSeek + Research v1。v2 将六维理由改为独立顶层字段，完整映射回原科学结果；保留思考、评分和绑定校验。两版均不自动降级或补 JSON，v2 尚未在线验证。"})+
      `<p class="setting-note">协议会冻结进新 Run 和 epoch 身份，不能直接升级当前运行。旧副本默认保留标准 JSON。2026-09-20 deepseek-flash 单次兼容检查通过，但 Run010 第 8 场仍返回非法工具参数；完整闭环未通过，不保证 JSON 有效或科研质量。</p>`)+
    panel("质量停止门槛","先满足最低覆盖，再联合检查稳定性与多样性；Elo plateau 仅作辅助。",
      field("profile.stop.minimum_hypotheses","最低候选数量",{type:"number",min:0})+
      field("profile.stop.minimum_matches","最低比赛数量",{type:"number",min:0})+
      field("profile.stop.minimum_model_calls","最低外部调用数量",{type:"number",min:0,hint:"和上限不同；低于此覆盖时，不会因质量收敛正常结束。"})+
      field("profile.stop.top_k","重点关注 Top-k",{type:"number",min:1})+
      field("profile.stop.top_k_stability_window","Top-k 稳定窗口",{type:"number",min:1,hint:"窗口更长，需要更多比较来证明排名稳定。"})+
      field("profile.stop.cluster_diversity_window","聚类多样性窗口",{type:"number",min:1})+
      field("profile.stop.elo_plateau_window","Elo 平台期窗口（辅助）",{type:"number",min:1})+
      `<div class="setting-note">${frozen("Anchor + Top-k + Cluster 联合检查")}<p>当前停止内核不支持单独关闭这些检查。预算触达与研究者停止仍是独立停止来源。</p></div>`);}
  function budgetPanel(){return panel("总计算预算","不设上限以 null 保存；0 表示预算为零，不是无限制。",
    field("profile.budget.hypothesis_limit_policy","候选上限行为",{type:"select",options:[["hard-stop-v1","达到上限停止整轮（旧版）"],["capacity-v2","达到上限停止新增，继续处理已有候选"]],hint:"仅对新运行生效；调用、token、费用和比赛上限仍触发全局停止。"})+
    field("profile.budget.max_model_calls","外部调用次数上限",{type:"number",min:0,nullable:true,hint:"包含模型与被账本计入的文献调用。建议保留有界调用和比赛上限。"})+
    field("profile.budget.max_hypotheses","候选假设数量上限",{type:"number",min:0,nullable:true,hint:"限制探索规模，不要求所有候选通过审查。"})+
    field("profile.budget.max_matches","比赛数量上限",{type:"number",min:0,nullable:true})+
    field("profile.budget.max_input_tokens","输入 token 总上限",{type:"number",min:0,nullable:true})+
    field("profile.budget.max_output_tokens","输出 token 总上限",{type:"number",min:0,nullable:true})+
    field("profile.budget.max_usd","美元预算上限（USD）",{type:"number",min:0,step:0.01,nullable:true,hint:"当前供应商未完整定价，不可用它作为可靠账单硬保护；请同时设置调用 / token 上限。"})+
    `<div class="setting-note warning">预算用尽可早于质量收敛。取消费用上限不会自动打开无限自主探索，当前续赛策略依赖有限调用与比赛预算。</div>`);}
  function interfacePanel(){return panel("本浏览器偏好","立即应用，只保存在当前浏览器；不进入 ResearchPlan，不改变计算预算。",
    `<div class="setting-field switch-field"><label for="autoRefresh">自动刷新运行数据</label><input id="autoRefresh" type="checkbox" data-pref="autoRefresh" ${prefs.autoRefresh?"checked":""}><span class="switch-track" aria-hidden="true"></span><small>编辑设置和后台页签期间不会自动刷新运行数据。</small></div>
    <div class="setting-field"><label for="pollSeconds">刷新间隔</label><select id="pollSeconds" data-pref="pollSeconds">${[5,10,30,60].map(n=>`<option value="${n}" ${prefs.pollSeconds===n?"selected":""}>${n} 秒</option>`).join("")}</select><small>只影响界面读取频率，不影响 Agent 执行。</small></div>
    <div class="setting-field"><label for="density">阅读密度</label><select id="density" data-pref="density"><option value="comfortable" ${prefs.density==="comfortable"?"selected":""}>舒适</option><option value="compact" ${prefs.density==="compact"?"selected":""}>紧凑</option></select></div>`);}

  function render(){
    if(!root||!isActive())return;
    if(!catalog||!draft){root.innerHTML=`<div class="empty">${e(loadError||"正在读取可用参数与配置模板…")}${loadError?'<button class="text-button" data-settings-action="retry">重试</button>':""}</div>`;return;}
    const counts=errorsByGroup(errors),descriptor=groups.find(g=>g[0]===group);
    const sameSaved=saved&&dirtyFingerprint(draft)===dirtyFingerprint(saved.draft);
    root.innerHTML=`<div class="settings-notice"><strong>新运行配置</strong><span>保存只创建配置文件，不启动模型，也不修改正在运行或已完成的研究。</span></div>
      <div class="settings-toolbar"><div class="config-name">${field("name","配置名称",{hint:"每次保存生成新版本；不会覆盖旧配置。"})}</div><div class="preset-picker"><label for="settingsPreset">从模板或已保存配置开始</label><div><select id="settingsPreset"><option value="run" ${choice==="run"?"selected":""} ${getRun()?"":"disabled"}>当前运行的冻结配置副本</option>${catalog.templates.map(t=>`<option value="template:${e(t.id)}" ${choice===`template:${t.id}`?"selected":""}>${e(providerNames[t.id])} · 仓库模板</option>`).join("")}${catalog.saved.map(s=>`<option value="saved:${e(s.id)}" ${choice===`saved:${s.id}`?"selected":""}>已保存 · ${e(s.draft.name)} · ${e(s.id)}</option>`).join("")}</select><button class="quiet-button" data-settings-action="load" ${busy?"disabled":""}>载入</button></div></div></div>
      ${replacePending?`<div class="replace-confirm" role="alert">当前草稿有未保存修改。载入将替换草稿，不会改动已保存文件。<button class="quiet-button" data-settings-action="confirm-load">替换草稿</button><button class="text-button" data-settings-action="cancel-load">保留草稿</button></div>`:""}
      <div class="settings-layout"><nav class="settings-nav" aria-label="设置分类">${groups.map(([id,title,subtitle,category],i)=>`${i===0||groups[i-1][3]!==category?`<small>${e(category)}</small>`:""}<button data-settings-group="${id}" class="${id===group?"selected":""}" aria-current="${id===group?"page":"false"}"><span>${e(title)}${counts[id]?`<b>${counts[id]}</b>`:""}</span><small>${e(subtitle)}</small></button>`).join("")}</nav>
      <div class="settings-content"><header class="settings-section-title"><span>0${groups.findIndex(g=>g[0]===group)+1} / 07</span><h2>${e(descriptor[1])}</h2><p>${e(descriptor[2])}</p></header>${({goal:goalPanel,model:modelPanel,literature:literaturePanel,review:reviewPanel,ranking:rankingPanel,budget:budgetPanel,interface:interfacePanel}[group])()}
      <div id="settingsFeedback" class="settings-feedback" role="status">${errors.length?`<div class="validation-errors"><strong>${errors.length} 项设置需要修改</strong><ul>${errors.map(x=>`<li><code>${e(x.field)}</code>：${e(x.message)}</li>`).join("")}</ul></div>`:""}${warnings.length?`<details class="settings-warnings" open><summary>${warnings.length} 项运行提示</summary><ul>${warnings.map(w=>`<li>${e(w)}</li>`).join("")}</ul></details>`:""}</div>
      ${saved?`<section class="settings-panel saved-config"><header><h3>${sameSaved?"已保存，可交给 CLI 执行":"上次保存版本（不含当前修改）"}</h3><p>${e(saved.directory)} · 未启动运行</p></header><div class="settings-fields"><p class="setting-note">在项目根目录、已激活 Python 环境且配置好密钥的终端运行。命令真正执行时，在线模型才会产生费用。</p><pre>${e(saved.command)}</pre><div class="settings-downloads"><button class="quiet-button" data-settings-action="copy-command">复制启动命令</button><button class="quiet-button" data-settings-action="download-goal">下载 goal.yaml</button><button class="quiet-button" data-settings-action="download-profile">下载 profile.yaml</button></div><details><summary>查看保存的 YAML</summary><pre>${e(saved.files["profile.yaml"])}</pre></details></div></section>`:""}
      </div></div><footer class="settings-actions"><div><strong id="settingsDirty">${modified?"有未保存修改":sameSaved?"配置已保存":"新配置草稿"}</strong><small>参数只有在新运行启动时才生效 · 不写入历史 Run</small></div><button class="quiet-button" data-settings-action="validate" ${busy?"disabled":""}>${busy?"处理中…":"校验配置"}</button><button class="primary-button" data-settings-action="save" ${busy?"disabled":""}>保存为新配置</button></footer>`;
    const menu=root.querySelector(".settings-nav"),selected=menu.querySelector(".selected");
    if(menu.scrollWidth>menu.clientWidth)menu.scrollLeft=selected.offsetLeft-menu.offsetLeft-(menu.clientWidth-selected.clientWidth)/2;
    if(busy)root.querySelectorAll("input,select,textarea").forEach(control=>control.disabled=true);
  }
  async function loadCatalog(){
    if(loading)return;loading=true;loadError="";render();
    try{const response=await fetch("/api/settings");if(!response.ok)throw new Error("设置服务无法连接，请确认 Python 环境并重启最新版前端服务。");catalog=await response.json();
      if(!draft){try{draft=fromRun(getRun());}catch{draft=fromTemplate(catalog.templates.find(t=>t.id==="deepseek"),catalog.providers.find(p=>p.id==="deepseek"));choice="template:deepseek";}}
    }catch(error){loadError=error.message;}finally{loading=false;render();}
  }
  function touch(){modified=true;checked=null;errors=[];warnings=[];const indicator=document.getElementById("settingsDirty");if(indicator)indicator.textContent="有未保存修改";
    const savedTitle=root?.querySelector(".saved-config h3");if(savedTitle)savedTitle.textContent="上次保存版本（不含当前修改）";
  }
  function loadChoice(){
    try{if(choice==="run")draft=fromRun(getRun());else if(choice.startsWith("saved:"))draft=clone(catalog.saved.find(s=>s.id===choice.slice(6)).draft);
      else {const id=choice.slice(9);draft=fromTemplate(catalog.templates.find(t=>t.id===id),catalog.providers.find(p=>p.id===id));}
      modified=false;errors=[];warnings=[];saved=null;checked=null;replacePending=false;render();notify("已载入为新运行草稿，历史运行未改变。");
    }catch(error){notify(error.message);}
  }
  async function submit(action){
    if(busy)return;busy=true;errors=[];warnings=[];render();
    try{
      const response=await fetch(`/api/settings/${action}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(draft)});
      const result=await response.json();
      if(!response.ok&&response.status!==422)throw new Error(result.error||"设置服务失败");
      errors=result.errors||[];warnings=result.warnings||[];
      if(result.ok){draft=result.draft;checked=dirtyFingerprint(draft);
        if(action==="save"){saved=clone(result);modified=false;catalog.saved.unshift({id:result.id,draft:clone(draft)});notify("配置已保存；没有启动运行或调用模型。");}
        else notify("参数格式与支持范围校验通过；没有联网测试模型。");
      }else notify("有参数需要修改，请查看设置页中的错误提示。");
    }catch(error){errors=[{field:"服务",message:error.message}];}
    finally{busy=false;render();document.getElementById("settingsFeedback")?.scrollIntoView({behavior:"smooth",block:"nearest"});}
  }
  async function actionClick(action){
    if(action==="retry")return loadCatalog();
    if(action==="load"){if(modified){replacePending=true;render();}else loadChoice();}
    if(action==="confirm-load")loadChoice();if(action==="cancel-load"){replacePending=false;render();}
    if(action==="validate"||action==="save")return submit(action);
    if(action==="copy-command"&&saved){try{await navigator.clipboard.writeText(saved.command);notify("已复制保存版本的启动命令。");}catch{notify("浏览器不允许自动复制，请手动选择上方命令。");}}
    if(action.startsWith("download-")&&saved){const filename=action==="download-goal"?"goal.yaml":"profile.yaml";const url=URL.createObjectURL(new Blob([saved.files[filename]],{type:"application/yaml"}));const link=document.createElement("a");link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  }
  document.addEventListener("click",event=>{
    if(!isActive())return;const target=event.target.closest("[data-settings-group],[data-settings-action]");if(!target)return;
    if(target.dataset.settingsGroup){group=target.dataset.settingsGroup;render();}
    if(target.dataset.settingsAction)actionClick(target.dataset.settingsAction);
  });
  document.addEventListener("change",event=>{
    if(!isActive())return;const t=event.target;
    if(t.id==="settingsPreset"){choice=t.value;return;}
    if(t.id==="modelCatalogChoice"){if(t.value){draft.model=t.value;touch();render();}else document.getElementById("setting-model")?.focus();return;}
    if(t.dataset.pref){prefs=preferences({...prefs,[t.dataset.pref]:t.type==="checkbox"?t.checked:t.value});
      try{localStorage.setItem(preferenceKey,JSON.stringify(prefs));}catch{notify("浏览器存储不可用，偏好仅在本次页面生效。");}
      document.documentElement.dataset.density=prefs.density;onPreferences(prefs);return;}
    if(t.dataset.unlimited){setPath(draft,t.dataset.unlimited,t.checked?null:0);touch();render();return;}
    if(t.dataset.special==="full-review"){draft.profile.review_policy.required_before_admission=t.checked?["initial_review","full_review"]:["initial_review"];touch();render();return;}
    if(t.dataset.field==="profile.providers.llm"){
      draft=switchProvider(draft,t.value,catalog.templates,catalog.providers.find(p=>p.id===t.value));touch();render();return;
    }
    if(t.dataset.field&&(t.type==="checkbox"||t.tagName==="SELECT")){
      setPath(draft,t.dataset.field,t.type==="checkbox"?t.checked:(["profile.literature_sort","profile.research_protocol_version","profile.ranking_output_protocol"].includes(t.dataset.field)&&t.value===""?null:t.value));touch();render();
    }
  });
  document.addEventListener("input",event=>{
    if(!isActive())return;const t=event.target,path=t.dataset.field;
    if(!path||t.tagName==="SELECT"||t.type==="checkbox")return;
    let v=t.value;if(t.dataset.lines==="true")v=v.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(t.type==="number")v=v===""?null:Number(v);
    setPath(draft,path,v);touch();
    if(path==="model"){
      const quote=document.getElementById("modelPriceReference");if(quote)quote.innerHTML=priceCard();
      const choice=document.getElementById("modelCatalogChoice");if(choice)choice.value=listedModels(catalog.model_catalog,draft.profile.providers.llm).some(m=>m.id===v&&m.selectable)?v:"";
    }
  });
  window.addEventListener("beforeunload",event=>{if(modified){event.preventDefault();event.returnValue="";}});
  return {mount(element){root=element;if(!catalog)loadCatalog();else render();},getPreferences:()=>prefs};
}
