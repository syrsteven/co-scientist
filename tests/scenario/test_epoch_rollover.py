import pytest

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.admission import AdmissionPolicy
from co_scientist.domain.research_plan import ResearchPlan
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import ExternalCallState, RunState
from co_scientist.domain.task import NewTask
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.supervisor.orchestrator import Supervisor, plan_revision_action
from tests._fenced_runtime import (
    acknowledge_result,
    budgeted_task,
    claim_running_task,
    execution_manifest,
    fenced_context,
)


def _plan(*, version: int, scope: str = "scope-a", rules: str = "rules-a") -> ResearchPlan:
    return ResearchPlan(
        run_id="run-1",
        version=version,
        scientific_scope_hash=scope,
        evaluation_rules_hash=rules,
        ranking_prompt_hash=f"prompt-{version}",
        judge_profile_hash=f"judge-{version}",
        rating_policy_version="elo-32-v1",
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
    policies = {
        f"admission-{version}": AdmissionPolicy(
            version=f"admission-{version}",
            review_policy=ReviewPolicy(profile_id="minimal"),
            literature_novelty_required=False,
            duplicate_likelihood_threshold=0.5,
        ).model_dump(mode="json")
        for version in (1, 2, 3)
    }
    uow.create_run(
        "run-1",
        manifest=execution_manifest(admission_policies=policies),
    )
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


def _append_admission_evidence(
    supervisor: Supervisor,
    *,
    expected_sequence: int,
    plan_version: int,
) -> int:
    generation = _apply_scientific_result(
        supervisor,
        expected_sequence=expected_sequence,
        task_id=f"generation:{plan_version}",
        skill_id="generation",
        output_schema_id="GenerationResultV1",
        plan_version=plan_version,
        payload={
            "schema_version": 1,
            "research_plan_version": plan_version,
            "hypotheses": [
                {
                    "schema_version": 1,
                    "hypothesis_id": "h-1",
                    "content_id": f"content-{plan_version}",
                    "research_plan_version": plan_version,
                    "title": "Epoch candidate",
                    "claim": "The epoch candidate remains independently testable.",
                    "mechanism_chain": ["candidate", "test", "result"],
                    "assumptions": [],
                    "predictions": [],
                    "falsifiers": [],
                    "generation_strategy": "epoch scenario",
                }
            ],
        },
    )
    content_event = next(
        event
        for event in reversed(supervisor.uow.load("run-1"))
        if event.event_type == "HypothesisContentCreated"
        and event.payload.get("hypothesis_id") == "h-1"
    )
    content_hash = str(content_event.payload["content_hash"])
    reviewed = _apply_scientific_result(
        supervisor,
        expected_sequence=generation,
        task_id="review:initial_review:h-1",
        skill_id="reflection",
        output_schema_id="ReflectionResultV1",
        plan_version=plan_version,
        payload={
            "schema_version": 1,
            "research_plan_version": plan_version,
            "review_id": f"review-{plan_version}",
            "hypothesis_id": "h-1",
            "content_hash": content_hash,
            "stage": "initial_review",
            "recommendation": "pass",
            "safety_status": "passed",
            "critical_flaws": [],
        },
    )
    return _apply_scientific_result(
        supervisor,
        expected_sequence=reviewed,
        task_id=f"proximity:{plan_version}",
        skill_id="proximity",
        output_schema_id="ProximityResultV1",
        plan_version=plan_version,
        payload={
            "schema_version": 1,
            "research_plan_version": plan_version,
            "edge_id": f"edge-{plan_version}",
            "left_id": "h-1",
            "left_content_hash": content_hash,
            "right_id": "anchor-1",
            "right_content_hash": "sha256:" + "a" * 64,
            "similarity": 1,
            "duplicate_likelihood": 0.1,
            "rationale": "Distinct from the anchor.",
        },
    )


def _apply_scientific_result(
    supervisor: Supervisor,
    *,
    expected_sequence: int,
    task_id: str,
    skill_id: str,
    output_schema_id: str,
    plan_version: int,
    payload: dict[str, object],
) -> int:
    uow = supervisor.uow
    inputs: dict[str, object] = {}
    if skill_id == "reflection":
        inputs = {
            "hypothesis_id": payload["hypothesis_id"],
            "content_hash": payload["content_hash"],
            "review_stage": payload["stage"],
        }
    elif skill_id == "proximity":
        inputs = {
            field: payload[field]
            for field in (
                "edge_id",
                "left_id",
                "left_content_hash",
                "right_id",
                "right_content_hash",
            )
        }
    input_snapshot_hash = request_fingerprint(inputs)
    try:
        uow.task_state(task_id)
    except KeyError:
        scheduled = supervisor.enqueue_task(
            task=budgeted_task(
                NewTask(
                    task_id=task_id,
                    run_id="run-1",
                    idempotency_key=task_id,
                    intent_type=f"run_{skill_id}",
                    payload={
                        "skill_id": skill_id,
                        "skill_version": "0.2.0",
                        "output_schema_id": output_schema_id,
                        "output_schema_version": 1,
                        "research_plan_version": plan_version,
                        "provider_id": "scenario",
                        "model_or_tool": "typed-fixture",
                        "inputs": inputs,
                        "input_snapshot_hash": input_snapshot_hash,
                        "prompt_hash": "sha256:prompt",
                    },
                )
            ),
            expected_sequence=expected_sequence,
        )
        expected_sequence = scheduled.last_sequence
    claimed = claim_running_task(uow, run_id="run-1", task_id=task_id)
    expected_sequence = uow.load("run-1")[-1].sequence
    call_id = f"call:{task_id}:{plan_version}"
    context = fenced_context(
        {
            "run_id": "run-1",
            "task_id": task_id,
            "idempotency_key": task_id,
            "skill_id": skill_id,
            "skill_version": "0.2.0",
            "output_schema_id": output_schema_id,
            "output_schema_version": 1,
            "research_plan_version": plan_version,
            "provider": "scenario",
            "model_or_tool": "typed-fixture",
            "input_snapshot_hash": input_snapshot_hash,
            "prompt_hash": "sha256:prompt",
        },
        claimed,
    ).model_dump(mode="json")
    uow.plan_external_call(
        call_id,
        "sha256:request",
        run_id="run-1",
        task_id=task_id,
        execution_context=context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.transition_call(
        call_id,
        ExternalCallState.STARTED,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    raw_ref = ArtifactRef(
        path=f"raw/{call_id}",
        sha256="sha256:" + "f" * 64,
        mime_type="application/json",
        byte_length=2,
    )
    uow.record_raw_and_transition(
        call_id,
        raw_ref,
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        usage={"input_tokens": 1, "output_tokens": 1, "pricing_version": "scenario"},
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    result = AgentResult(
        result_id=f"result:{task_id}:{plan_version}",
        external_call_id=call_id,
        status="completed",
        payload=payload,
        raw_artifact_ref=raw_ref,
        **context,
    )
    uow.record_validated_and_submitted(
        call_id,
        payload,
        result,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    acknowledge_result(uow, claimed)
    committed = supervisor.handle_result(
        "run-1",
        task_id,
        result,
        expected_sequence,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    return committed.last_sequence


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
    evidence_sequence = _append_admission_evidence(
        supervisor,
        expected_sequence=outcome.commit.last_sequence,
        plan_version=2,
    )
    admission = supervisor.admit_hypothesis(
        run_id="run-1",
        hypothesis_id="h-1",
        expected_sequence=evidence_sequence,
        idempotency_key="admit:h-1:epoch-2",
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


# Mutation caught: allowing a closed epoch ID to be recycled after a later epoch opened.
def test_plan_revision_rejects_any_previously_used_epoch_id(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    second = supervisor.accept_plan_revision(
        old=_plan(version=1),
        new=_plan(version=2, rules="rules-b"),
        expected_sequence=2,
        next_epoch_id="epoch-2",
        next_anchor_set_id="anchors-2",
    )

    with pytest.raises(ValueError, match="previously used"):
        supervisor.accept_plan_revision(
            old=_plan(version=2, rules="rules-b"),
            new=_plan(version=3, rules="rules-c"),
            expected_sequence=second.commit.last_sequence,
            next_epoch_id="epoch-1",
            next_anchor_set_id="anchors-3",
        )

    assert [event.event_type for event in supervisor.uow.load("run-1")] == [
        "RunStarted",
        "TournamentEpochOpened",
        "ResearchPlanAccepted",
        "TournamentEpochClosed",
        "TournamentEpochOpened",
    ]


# Mutation caught: leaving admission and initial Elo assignment to a caller-side helper.
def test_supervisor_atomically_admits_into_active_epoch_at_policy_rating(tmp_path) -> None:
    supervisor = _supervisor(tmp_path)
    evidence_sequence = _append_admission_evidence(
        supervisor,
        expected_sequence=2,
        plan_version=1,
    )

    outcome = supervisor.admit_hypothesis(
        run_id="run-1",
        hypothesis_id="h-1",
        expected_sequence=evidence_sequence,
        idempotency_key="admit:h-1:epoch-1",
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
    assert outcome.commit.events[2].payload["rating_policy_version"] == "elo-32-v1"


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
