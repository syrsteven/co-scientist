from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from co_scientist.adapters.persistence.sqlite import TaskRow
from co_scientist.domain.review import ReviewPolicy
from co_scientist.events.models import NewEvent
from co_scientist.runtime.checkpoints import ConvergenceCheckpointBuilder
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.worker import Worker
from co_scientist.supervisor.orchestrator import Supervisor
from tests.unit.runtime.test_checkpoint_builder import _seed


def _checkpointed(tmp_path):
    uow, sequence = _seed(tmp_path)
    recorded = ConvergenceCheckpointBuilder(uow).build_and_record(
        run_id="run-1", expected_sequence=sequence
    )
    return (
        Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal")),
        recorded,
    )


@pytest.mark.parametrize(
    "prefix",
    [
        (),
        ("StopSignalObserved",),
        ("StopSignalObserved", "StopPolicyTriggered"),
        ("StopSignalObserved", "StopPolicyTriggered", "RunStopping"),
        (
            "StopSignalObserved",
            "StopPolicyTriggered",
            "RunStopping",
            "FinalizationRequested",
        ),
        ("StopPolicyTriggered",),
        ("StopPolicyTriggered", "RunStopping"),
        ("StopPolicyTriggered", "RunStopping", "FinalizationRequested"),
    ],
)
def test_ensure_finalization_repairs_every_durable_stop_prefix_once(tmp_path, prefix) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    sequence = recorded.commit.last_sequence
    if prefix:
        events = []
        for event_type in prefix:
            payload = {"checkpoint_id": recorded.checkpoint_id}
            if event_type == "StopSignalObserved":
                payload["action"] = "soft_stop"
            elif event_type == "RunStopping":
                payload["reason"] = "quality_converged"
            elif event_type == "FinalizationRequested":
                payload["task_id"] = "finalize:run-1"
            events.append(NewEvent(event_type=event_type, payload=payload))
        target = "stopping" if "RunStopping" in prefix else None
        committed = supervisor.uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=sequence,
            events=tuple(events),
            target_run_state=target,
            idempotency_key=f"crash-prefix:{len(prefix)}",
        )
        sequence = committed.last_sequence

    ensured = supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    replayed = supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=ensured.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )

    with supervisor.uow.session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(TaskRow).where(
                TaskRow.run_id == "run-1", TaskRow.intent_type == "finalize_run"
            )
        )
    assert count == 1
    assert replayed.last_sequence == ensured.last_sequence
    assert supervisor.uow.run_state("run-1") == "stopping"


@pytest.mark.parametrize("crash_state", ["leased", "running", "result_received"])
def test_ensure_finalization_validates_checkpoint_after_finalization_task_progress(
    tmp_path, crash_state: str
) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    claimed = supervisor.uow.claim_next_task(
        run_id="run-1",
        worker_id="finalizer",
        lease_token="crashed-finalization-lease",
        now=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
        lease_duration=timedelta(minutes=5),
    ).task
    assert claimed is not None
    if crash_state != "leased":
        claimed = supervisor.uow.mark_task_running(fence=claimed)
    if crash_state == "result_received":
        supervisor.uow.acknowledge_task(fence=claimed, target_state="result_received")
    sequence = supervisor.uow.load("run-1")[-1].sequence

    supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=sequence,
        checkpoint_id=recorded.checkpoint_id,
    )

    with supervisor.uow.session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(TaskRow).where(
                TaskRow.run_id == "run-1", TaskRow.intent_type == "finalize_run"
            )
        )
    assert count == 1


def test_complete_finalization_uses_lease_fence_and_derives_partial_from_unresolved_work(
    tmp_path,
) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    stopped = supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    outcome = supervisor.uow.claim_next_task(
        run_id="run-1",
        worker_id="finalizer",
        lease_token="finalization-lease",
        now=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
        lease_duration=timedelta(minutes=5),
    )
    assert outcome.task is not None
    fence = supervisor.uow.mark_task_running(fence=outcome.task)
    supervisor.uow.acknowledge_task(fence=fence, target_state="result_received")

    completed = supervisor.complete_finalization(
        run_id="run-1",
        expected_sequence=stopped.last_sequence + 2,
        lease_fence=fence,
    )

    assert completed.events[-1].event_type == "RunCompleted"
    assert supervisor.uow.run_state("run-1") == "completed"
    assert supervisor.uow.task_state("finalize:run-1") == "succeeded"


def test_terminal_run_rejects_fenced_lease_and_reservation_mutations(tmp_path) -> None:
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
    supervisor.complete_finalization(
        run_id="run-1", expected_sequence=stopped.last_sequence + 2, lease_fence=fence
    )

    with pytest.raises(ValueError, match="completed"):
        supervisor.uow.heartbeat_task(
            fence=fence,
            now=datetime(2026, 8, 18, 10, 1, tzinfo=UTC),
            lease_duration=timedelta(minutes=5),
        )


@pytest.mark.asyncio
async def test_worker_executes_finalization_as_a_normal_fenced_local_task(tmp_path) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    worker = Worker(
        runtime=SimpleNamespace(uow=supervisor.uow, artifacts=None),
        task_runtime=supervisor.uow,
        supervisor=supervisor,
        skills=SkillRegistry({}),
        providers=ProviderRegistry({}),
        worker_id="finalizer",
        clock=lambda: datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
        token_factory=lambda: "worker-finalization-lease",
    )

    step = await worker.run_once("run-1")

    assert step.status == "completed"
    assert supervisor.uow.run_state("run-1") == "completed"
    assert supervisor.uow.task_state("finalize:run-1") == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_state", ["running", "result_received"])
async def test_worker_restart_adopts_fenced_finalization_after_claim_or_result(
    tmp_path, crash_state: str
) -> None:
    supervisor, recorded = _checkpointed(tmp_path)
    supervisor.ensure_finalization(
        run_id="run-1",
        expected_sequence=recorded.commit.last_sequence,
        checkpoint_id=recorded.checkpoint_id,
    )
    claimed = supervisor.uow.claim_next_task(
        run_id="run-1",
        worker_id="finalizer",
        lease_token="crashed-finalization-lease",
        now=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
        lease_duration=timedelta(minutes=5),
    ).task
    assert claimed is not None
    claimed = supervisor.uow.mark_task_running(fence=claimed)
    if crash_state == "result_received":
        supervisor.uow.acknowledge_task(fence=claimed, target_state="result_received")
    worker = Worker(
        runtime=SimpleNamespace(uow=supervisor.uow, artifacts=None),
        task_runtime=supervisor.uow,
        supervisor=supervisor,
        skills=SkillRegistry({}),
        providers=ProviderRegistry({}),
        worker_id="finalizer",
        clock=lambda: datetime(2026, 8, 18, 10, 1, tzinfo=UTC),
        token_factory=lambda: "adopted-finalization-lease",
    )

    step = await worker.run_once("run-1")

    assert step.status == "completed"
    assert supervisor.uow.run_state("run-1") == "completed"
