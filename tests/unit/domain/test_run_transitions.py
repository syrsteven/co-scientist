import pytest

from co_scientist.domain.states import RunState
from co_scientist.domain.transitions import InvalidTransition, transition_run


def test_running_cannot_complete_without_stopping() -> None:
    with pytest.raises(InvalidTransition):
        transition_run(RunState.RUNNING, RunState.COMPLETED)
    assert transition_run(RunState.RUNNING, RunState.STOPPING) is RunState.STOPPING
    assert transition_run(RunState.STOPPING, RunState.COMPLETED) is RunState.COMPLETED
