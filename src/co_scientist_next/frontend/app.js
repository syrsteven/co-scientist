"use strict";
const el = (id) => document.getElementById(id);
const workspaceChanged = () => document.dispatchEvent(new CustomEvent("workspace-change"));
const state = {
  project: null,
  revision: null,
  run: null,
  config: null,
  dirty: false,
  busy: false,
};
const labels = {
  ready: "已保存，待显式执行",
  running: "执行事实未收尾，可显式恢复",
  awaiting_clarification: "待澄清关键歧义",
  missing_policy: "缺少显式政策",
  invalid_policy: "政策输入无效",
  invalid_input: "输入无效",
  invalid_output: "模型输出无效",
  awaiting_risk_context: "风险信息待补充（非伦理结论）",
  awaiting_background: "目标前置完成 · 可开始文献与背景准备",
  goal_rejected: "目标筛查 reject，已停止",
  adapter_not_configured: "未接入模型适配器",
  failed: "技术执行失败",
  blocked: "发送状态不确定，已阻断",
  literature_acquired_unread: "文献请求已完成 · 尚未解读",
  literature_incomplete: "文献获取部分完成 · 尚未解读",
  literature_failed: "文献请求失败（不是没有证据）",
  background_saved: "背景步骤已保存 · 未生成候选",
  background_problem: "背景准备/执行问题",
  background_no_progress: "无新资料，已停止重复检查",
  awaiting_generation: "seed 已 ready · 可显式生成",
  awaiting_candidate_ethics: "已生成 · 待 Candidate Ethics/R0",
  awaiting_r0: "Candidate Ethics通过 · 待R0",
  awaiting_r1: "R0允许进入R1 · R1未实现",
  candidate_ethics_hold: "候选伦理待补充 · 未放行",
  candidate_ethics_stopped: "候选伦理按政策停止",
  candidate_r0_blocked: "R0明确阻断",
  candidate_review_problem: "候选审查未完成 · 查看执行问题",
  generation_problem: "生成准备/执行问题（非科学否定）",
};
async function api(path, data) {
  const response = await fetch(
    path,
    data
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }
      : {},
  );
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败");
  return result;
}
async function action(fn) {
  if (state.busy) return;
  state.busy = true;
  el("notice").textContent = "";
  const buttons = [...document.querySelectorAll("button:not([data-nav]):not(#refresh)")];
  const disabled = buttons.map((b) => b.disabled);
  buttons.forEach((b) => (b.disabled = true));
  try {
    await fn();
  } catch (e) {
    el("notice").textContent = e.message;
  } finally {
    state.busy = false;
    buttons.forEach((b, i) => (b.disabled = disabled[i]));
    updateActions();
    if (state.run) {
      await showLiterature(state.run);
      await showBackground(state.run);
      await showGeneration(state.run);
    }
  }
}
const lines = (id) =>
  el(id)
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
function brief() {
  return {
    question: el("question").value,
    hard_constraints: lines("constraints"),
    preferences: lines("preferences"),
    background: el("background").value,
    intended_use: el("intended-use").value || null,
    materials: lines("materials"),
  };
}
function block(title, data) {
  const item = document.createElement("div");
  item.className = "block";
  const h = document.createElement("h3");
  h.textContent = title;
  const p = document.createElement("pre");
  p.className = "data";
  p.textContent =
    typeof data === "string" ? data : JSON.stringify(data, null, 2);
  item.append(h, p);
  return item;
}
function updateActions() {
  document.querySelectorAll("#runs button, #projects button").forEach((b) => (b.disabled = state.busy));
  el("create-run").disabled = !state.revision || state.dirty || (state.config?.goal_test_opt_in_required && el("goal-test-choice")?.value !== "deterministic_development");
  const status = state.run?.run.status;
  el("execute").disabled =
    status !== "ready" ||
    state.run?.tasks.at(-1)?.module.startsWith("literature.") ||
    state.run?.tasks.at(-1)?.module.startsWith("background.") ||
    state.run?.tasks.at(-1)?.module.startsWith("generation.") ||
    state.run?.tasks.at(-1)?.module.startsWith("candidate_review.");
  el("recover").hidden =
    status !== "running" ||
    state.run?.tasks.at(-1)?.module.startsWith("literature.") ||
    state.run?.tasks.at(-1)?.module.startsWith("background.") ||
    state.run?.tasks.at(-1)?.module.startsWith("generation.") ||
    state.run?.tasks.at(-1)?.module.startsWith("candidate_review.");
}
function reset() {
  state.project = null;
  state.revision = null;
  state.run = null;
  generationData = null; backgroundData = null; literatureData = [];
  el("literature-panel").hidden = true;
  el("background-panel").hidden = true;
  el("generation-panel").hidden = true;
  state.dirty = false;
  location.hash = "";
  el("brief-form").reset();
  if (el("goal-test-choice")) el("goal-test-choice").value = "";
  el("name").readOnly = false;
  el("revision-badge").textContent = "尚未保存";
  el("runs").replaceChildren();
  el("run-detail").textContent = "保存简报并创建 Run 后，查看真实记录。";
  el("run-tools").hidden = true;
  el("run-state").textContent = "未选择 Run";
  updateActions();
  workspaceChanged();
}
async function projects() {
  const list = await api("/api/projects");
  el("projects").replaceChildren();
  if (!list.length) el("projects").textContent = "尚无研究，先保存一份简报。";
  for (const p of list) {
    const b = document.createElement("button");
    b.textContent = p.name;
    b.onclick = () => action(() => project(p.id));
    el("projects").append(b);
  }
}
async function project(id) {
  const data = await api("/api/project?id=" + encodeURIComponent(id));
  if (state.project && state.project !== id) {
    state.run = null;
    generationData = null; backgroundData = null; literatureData = [];
    el("literature-panel").hidden = true;
    el("background-panel").hidden = true;
    el("generation-panel").hidden = true;
    el("run-tools").hidden = true;
    el("run-detail").textContent = "请选择此研究的固定 Run。";
    el("run-state").textContent = "未选择 Run";
  }
  state.project = id;
  state.dirty = false;
  el("name").readOnly = true;
  const r = data.revisions[0];
  state.revision = r?.id;
  el("name").value = data.project.name;
  const b = r?.content || {};
  el("question").value = b.question || "";
  el("constraints").value = (b.hard_constraints || []).join("\n");
  el("preferences").value = (b.preferences || []).join("\n");
  el("background").value = b.background || "";
  el("intended-use").value = b.intended_use || "";
  el("materials").value = (b.materials || []).join("\n");
  el("revision-badge").textContent = r
    ? "草稿版本 " + r.id.slice(0, 8)
    : "尚未保存";
  el("runs").replaceChildren();
  for (const [index, run] of data.runs.entries()) {
    const button = document.createElement("button");
    button.textContent =
      "运行 " + (index+1) + " · " + (labels[run.status] || run.status);
    button.onclick = () => action(() => showRun(run.id));
    el("runs").append(button);
  }
  updateActions();
  workspaceChanged();
}
function folded(title, data) {
  const d = document.createElement("details");
  const h = document.createElement("summary");
  h.textContent = title;
  d.append(h, block("", data));
  return d;
}
function goalCard(goal) {
  const card = document.createElement("div");
  card.className = "block";
  const h = document.createElement("h3");
  h.textContent = "制备 Goal";
  card.append(h);
  const q = document.createElement("p");
  q.textContent = goal.prepared_question;
  card.append(q);
  for (const [label, items] of [
    ["硬约束", goal.hard_requirements],
    ["偏好", goal.preferences],
    ["未指定条件", goal.unspecified_details],
    ["系统解释（不作为用户条件）", goal.optional_interpretations],
  ]) {
    const heading = document.createElement("strong");
    heading.textContent = label;
    card.append(heading);
    const ul = document.createElement("ul");
    if (!items.length) {
      const li = document.createElement("li");
      li.textContent = "无新增内容";
      ul.append(li);
    }
    for (const item of items) {
      const li = document.createElement("li");
      li.textContent =
        typeof item === "string"
          ? item
          : item.text + " · 来源 " + item.input_locator;
      ul.append(li);
    }
    card.append(ul);
  }
  if (goal.clarification_questions.length)
    card.append(
      block(
        "待澄清项",
        goal.clarification_questions.map((q) => q.question).join("\n"),
      ),
    );
  card.append(folded("查看 Goal 原始问题、背景与完整来源定位", goal));
  return card;
}
async function showRun(id) {
  const data = await api("/api/run?id=" + encodeURIComponent(id));
  state.run = data;
  location.hash = "run=" + id;
  el("run-tools").hidden = false;
  el("run-state").textContent = labels[data.run.status] || data.run.status;
  const detail = el("run-detail");
  detail.className = "";
  detail.replaceChildren(
    folded("Run 身份与固定输入", {
      run_id: id,
      brief_revision_id: data.run.revision_id,
      goal_context_ref: data.run.goal_context_ref,
      original_question: data.fixed_brief.question,
      development_test: data.development_test,
    }),
  );
  detail.append(folded("固定简报（与左侧草稿分离）", data.fixed_brief));
  for (const result of data.results) {
    const output = result.output;
    if (output.goal_context) {
      detail.append(goalCard(output.goal_context));
    }
    if (output.ethics) {
      const ethics = output.ethics;
      const card = document.createElement("div");
      card.className = "block ethics-readable";
      const title = document.createElement("h3");
      title.textContent = ethics.completed
        ? ethics.decision === "pass"
          ? "目标筛查：通过（pass）"
          : "目标筛查：拒绝（reject）"
        : "目标筛查：风险信息待补充（未形成伦理决定）";
      const reason = document.createElement("p");
      reason.textContent = "理由：" + ethics.rationale;
      card.append(title, reason);
      if (ethics.missing_information) {
        const missing = document.createElement("p");
        missing.textContent =
          "待补信息：" + ethics.missing_information.join("；");
        card.append(missing);
      }
      card.append(folded("原始筛查 JSON 与政策引用", ethics));
      detail.append(card);
    }
    if (output.parse_error || output.reason)
      detail.append(block("准备 / 解析状态", output));
  }
  detail.append(folded("显式政策快照", data.policy || "未提供政策"));
  detail.append(
    folded(
      "任务执行事实",
      data.tasks.map((t) => ({
        id: t.id,
        module: t.module,
        status: t.status,
        error: t.error ? JSON.parse(t.error) : null,
      })),
    ),
  );
  detail.append(folded("消耗记录（未知值保持未知）", data.usage));
  if (data.run.status === "awaiting_background")
    detail.append(
      block(
        "下一步：显式准备文献与背景",
        "Goal Ethics 已完成 pass；可以显式检索/获取和执行 P03–P07 背景准备。模型表现仍需审阅，P08需显式提交，科研未完成。",
      ),
    );
  if (data.run.status === "blocked")
    detail.append(
      block(
        "需要人工核实",
        "外部执行结果不确定。刷新不会重发；需后端核实并显式授权后才能重试。",
      ),
    );
  await showLiterature(data);
  await showBackground(data);
  await showGeneration(data);
  updateActions();
  workspaceChanged();
}
el("new-project").onclick = () => reset();
el("brief-form").oninput = () => {
  state.dirty = true;
  el("revision-badge").textContent = "有未保存编辑";
  updateActions();
};
el("brief-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    const r = await api("/api/brief", {
      project_id: state.project,
      previous_revision_id: state.revision,
      name: el("name").value,
      brief: brief(),
    });
    await projects();
    await project(r.project_id);
    el("notice").textContent = "简报新版本已保存；既有 Run 输入保持不变。";
  });
};
el("example-policy").onclick = () => {
  const p = state.config.example_policy;
  el("policy-id").value = p.id;
  el("policy-version").value = p.version;
  el("policy-text").value = p.text;
};
el("create-run").onclick = () =>
  action(async () => {
    const text = el("policy-text").value;
    const policy = text
      ? {
          id: el("policy-id").value,
          version: el("policy-version").value,
          text,
          development_only:
            el("policy-id").value === state.config.example_policy?.id,
        }
      : null;
    const result = await api("/api/runs", {
      revision_id: state.revision,
      policy,
      scenario: el("scenario").value,
      goal_test_mode: el("goal-test-choice")?.value,
    });
    await project(state.project);
    await showRun(result.run_id);
    if (typeof wbShow === "function") wbShow("overview");
  });
