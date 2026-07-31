from typing import Literal

from pydantic import BaseModel, ConfigDict

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
