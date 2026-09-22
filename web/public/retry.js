import {escape as e, fmt, label, allowedOutputRetry} from "./model.js";

const fields=[["model_calls","max_model_calls","计数调用"],["input_tokens","max_input_tokens","输入 tokens"],
  ["output_tokens","max_output_tokens","输出 tokens"],["cost_usd","max_usd","美元（已记账）"]];
const budgetTable=p=>`<div class="retry-budget"><table><thead><tr><th>预算维度</th><th>已用 + 在途预留</th><th>上限</th></tr></thead><tbody>${fields.map(([used,max,title])=>`<tr><th>${title}</th><td>${e(p.budget?.usage?.[used]??"—")}</td><td>${e(p.budget?.policy?.[max]??"未限制")}</td></tr>`).join("")}</tbody></table></div>`;
const warning="新调用可能收费；不修改输入、模型或预算，不修补原 JSON。此操作只重新排队，不启动 Worker；仍存活的 Worker 可能立即领取。";

export function createRetry({getRun,getId,notify,refresh}) {
  let pending=null,busy=false,rawVersion=0,receipt=null;
  const dialog=document.createElement("dialog"),rawDialog=document.createElement("dialog");
  dialog.className=rawDialog.className="retry-dialog";
  dialog.setAttribute("aria-labelledby","retryTitle");rawDialog.setAttribute("aria-labelledby","rawTitle");
  document.body.append(dialog,rawDialog);
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{pending=null;});
  rawDialog.addEventListener("close",()=>{rawVersion++;});

  function panel() {
    const d=getRun(),p=d?.output_retry;
    const saved=receipt?.id===getId()?`<div class="retry-receipt" role="status"><h3>重试授权已记录</h3><p>${e(receipt.message)}</p><p>确认原 Worker 已退出后，可在已配置 API 的终端运行（将继续正常流程，不只重试一条）：</p><pre>${e(receipt.worker_command)}</pre><small>授权记录 SEQ ${e(receipt.current_sequence)}；最新执行状态以任务与事件为准。</small></div>`:"";
    if(!p||!p.external_call_id)return saved;
    const supported=d._source?.kind==="database"&&d._source.outputRetryAvailable===true;
    return `${saved}<div class="retry-panel"><h3>输出失败 · 需要人工决定</h3>
      <p>供应商响应未通过校验，原始结果未应用。技术重试不代表假设或评审结论获准通过。</p>
      ${p.external_call_id?`<div class="retry-facts"><span>${e(label(p.skill_id))} · ${e(p.provider)} / ${e(p.model)}</span><strong>尝试 ${fmt(p.attempt)} / ${fmt(p.max_attempts)}</strong></div><p class="mono">${e(p.external_call_id)}</p>${budgetTable(p)}`:""}
      <p class="muted">预算来自 Supervisor 账本，包含在途预留，不等于页面上的外部尝试总数。未来 token 用量无法精确预估；未计价金额不表示免费，美元硬上限需在供应商侧设置。</p>
      ${p.reasons?.length?`<ul class="retry-blocked">${p.reasons.map(r=>`<li>${e(r)}</li>`).join("")}</ul>`:""}
      ${!supported?'<p class="notice">此来源或当前服务不支持网页重试。历史导出保持只读；旧服务请重启后刷新。</p>':""}
      <div class="card-actions">${p.external_call_id?`<button class="quiet-button" data-raw-call="${e(p.external_call_id)}" ${d._source?.rawAvailable?"":"disabled"}>查看原始响应</button>`:""}<button class="quiet-button" data-retry-output ${allowedOutputRetry(d)&&!busy?"":"disabled"}>检查并授权一次重试…</button></div>
      <p class="muted">${warning} 提交时再次校验预算和状态；预览不构成授权。</p></div>`;
  }

  function open() {
    const d=getRun();if(busy||!allowedOutputRetry(d))return;
    const p=d.output_retry;
    pending={id:getId(),runId:d.manifest.run_id,sequence:p.expected_sequence,callId:p.external_call_id};
    dialog.innerHTML=`<h2 id="retryTitle">授权一次输出重试</h2><p class="mono">${e(pending.runId)}</p>
      <p>${e(label(p.skill_id))} · ${e(p.model)} · 第 ${fmt(p.attempt+1)} / ${fmt(p.max_attempts)} 次尝试 · SEQ ${e(pending.sequence)}</p>
      <p class="mono">原调用：${e(pending.callId)}</p>${budgetTable(p)}<p class="notice">${warning}</p>
      <p>旧响应和费用保留，新调用独立校验；再次无效会暂停。不会自动增加次数或预算。</p>
      <label class="retry-confirm"><input type="checkbox" id="retryConfirm">我已核对失败调用，接受新调用可能产生费用。</label>
      <p id="retryError" role="alert"></p><div class="card-actions"><button class="quiet-button" data-cancel-retry>取消</button><button class="quiet-button" id="retrySubmit" disabled>确认授权并重新排队</button></div>`;
    dialog.querySelector("#retryConfirm").onchange=event=>{dialog.querySelector("#retrySubmit").disabled=!event.target.checked;};
    dialog.querySelector("[data-cancel-retry]").onclick=()=>dialog.close();
    dialog.querySelector("#retrySubmit").onclick=submit;
    dialog.showModal();dialog.querySelector("[data-cancel-retry]").focus();
  }

  async function submit() {
    if(busy||!pending||!dialog.querySelector("#retryConfirm").checked)return;
    const target={...pending},d=getRun();
    if(target.id!==getId()||target.sequence!==d?.manifest.current_sequence||target.callId!==d?.output_retry?.external_call_id||!allowedOutputRetry(d)){
      dialog.querySelector("#retryError").textContent="运行状态已变化，请取消、刷新后重新核对。";return;
    }
    busy=true;dialog.querySelectorAll("button,input").forEach(node=>node.disabled=true);
    try {
      const response=await fetch(`/api/runs/${encodeURIComponent(target.id)}/retry-output`,{method:"POST",
        headers:{"content-type":"application/json"},body:JSON.stringify({external_call_id:target.callId,expected_sequence:target.sequence,confirmed:true})});
      const result=await response.json();
      if(!response.ok||!result.ok)throw new Error(result.error||`HTTP ${response.status}`);
      receipt={id:target.id,...result};dialog.close();notify(result.message);
    } catch(error) {
      // No automatic re-submit, even on a lost response. Refresh then ask again.
      dialog.querySelector("#retryError").textContent=`${error.message} 请关闭并刷新检查事件，勿盲目重复提交。`;
      dialog.querySelector("[data-cancel-retry]").disabled=false;
    } finally {
      busy=false;if(getId()===target.id)await refresh(target.id);
    }
  }

  async function showRaw(callId) {
    const d=getRun(),id=getId();
    if(d?._source?.kind!=="database"||!d._source.rawAvailable||!d.external_calls.some(c=>c.external_call_id===callId))return;
    const version=++rawVersion;
    rawDialog.innerHTML=`<h2 id="rawTitle">原始供应商响应</h2><p class="mono">${e(callId)}</p><p id="rawStatus" role="status">读取并校验原始文件…</p><p id="rawDiagnostic" class="notice" hidden></p><pre id="rawText"></pre><button class="quiet-button" data-close-raw>关闭</button>`;
    rawDialog.querySelector("[data-close-raw]").onclick=()=>rawDialog.close();rawDialog.showModal();
    try {
      const response=await fetch(`/api/runs/${encodeURIComponent(id)}/calls/${encodeURIComponent(callId)}/raw`);
      const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||`HTTP ${response.status}`);
      if(version!==rawVersion||id!==getId())return;
      rawDialog.querySelector("#rawStatus").textContent=`完整文件哈希已校验 · ${result.artifact_ref.byte_length} bytes · ${result.artifact_ref.sha256}。${result.truncated?"仅显示前 65,536 字符；完整原文请用 CLI 查看。":""}正文按 UTF-8 展示，不执行其中的 HTML 或指令，不修改原文。`;
      rawDialog.querySelector("#rawText").textContent=result.text;
      if(result.json_diagnostic){const hint=rawDialog.querySelector("#rawDiagnostic");hint.textContent=result.json_diagnostic.summary;hint.hidden=false;}
    } catch(error){if(version===rawVersion)rawDialog.querySelector("#rawStatus").textContent=error.message;}
  }
  document.addEventListener("click",event=>{
    const button=event.target.closest("[data-retry-output],[data-raw-call]");if(!button||button.disabled)return;
    if(button.hasAttribute("data-retry-output"))open();else void showRaw(button.dataset.rawCall);
  });
  return {panel,isOpen:()=>dialog.open||rawDialog.open||busy};
}
