import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.budget import BudgetLedger, BudgetPolicy
from co_scientist.domain.convergence import ConvergenceSnapshot
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.domain.tournament import EpochContractMismatch, TournamentEpoch
from co_scientist.domain.transitions import InvalidTransition
from co_scientist.events.models import NewEvent
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.supervisor.orchestrator import Supervisor


def _supervisor(tmp_path) -> Supervisor:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'finalization.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=0,
        events=[NewEvent(event_type="RunStarted", payload={})],
        target_run_state=RunState.RUNNING,
        idempotency_key="start:run-1",
    )
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))


def _empty_supervisor(tmp_path) -> Supervisor:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'empty.db'}")
    uow.create_schema()
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))


def _advance_finalization_to_result_received(supervisor: Supervisor) -> None:
    supervisor.uow.transition_task("finalize:run-1", "leased")
    supervisor.uow.transition_task("finalize:run-1", "running")
    supervisor.uow.transition_task("finalize:run-1", "result_received")


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


def _snapshot(
    *,
    epoch_id: str = "epoch-1",
    anchor_set_id: str = "anchors-1",
) -> ConvergenceSnapshot:
    return ConvergenceSnapshot(
        epoch_id=epoch_id,
        anchor_set_id=anchor_set_id,
        elo_plateau=True,
        anchor_plateau=True,
        top_k_stable=True,
        cluster_diversity_plateau=True,
        minimum_budget_satisfied=True,
    )


def _continuing_snapshot() -> ConvergenceSnapshot:
    return ConvergenceSnapshot(
        epoch_id="epoch-1",
        anchor_set_id="anchors-1",
        elo_plateau=False,
        anchor_plateau=False,
        top_k_stable=False,
        cluster_diversity_plateau=False,
        minimum_budget_satisfied=False,
    )


def _open_epoch(supervisor: Supervisor) -> int:
    commit = supervisor.uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=1,
        events=[
            NewEvent(
                event_type="TournamentEpochOpened",
                payload=_epoch().model_dump(mode="json"),
            )
        ],
        idempotency_key="open:epoch-1",
    )
    return commit.last_sequence


# Mutation caught: application/persistence callers creating then starting a Run separately.
def test_supervisor_atomically_creates_and_starts_run(tmp_path) -> None:
    supervisor = _empty_supervisor(tmp_path)

    started = supervisor.create_and_start_run(
        "run-new",
        manifest={"provider": "replay"},
        start_payload={"provider": "replay"},
    )

    assert started.last_sequence == 1
    assert supervisor.uow.run_state("run-new") == "running"
    assert [event.event_type for event in supervisor.uow.load("run-new")] == ["RunStarted"]


# Mutation caught: fixed lifecycle keys replaying old pause/resume commits on later cycles.
def test_supervisor_supports_repeated_pause_resume_cycles_and_rejects_stale_retry(
    tmp_path,
) -> None:
    supervisor = _supervisor(tmp_path)

    first_pause = supervisor.pause_run("run-1", expected_sequence=1)
    with pytest.raises(ConcurrencyConflict, match="expected 1, got 3"):
        supervisor.pause_run("run-1", expected_sequence=1)
    first_resume = supervisor.resume_run(
        "run-1", expected_sequence=first_pause.last_sequence
    )
    second_pause = supervisor.pause_run(
        "run-1", expected_sequence=first_resume.last_sequence
    )
    second_resume = supervisor.resume_run(
        "run-1", expected_sequence=second_pause.last_sequence
    )

    assert (
        first_pause.last_sequence,
        first_resume.last_sequence,
        second_pause.last_sequence,
        second_resume.last_sequence,
    ) == (3, 4, 6, 7)
    assert supervisor.uow.run_state("run-1") == "running"
    assert [event.event_type for event in supervisor.uow.load("run-1")] == [
        "RunStarted",
        "RunPausing",
        "RunPaused",
        "RunResumed",
        "RunPausing",
        "RunPaused",
        "RunResumed",
    ]


