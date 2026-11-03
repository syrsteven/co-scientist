"use strict";
const el = (id) => document.getElementById(id);
const state = {
  project: null,
  revision: null,
  run: null,
  config: null,
  dirty: false,
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
  awaiting_background: "等待背景调研接入",
  goal_rejected: "目标筛查 reject，已停止",
  adapter_not_configured: "未接入模型适配器",
  failed: "技术执行失败",
  blocked: "发送状态不确定，已阻断",
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
  el("notice").textContent = "";
  const buttons = [...document.querySelectorAll("button")];
  const disabled = buttons.map((b) => b.disabled);
  buttons.forEach((b) => (b.disabled = true));
  try {
    await fn();
  } catch (e) {
    el("notice").textContent = e.message;
  } finally {
    buttons.forEach((b, i) => (b.disabled = disabled[i]));
    updateActions();
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
  el("create-run").disabled = !state.revision || state.dirty;
  const status = state.run?.run.status;
  el("execute").disabled = status !== "ready";
  el("recover").hidden = status !== "running";
}
function reset() {
  state.project = null;
  state.revision = null;
  state.run = null;
  state.dirty = false;
  location.hash = "";
  el("brief-form").reset();
  el("name").readOnly = false;
  el("revision-badge").textContent = "尚未保存";
  el("runs").replaceChildren();
  el("run-detail").textContent = "保存简报并创建 Run 后，查看真实记录。";
  el("run-tools").hidden = true;
  el("run-state").textContent = "未选择 Run";
  updateActions();
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
  for (const run of data.runs) {
    const button = document.createElement("button");
    button.textContent =
      run.id.slice(0, 8) + " · " + (labels[run.status] || run.status);
    button.onclick = () => action(() => showRun(run.id));
    el("runs").append(button);
  }
  updateActions();
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
      detail.append(
        block(
          output.ethics.completed
            ? "完成的 Goal Ethics 决定"
            : "执行状态：风险信息待补充",
          output.ethics,
        ),
      );
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
        "真实待接入边界",
        "Goal Ethics 已完成 pass；背景调研尚未接入，因此未进入 Generation，科研未完成。",
      ),
    );
  if (data.run.status === "blocked")
    detail.append(
      block(
        "需要人工核实",
        "外部执行结果不确定。刷新不会重发；需后端核实并显式授权后才能重试。",
      ),
    );
  updateActions();
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
    });
    await project(state.project);
    await showRun(result.run_id);
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
el("refresh").onclick = () =>
  action(async () => {
    await projects();
    if (state.project) await project(state.project);
    if (state.run) await showRun(state.run.run.id);
  });
(async () => {
  try {
    state.config = await api("/api/config");
    el("mode").textContent = state.config.development_test
      ? "开发测试模式 · 确定性适配器仅验证工程流程，不代表真实 Goal 制备或伦理分类能力；没有付费模型调用。"
      : "真实模型适配器尚未接入 · 可以保存简报与查看记录，执行会记录未配置状态。";
    el("example-policy").hidden = !state.config.development_test;
    el("fixture-label").hidden = !state.config.development_test;
    await projects();
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
