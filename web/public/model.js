export const stages = [
  ["literature", "文献检索", "Literature", "检索题录与摘要，为评审提供可追溯的证据。"],
  ["generation", "生成假设", "Generation", "从研究目标生成机制明确、可证伪的候选。"],
  ["reflection", "审查与新颖性", "Reflection", "按冻结策略执行评审；文献新颖性由 Reflection 评估。"],
  ["evolution", "演化与改进", "Evolution", "结合父假设与反馈生成独立子假设；子代必须重新审查。"],
  ["proximity", "相似度与聚类", "Proximity", "比较候选之间的机制相似度，辅助去重、聚类与配对。"],
  ["ranking", "对比与排名", "Ranking", "只在同一 epoch 内比较；只有 decisive 比赛更新 Elo。"],
  ["meta_review", "综合反馈", "Meta-review", "综合已有结果，整理证据缺口和下一步研究建议。"],
  ["finalize", "停止与汇总", "Finalization", "Supervisor 根据预算和收敛证据停止，完成 finalization。"],
];
export const labels = {
  completed:"已完成", completed_partial:"部分完成", running:"运行中", created:"已创建",
  stopping:"收尾中", needs_attention:"需要处理", paused:"已暂停", cancelled:"已取消",
  succeeded:"执行成功", failed:"失败", queued:"排队中", leased:"已领取", result_received:"结果已接收",
  pending:"等待领取", blocked:"受阻", failed_before_response:"响应前失败",
  raw_persist_failed:"原始响应保存失败", validation_failed:"响应校验失败",
  submission_failed:"结果提交失败", domain_apply_failed:"领域应用失败",
  pass:"建议通过", reject:"建议拒绝", needs_more_evidence:"需更多证据", not_assessed:"未评估",
  decisive:"胜负明确", inconclusive:"无定论", invalid:"无效", needs_tiebreaker:"需加赛",
  initial_review:"初审 / 安全", full_review:"完整评审", quality_converged:"达到配置的收敛条件",
  hard_budget_reached:"已达硬预算", review_requires_scientist_input:"评审需要研究者介入",
  meta_review_requires_scientist_input:"综合反馈需要研究者确认安全方向",
  provider_output_invalid:"供应商输出未通过校验", scientist_stop:"研究者停止",
  applied:"领域结果已应用", planned:"已计划", started:"调用中", raw_response_persisted:"原始响应已保存",
  validated:"已校验", agent_result_submitted:"AgentResult 已提交", passed:"通过",
  raw_persisted:"原始响应已保存", domain_result_applied:"领域结果已应用",
  abstract:"摘要", metadata:"题录", full_text:"全文", partially_novel:"部分新颖",
  generation:"生成假设", evolution:"演化改进", proximity:"相似度评估", ranking:"候选对比",
  meta_review:"综合反馈", literature_search:"文献检索", literature_summary:"获取文献记录",
  finalize_run:"停止与汇总",
};
export const label = value => labels[value] || value || "—";
export const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export const arr = value => Array.isArray(value) ? value : [];
export const fmt = value => Number(value || 0).toLocaleString("zh-CN");
export const callApplied = call => ["domain_result_applied", "applied"].includes(call.state);
export const short = (value, size=100) => String(value ?? "").length > size ? `${String(value).slice(0,size)}…` : String(value ?? "");
export function feedbackUsage(data,epochId) {
  const records=arr(data.events).filter(e=>e.event_type==="ResearchFeedbackRecorded"&&(!epochId||e.payload.epoch_id===epochId));
  const latest=records.at(-1),id=latest?.payload.feedback_id;
  const consumers=id?arr(data.tasks).filter(t=>t.payload?.inputs?.research_feedback?.feedback_id===id):[];
  return {latest,rounds:records.length,scheduled:consumers.length,
    completed:consumers.filter(t=>t.state==="succeeded").length,
    evolution:consumers.filter(t=>role(t)==="evolution")};
}
export function role(task) {
  if (task.intent_type?.startsWith("run_literature")) return "literature";
  if (task.intent_type === "finalize_run") return "finalize";
  return task.payload?.skill_id || task.intent_type?.replace(/^run_/, "") || "unknown";
}
// Display projection only: a retained task lease does not mean its failed call is active.
export function taskDisplayState(task, calls=[]) {
  if (["running","leased"].includes(task.state) && Number.isInteger(task.attempt) && task.attempt>0 &&
    calls.some(c=>c.attempt===task.attempt && c.task_id===task.task_id && c.state==="validation_failed")) return "validation_failed";
  return task.state;
}
export function stageState(tasks, calls=[]) {
  if (!tasks.length) return {text:"尚未调度", tone:"muted"};
  if (tasks.some(t=>taskDisplayState(t,calls)==="validation_failed")) return {text:"输出校验失败 · 待人工处理", tone:"reject"};
  if (tasks.some(t=>["failed","needs_attention"].includes(t.state))) return {text:"存在失败 / 待处理异常", tone:"reject"};
  if (tasks.some(t=>t.state === "blocked")) return {text:"存在受阻任务", tone:"warning"};
  if (tasks.some(t=>t.state === "result_received")) return {text:"结果已收取 · 等待领域应用", tone:"partial"};
  if (tasks.some(t=>["running","leased"].includes(t.state))) return {text:"任务执行中 · 请核对心跳", tone:"partial"};
  if (tasks.some(t=>!["succeeded","cancelled"].includes(t.state))) return {text:"有待处理任务", tone:"partial"};
  return {text: tasks.every(t=>t.state === "succeeded") ? "任务执行完成" : "已结束 / 含取消", tone:"pass"};
}
export function workerStatus(tasks, now=Date.now()) {
  const active=tasks.filter(t=>["leased","running","result_received"].includes(t.state));
  const fresh=active.filter(t=>t.worker_id && Date.parse(t.lease_expires_at)>now &&
    Date.parse(t.heartbeat_at)>now-120000 && Date.parse(t.heartbeat_at)<=now+5000);
  return {active:active.length,fresh:fresh.length, workers:[...new Set(fresh.map(t=>t.worker_id))],
    text:fresh.length?`最近 2 分钟有心跳 · ${fresh.length} 个有效租约任务`:
      active.length?"任务在途，但未观测到新鲜心跳；可能失联或租约过期":"暂无在途任务心跳；不能据此确认 Worker 在线"};
}
export function allowedControl(data, action) {
  return data?._source?.kind==="database" && data?._source?.controlAvailable===true && data?.manifest.execution_contract_version===3 &&
    ({pause:["running"],resume:["paused"],stop:["running","paused"]}[action]||[]).includes(data.manifest.final_state);
}
export function allowedOutputRetry(data) {
  return data?._source?.kind==="database" && data._source.outputRetryAvailable===true &&
    data.manifest?.final_state==="needs_attention" && data.manifest.execution_contract_version===3 &&
    data.output_retry?.eligible===true && typeof data.output_retry.external_call_id==="string" &&
    data.output_retry.expected_sequence===data.manifest.current_sequence;
}
export function costSummary(costs) {
  return arr(costs).reduce((a,c)=>({
    input:a.input+Number(c.input_tokens||0), output:a.output+Number(c.output_tokens||0),
    usd:a.usd+(c.pricing_version && c.pricing_version!=="unpriced" ? Number(c.cost_usd||0) : 0),
    unpriced:a.unpriced+(!c.pricing_version || c.pricing_version==="unpriced" ? 1 : 0),
  }),{input:0,output:0,usd:0,unpriced:0});
}
export function normalize(data) {
  if (!data.manifest || typeof data.manifest.run_id !== "string") throw new Error("缺少有效的 manifest.json / run_id");
  for (const name of ["hypotheses","hypothesis_projections","reviews","novelty_assessments","proximity",
    "matches","tasks","costs","convergence_checkpoints","stop_decisions","external_calls","events","tournament_epochs"])
    data[name] = arr(data[name]);
  data.events.sort((a,b)=>a.sequence-b.sequence);
  data.ratings ||= {};
  data.literature ||= {};
  return data;
}
export function admission(data, hypothesis, epoch) {
  return arr(data.manifest.admission_evidence).find(a=>a.hypothesis_id===hypothesis.hypothesis_id &&
    (!epoch || a.epoch_id===epoch) && (!a.evidence?.content_hash || a.evidence.content_hash===hypothesis.content_hash));
}
export function ranked(data, epoch) {
  const ids = new Set(data.hypotheses.map(h=>h.hypothesis_id));
  return Object.entries(data.ratings[epoch] || {}).filter(([id])=>ids.has(id)).sort((a,b)=>b[1]-a[1]);
}
export function parents(data, hypothesis) {
  return arr(hypothesis.parent_content_ids).map(id=>({id, hypothesis:data.hypotheses.find(h=>h.content_id===id)}));
}
export function parseFolder(entries) {
  const data = {};
  for (const [name, text] of entries) {
    if (name === "events.jsonl") data.events = text.split(/\r?\n/).filter(Boolean).map(JSON.parse);
    else if (/\.json$/.test(name)) data[name.slice(0,-5)] = JSON.parse(text);
  }
  return normalize(data);
}
