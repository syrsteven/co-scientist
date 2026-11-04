"use strict";
let generationData = null;
function generationSpecificity() {
  const ready = generationData?.ready_records.find((r) => r.readiness_ref === el("generation-ready").value);
  el("generation-specificity").textContent = ready ? "固定背景包：" + ready.packet_ref + "；允许具体程度：" + ready.allowed_specificity : "没有已完成且绑定正确的 ready 记录。";
}
el("generation-ready").onchange = generationSpecificity;
el("generation-submit").onclick = () => action(async () => {
  const ready = generationData.ready_records.find((r) => r.readiness_ref === el("generation-ready").value);
  if (!ready) throw new Error("请选择已完成 ready 的 seed");
  const candidate_id = el("generation-candidate-id").value.trim() || "candidate-" + crypto.randomUUID();
  el("generation-candidate-id").value = candidate_id;
  const request_id = "p08-" + crypto.randomUUID();
  await api("/api/generation", {run_id: state.run.run.id, request_id, request: {
    seed_id: ready.seed_id, readiness_ref: ready.readiness_ref, packet_ref: ready.packet_ref,
    mode: el("generation-method").value, candidate_id,
  }});
  el("notice").textContent = "生成任务已保存，正在显式执行；刷新只读取。";
  await api("/api/generation/execute", {request_id});
  await project(state.project);
  await showRun(state.run.run.id);
  el("generation-candidate-id").value = "";
  el("notice").textContent = "调用事实已保存；查看候选或失败/不确定状态。未执行 Candidate Ethics/R0。";
});
function genTextSection(parent, title, value) {
  const section = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = title;
  const body = document.createElement("pre");
  body.className = "data";
  body.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  section.append(summary, body);
  parent.append(section);
}
async function showGeneration(data) {
  const saved = await api("/api/generation?run_id=" + encodeURIComponent(data.run.id));
  generationData = saved;
  el("generation-panel").hidden = false;
  const mode = saved.model_config.execution_mode;
  el("generation-mode").textContent = mode === "development_fixture"
    ? "开发生成替身 · 工程验证，不是真实模型能力；science_validated=false。"
    : mode === "real_model" ? "真实适配器配置 · 仅显式且已授权操作才发送；科学未验证。"
    : "生成模型未配置；不会自动使用开发替身。";
  if (data.development_test) el("generation-mode").textContent += " Goal Ethics 为开发测试结果，不代表真实伦理审查。";
  el("generation-prompt").textContent = "当前 Prompt：" + saved.prompt_version + "；" + (saved.blocked_reason || "按保存 ready 记录放行，不仅依赖 Run 状态。");
  bgOptions("generation-ready", saved.ready_records.map((r) => ({...r, id: r.readiness_ref})), (r) => r.seed_id + " · " + r.readiness_ref + " · " + r.question);
  generationSpecificity();
  el("generation-submit").disabled = !saved.can_submit || mode === "not_configured" || (mode === "real_model" && (!saved.real_calls_authorized || !saved.model_config.credential_configured));
  el("generation-records").replaceChildren();
  for (const a of saved.actions) {
    const card = document.createElement("div");
    card.className = "block candidate-card";
    card.dataset.candidateId = a.candidate_id;
    const candidate = a.result?.candidate;
    const title = document.createElement("h3");
    title.textContent = candidate?.title || a.candidate_id;
    card.append(title);
    note("候选身份：" + a.candidate_id + " · 方式：" + a.request.mode, card);
    const status = a.result?.generation_status;
    note(status === "generated" ? "已生成，待Candidate Ethics/R0；未准入、未评分、科学未验证。" : "调用状态：" + ({blocked: "发送不确定，已停止；不自动重发", failed: "技术失败（非科学否定）", running: "执行中，尚未收尾", ready: "已保存待显式执行"}[a.task_status] || a.task_status) + " · " + (status || "结果未完成"), card);
    note("执行标识：" + a.config.execution_mode + " · 固定Prompt：" + a.prompt_version, card);
    note("seed：" + a.request.seed_id + " · 背景包：" + a.request.packet_ref + " · readiness：" + a.request.readiness_ref, card);
    if (a.error) note("技术状态：" + a.error.message, card);
    if (a.result?.parse_error) note(a.result.parse_error, card);
    if (status === "capacity_exceeded") note("完整输入超出容量，未发送、未静默裁剪。", card);
    if (candidate) {
      note(candidate.scoped_claim, card);
      for (const [label, value] of [
        ["主张与实验情境", {claim: candidate.scoped_claim, context: candidate.biological_context}],
        ["机制步骤：来源报告 / 作者解释 / 新猜想", candidate.mechanism_steps],
        ["实际证据锚点与新因果桥接", {anchors: candidate.evidence_anchors, new_links: candidate.proposed_new_links}],
        ["公开必要假设清单", candidate.assumption_ledger],
        ["竞争解释和区分性预测", {alternatives: candidate.competing_explanations, predictions: candidate.predictions}],
        ["证伪与概念验证", {falsification: candidate.falsification_conditions, validation: candidate.validation_concept}],
        ["近邻范围、引用与限制", {scope: candidate.nearest_prior_work_scope, sources: candidate.source_refs, limitations: candidate.limitations}],
      ]) genTextSection(card, label, value);
    }
    for (const attempt of a.attempts) {
      note("Attempt " + attempt.id + " · " + attempt.status + " · 用量：" + attempt.usage + "（null为未知）", card);
      const button = document.createElement("button");
      button.textContent = "查看保存的实际请求 / 原始响应";
      button.onclick = () => action(async () => {
        const raw = await api("/api/generation/attempt?attempt_id=" + encodeURIComponent(attempt.id));
        card.append(folded("M15 调用事实", raw));
      });
      card.append(button);
    }
    if (["ready", "running"].includes(a.task_status)) {
      const button = document.createElement("button");
      button.textContent = "显式执行 / 恢复此任务";
      button.onclick = () => action(async () => {await api("/api/generation/execute", {request_id: a.request_id, recover: true}); await showRun(data.run.id);});
      card.append(button);
    }
    genTextSection(card, "固定输入、配置和来源关联", {input: a.input, config: a.config, provenance: a.result?.call_provenance});
    el("generation-records").append(card);
  }
  if (state.busy) document.querySelectorAll("button").forEach((b) => (b.disabled = true));
}
