import pytest

from co_scientist.domain.states import TaskState
from co_scientist.domain.transitions import InvalidTransition, transition_task


def test_expired_lease_returns_to_pending_but_success_is_terminal() -> None:
    assert transition_task(TaskState.LEASED, TaskState.PENDING) is TaskState.PENDING
    with pytest.raises(InvalidTransition):
        transition_task(TaskState.SUCCEEDED, TaskState.PENDING)


# Mutation caught: omitting the terminal failure path for a durably received failed result.
def test_received_result_can_finish_as_failed() -> None:
    assert transition_task(TaskState.RESULT_RECEIVED, TaskState.FAILED) is TaskState.FAILED
