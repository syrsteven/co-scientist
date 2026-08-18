import inspect

import pytest

from co_scientist.domain.review import ReviewPolicy
from co_scientist.runtime.checkpoints import ConvergenceCheckpointBuilder
from co_scientist.supervisor.orchestrator import Supervisor
from tests.unit.runtime.test_checkpoint_builder import _seed


def test_tick_accepts_only_durable_checkpoint_identity_not_caller_truth(tmp_path) -> None:
    uow, sequence = _seed(tmp_path)
    recorded = ConvergenceCheckpointBuilder(uow).build_and_record(
        run_id="run-1", expected_sequence=sequence
    )
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
        scientist_action=None,
    )

    assert outcome.decision.reason == "quality_converged"
    assert [event.event_type for event in outcome.commit.events] == [
        "StopPolicyTriggered",
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
    ]
    parameters = inspect.signature(Supervisor.tick).parameters
    assert "convergence" not in parameters
    assert "budget" not in parameters
    assert "hard_budget_reached" not in parameters


def test_tick_rejects_stale_checkpoint_after_new_persisted_evidence(tmp_path) -> None:
    uow, sequence = _seed(tmp_path)
    recorded = ConvergenceCheckpointBuilder(uow).build_and_record(
        run_id="run-1", expected_sequence=sequence
    )
    uow.append_new(
        "run-1",
        recorded.commit.last_sequence,
        "OperatorNoteRecorded",
        {"note": "new evidence boundary"},
    )
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))

    with pytest.raises(ValueError, match="stale checkpoint"):
        supervisor.tick(
            run_id="run-1",
            expected_sequence=uow.load("run-1")[-1].sequence,
            checkpoint_id=recorded.checkpoint_id,
            scientist_action=None,
        )


def test_elo_plateau_alone_cannot_trigger_stop(tmp_path) -> None:
    uow, sequence = _seed(tmp_path)
    # The durable builder derives convergence; lowering no primary evidence is impossible
    # through tick arguments. A missing cluster source therefore fails closed before stop.
    with uow.session_factory.begin() as session:
        from co_scientist.adapters.persistence.sqlite import EventRow

        for current in (sequence - 3, sequence - 2):
            session.delete(session.get(EventRow, ("run-1", current)))

    with pytest.raises(ValueError, match="cluster"):
        ConvergenceCheckpointBuilder(uow).build_and_record(
            run_id="run-1", expected_sequence=sequence
        )
