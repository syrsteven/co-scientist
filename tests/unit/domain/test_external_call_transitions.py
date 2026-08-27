import pytest

from co_scientist.domain.states import ExternalCallState
from co_scientist.domain.transitions import InvalidTransition, transition_external_call


def test_raw_response_must_precede_validation() -> None:
    with pytest.raises(InvalidTransition):
        transition_external_call(ExternalCallState.STARTED, ExternalCallState.VALIDATED)
    state = ExternalCallState.PLANNED
    for target in (
        ExternalCallState.STARTED,
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        ExternalCallState.VALIDATED,
        ExternalCallState.AGENT_RESULT_SUBMITTED,
        ExternalCallState.DOMAIN_RESULT_APPLIED,
    ):
        state = transition_external_call(state, target)
    assert state is ExternalCallState.DOMAIN_RESULT_APPLIED
