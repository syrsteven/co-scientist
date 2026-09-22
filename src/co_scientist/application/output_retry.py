"""Shared delivery boundary and advisory UI projection for explicit output retry."""

from typing import Any

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.commands import RetryInvalidOutput
from co_scientist.domain.budget import BudgetEstimate, BudgetPolicy, BudgetUsage
from co_scientist.ports.artifact_store import ArtifactStore
from co_scientist.supervisor.orchestrator import Supervisor


def submit_output_retry(
    supervisor: Supervisor, artifacts: ArtifactStore, command: RetryInvalidOutput,
) -> dict[str, Any]:
    if not command.confirmed:
        raise ValueError("explicit confirmation required: a new attempt may incur provider costs")
    call = supervisor.uow.get_external_call(command.external_call_id)
    if call.run_id != command.run_id or call.raw_artifact_ref is None:
        raise ValueError("retry requires this Run's persisted raw response")
    artifacts.read(call.raw_artifact_ref)
    result = supervisor.retry_invalid_output(
        run_id=command.run_id, external_call_id=command.external_call_id,
        expected_sequence=command.expected_run_sequence,
    )
    return {
        "run_id": command.run_id, "state": "running", "current_sequence": result.last_sequence,
        "task_id": call.task_id, "retry_of": call.external_call_id,
        "authorized_attempt": call.attempt + 1, "worker_started": False,
        "message": "Retry queued. No Worker started; an existing Worker may claim it. New calls may incur costs.",
    }


def output_retry_preview(data: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any] | None:
    """Read-only guidance, not an authorization; the command rechecks all invariants."""
    manifest = data["manifest"]
    if manifest["final_state"] != "needs_attention":
        return None
    attention: dict[str, Any] = next((e for e in reversed(data["events"]) if e["event_type"] == "RunNeedsAttention"), {})
    cause = attention.get("payload", {})
    if cause.get("reason") != "provider_output_invalid":
        return {"eligible": False, "reasons": ["这是科学评审或其他待处理问题，不能用输出重试绕过。"]}
    call = next((c for c in data["external_calls"] if c["external_call_id"] == cause.get("external_call_id")), None)
    task = next((t for t in data["tasks"] if t["task_id"] == cause.get("task_id")), None)
    if call is None or task is None:
        return {"eligible": False, "reasons": ["当前失败调用或任务记录缺失，请使用 CLI 检查。"]}
    reasons = []
    if manifest.get("execution_contract_version") != 3 or manifest.get("profile", {}).get("scientific_context") is not True:
        reasons.append("仅支持启用科研上下文的 v3 运行；旧配置不会自动升级。")
    if (call["state"] != "validation_failed" or task["state"] != "running"
            or call["attempt"] != task["attempt"] or not call["raw_artifact_ref"]
            or call["applied_domain_sequence"] is not None):
        reasons.append("调用不是当前尚未应用的响应校验失败。")
    if not any(c["external_call_id"] == call["external_call_id"] for c in data["costs"]):
        reasons.append("失败响应尚无成本记录，不能授权重试。")
    if task["attempt"] >= task["max_attempts"]:
        reasons.append("尝试次数已用尽（包含首次调用和网络恢复尝试）。")
    policy = BudgetPolicy.model_validate(budget["policy"])
    usage = BudgetUsage.model_validate(budget["usage"])
    estimate = BudgetEstimate.model_validate(task["payload"]["budget_estimate"])
    additional = SqliteUnitOfWork._retry_provider_estimate(estimate)
    if policy.max_model_calls is None:
        reasons.append("需要设置有限调用预算；不能在此修改冻结配置。")
    elif not SqliteUnitOfWork._fits_retry_budget(policy, usage, additional):
        reasons.append("剩余预算不足或已达上限；不会自动扩容。")
    return {
        "eligible": not reasons, "reasons": reasons, "external_call_id": call["external_call_id"],
        "task_id": task["task_id"], "skill_id": task["payload"]["skill_id"],
        "provider": call["provider"], "model": call["model_or_tool"],
        "attempt": task["attempt"], "max_attempts": task["max_attempts"],
        "raw_artifact_ref": call["raw_artifact_ref"], "expected_sequence": manifest["current_sequence"],
        "budget": {**budget, "additional_estimate": additional.model_dump(mode="json")},
    }
