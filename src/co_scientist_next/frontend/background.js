"use strict";
let backgroundData = null;
const backgroundTaskLabels = {P03:"规划查询",P04:"阅读原文",P05:"综合背景资料",P06_DIRECTED:"准备定向研究方向",P06_OPEN:"准备开放研究方向",P07:"评估准备程度"};
const backgroundLabels = {
  saved: "已保存解读/准备结果",
  invalid_output: "阅读失败：输出解析或契约无效",
  model_not_configured: "模型未配置，未调用",
  model_call_not_authorized: "真实调用未获显式执行许可，未调用",
  capacity_exceeded: "容量不足，未调用；没有静默截断",
  no_progress:
    "原文、阅读、背景包、检索覆盖和具体程度均无内容变化，停止重复检查",
};
function bgOptions(id, items, label) {
  const select = el(id),
    previous = select.value;
  select.replaceChildren();
  for (const item of items) {
    const o = document.createElement("option");
    o.value = item.id;
    o.textContent = label(item);
    select.append(o);
  }
  if ([...select.options].some((o) => o.value === previous))
    select.value = previous;
}
function bgFields() {
  const op = el("background-operation").value;
  el("background-prompt").textContent =
    "当前新任务 Prompt：" + op + " · " +
    (backgroundData?.current_prompt_versions?.[op] || "未取得版本") +
    "；历史任务按各自固定版本展示和恢复。";
  el("background-view-label").hidden = op !== "P04";
  el("background-orientation-label").hidden = !op.startsWith("P06");
  el("background-packet-label").hidden = op !== "P07";
  el("background-number-label").hidden = !(
    op.startsWith("P06") || op === "P03"
  );
  el("background-specificity-label").hidden = op !== "P07";
}
function bgMaterialRange() {
  const material = backgroundData?.materials.find(
    (m) => m.acquisition_task_id === el("background-material").value,
  );
  el("view-start").value = 0;
  el("view-end").value = material ? Math.min(material.characters, 5000) : "";
}
async function bgOperation() {
  const run = state.run.run.id,
    operation = el("background-operation").value;
  const request = {},
    seed = el("background-scope").value;
  if (seed && !operation.startsWith("P06")) request.seed_id = seed;
  if (operation === "P04") request.view_id = el("background-view").value;
  if (operation.startsWith("P06")) {
    request.orientation_ref = el("background-orientation").value;
    request.count = Number(el("background-number").value);
  }
  if (operation === "P03")
    request.query_count = Number(el("background-number").value);
  if (operation === "P07") {
    request.packet_ref = el("background-packet").value;
    request.requested_specificity = el("background-specificity").value;
  }
  if (
    backgroundData.current_model_config.execution_mode === "development_fixture"
  )
    request.fixture_scenario = el("background-fixture").value;
  const request_id = crypto.randomUUID();
  await api("/api/background", { run_id: run, request_id, operation, request });
  await showBackground(state.run);
  el("notice").textContent =
    "任务已持久保存，执行请求中。刷新只读取，绝不自动重发。";
  await api("/api/background/execute", { request_id });
  await project(state.project);
  await showRun(run);
  el("notice").textContent =
    "本步执行事实已保存；请查看成功、失败或待补状态。没有生成候选。";
}
el("background-run").onclick = () => action(bgOperation);
el("background-operation").onchange = bgFields;
el("background-scope").onchange = () => action(() => showBackground(state.run));
el("background-material").onchange = bgMaterialRange;
el("save-view").onclick = () =>
  action(async () => {
    await api("/api/material-views", {
      run_id: state.run.run.id,
      acquisition_task_id: el("background-material").value,
      start: Number(el("view-start").value),
      end: Number(el("view-end").value),
      reason: el("view-reason").value,
      seed_id: el("background-scope").value || null,
    });
    await showBackground(state.run);
  });
