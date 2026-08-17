"""Fail-closed policy for mutations against a durable Run lifecycle."""

from enum import StrEnum

from co_scientist.domain.states import RunState


class RunMutationKind(StrEnum):
    ENQUEUE_EXPLORATION_TASK = "enqueue_exploration_task"
    ENQUEUE_FINALIZATION_TASK = "enqueue_finalization_task"
    PLAN_EXPLORATION_CALL = "plan_exploration_call"
    PLAN_FINALIZATION_CALL = "plan_finalization_call"
    APPLY_SCIENTIFIC_RESULT = "apply_scientific_result"
    APPEND_SCIENTIFIC_EVENT = "append_scientific_event"
    RECORD_COST = "record_cost"


_TERMINAL_STATES = frozenset(
    {
        RunState.COMPLETED,
        RunState.COMPLETED_PARTIAL,
        RunState.FAILED,
        RunState.CANCELLED,
    }
)


def validate_run_mutation(
    state: RunState, kind: RunMutationKind, *, task_intent: str | None = None
) -> None:
    """Reject mutations not authorized by the current durable Run state."""

    state = RunState(state)
    kind = RunMutationKind(kind)
    if state in _TERMINAL_STATES:
        raise ValueError(f"run state {state.value} does not allow {kind.value}")

    finalization_kind = kind in {
        RunMutationKind.ENQUEUE_FINALIZATION_TASK,
        RunMutationKind.PLAN_FINALIZATION_CALL,
    }
    if finalization_kind and task_intent != "finalize_run":
        raise ValueError(f"run state {state.value} does not allow unauthorized finalization")

    allowed = False
    if state is RunState.RUNNING:
        allowed = kind is not RunMutationKind.PLAN_FINALIZATION_CALL
    elif state is RunState.STOPPING:
        allowed = kind in {
            RunMutationKind.ENQUEUE_FINALIZATION_TASK,
            RunMutationKind.PLAN_FINALIZATION_CALL,
        } or (
            task_intent is not None
            and kind
            in {
                RunMutationKind.APPLY_SCIENTIFIC_RESULT,
                RunMutationKind.APPEND_SCIENTIFIC_EVENT,
                RunMutationKind.RECORD_COST,
            }
        )
    if not allowed:
        raise ValueError(f"run state {state.value} does not allow {kind.value}")
