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
    note(status === "generated" ? "已生成，待Candidate Ethics/R0；未准入、未评分、科学未验证。" : "调用状态：" + ({blocked: "发送不确定，已停止；不自动重发", failed: "技术失败（非科学否定）", running: "执行中，尚未收尾", waiting_remote: "远端任务已保存，等待显式查询", ready: "已保存待显式执行"}[a.task_status] || a.task_status) + " · " + (status || "结果未完成"), card);
    note("执行标识：" + a.config.execution_mode + " · 固定Prompt：" + a.prompt_version, card);
    note("seed：" + a.request.seed_id + " · 背景包：" + a.request.packet_ref + " · readiness：" + a.request.readiness_ref, card);
    if (a.remote) {
      note("远端任务：" + a.remote.response_id + " · 最近观测状态 " + a.remote.status + " · 已等待 " + Math.floor(a.remote.elapsed_seconds) + " 秒（自本地保存提交响应起，非供应商计算时长）", card);
      note("最近查询：" + JSON.stringify(a.remote.latest_query || {outcome: "尚未查询"}) + "；刷新只读，不自动查询或重新提交。", card);
      if (["queued", "in_progress", "unknown"].includes(a.remote.status)) {
        const query = document.createElement("button");
        query.textContent = "显式查询同一远端任务（不创建新生成）";
        query.disabled = !saved.real_calls_authorized || !saved.model_config.credential_configured;
        query.onclick = () => action(async () => {await api("/api/generation/query", {request_id: a.request_id}); await showRun(data.run.id);});
        card.append(query);
      }
    } else if (a.task_status === "blocked") {
      note("没有已保存的远端任务 ID；提交结果不确定，不能作为正在远端执行显示。", card);
    }
    if (a.config.api_mode === "responses_background_v1") note("Responses 后台 · store=true；供应商存储保留按已确认配置执行，未知费用不记0。", card);
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
    if (a.migration) {
      const m = a.migration;
      note("迁移关联：原 Task " + m.source_task_id + " → 后继 Task " + m.successor_task_id + "。旧两次调用仍 uncertain，可能已执行/收费。", card);
      note(m.successor_task_id === a.task_id ? (a.attempts.length ? "后继执行状态见下方保存事实。" : "后继任务已创建，模型尚未运行；迁移本身不联网。") : "原历史记录保留；后继任务另列，不代表旧调用已解决。", card);
      note(m.execution_authorization ? "本后继任务已有单独执行授权；不允许自动重发。" : "尚未授予本后继任务付费执行授权。", card);
      genTextSection(card, "迁移确认、身份替代与来源哈希", m);
    } else if (saved.model_config.api_mode === "responses_background_v1" && a.request.mode === "DIRECT" && a.task_status === "blocked" && a.config.api_mode !== "responses_background_v1" && a.attempts.length === 2 && a.attempts.every((p) => p.status === "uncertain")) {
      migrationPreviewControl(card, a, data.run.id);
    }
    if (["ready", "running"].includes(a.task_status)) {
      const button = document.createElement("button");
      const needsAuthorization = a.migration?.successor_task_id === a.task_id && !a.migration.execution_authorization;
      button.textContent = needsAuthorization ? "另行授权并执行此后继任务（可能收费）" : "显式执行 / 恢复此任务";
      button.disabled = a.migration && (!saved.real_calls_authorized || !saved.model_config.credential_configured);
      if (needsAuthorization) {
        const consent = document.createElement("input");
        consent.type = "checkbox";
        consent.setAttribute("aria-label", "另行接受此后继任务的付费执行风险");
        const label = document.createElement("label");
        label.append(consent, document.createTextNode("另行接受此后继任务的付费执行风险；迁移创建未包含本授权"));
        card.append(label);
        button.disabled = true;
        consent.onchange = () => {button.disabled = !consent.checked || !saved.real_calls_authorized || !saved.model_config.credential_configured;};
      }
      button.onclick = () => action(async () => {await api("/api/generation/execute", {request_id: a.request_id, recover: true, authorize_migrated_execution: needsAuthorization}); await showRun(data.run.id);});
      card.append(button);
    }
    genTextSection(card, "固定输入、配置和来源关联", {input: a.input, config: a.config, provenance: a.result?.call_provenance});
    el("generation-records").append(card);
  }
  if (state.busy) document.querySelectorAll("button").forEach((b) => (b.disabled = true));
}