el("execute").onclick = () =>
  action(async () => {
    const id = state.run.run.id;
    await api("/api/execute", { run_id: id });
    await project(state.project);
    await showRun(id);
  });
el("recover").onclick = () =>
  action(async () => {
    const id = state.run.run.id;
    await api("/api/execute", { run_id: id, recover: true });
    await project(state.project);
    await showRun(id);
  });
el("refresh").onclick = async () => {
    try {
    await projects();
    if (state.project) await project(state.project);
    if (state.run) await showRun(state.run.run.id);
    workspaceChanged();
    } catch(e) {el("notice").textContent=e.message;}
  };
(async () => {
  try {
    state.config = await api("/api/config");
    el("mode").textContent = state.config.development_test
      ? "开发测试模式 · Goal 制备与 Goal Ethics 当前仅提供确定性开发适配器；每次新运行须明确选择；Candidate Ethics/R0 的政策范围及真实／替身执行方式见各自记录。不代表组织伦理批准。"
      : "Goal 模型适配器未配置 · 背景阅读的供应商配置与执行标识另见下方；没有默认替身。";
    el("example-policy").hidden = !state.config.development_test;
    el("fixture-label").hidden = !state.config.development_test;
    await projects();
    workspaceChanged();
    const match = location.hash.match(/^#run=([a-f0-9]+)$/);
    if (match) {
      const saved = await api("/api/run?id=" + match[1]);
      await project(saved.run.project_id);
      await showRun(match[1]);
    }
  } catch (e) {
    el("notice").textContent = e.message;
  }
})();

function note(text, parent) {
  const p = document.createElement("p");
  p.textContent = text;
  parent.append(p);
  return p;
}
function litButton(text, parent, fn) {
  const b = document.createElement("button");
  b.textContent = text;
  b.onclick = () => action(fn);
  parent.append(b);
  return b;
}
let literatureData = [];
let pendingLiterature = null;
async function submitLiterature(request) {
  const run = state.run.run.id;
  const signature = JSON.stringify({ run, request });
  if (!pendingLiterature || pendingLiterature.signature !== signature)
    pendingLiterature = { signature, id: crypto.randomUUID() };
  await api("/api/literature", {
    run_id: run,
    request_id: pendingLiterature.id,
    request,
  });
  pendingLiterature = null;
  await project(state.project);
  await showRun(run);
}
el("literature-search").onclick = () =>
  action(() =>
    submitLiterature({
      kind: "search",
      query: el("literature-query").value,
      page_size: Number(el("literature-page-size").value),
    }),
  );
async function showLiterature(data) {
  el("literature-panel").hidden = false;
  const passed = data.results.some(
    (r) =>
      r.output.ethics?.completed === true &&
      r.output.ethics?.decision === "pass",
  );
  const allowed = state.config.public_literature_enabled && passed;
  const idle = [
    "awaiting_background",
    "literature_acquired_unread",
    "literature_incomplete",
    "literature_failed",
    "background_saved",
    "background_problem",
    "background_no_progress",
    "awaiting_generation",
  ].includes(data.run.status);
  el("literature-search").disabled = !allowed || !idle;
  el("literature-mode").textContent = state.config.literature_execution_mode === "offline_fixture" ? "OFFLINE 响应夹具 · 不是真实检索或科学证据。" : data.development_test
    ? "目标筛查为测试结果，文献获取为真实请求（需显式操作）；不代表真实伦理审查或生产科学链。"
    : "真实公共文献请求；未执行模型阅读。";
  el("literature-gate").textContent = !passed
    ? "未有保存的完成 pass，不允许进入检索。"
    : !state.config.public_literature_enabled
      ? "服务未启用 --public-literature；不会发出公共请求。"
      : !idle
        ? "存在未完成/阻断任务；新检索暂停，刷新只读取。"
        : "可执行人工查询；每次查询、翻页和逐篇获取均保存历史。";
  const history = await api(
    "/api/literature?run_id=" + encodeURIComponent(data.run.id),
  );
  literatureData = history;
  const root = el("literature-history");
  root.replaceChildren();
  if (!history.length) note("尚无检索记录。", root);
  const unique = new Set();
  for (const entry of history) {
    const card = document.createElement("div");
    card.className = "block literature-entry";
    root.append(card);
    const request = entry.request,
      result = entry.result?.acquisition;
    const h = document.createElement("h3");
    h.textContent =
      request.kind === "search"
        ? "显式查询：" + request.query
        : "获取材料：" + request.source_ref;
    card.append(h);
    note(
      "请求 " +
        entry.request_id +
        " · " +
        entry.created_at +
        " · 任务 " +
        entry.task_status,
      card,
    );
    if (!result) {
      note(
        entry.error
          ? "技术/不确定状态：" + entry.error.message
          : "尚无已应用结果；刷新不会自动执行。",
        card,
      );
      if (allowed && ["ready", "running"].includes(entry.task_status))
        litButton("显式恢复此文献任务", card, async () => {
          await api("/api/literature/execute", {
            request_id: entry.request_id,
            recover: true,
          });
          await showRun(data.run.id);
        });
      card.append(folded("实际请求与调用事实", entry));
      continue;
    }
    note(
      "执行：" + result.status + " · 已获取、尚未解读 · 科学能力未验证",
      card,
    );
    if (result.error || result.limitation)
      note("限制/错误：" + (result.error || result.limitation), card);
    if (request.kind === "search") {
      note(
        "来源 Europe PMC · 人工查询 · 本页取得 " +
          result.items.length +
          " 篇元数据 · 报告总数 " +
          (result.reported_total ?? "未知") +
          " · 每页 " +
          request.page_size +
          " · 范围完成 " +
          result.scope_complete,
        card,
      );
      note(
        "分页：" +
          (request.cursor || "起始页 *") +
          " → " +
          (result.next_cursor || "无后继游标") +
          "；分页未完成不表示已穷尽文献。",
        card,
      );
      if (result.next_cursor) {
        const b = litButton("显式检索下一页", card, () =>
          submitLiterature({
            kind: "search",
            query: request.query,
            cursor: result.next_cursor,
            parent_search_id: entry.request_id,
            page_size: request.page_size,
          }),
        );
        b.disabled = !allowed || !idle;
      }
      for (const source of result.items) {
        unique.add(source.source_ref);
        const item = document.createElement("div");
        item.className = "source-card";
        card.append(item);
        const a = document.createElement("a");
        a.textContent = source.title;
        a.href = source.citation;
        a.target = "_blank";
        a.rel = "noreferrer";
        item.append(a);
        note(
          source.source_ref + " · 当前检索结果仅元数据；不代表全文或支持某主张",
          item,
        );
        for (const [label, level] of [
          ["获取摘要", "abstract"],
          ["尝试获取开放全文", "full_text"],
        ]) {
          const b = litButton(label, item, () =>
            submitLiterature({
              kind: "fetch",
              source_ref: source.source_ref,
              search_request_id: entry.request_id,
              desired_access: level,
            }),
          );
          b.disabled = !allowed || !idle;
        }
      }
    } else {
      note(
        "实际访问层级：" +
          result.access +
          " · 请求层级：" +
          request.desired_access,
        card,
      );
      if (result.source)
        note(result.source.title + " · " + result.source.citation, card);
      if (result.text)
        card.append(
          folded(
            result.access === "full_text"
              ? "查看已取得全文文本（图像/补充未获取）"
              : "查看已取得摘要",
            result.text,
          ),
        );
      note(
        "定位：" +
          (entry.result.details.text_locator ||
            entry.result.details.metadata_locator ||
            "无取得文本") +
          "；补充材料未获取。",
        card,
      );
    }
    card.append(folded("完整获取事实、来源定位与实际请求", entry));
  }
  if (unique.size)
    note("历史检索中去重来源数：" + unique.size + "（不表示独立研究数）", root);
}
