import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.research_plan import ResearchPlan
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.tournament import TournamentEpoch, admit_entry
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
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))


def test_evaluation_revision_closes_epoch_and_opens_reset_rating_epoch(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    old = _plan(version=1)
    new = _plan(version=2, rules="rules-b")

    outcome = supervisor.accept_plan_revision(
        old=old,
        new=new,
        current_epoch=_epoch(old),
        expected_sequence=0,
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
    reset_entry = admit_entry(outcome.next_epoch, "h-1", "sha256:content")
    assert (reset_entry.rating, reset_entry.matches_played) == (1200.0, 0)


def test_scientific_scope_revision_closes_epoch_and_requires_fork(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    old = _plan(version=1)
    new = _plan(version=2, scope="scope-b")

    outcome = supervisor.accept_plan_revision(
        old=old,
        new=new,
        current_epoch=_epoch(old),
        expected_sequence=0,
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
