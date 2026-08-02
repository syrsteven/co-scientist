import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.research_plan import ResearchPlan
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.supervisor.orchestrator import Supervisor, plan_revision_action


def _plan(*, version: int, scope: str = "scope-a", rules: str = "rules-a") -> ResearchPlan:
    return ResearchPlan(
        run_id="run-1",
        version=version,
        scientific_scope_hash=scope,
        evaluation_rules_hash=rules,
        ranking_prompt_hash=f"prompt-{version}",
        judge_profile_hash=f"judge-{version}",
        rating_policy_version=f"rating-{version}",
        admission_policy_version=f"admission-{version}",
        review_policy=ReviewPolicy(profile_id="minimal"),
        literature_novelty_required=False,
    )


def _epoch(plan: ResearchPlan) -> TournamentEpoch:
    return TournamentEpoch(
        epoch_id="epoch-1",
        research_plan_version=plan.version,
        evaluation_rules_hash=plan.evaluation_rules_hash,
        ranking_prompt_hash=plan.ranking_prompt_hash,
        judge_profile_hash=plan.judge_profile_hash,
        rating_policy_version=plan.rating_policy_version,
        admission_policy_version=plan.admission_policy_version,
        anchor_set_id="anchors-1",
    )


def _supervisor(tmp_path) -> Supervisor:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'epoch.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    started = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=0,
        events=[NewEvent(event_type="RunStarted", payload={})],
        target_run_state=RunState.RUNNING,
        idempotency_key="start:run-1",
    )
    epoch = _epoch(_plan(version=1))
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=started.last_sequence,
        events=[
            NewEvent(
                event_type="TournamentEpochOpened",
                payload=epoch.model_dump(mode="json"),
            )
        ],
        idempotency_key="open:epoch-1",
    )
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))


# Mutation caught: trusting a caller-provided epoch instead of the durable open epoch.
def test_evaluation_revision_closes_durable_epoch_and_opens_fresh_epoch(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    old = _plan(version=1)
    new = _plan(version=2, rules="rules-b")

    outcome = supervisor.accept_plan_revision(
        old=old,
        new=new,
        expected_sequence=2,
        next_epoch_id="epoch-2",
        next_anchor_set_id="anchors-2",
    )

    assert outcome.action == "new_epoch"
    assert outcome.next_epoch is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "ResearchPlanAccepted",
        "TournamentEpochClosed",
        "TournamentEpochOpened",
    ]
    assert outcome.next_epoch.anchor_set_id == "anchors-2"
    admission = supervisor.admit_hypothesis(
        run_id="run-1",
        expected_sequence=outcome.commit.last_sequence,
        hypothesis_id="h-1",
        content_hash="sha256:content",
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=False,
        novelty_assessment=None,
        proximity_complete=True,
        duplicate=False,
    )
    assert admission.entry is not None
    assert (admission.entry.rating, admission.entry.matches_played) == (1200.0, 0)


# Mutation caught: failing to close the durable active epoch before requiring a fork.
def test_scientific_scope_revision_closes_epoch_and_requires_fork(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    old = _plan(version=1)
    new = _plan(version=2, scope="scope-b")

    outcome = supervisor.accept_plan_revision(
        old=old,
        new=new,
        expected_sequence=2,
    )

    assert outcome.action == "fork_run"
    assert outcome.next_epoch is None
    assert [event.event_type for event in outcome.commit.events] == [
        "ResearchPlanAccepted",
        "TournamentEpochClosed",
        "RunForkRequired",
    ]


def test_plan_revision_requires_a_strict_version_increment() -> None:
    with pytest.raises(ValueError, match="version must increase"):
        plan_revision_action(_plan(version=1), _plan(version=1))


# Mutation caught: reopening the replacement epoch under the current epoch's identity.
def test_plan_revision_rejects_reused_active_epoch_id(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    with pytest.raises(ValueError, match="new epoch ID"):
        supervisor.accept_plan_revision(
            old=_plan(version=1),
            new=_plan(version=2, rules="rules-b"),
            expected_sequence=2,
            next_epoch_id="epoch-1",
        )

    assert [event.event_type for event in supervisor.uow.load("run-1")] == [
        "RunStarted",
        "TournamentEpochOpened",
    ]


# Mutation caught: leaving admission and initial Elo assignment to a caller-side helper.
def test_supervisor_atomically_admits_into_active_epoch_at_internal_1200(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)

    outcome = supervisor.admit_hypothesis(
        run_id="run-1",
        expected_sequence=2,
        hypothesis_id="h-1",
        content_hash="sha256:content",
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=False,
        novelty_assessment=None,
        proximity_complete=True,
        duplicate=False,
    )

    assert outcome.decision.admitted
    assert outcome.entry is not None
    assert (outcome.entry.epoch_id, outcome.entry.rating) == ("epoch-1", 1200.0)
    assert outcome.commit is not None
    assert [event.event_type for event in outcome.commit.events] == [
        "HypothesisTournamentReady",
        "TournamentEntryCreated",
        "InitialRatingAssigned",
    ]
    assert [
        outcome.commit.events[1].payload["rating"],
        outcome.commit.events[2].payload["rating"],
    ] == [1200.0, 1200.0]


# Mutation caught: applying a plan revision while ignoring the durable Run state.
def test_plan_revision_requires_durable_running_run(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    stopped = supervisor.uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=2,
        events=[NewEvent(event_type="RunStopping", payload={})],
        target_run_state=RunState.STOPPING,
        idempotency_key="stop:run-1",
    )

    with pytest.raises(ValueError, match="running Run"):
        supervisor.accept_plan_revision(
            old=_plan(version=1),
            new=_plan(version=2, rules="rules-b"),
            expected_sequence=stopped.last_sequence,
            next_epoch_id="epoch-2",
        )


# Mutation caught: resolving the replacement epoch before exact idempotency replay.
def test_exact_plan_revision_replay_returns_prior_commit(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    kwargs = {
        "old": _plan(version=1),
        "new": _plan(version=2, rules="rules-b"),
        "expected_sequence": 2,
        "next_epoch_id": "epoch-2",
        "next_anchor_set_id": "anchors-2",
    }
    committed = supervisor.accept_plan_revision(**kwargs)

    replayed = supervisor.accept_plan_revision(**kwargs)

    assert replayed.commit == committed.commit
    assert len(supervisor.uow.load("run-1")) == 5