async function showBackground(data) {
  const saved = await api(
    "/api/background?run_id=" + encodeURIComponent(data.run.id),
  );
  backgroundData = saved;
  el("background-panel").hidden = false;
  const mode = saved.current_model_config.execution_mode;
  el("background-mode").textContent =
    mode === "development_fixture"
      ? "开发阅读替身 · 工程验证。可能使用真实已取得文献，但没有真实模型阅读、科学解读审阅或科学有效性验证。"
      : mode === "real_model"
        ? "真实适配器配置 · " +
          (saved.real_calls_authorized && saved.current_model_config.credential_configured
            ? "当前具备显式调用条件；仅点击执行才会发送，真实表现仍需审阅。"
            : "当前未授权或未配置凭据，未发送模型请求；不回退开发替身。")
        : "真实模型未配置 · 不会自动使用开发替身。";
  if (state.config.development_test)
    el("background-mode").textContent +=
      " Goal 制备/目标筛查为开发测试结果，不代表真实伦理审查。";
  el("background-config").textContent = JSON.stringify(
    {
      config: saved.current_model_config,
      real_calls_authorized: saved.real_calls_authorized,
      usage: data.usage,
    },
    null,
    2,
  );
  el("background-count").textContent =
    "已保存 P04 解读记录：" +
    saved.reading_count_saved +
    (mode === "development_fixture" ? "（开发替身，不计为真实模型阅读）" : "") +
    "；真实适配器 Attempt 数：" +
    saved.real_adapter_attempts_recorded +
    "。科学未验证。";
  el("background-fixture-label").hidden = mode !== "development_fixture";
  bgOptions(
    "background-scope",
    [{ id: "", kind: "broad", question: "宽背景 / 中性概览" }, ...saved.seeds],
    (s) => s.kind + " · " + s.question,
  );
  const seed = el("background-scope").value;
  const materials = saved.materials
    .filter((m) => !m.context?.seed_id || m.context.seed_id === seed)
    .map((m) => ({ id: m.acquisition_task_id, ...m }));
  const old = el("background-material").value;
  bgOptions(
    "background-material",
    materials,
    (m) =>
      m.source.source_ref + " · " + m.access + " · " + m.characters + "字符",
  );
  if (old !== el("background-material").value || !el("view-end").value)
    bgMaterialRange();
  const views = saved.views.filter((v) => !v.seed_id || v.seed_id === seed);
  bgOptions(
    "background-view",
    views,
    (v) =>
      v.id.slice(0, 8) +
      " · " +
      v.source_ref +
      " · " + v.access +
      " · " +
      v.character_range.join("–"),
  );
  const success = saved.actions.filter(
    (a) => a.result?.background_status === "saved",
  );
  bgOptions(
    "background-orientation",
    success
      .filter((a) => a.operation === "P05" && !a.seed_id)
      .map((a) => ({ id: a.request_id, label: a.result.artifact.overview[0] || "已保存背景包" })),
    (a) => a.label,
  );
  bgOptions(
    "background-packet",
    success
      .filter((a) => a.operation === "P05" && a.seed_id === seed && seed)
      .map((a) => ({ id: a.request_id, label: a.result.artifact.overview[0] || "已保存背景包" })),
    (a) => a.label,
  );
  const idle = [
    "awaiting_background",
    "literature_acquired_unread",
    "literature_incomplete",
    "literature_failed",
    "background_saved",
    "background_problem",
    "background_no_progress",
    "awaiting_generation",
    "failed",
  ].includes(data.run.status);
  el("background-run").disabled = !idle;
  el("save-view").disabled = !materials.length;
  el("background-views").replaceChildren();
  for (const view of views) {
    const d = document.createElement("div");
    d.className = "block";
    note(
      "原文视图（与模型解读分区）：" +
        view.source_ref +
        " · " +
        (view.cropped ? "全文/已取得文本的显式片段（" + view.access + "）" : view.access) +
        " · 范围 " +
        view.character_range.join("–") +
        " / " +
        view.original_characters +
        "字符",
      d,
    );
    note(
      view.selection_reason +
        "；" +
        view.access_limitations +
        "；未读取图像或补充材料。",
      d,
    );
    d.append(folded("查看固定原文 / 裁剪记录", view));
    el("background-views").append(d);
  }
  el("background-seeds").replaceChildren();
  for (const s of saved.seeds) {
    const d = document.createElement("div");
    d.className = "block seed-card";
    d.dataset.seedId = s.id;
    note(
      (s.kind === "open" ? "开放 seed（隔离输入）" : "定向 seed") +
        "：" +
        s.question,
      d,
    );
    const checks = success.filter(
      (a) => a.operation === "P07" && a.seed_id === s.id,
    );
    const latest = checks.at(-1)?.result.artifact;
    note("最近完成的 readiness：" + (latest?.decision || "尚未检查"), d);
    if (latest) {
      note("理由：" + latest.rationale, d);
      note("允许具体程度：" + latest.allowed_specificity, d);
      if (latest.decision === "ready")
        note("可显式选择 P08 生成；不代表机制正确、新颖或已准入。", d);
      d.append(folded("待补资料与完整 readiness", latest));
    }
    el("background-seeds").append(d);
  }
  el("background-records").replaceChildren();
  for (const a of saved.actions) {
    const d = document.createElement("div");
    d.className = "block background-record";
    d.dataset.requestId = a.request_id;
    const h = document.createElement("h3");
    h.textContent = (backgroundTaskLabels[a.operation] || a.operation) + " · " + (saved.seeds.find(s=>s.id===a.seed_id)?.question || "宽背景");
    d.append(h);
    note("固定 Prompt 版本：" + a.prompt_version, d);
    const status = a.result?.background_status;
    note(
      (a.task_status === "running"
        ? "阅读中 / 执行尚未收尾"
        : a.task_status === "ready"
          ? "已保存待执行"
          : a.task_status === "failed"
            ? "阅读/准备技术失败（非科学否定）"
            : backgroundLabels[status] || a.task_status) +
        " · " +
        a.request_id,
      d,
    );
    note("执行标识：" + a.config.execution_mode, d);
    if (a.error) note("错误：" + a.error.message, d);
    if (a.result?.reason || a.result?.parse_error)
      note(a.result.reason || a.result.parse_error, d);
    const artifact = a.result?.artifact;
    if (a.operation === "P04" && artifact) {
      for (const c of artifact.finding_cards) {
        note("模型解读 / 观察：" + c.reported_observation, d);
        note(
          "实验情境：" +
            c.biological_context +
            "；干预/对照：" +
            c.intervention_comparator +
            "；终点：" +
            c.endpoint,
          d,
        );
        note(
          "负结果：" +
            c.negative_findings.join("；") +
            "；未证明：" +
            c.not_established.join("；") +
            "；外推假设：" +
            c.transfer_assumptions.join("；"),
          d,
        );
        note(
          "作者解释：" +
            c.author_interpretation +
            "；来源视图 " +
            c.source_view_ref +
            " / " +
            c.source_locator,
          d,
        );
      }
    }
    if (a.operation === "P05" && artifact) {
      note("中性背景 / 单 seed 资料：" + artifact.overview.join("\n"), d);
      note("竞争解释：" + artifact.competing_explanations.join("；"), d);
      note("未排序研究问题：" + artifact.unranked_questions.join("；"), d);
      note("覆盖限制：" + artifact.limitations.join("；"), d);
    }
    if (a.operation === "P03" && artifact) {
      note(
        "仅查询计划，未自动执行；计划执行模式：" + a.config.execution_mode,
        d,
      );
      artifact.queries.forEach((q, i) => {
        note(q.query + " · " + q.why, d);
        const b = litButton("显式执行这条计划查询", d, async () => {
          await api("/api/background/query", {
            run_id: data.run.id,
            plan_ref: a.request_id,
            query_index: i,
            request_id: crypto.randomUUID(),
          });
          await project(state.project);
          await showRun(data.run.id);
        });
        b.disabled = !state.config.public_literature_enabled || !idle;
      });
    }
    if (["ready", "running"].includes(a.task_status))
      litButton("显式执行 / 恢复此准备任务", d, async () => {
        await api("/api/background/execute", {
          request_id: a.request_id,
          recover: true,
        });
        await showRun(data.run.id);
      });
    d.append(folded("原始输入、模型输出、配置与用量事实", a));
    el("background-records").append(d);
  }
  bgFields();
  if (state.busy)
    document
      .querySelectorAll("button:not([data-nav]):not(#refresh)")
      .forEach((button) => (button.disabled = true));
}