# Mutation caught: application code advancing the finalization Task outside Supervisor.
def test_supervisor_core_preview_stop_owns_partial_finalization(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    completed = supervisor.stop_and_finalize_partial(
        "run-1", expected_sequence=1, reason="scientist_stop"
    )

    assert completed.last_sequence == 6
    assert supervisor.uow.run_state("run-1") == "completed_partial"
    assert supervisor.uow.task_state("finalize:run-1") == "succeeded"
    assert [event.event_type for event in supervisor.uow.load("run-1")][-2:] == [
        "FinalizationCompleted",
        "RunCompletedPartial",
    ]


# Mutation caught: routing explicit cancel through application-owned state mutation.
def test_supervisor_owns_explicit_cancel(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    cancelled = supervisor.cancel_run("run-1", expected_sequence=1)

    assert cancelled.last_sequence == 2
    assert supervisor.uow.run_state("run-1") == "cancelled"


# Mutation caught: persisting terminal events without the Run and finalization Task states.
def test_normal_completion_atomically_persists_legal_run_and_task_states(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    stopping = supervisor.request_normal_completion(
        "run-1", expected_sequence=1, reason="work_complete"
    )
    assert supervisor.uow.run_state("run-1") == "stopping"
    _advance_finalization_to_result_received(supervisor)
    completed = supervisor.apply_finalization(
        "run-1", expected_sequence=stopping.last_sequence, completeness="complete"
    )

    events = supervisor.uow.load("run-1", after_sequence=1)
    assert [event.event_type for event in events] == [
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
        "FinalizationCompleted",
        "RunCompleted",
    ]
    assert events[2].payload == {
        "task_id": "finalize:run-1",
        "run_id": "run-1",
        "idempotency_key": "finalize:run-1",
        "intent_type": "finalize_run",
        "payload": {
            "reason": "work_complete",
            "budget_estimate": {
                "model_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": "0",
                "hypotheses": 0,
                "matches": 0,
            },
        },
        "created_by": "supervisor",
    }
    assert completed.events[-1].payload["completeness"] == "complete"
    assert supervisor.uow.task_state("finalize:run-1") == "succeeded"
    assert supervisor.uow.run_state("run-1") == "completed"


# Mutation caught: allowing pending -> succeeded for the finalization Task.
def test_finalization_requires_durable_result_received_task(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    stopping = supervisor.request_normal_completion("run-1", expected_sequence=1)

    with pytest.raises(InvalidTransition, match="pending.*succeeded"):
        supervisor.apply_finalization(
            "run-1",
            expected_sequence=stopping.last_sequence,
            completeness="complete",
        )

    assert supervisor.uow.run_state("run-1") == "stopping"
    assert supervisor.uow.task_state("finalize:run-1") == "pending"
    assert [event.event_type for event in supervisor.uow.load("run-1", after_sequence=1)] == [
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
    ]


def test_finalization_cannot_complete_a_run_that_never_stopped(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    with pytest.raises(InvalidTransition, match="running.*completed_partial"):
        supervisor.apply_finalization(
            "run-1", expected_sequence=1, completeness="partial"
        )

    assert [event.event_type for event in supervisor.uow.load("run-1")] == ["RunStarted"]


def test_quality_stop_requires_snapshot_anchor_to_match_epoch(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    expected_sequence = _open_epoch(supervisor)

    with pytest.raises(EpochContractMismatch, match="anchor set"):
        supervisor.tick(
            run_id="run-1",
            expected_sequence=expected_sequence,
            convergence=_snapshot(anchor_set_id="different"),
            hard_budget_reached=False,
            scientist_action=None,
        )

    assert [event.event_type for event in supervisor.uow.load("run-1")] == [
        "RunStarted",
        "TournamentEpochOpened",
    ]


# Mutation caught: accepting a convergence snapshot for a caller-spoofed epoch identity.
def test_quality_stop_rejects_snapshot_for_non_active_epoch(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    expected_sequence = _open_epoch(supervisor)

    with pytest.raises(EpochContractMismatch, match="active TournamentEpoch"):
        supervisor.tick(
            run_id="run-1",
            expected_sequence=expected_sequence,
            convergence=_snapshot(epoch_id="epoch-stale"),
            hard_budget_reached=False,
            scientist_action=None,
        )

    assert supervisor.uow.run_state("run-1") == "running"


# Mutation caught: allowing a non-terminal tick to continue a durable stopping Run.
def test_tick_cannot_continue_a_non_running_durable_run(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    expected_sequence = _open_epoch(supervisor)
    stopped = supervisor.uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=expected_sequence,
        events=[NewEvent(event_type="RunStopping", payload={})],
        target_run_state=RunState.STOPPING,
        idempotency_key="prepare-stopping:run-1",
    )

    with pytest.raises(ValueError, match="running Run"):
        supervisor.tick(
            run_id="run-1",
            expected_sequence=stopped.last_sequence,
            convergence=_continuing_snapshot(),
        )


@pytest.mark.parametrize(
    ("open_epoch", "hard_budget_reached", "scientist_action", "reason", "state"),
    [
        (False, True, None, "hard_budget_reached", "stopping"),
        (True, False, "soft_stop", "scientist_stop", "stopping"),
        (True, False, "hard_cancel", "scientist_cancel", "cancelled"),
    ],
)
# Mutation caught: validating convergence epoch data before terminal stop precedence.
def test_terminal_tick_is_not_blocked_by_missing_or_stale_epoch_data(
    tmp_path,
    open_epoch: bool,
    hard_budget_reached: bool,
    scientist_action: str | None,
    reason: str,
    state: str,
) -> None:
    supervisor = _supervisor(tmp_path)
    expected_sequence = _open_epoch(supervisor) if open_epoch else 1

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=expected_sequence,
        convergence=_snapshot(epoch_id="epoch-stale", anchor_set_id="anchors-stale"),
        hard_budget_reached=hard_budget_reached,
        scientist_action=scientist_action,
    )

    assert outcome.decision.reason == reason
    assert outcome.commit is not None
    assert supervisor.uow.run_state("run-1") == state


@pytest.mark.parametrize(
    ("hard_budget_reached", "scientist_action", "target"),
    [
        (True, None, "stopping"),
        (False, "soft_stop", "stopping"),
        (False, "hard_cancel", "cancelled"),
    ],
)
# Mutation caught: allowing terminal precedence to bypass durable Run transition legality.
def test_terminal_tick_still_obeys_the_durable_run_state_machine(
    tmp_path,
    hard_budget_reached: bool,
    scientist_action: str | None,
    target: str,
) -> None:
    supervisor = _supervisor(tmp_path)
    stopped = supervisor.uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=1,
        events=[NewEvent(event_type="RunStopping", payload={})],
        target_run_state=RunState.STOPPING,
        idempotency_key="prepare-stopping:run-1",
    )

    with pytest.raises(InvalidTransition, match=f"stopping.*{target}"):
        supervisor.tick(
            run_id="run-1",
            expected_sequence=stopped.last_sequence,
            convergence=_snapshot(epoch_id="epoch-stale", anchor_set_id="anchors-stale"),
            hard_budget_reached=hard_budget_reached,
            scientist_action=scientist_action,
        )


def test_matching_quality_stop_enters_stopping_and_enqueues_finalization(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    expected_sequence = _open_epoch(supervisor)

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=expected_sequence,
        convergence=_snapshot(),
        hard_budget_reached=False,
        scientist_action=None,
    )

    assert outcome.decision.reason == "quality_converged"
    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
    ]


def test_tick_consumes_budget_ledger_and_routes_hard_limit_through_finalization(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    expected_sequence = _open_epoch(supervisor)
    budget = BudgetLedger(
        policy=BudgetPolicy(max_model_calls=1),
        model_calls=1,
    )

    outcome = supervisor.tick(
        run_id="run-1",
        expected_sequence=expected_sequence,
        convergence=_snapshot(anchor_set_id="different"),
        budget=budget,
        scientist_action=None,
    )

    assert outcome.decision.reason == "hard_budget_reached"
    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
    ]
