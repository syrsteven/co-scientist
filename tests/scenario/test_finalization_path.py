from datetime import UTC, datetime, timedelta

import pytest

from co_scientist.domain.review import ReviewPolicy
from co_scientist.runtime.checkpoints import ConvergenceCheckpointBuilder
from co_scientist.supervisor.orchestrator import Supervisor
from tests.unit.runtime.test_checkpoint_builder import _seed


def _checkpointed(tmp_path):
    uow, sequence = _seed(tmp_path)
    recorded = ConvergenceCheckpointBuilder(uow).build_and_record(
        run_id="run-1", expected_sequence=sequence
    )
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal")), recorded


def test_quality_stop_atomically_records_policy_and_one_finalization_task(tmp_path) -> None:
    supervisor, recorded = _checkpointed(tmp_path)

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
        scientist_action=None,
    )

    assert outcome.decision.reason == "quality_converged"
    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "StopPolicyTriggered",
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
    ]
    assert supervisor.uow.run_state("run-1") == "stopping"
    assert supervisor.uow.task_state("finalize:run-1") == "pending"


def test_soft_stop_is_bound_to_checkpoint_and_uses_resumable_finalization(tmp_path) -> None:
    supervisor, recorded = _checkpointed(tmp_path)

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
        scientist_action="soft_stop",
    )

    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events][:2] == [
        "StopSignalObserved",
        "StopPolicyTriggered",
    ]
    assert outcome.commit.events[0].payload["checkpoint_id"] == recorded.checkpoint_id


def test_hard_cancel_records_signal_and_terminal_transition_atomically(tmp_path) -> None:
    supervisor, recorded = _checkpointed(tmp_path)

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
        scientist_action="hard_cancel",
    )

    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "StopSignalObserved",
        "RunCancelled",
    ]
    assert supervisor.uow.run_state("run-1") == "cancelled"


def test_completed_vs_partial_is_derived_from_durable_unresolved_tasks(tmp_path) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    stopped = supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    claimed = supervisor.uow.claim_next_task(
        run_id="run-1",
        worker_id="finalizer",
        lease_token="finalization-lease",
        now=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
        lease_duration=timedelta(minutes=5),
    ).task
    assert claimed is not None
    fence = supervisor.uow.mark_task_running(fence=claimed)
    supervisor.uow.acknowledge_task(fence=fence, target_state="result_received")

    completed = supervisor.complete_finalization(
        run_id="run-1",
        expected_sequence=stopped.last_sequence + 2,
        lease_fence=fence,
    )

    assert completed.events[-1].event_type == "RunCompleted"
    assert completed.events[-1].payload["unresolved_task_ids"] == ()


def test_finalization_rejects_a_stale_or_unleased_fence(tmp_path) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    stopped = supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    from co_scientist.domain.task import TaskLeaseFence

    forged = TaskLeaseFence(
        run_id="run-1",
        task_id="finalize:run-1",
        lease_token="forged",
        attempt=1,
    )

    with pytest.raises(ValueError, match="stale task lease fence"):
        supervisor.complete_finalization(
            run_id="run-1",
            expected_sequence=stopped.last_sequence,
            lease_fence=forged,
        )
