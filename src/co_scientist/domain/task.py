import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from co_scientist.domain.states import TaskState


class NewTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    run_id: str
    idempotency_key: str
    intent_type: str
    payload: dict
    created_by: Literal["supervisor"] = "supervisor"


class TaskMutation(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    target_state: TaskState

    @classmethod
    def succeed(cls, task_id: str) -> "TaskMutation":
        return cls(task_id=task_id, target_state=TaskState.SUCCEEDED)


class TaskLeaseFence(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    task_id: str
    lease_token: str
    attempt: int = Field(ge=1)


def lease_fence_fingerprint(fence: TaskLeaseFence) -> str:
    """Return non-reusable provenance for a task lease capability."""

    canonical = (
        f"{fence.run_id}\0{fence.task_id}\0{fence.attempt}\0{fence.lease_token}"
    ).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


class ClaimedTask(TaskLeaseFence):
    worker_id: str
    idempotency_key: str
    intent_type: str
    payload: Mapping[str, Any]
    reservation_id: str
    heartbeat_at: datetime
    lease_expires_at: datetime
    max_attempts: int = Field(ge=1)


class ClaimOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal[
        "claimed",
        "no_task",
        "paused",
        "stopping_no_finalization",
        "terminal",
        "budget_exhausted",
    ]
    task: ClaimedTask | None = None


class LeaseRecovery(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    expired_attempt: int
    action: Literal["requeued", "exhausted"]
