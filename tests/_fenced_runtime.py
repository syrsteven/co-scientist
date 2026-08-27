"""Helpers for exercising the mandatory Task 5 worker fence in tests."""

from datetime import UTC, datetime, timedelta
from typing import Any

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import ClaimedTask, NewTask, lease_fence_fingerprint


def execution_manifest(**values: Any) -> dict[str, Any]:
    manifest = {"execution_contract_version": 3, "budget": {}}
    manifest.update(values)
    return manifest


def budgeted_task(task: NewTask) -> NewTask:
    payload = dict(task.payload)
    payload.setdefault(
        "budget_estimate",
        {
            "model_calls": 1,
            "input_tokens": 10,
            "output_tokens": 20,
            "cost_usd": "0.01",
            "hypotheses": 1,
            "matches": 1 if "rank" in task.intent_type else 0,
        },
    )
    return task.model_copy(update={"payload": payload})


def claim_running_task(
    uow: SqliteUnitOfWork,
    *,
    run_id: str,
    task_id: str,
) -> ClaimedTask:
    claimed = uow.claim_next_task(
        run_id=run_id,
        worker_id="test-worker",
        lease_token=f"lease:{task_id}",
        now=datetime.now(UTC),
        lease_duration=timedelta(minutes=5),
        allowed_intents=frozenset({uow.task_intent(task_id)}),
    ).task
    if claimed is None or claimed.task_id != task_id:
        raise AssertionError(f"expected to claim {task_id}")
    return uow.mark_task_running(fence=claimed)


def fenced_context(
    context: AgentExecutionContext | dict[str, Any],
    claimed: ClaimedTask,
) -> AgentExecutionContext:
    data = (
        context.model_dump(mode="json")
        if isinstance(context, AgentExecutionContext)
        else dict(context)
    )
    data.update(
        {
            "attempt": claimed.attempt,
            "reservation_id": claimed.reservation_id,
            "lease_fence_fingerprint": lease_fence_fingerprint(claimed),
        }
    )
    return AgentExecutionContext.model_validate(data)


def acknowledge_result(uow: SqliteUnitOfWork, claimed: ClaimedTask) -> None:
    uow.acknowledge_task(fence=claimed, target_state=TaskState.RESULT_RECEIVED)
