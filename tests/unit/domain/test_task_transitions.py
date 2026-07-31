import pytest

from co_scientist.domain.states import TaskState
from co_scientist.domain.transitions import InvalidTransition, transition_task


def test_expired_lease_returns_to_pending_but_success_is_terminal() -> None:
    assert transition_task(TaskState.LEASED, TaskState.PENDING) is TaskState.PENDING
    with pytest.raises(InvalidTransition):
        transition_task(TaskState.SUCCEEDED, TaskState.PENDING)
