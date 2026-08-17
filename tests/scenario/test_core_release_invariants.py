from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from co_scientist.adapters.persistence.sqlite import EventRow, ExternalCallRow, RunRow, TaskRow
from co_scientist.domain.task import NewTask
from co_scientist.events.models import NewEvent
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
    with pytest.raises(ValueError, match="completed"):
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

    assert report.agent_created_task_count == 0
    with uow.session_factory() as session:
        assert session.scalar(
            select(TaskRow.task_id).where(TaskRow.task_id == "unproven-agent-task")
        ) is None


# Mutation caught: trusting an epoch ID/contract without proving both entries belong to it.
def test_release_report_detects_cross_epoch_match(tmp_path: Path) -> None:
    harness = ReleaseHarness(tmp_path)
    assert harness.lens.run is not None
    uow = harness.lens.run.uow
    sequence = uow.load(harness.run_id)[-1].sequence
    with pytest.raises(ValueError, match="completed"):
        uow.commit_domain_batch(
            run_id=harness.run_id,
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="MatchEvaluated",
                    schema_version=2,
                    payload={
                        "match_id": "cross-epoch-match",
                        "epoch_id": "epoch-not-opened",
                        "left_id": "h-1",
                        "right_id": "h-2",
                        "decision": "inconclusive",
                        "winner_id": None,
                        "research_plan_version": 1,
                        "evaluation_rules_hash": "sha256:lens-rules-v1",
                        "ranking_prompt_hash": "wrong-epoch",
                        "judge_profile_hash": "sha256:replay-judge-v1",
                        "rating_policy_version": "elo-32-v1",
                        "admission_policy_version": "core-preview-v1",
                    },
                ),
            ),
            idempotency_key="inject-cross-epoch-match",
        )

    assert harness.verify().cross_epoch_elo_comparison_count == 0


# Mutation caught: applying Elo to an inconclusive decision.
def test_release_report_detects_non_decisive_rating_update(tmp_path: Path) -> None:
    harness = ReleaseHarness(tmp_path)
    assert harness.lens.run is not None
    uow = harness.lens.run.uow
    sequence = uow.load(harness.run_id)[-1].sequence
    with pytest.raises(ValueError, match="completed"):
        uow.commit_domain_batch(
            run_id=harness.run_id,
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="RatingUpdated",
                    payload={
                        "match_id": "match-3",
                        "epoch_id": "epoch-1",
                        "hypothesis_id": "h-1",
                        "before_rating": 1200.0,
                        "rating": 1201.0,
                        "rating_policy_version": "elo-32-v1",
                    },
                ),
            ),
            idempotency_key="inject-non-decisive-rating",
        )

    assert harness.verify().non_decisive_rating_update_count == 0


# Mutation caught: treating candidate-space proximity as literature novelty evidence.
def test_release_report_detects_proximity_derived_novelty(tmp_path: Path) -> None:
    harness = ReleaseHarness(tmp_path)
    assert harness.lens.run is not None
    uow = harness.lens.run.uow
    events = uow.load(harness.run_id)
    proximity = next(event for event in events if event.event_type == "ProximityAssessed")
    with pytest.raises(ValueError, match="completed"):
        uow.commit_domain_batch(
            run_id=harness.run_id,
            expected_sequence=events[-1].sequence,
            events=(
                NewEvent(
                    event_type="NoveltyAssessmentRecorded",
                    payload={"source_result_id": proximity.payload["source_result_id"]},
                ),
            ),
            idempotency_key="inject-proximity-novelty",
        )

    assert harness.verify().proximity_derived_novelty_count == 0


# Mutation caught: allowing terminal completion without a prior finalization event.
def test_release_report_detects_completion_without_finalization(tmp_path: Path) -> None:
    harness = ReleaseHarness(tmp_path)
    assert harness.lens.run is not None
    uow = harness.lens.run.uow
    uow.create_run("unfinalized-run", manifest={})
    # Simulate corruption below the public transaction boundary. Public UoW APIs
    # reject this lifecycle divergence; the release verifier must still diagnose
    # a pre-existing/corrupt database.
    with uow.session_factory.begin() as session:
        run = session.get(RunRow, "unfinalized-run")
        assert run is not None
        session.add(
            EventRow(
                run_id="unfinalized-run",
                sequence=1,
                event_type="RunCompleted",
                schema_version=1,
                payload_json="{}",
                occurred_at=datetime.now(UTC),
                causation_id=None,
                correlation_id=None,
            )
        )
        run.current_sequence = 1

    report = verify_core_release_invariants(
        "unfinalized-run",
        SqliteRunReadModel(uow),
    )

    assert report.run_completed_without_finalization_count == 1


# Mutation caught: retaining parsed/applied call state after losing the raw reference.
def test_release_report_detects_parsed_call_without_raw_artifact(tmp_path: Path) -> None:
    harness = ReleaseHarness(tmp_path)
    assert harness.lens.run is not None
    uow = harness.lens.run.uow
    with uow.session_factory.begin() as session:
        call = session.scalar(
            select(ExternalCallRow).where(ExternalCallRow.run_id == harness.run_id)
        )
        assert call is not None
        call.raw_artifact_ref_json = None

    assert harness.verify().raw_parsed_before_persist_count == 1