const migrationPreviews = new Map();
function migrationProposal(a) {
  return {source_task_id: a.task_id, source_attempt_ids: a.attempts.map((p) => p.id),
    seed_id: a.request.seed_id, packet_ref: a.request.packet_ref, readiness_ref: a.request.readiness_ref,
    request_id: "p08-migration-" + a.task_id, candidate_id: a.candidate_id + "-responses"};
}
function migrationPreviewControl(card, a, runId) {
  const savedPreview = migrationPreviews.get(a.task_id);
  if (!savedPreview) {
    const candidate = document.createElement("input");
    candidate.value = a.candidate_id + "-responses";
    candidate.setAttribute("aria-label", "迁移后新候选身份");
    const label = document.createElement("label");
    label.textContent = "迁移后新候选身份（明确关联原候选）";
    label.append(candidate);
    card.append(label);
    const previewButton = document.createElement("button");
    previewButton.textContent = "只读预览 Responses 迁移（不发送）";
    previewButton.onclick = () => action(async () => {
      const request = {...migrationProposal(a), candidate_id: candidate.value.trim()};
      const preview = await api("/api/generation/migration/preview", {run_id: runId, request});
      migrationPreviews.set(a.task_id, {request, preview});
    });
    card.append(previewButton);
    return;
  }
  const {request, preview} = savedPreview;
  note("旧两次调用可能已执行并收费；迁移不更改 uncertain，不确认旧调用已停止。新配置 store=true，供应商标准保留至少30天且有组织例外；迁移不授权付费执行。", card);
  note("原候选 " + preview.identity_relation.original_candidate_id + " → 新执行候选 " + preview.identity_relation.successor_candidate_id + "；不是旧调用已解决。科学输入仅替换候选身份，Prompt 不变。", card);
  note("预览 SHA-256：" + preview.preview_hash + "；新配置 SHA-256：" + preview.new_config_sha256, card);
  genTextSection(card, "完整只读预览、冻结请求与新实际请求", preview);
  const confirms = [
    ["old_calls_may_have_executed_and_charged", "确认旧两次调用可能已执行并收费，旧记录保留未知"],
    ["accept_duplicate_execution_and_charge_risk", "接受后继执行可能造成重复执行和收费的风险"],
    ["accept_store_true_retention", "接受新配置 store=true 及所示供应商保留安排"],
    ["creation_is_not_paid_execution_authorization", "仅创建后继任务，不授权付费发送，不自动执行"],
  ];
  const submit = document.createElement("button");
  submit.textContent = "确认迁移，仅创建一个关联任务（不发送）";
  submit.disabled = true;
  const inputs = confirms.map(([key, text]) => {
    const line = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.setAttribute("aria-label", text);
    box.onchange = () => {submit.disabled = !inputs.every((i) => i.box.checked);};
    line.append(box, document.createTextNode(text));
    card.append(line);
    return {key, box};
  });
  submit.onclick = () => action(async () => {
    const acknowledgements = Object.fromEntries(inputs.map((i) => [i.key, i.box.checked]));
    await api("/api/generation/migration/confirm", {run_id: runId, request, preview_hash: preview.preview_hash, acknowledgements});
    migrationPreviews.delete(a.task_id);
    await project(state.project);
    await showRun(runId);
    el("notice").textContent = "迁移任务已原子创建；没有发送模型请求，尚未授权付费执行。旧 uncertain 记录不变。";
  });
  card.append(submit);
}
