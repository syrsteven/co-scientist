import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.budget import BudgetLedger, BudgetPolicy
from co_scientist.domain.convergence import ConvergenceSnapshot
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.domain.tournament import EpochContractMismatch, TournamentEpoch
from co_scientist.supervisor.orchestrator import Supervisor


def _supervisor(tmp_path) -> Supervisor:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'finalization.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))


def _epoch() -> TournamentEpoch:
    return TournamentEpoch(
        epoch_id="epoch-1",
        research_plan_version=1,
        evaluation_rules_hash="rules",
        ranking_prompt_hash="prompt",
        judge_profile_hash="judge",
        rating_policy_version="rating",
        admission_policy_version="admission",
        anchor_set_id="anchors-1",
    )


def _snapshot(*, anchor_set_id: str = "anchors-1") -> ConvergenceSnapshot:
    return ConvergenceSnapshot(
        epoch_id="epoch-1",
        anchor_set_id=anchor_set_id,
        elo_plateau=True,
        anchor_plateau=True,
        top_k_stable=True,
        cluster_diversity_plateau=True,
        minimum_budget_satisfied=True,
    )


def test_normal_completion_always_stops_and_runs_finalization_first(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    stopping = supervisor.request_normal_completion(
        "run-1", expected_sequence=0, reason="work_complete"
    )
    completed = supervisor.apply_finalization(
        "run-1", expected_sequence=stopping.last_sequence, completeness="complete"
    )

    events = supervisor.uow.load("run-1")
    assert [event.event_type for event in events] == [
        "RunStopping",
        "FinalizationRequested",
        "FinalizationCompleted",
        "RunCompleted",
    ]
    assert completed.events[-1].payload["completeness"] == "complete"
    assert supervisor.uow.task_state("finalize:run-1") == "succeeded"


def test_finalization_cannot_complete_a_run_that_never_stopped(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    with pytest.raises(ValueError, match="stopping"):
        supervisor.apply_finalization(
            "run-1", expected_sequence=0, completeness="partial"
        )

    assert supervisor.uow.load("run-1") == []


def test_quality_stop_requires_snapshot_anchor_to_match_epoch(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    with pytest.raises(EpochContractMismatch, match="anchor set"):
        supervisor.tick(
            run_id="run-1",
            expected_sequence=0,
            run_state=RunState.RUNNING,
            epoch=_epoch(),
            convergence=_snapshot(anchor_set_id="different"),
            hard_budget_reached=False,
            scientist_action=None,
        )

    assert supervisor.uow.load("run-1") == []


def test_matching_quality_stop_enters_stopping_and_enqueues_finalization(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=0,
        run_state=RunState.RUNNING,
        epoch=_epoch(),
        convergence=_snapshot(),
        hard_budget_reached=False,
        scientist_action=None,
    )

    assert outcome.decision.reason == "quality_converged"
    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "RunStopping",
        "FinalizationRequested",
    ]


def test_tick_consumes_budget_ledger_and_routes_hard_limit_through_finalization(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    budget = BudgetLedger(
        policy=BudgetPolicy(max_model_calls=1),
        model_calls=1,
    )

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=0,
        run_state=RunState.RUNNING,
        epoch=_epoch(),
        convergence=_snapshot(anchor_set_id="different"),
        budget=budget,
        scientist_action=None,
    )

    assert outcome.decision.reason == "hard_budget_reached"
    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "RunStopping",
        "FinalizationRequested",
    ]
