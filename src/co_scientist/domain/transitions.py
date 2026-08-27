from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from typing import TypeVar

from co_scientist.domain.states import ExternalCallState, RunState, TaskState


class InvalidTransition(ValueError):
    pass


StateT = TypeVar("StateT")


def _transition(
    current: StateT,
    target: StateT,
    allowed: Mapping[StateT, AbstractSet[StateT]],
) -> StateT:
    if target not in allowed[current]:
        raise InvalidTransition(f"{current} -> {target}")
    return target


RUN_TRANSITIONS = {
    RunState.CREATED: {RunState.RUNNING, RunState.CANCELLED},
    RunState.RUNNING: {
        RunState.PAUSING,
        RunState.NEEDS_ATTENTION,
        RunState.STOPPING,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.PAUSING: {RunState.PAUSED, RunState.CANCELLED},
    RunState.PAUSED: {RunState.RUNNING, RunState.STOPPING, RunState.CANCELLED},
    RunState.NEEDS_ATTENTION: {RunState.RUNNING, RunState.FAILED, RunState.CANCELLED},
    RunState.STOPPING: {RunState.COMPLETED, RunState.COMPLETED_PARTIAL},
    RunState.COMPLETED: set(),
    RunState.COMPLETED_PARTIAL: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}

TASK_TRANSITIONS = {
    TaskState.PENDING: {
        TaskState.LEASED,
        TaskState.BLOCKED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.LEASED: {TaskState.RUNNING, TaskState.PENDING, TaskState.CANCELLED},
    TaskState.RUNNING: {
        TaskState.RESULT_RECEIVED,
        TaskState.PENDING,
        TaskState.NEEDS_ATTENTION,
        TaskState.FAILED,
    },
    TaskState.RESULT_RECEIVED: {TaskState.SUCCEEDED, TaskState.PENDING, TaskState.FAILED},
    TaskState.BLOCKED: {TaskState.PENDING, TaskState.CANCELLED},
    TaskState.NEEDS_ATTENTION: {TaskState.PENDING, TaskState.CANCELLED},
    TaskState.SUCCEEDED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}

EXTERNAL_CALL_TRANSITIONS = {
    ExternalCallState.PLANNED: {
        ExternalCallState.STARTED,
        ExternalCallState.FAILED_BEFORE_RESPONSE,
    },
    ExternalCallState.STARTED: {
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        ExternalCallState.FAILED_BEFORE_RESPONSE,
        ExternalCallState.RAW_PERSIST_FAILED,
    },
    ExternalCallState.RAW_RESPONSE_PERSISTED: {
        ExternalCallState.VALIDATED,
        ExternalCallState.VALIDATION_FAILED,
    },
    ExternalCallState.VALIDATED: {
        ExternalCallState.AGENT_RESULT_SUBMITTED,
        ExternalCallState.SUBMISSION_FAILED,
    },
    ExternalCallState.AGENT_RESULT_SUBMITTED: {
        ExternalCallState.DOMAIN_RESULT_APPLIED,
        ExternalCallState.DOMAIN_APPLY_FAILED,
    },
    ExternalCallState.DOMAIN_RESULT_APPLIED: set(),
    ExternalCallState.FAILED_BEFORE_RESPONSE: set(),
    ExternalCallState.RAW_PERSIST_FAILED: set(),
    ExternalCallState.VALIDATION_FAILED: set(),
    ExternalCallState.SUBMISSION_FAILED: set(),
    ExternalCallState.DOMAIN_APPLY_FAILED: set(),
}


def transition_run(current: RunState, target: RunState) -> RunState:
    return _transition(current, target, RUN_TRANSITIONS)


def transition_task(current: TaskState, target: TaskState) -> TaskState:
    return _transition(current, target, TASK_TRANSITIONS)


def transition_external_call(
    current: ExternalCallState, target: ExternalCallState
) -> ExternalCallState:
    return _transition(current, target, EXTERNAL_CALL_TRANSITIONS)
