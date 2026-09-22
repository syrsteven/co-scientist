import {escape as e} from "./model.js";

export function createScientistFeedback({getRun,getId,notify,refresh}) {
  const dialog=document.createElement("dialog");
  dialog.className="retry-dialog scientist-dialog";document.body.append(dialog);
  let busy=false,target=null,receipt=null;
  function blocker() {
    const d=getRun();
    if(d?.manifest?.final_state!=="needs_attention")return null;
    const event=[...(d.events||[])].reverse().find(x=>x.event_type==="RunNeedsAttention");
    return event?.payload.reason==="meta_review_requires_scientist_input"?event.payload:null;
  }
  function panel() {
    const d=getRun(),b=blocker();
    if(!b)return receipt?.id===getId()?`<p class="notice">${e(receipt.message)} · ${e(receipt.scientist_feedback_id)}</p>`:"";
    const remaining=Math.max(0,(d.manifest.profile?.meta_review?.max_rounds||0)-(d.tasks||[]).filter(t=>t.intent_type==="run_meta_review"&&t.payload?.inputs?.meta_review_round).length);
    const available=d._source?.scientistFeedbackAvailable&&remaining>0;
    return `<section class="notice"><h3>提交研究者意见</h3><p>针对当前反馈提交依据或异议，申请一次独立复评。原判定保留；复评仍可能暂停，也可能继续后续运行。</p><p class="muted">剩余Meta-review轮次：${remaining}，提交时还会核对调用预算。不会自动启动Worker；存活Worker可能继续执行并产生费用。署名由提交者填写，未经身份认证。</p><button class="quiet-button" data-scientist-open ${available&&!busy?"":"disabled"}>填写意见并核对…</button>${remaining===0?"<p>现有评审轮次已用尽，请创建新配置继续研究。</p>":!available?"<p>导出快照不支持提交；旧服务需重启。</p>":""}</section>`;
  }
  function open() {
    const d=getRun(),b=blocker();if(busy||!b||!d._source?.scientistFeedbackAvailable)return;
    target={id:getId(),sequence:d.manifest.current_sequence,feedback:b.feedback_id};
    dialog.innerHTML=`<h2>研究者意见与独立复评</h2><p>${e(d.manifest.run_id)} · SEQ ${e(target.sequence)}</p><p class="mono">${e(target.feedback)}</p>
      <label>研究者署名 <input id="scientistActor" maxlength="200" autocomplete="off"></label>
      <label>意见与依据 <textarea id="scientistNote" rows="8" maxlength="12000" placeholder="指出具体疑问、对应评审或来源，以及支持或反对的理由。意见不会自动成为已验证证据。"></textarea></label>
      <label><input type="checkbox" id="scientistConfirm">我接受复评及恢复后续运行可能产生费用；这不会直接改判。</label>
      <p id="scientistError" role="alert"></p><div class="card-actions"><button data-scientist-cancel>取消</button><button id="scientistSubmit" disabled>记录意见并排队复评</button></div>`;
    const valid=()=>{dialog.querySelector("#scientistSubmit").disabled=!(dialog.querySelector("#scientistActor").value.trim()&&dialog.querySelector("#scientistNote").value.trim()&&dialog.querySelector("#scientistConfirm").checked);};
    dialog.querySelectorAll("input,textarea").forEach(x=>x.addEventListener("input",valid));
    dialog.querySelector("[data-scientist-cancel]").onclick=()=>dialog.close();
    dialog.querySelector("#scientistSubmit").onclick=submit;
    dialog.showModal();dialog.querySelector("#scientistActor").focus();
  }
  async function submit() {
    if(busy||!target||!dialog.querySelector("#scientistConfirm").checked)return;
    const d=getRun(),b=blocker(),t={...target};
    if(getId()!==t.id||d.manifest.current_sequence!==t.sequence||b?.feedback_id!==t.feedback){dialog.querySelector("#scientistError").textContent="状态已变化，请关闭并刷新后重新核对。";return;}
    const payload={feedback_id:t.feedback,expected_run_sequence:t.sequence,actor:dialog.querySelector("#scientistActor").value,note:dialog.querySelector("#scientistNote").value,confirmed:true};
    busy=true;dialog.querySelectorAll("button,input,textarea").forEach(x=>x.disabled=true);
    try {
      const response=await fetch(`/api/runs/${encodeURIComponent(t.id)}/scientist-feedback`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
      const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||`HTTP ${response.status}`);
      receipt={id:t.id,...result};dialog.close();notify(result.message);await refresh(t.id);
    } catch(error){dialog.querySelector("#scientistError").textContent=`${error.message} 请关闭并刷新核对事件；不会自动重试。`;dialog.querySelector("[data-scientist-cancel]").disabled=false;}
    finally{busy=false;}
  }
  document.addEventListener("click",event=>{if(event.target.closest("[data-scientist-open]"))open();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  return {panel,isOpen:()=>dialog.open};
}
