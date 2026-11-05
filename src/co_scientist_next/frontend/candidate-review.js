"use strict";
function reviewField(parent, title, value = "") {
  const label = document.createElement("label");
  label.textContent = title;
  const input = document.createElement("textarea");
  input.value = value;
  input.rows = title.includes("政策文本") ? 4 : 2;
  input.setAttribute("aria-label", title);
  label.append(input); parent.append(label);
  return input;
}
function showCandidateReviews(card, generation, runId, saved) {
  const panel = document.createElement("section");
  panel.className = "candidate-review";
  const heading = document.createElement("h3"); heading.textContent = "候选伦理与 R0 初审"; panel.append(heading);
  note(saved.development ? "开发测试 · 确定性替身结论，非真实伦理或科学审查；science_validated=false。" : "生产政策须显式配置；未配置时不产生通过结论。刷新只读，不执行或查询供应商。", panel);
  for (const ref of generation.input.actual_frozen_seed_background_packet.source_views) {
    const details = document.createElement("details");
    const title = document.createElement("summary"); title.textContent = "来源 " + ref.source_ref + " · " + ref.access + " · " + ref.character_range.join("–");
    const text = document.createElement("pre"); text.className = "data"; text.textContent = ref.text;
    details.append(title, text); panel.append(details);
  }
  const actions = saved.actions.filter((a) => a.generation_ref === generation.request_id);
  for (const a of actions) {
    const block = document.createElement("div"); block.className = "block";
    const title = document.createElement("h4"); title.textContent = a.operation === "P09" ? "Candidate Ethics" : "R0 · 初步科学检查"; block.append(title);
    const result = a.result; const value = result?.artifact;
    note((result?.development ? "开发结论 · " : "") + "状态：" + (value?.decision_per_approved_policy || value?.disposition || result?.review_status || a.task_status), block);
    note("政策：" + (a.request.policy ? a.request.policy.id + "@" + a.request.policy.version + " · " + a.request.policy.mode : "未配置") + "；Prompt：" + a.prompt_version, block);
    if (value) {
      note(value.rationale || value.goal_alignment, block);
      for (const risk of value.specific_risks || []) note("具体风险：" + risk, block);
      for (const gap of value.limitations_or_missing_context || []) note("限制/缺少信息：" + gap, block);
      for (const defect of value.blocking_defects || []) {
        note("阻断问题：" + defect.defect + "；候选片段：" + defect.candidate_span + "；核心性：" + defect.why_indispensable, block);
        genTextSection(block, "原文定位、访问范围与阻断依据", defect.actual_visible_basis);
      }
      for (const unknown of value.scientific_unknowns || []) note("科学未知：" + unknown, block);
      for (const check of value.required_R1_checks || []) note("下一步 R1 核查（尚未执行）：" + check, block);
      for (const limit of value.limitations || []) note("限制：" + limit, block);
      if (value.disposition === "proceed_to_R1") note("等待 R1 能力；不是科学准入或已完成评议。", block);
    }
    if (result?.parse_error) note(result.parse_error, block);
    if (a.error) note("技术错误（不是伦理/科学结论）：" + a.error.message, block);
    if (a.remote) {
      note("远端状态：" + a.remote.status + "；ID：" + a.remote.response_id + "；已等待 " + Math.floor(a.remote.elapsed_seconds) + " 秒；最近查询：" + JSON.stringify(a.remote.latest_query), block);
      if (["queued", "in_progress", "unknown"].includes(a.remote.status)) {
        const query = document.createElement("button"); query.textContent = "显式查询此审查的同一远端ID";
        query.disabled = !saved.real_calls_authorized || !saved.model_config.credential_configured;
        query.onclick = () => action(async () => { await api("/api/candidate-review/query", {request_id:a.request_id}); await showRun(runId); }); block.append(query);
      }
    } else if (a.task_status === "blocked") note("提交结果不确定且无远端ID；停止，不自动重发。", block);
    if (["ready", "running"].includes(a.task_status)) {
      const execute = document.createElement("button"); execute.textContent = "显式执行/恢复此审查";
      execute.disabled = saved.model_config.execution_mode === "not_configured" || (saved.model_config.execution_mode === "real_model" && !saved.real_calls_authorized);
      execute.onclick = () => action(async () => {await api("/api/candidate-review/execute", {request_id:a.request_id,recover:true}); await showRun(runId);}); block.append(execute);
    }
    genTextSection(block, "技术详情：固定输入、政策、调用状态与用量", a);
    panel.append(block);
  }
  const setup = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "显式设置用途和政策并执行一次审查"; setup.append(summary);
  const latestEthics = [...actions].reverse().find((a) => a.operation === "P09");
  const use = reviewField(setup, "本候选实际拟议用途", latestEthics?.request.intended_use || generation.input.goal_context.intended_use || "");
  const id = reviewField(setup, "Candidate Ethics 政策标识");
  const version = reviewField(setup, "Candidate Ethics 政策版本");
  const policy = reviewField(setup, "Candidate Ethics 政策文本（无生产默认值）");
  const taxonomy = reviewField(setup, "decision_policy JSON（显式版本和决策路由）");
  const r0id = reviewField(setup, "R0 政策标识"); const r0version = reviewField(setup, "R0 政策版本"); const r0text = reviewField(setup, "R0 政策文本");
  if (saved.development) {
    const fill = document.createElement("button"); fill.textContent = "明确填入开发测试政策（非生产批准）";
    fill.onclick = () => {id.value="CANDIDATE-DEV-ONLY";version.value="1";policy.value="DEV-1: Offline engineering policy ONLY, not production approval. DEV-2: Non-clinical conceptual ideation is not execution authorization. DEV-3: Scientific uncertainty alone is not an ethical violation.";taxonomy.value=JSON.stringify({id:"CANDIDATE-DEV-DECISIONS",version:"1",routes:{pass:"continue",reject:"stop",incomplete:"hold"}});r0id.value="R0-DEV-ONLY";r0version.value="1";r0text.value="Development engineering policy only. Core reliable visible factual errors may block; unknown bridges, local distortion and dispute go to R1. No scientific validation.";}; setup.append(fill);
  }
  const submit = document.createElement("button"); submit.textContent = "显式执行 Candidate Ethics";
  submit.disabled = saved.model_config.execution_mode === "not_configured" || (saved.model_config.execution_mode === "real_model" && (!saved.real_calls_authorized || !saved.model_config.credential_configured));
  submit.onclick = () => action(async () => {
    const request_id="p09-"+crypto.randomUUID();
    await api("/api/candidate-review", {run_id:runId,request_id,request:{operation:"P09",generation_ref:generation.request_id,intended_use:use.value,policy:policy.value.trim()?{id:id.value,version:version.value,text:policy.value,mode:saved.development?"development":"production"}:null,decision_policy:taxonomy.value.trim()?JSON.parse(taxonomy.value):null}});
    await api("/api/candidate-review/execute",{request_id}); await showRun(runId);
  }); setup.append(submit);
  const pass = latestEthics?.result?.review_status === "completed" && latestEthics?.result?.artifact?.decision_per_approved_policy === "pass" ? latestEthics : null;
  if (pass) {
    note("R0固定使用此pass的用途：" + pass.request.intended_use + "；更改用途须先重新执行候选伦理。", setup);
    const r0 = document.createElement("button"); r0.textContent = "显式执行 R0（绑定已通过候选伦理）";r0.disabled=submit.disabled;
    r0.onclick = () => action(async () => {
      if (use.value !== pass.request.intended_use) throw new Error("用途已改变，请先重新执行 Candidate Ethics");
      const request_id="p10-"+crypto.randomUUID();
      await api("/api/candidate-review",{run_id:runId,request_id,request:{operation:"P10",generation_ref:generation.request_id,ethics_ref:pass.request_id,policy:r0text.value.trim()?{id:r0id.value,version:r0version.value,text:r0text.value,mode:saved.development?"development":"production"}:null}});
      await api("/api/candidate-review/execute",{request_id});await showRun(runId);
    }); setup.append(r0);
  } else note("没有此候选的有效 Candidate Ethics pass；不能建立 R0 任务。", setup);
  panel.append(setup);card.append(panel);
}
