from pathlib import Path

from sqlalchemy import select

from co_scientist.adapters.persistence.sqlite import TaskRow
from co_scientist.domain.task import NewTask
from co_scientist.export.run_export import (
    SqliteRunReadModel,
    verify_core_release_invariants,
)
from tests.smoke.test_lens_replay_smoke import LensReplayHarness


class ReleaseHarness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lens = LensReplayHarness(root)
        self.run_id = self.lens.start_lens(provider="replay", data_dir=root)

    def verify(self):
        assert self.lens.run is not None
        return verify_core_release_invariants(
            self.run_id,
            SqliteRunReadModel(self.lens.run.uow),
        )


# Mutations caught: defaulting a report to zero instead of scanning persisted
# task provenance, epoch contracts, match/rating projections, call state, and finalization events.
def test_core_release_invariants(tmp_path: Path) -> None:
    report = ReleaseHarness(tmp_path).verify()

    assert report.persisted_task_count > 0
    assert report.external_call_count > 0
    assert report.match_count == 6
    assert report.agent_created_task_count == 0
    assert report.cross_epoch_elo_comparison_count == 0
    assert report.non_decisive_rating_update_count == 0
    assert report.proximity_derived_novelty_count == 0
    assert report.run_completed_without_finalization_count == 0
    assert report.raw_parsed_before_persist_count == 0


# Mutation caught: treating an unexplained persisted task as Supervisor-authored.
def test_release_report_detects_a_task_without_supervisor_provenance(tmp_path: Path) -> None:
    harness = ReleaseHarness(tmp_path)
    assert harness.lens.run is not None
    uow = harness.lens.run.uow
    uow.enqueue_tasks(
        (
            NewTask(
                task_id="unproven-agent-task",
                run_id=harness.run_id,
                idempotency_key="unproven-agent-task",
                intent_type="run_generation",
                payload={},
            ),
        )
    )

    report = verify_core_release_invariants(
        harness.run_id,
        SqliteRunReadModel(uow),
    )

    assert report.agent_created_task_count == 1
    with uow.session_factory() as session:
        assert session.scalar(
            select(TaskRow.task_id).where(TaskRow.task_id == "unproven-agent-task")
        ) == "unproven-agent-task"
