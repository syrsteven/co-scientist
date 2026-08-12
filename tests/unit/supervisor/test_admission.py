from decimal import Decimal

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.review import NoveltyAssessment, NoveltyVerdict, ReviewPolicy
from co_scientist.domain.states import ExternalCallState, TaskState
from co_scientist.domain.task import NewTask
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.supervisor.orchestrator import Supervisor, evaluate_admission


def _generation_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [
            {
                "schema_version": 1,
                "hypothesis_id": "h-1",
                "content_id": "content-1",
                "research_plan_version": 1,
                "title": "Candidate",
                "claim": "The candidate preserves typed scientific provenance.",
                "mechanism_chain": ["typed", "validated", "applied"],
                "assumptions": [],
                "predictions": [],
                "falsifiers": [],
                "generation_strategy": "admission fixture",
            }
        ],
    }


def _non_scientific_payload(status: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "outcome": status,
        "reason_code": f"fixture_{status}",
        "message": f"The fixture returned {status}.",
        "retryable": status == "partial",
        "missing_requirements": [],
    }


def _ranking_result(
    *, result_id: str, prompt_hash: str, winner_id: str = "h-1"
) -> AgentResult:
    return AgentResult(
        result_id=result_id,
        external_call_id=f"call-{result_id}",
        run_id="run-1",
        task_id=f"task-{result_id}",
        idempotency_key=f"ranking:{result_id}",
        skill_id="ranking",
        skill_version="0.2.0",
        output_schema_id="RankingResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="stub",
        model_or_tool="stub-model",
        input_snapshot_hash="sha256:input",
        prompt_hash=prompt_hash,
        status="completed",
        payload={
            "schema_version": 1,
            "research_plan_version": 1,
            "match_id": "match-1",
            "epoch_id": "epoch-1",
            "left_id": "h-1",
            "left_content_hash": "sha256:" + "1" * 64,
            "right_id": "h-2",
            "right_content_hash": "sha256:" + "2" * 64,
            "evaluation_rules_hash": "sha256:rules",
            "ranking_prompt_hash": "sha256:ranking-prompt",
            "judge_profile_hash": "sha256:judge",
            "rating_policy_version": "elo-32-v1",
            "admission_policy_version": "admission-v1",
            "decision_status": "decisive",
            "winner_slot": 1 if winner_id == "h-1" else 2,
            "dimension_reasons": {},
            "confidence": 0.9,
            "unresolved_disagreements": [],
        },
        raw_artifact_ref=ArtifactRef(
            path=f"raw/{result_id}",
            sha256="sha256:" + "a" * 64,
            mime_type="application/json",
            byte_length=2,
        ),
    )


def _ranking_uow(tmp_path) -> SqliteUnitOfWork:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'ranking.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    epoch = TournamentEpoch(
        epoch_id="epoch-1",
        research_plan_version=1,
        evaluation_rules_hash="sha256:rules",
        ranking_prompt_hash="sha256:ranking-prompt",
        judge_profile_hash="sha256:judge",
        rating_policy_version="elo-32-v1",
        admission_policy_version="admission-v1",
        anchor_set_id="anchors-1",
    )
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=0,
        events=(
            NewEvent(event_type="TournamentEpochOpened", payload=epoch.model_dump()),
            NewEvent(
                event_type="TournamentEntryCreated",
                payload={"epoch_id": "epoch-1", "hypothesis_id": "h-1", "rating": 1200.0},
            ),
            NewEvent(
                event_type="TournamentEntryCreated",
                payload={"epoch_id": "epoch-1", "hypothesis_id": "h-2", "rating": 1200.0},
            ),
            NewEvent(
                event_type="InitialRatingAssigned",
                payload={"epoch_id": "epoch-1", "hypothesis_id": "h-1", "rating": 1200.0},
            ),
            NewEvent(
                event_type="InitialRatingAssigned",
                payload={"epoch_id": "epoch-1", "hypothesis_id": "h-2", "rating": 1200.0},
            ),
        ),
        idempotency_key="ranking-seed",
    )
    return uow


# Mutation caught: trusting the payload's epoch prompt hash without binding execution bytes.
def test_ranking_result_prompt_hash_must_match_epoch_contract(tmp_path) -> None:
    supervisor = Supervisor(
        uow=_ranking_uow(tmp_path),
        review_policy=ReviewPolicy(profile_id="minimal"),
    )

    with pytest.raises(ValueError, match="execution prompt hash"):
        supervisor._rating_events_for_result(
            "run-1",
            _ranking_result(result_id="result-1", prompt_hash="sha256:different-prompt"),
        )


# Mutation caught: replaying ratings solely because an unrelated task reused match_id.
def test_conflicting_duplicate_match_id_cannot_reuse_persisted_ratings(tmp_path) -> None:
    uow = _ranking_uow(tmp_path)
    first = _ranking_result(
        result_id="result-1",
        prompt_hash="sha256:ranking-prompt",
    )
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=5,
        events=(
            NewEvent(
                event_type="MatchEvaluated",
                    payload={
                        **dict(first.payload),
                        "decision": "decisive",
                        "winner_id": "h-1",
                        "source_result_id": first.result_id,
                    "source_task_id": first.task_id,
                    "status": first.status,
                },
                causation_id=first.result_id,
                correlation_id="run-1",
            ),
            NewEvent(
                event_type="RatingUpdated",
                payload={
                    "match_id": "match-1",
                    "epoch_id": "epoch-1",
                    "hypothesis_id": "h-1",
                    "before_rating": 1200.0,
                    "rating": 1216.0,
                    "rating_policy_version": "elo-32-v1",
                },
                causation_id=first.result_id,
                correlation_id="run-1",
            ),
            NewEvent(
                event_type="RatingUpdated",
                payload={
                    "match_id": "match-1",
                    "epoch_id": "epoch-1",
                    "hypothesis_id": "h-2",
                    "before_rating": 1200.0,
                    "rating": 1184.0,
                    "rating_policy_version": "elo-32-v1",
                },
                causation_id=first.result_id,
                correlation_id="run-1",
            ),
        ),
        idempotency_key="first-match",
    )
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    replayed = supervisor._rating_events_for_result(
        "run-1", first
    )
    assert [event.payload["hypothesis_id"] for event in replayed] == ["h-1", "h-2"]
    conflicting = _ranking_result(
        result_id="result-2",
        prompt_hash="sha256:ranking-prompt",
        winner_id="h-2",
    )

    with pytest.raises(ValueError, match="duplicate match_id"):
        supervisor._rating_events_for_result(
            "run-1", conflicting
        )


def test_minimal_policy_admits_without_deep_review() -> None:
    decision = evaluate_admission(
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=False,
        novelty_assessment=None,
        proximity_complete=True,
        duplicate=False,
    )

    assert decision.admitted


def test_supervisor_is_available_from_its_public_package() -> None:
    from co_scientist.supervisor import Supervisor as PublicSupervisor

    assert PublicSupervisor is Supervisor


def test_initial_review_is_mandatory_even_when_caller_omits_it() -> None:
    decision = evaluate_admission(
        safety_passed=True,
        required_stages=set(),
        completed_stages=set(),
        novelty_required=False,
        novelty_assessment=None,
        proximity_complete=True,
        duplicate=False,
    )

    assert not decision.admitted
    assert decision.missing_requirements == ("initial_review",)


def test_novelty_and_candidate_proximity_remain_separate_admission_gates() -> None:
    novelty = NoveltyAssessment(
        assessment_id="novelty-1",
        hypothesis_id="h-1",
        content_hash="sha256:content",
        research_plan_version=1,
        verdict=NoveltyVerdict.NOVEL,
        closest_prior_work_ids=(),
    )

    missing_novelty = evaluate_admission(
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=True,
        novelty_assessment=None,
        proximity_complete=True,
        duplicate=False,
    )
    missing_proximity = evaluate_admission(
        hypothesis_id="h-1",
        content_hash="sha256:content",
        research_plan_version=1,
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=True,
        novelty_assessment=novelty,
        proximity_complete=False,
        duplicate=False,
    )

    assert missing_novelty.missing_requirements == ("novelty_assessment",)
    assert missing_proximity.missing_requirements == ("proximity",)


# Mutation caught: treating any non-null NoveltyAssessment as applicable and qualifying.
@pytest.mark.parametrize(
    "assessment",
    [
        NoveltyAssessment(
            assessment_id="wrong-hypothesis",
            hypothesis_id="h-other",
            content_hash="sha256:content",
            research_plan_version=2,
            verdict=NoveltyVerdict.NOVEL,
            closest_prior_work_ids=(),
        ),
        NoveltyAssessment(
            assessment_id="stale-content",
            hypothesis_id="h-1",
            content_hash="sha256:stale",
            research_plan_version=2,
            verdict=NoveltyVerdict.NOVEL,
            closest_prior_work_ids=(),
        ),
        NoveltyAssessment(
            assessment_id="stale-plan",
            hypothesis_id="h-1",
            content_hash="sha256:content",
            research_plan_version=1,
            verdict=NoveltyVerdict.NOVEL,
            closest_prior_work_ids=(),
        ),
        NoveltyAssessment(
            assessment_id="not-novel",
            hypothesis_id="h-1",
            content_hash="sha256:content",
            research_plan_version=2,
            verdict=NoveltyVerdict.NOT_NOVEL,
            closest_prior_work_ids=("paper-1",),
        ),
        NoveltyAssessment(
            assessment_id="insufficient",
            hypothesis_id="h-1",
            content_hash="sha256:content",
            research_plan_version=2,
            verdict=NoveltyVerdict.INSUFFICIENT_EVIDENCE,
            closest_prior_work_ids=(),
        ),
    ],
)
def test_required_novelty_rejects_inapplicable_or_nonqualifying_assessment(
    assessment: NoveltyAssessment,
) -> None:
    decision = evaluate_admission(
        hypothesis_id="h-1",
        content_hash="sha256:content",
        research_plan_version=2,
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=True,
        novelty_assessment=assessment,
        proximity_complete=True,
        duplicate=False,
    )

    assert not decision.admitted
    assert decision.missing_requirements == ("novelty_assessment",)


# Mutation caught: rejecting the policy-qualified partially_novel verdict.
def test_required_novelty_accepts_matching_partially_novel_assessment() -> None:
    assessment = NoveltyAssessment(
        assessment_id="novelty-1",
        hypothesis_id="h-1",
        content_hash="sha256:content",
        research_plan_version=2,
        verdict=NoveltyVerdict.PARTIALLY_NOVEL,
        closest_prior_work_ids=("paper-1",),
    )

    decision = evaluate_admission(
        hypothesis_id="h-1",
        content_hash="sha256:content",
        research_plan_version=2,
        safety_passed=True,
        required_stages={"initial_review"},
        completed_stages={"initial_review"},
        novelty_required=True,
        novelty_assessment=assessment,
        proximity_complete=True,
        duplicate=False,
    )

    assert decision.admitted


# Mutation caught: inserting a task without atomic, full Supervisor creator provenance.
def test_supervisor_enqueue_task_atomically_persists_full_provenance(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'enqueue.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    task = NewTask(
        task_id="generate-1",
        run_id="run-1",
        idempotency_key="generation:run-1:1",
        intent_type="generate",
        payload={"research_goal": "regeneration"},
    )

    commit = supervisor.enqueue_task(task=task, expected_sequence=0)

    assert [event.event_type for event in commit.events] == ["TaskEnqueued"]
    assert commit.events[0].payload == task.model_dump(mode="json")
    assert uow.task_state(task.task_id) == "pending"


def test_handle_result_atomically_applies_policy_owned_work_and_ignores_agent_actions(
    tmp_path,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'supervisor.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="generate-1",
                run_id="run-1",
                idempotency_key="generation:run-1:1",
                intent_type="generate",
                payload={},
            )
        ]
    )
    uow.transition_task("generate-1", TaskState.LEASED)
    uow.transition_task("generate-1", TaskState.RUNNING)
    uow.transition_task("generate-1", TaskState.RESULT_RECEIVED)
    context = {
        "run_id": "run-1",
        "task_id": "generate-1",
        "idempotency_key": "generation:run-1:1",
        "skill_id": "generation",
        "skill_version": "0.2.0",
        "output_schema_id": "GenerationResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider": "stub",
        "model_or_tool": "stub-model",
        "input_snapshot_hash": "sha256:input",
    }
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id="generate-1",
        execution_context=context,
    )
    uow.transition_call("call-1", ExternalCallState.STARTED)
    raw_ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    uow.record_raw_and_transition(
        "call-1",
        raw_ref,
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        usage={
            "input_tokens": 11,
            "output_tokens": 7,
            "cost_usd": "0.0123",
            "pricing_version": "2026-07",
        },
    )
    payload = _generation_payload()
    result = AgentResult(
        result_id="result-1",
        external_call_id="call-1",
        run_id="run-1",
        task_id="generate-1",
        idempotency_key="generation:run-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="stub",
        model_or_tool="stub-model",
        input_snapshot_hash="sha256:input",
        status="completed",
        payload=payload,
        recommended_actions=("run_deep_verification",),
        raw_artifact_ref=raw_ref,
    )
    uow.record_validated_and_submitted("call-1", payload, result)

    commit = Supervisor(
        uow=uow,
        review_policy=ReviewPolicy(profile_id="minimal"),
    ).handle_result(
        run_id="run-1",
        task_id="generate-1",
        result=result,
        expected_sequence=0,
    )

    assert [event.event_type for event in commit.events] == [
        "HypothesisContentCreated",
        "TaskEnqueued",
    ]
    assert commit.events[1].payload == {
        "task_id": "review:initial_review:h-1",
        "run_id": "run-1",
        "idempotency_key": "review:initial_review:h-1",
        "intent_type": "run_initial_review",
        "payload": {"hypothesis_id": "h-1", "review_stage": "initial_review"},
        "created_by": "supervisor",
    }
    assert uow.task_state("generate-1") == "succeeded"
    assert uow.task_state("review:initial_review:h-1") == "pending"
    assert uow.external_call_state("call-1") == "domain_result_applied"
    with uow.engine.connect() as connection:
        tasks = connection.execute(text("SELECT intent_type FROM tasks ORDER BY rowid"))
        task_rows = tasks.fetchall()
        cost = connection.execute(
            text("SELECT input_tokens, output_tokens, cost_usd, pricing_version FROM cost_entries")
        ).one()
    assert [row.intent_type for row in task_rows] == ["generate", "run_initial_review"]
    assert cost == (11, 7, str(Decimal("0.0123")), "2026-07")


def _submitted_generation_result(tmp_path, status: str):
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / f'{status}.db'}")
    uow.create_schema()
    uow.create_run("run-1", manifest={})
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="generate-1",
                run_id="run-1",
                idempotency_key="generation:run-1:1",
                intent_type="generate",
                payload={},
            )
        ]
    )
    uow.transition_task("generate-1", TaskState.LEASED)
    uow.transition_task("generate-1", TaskState.RUNNING)
    uow.transition_task("generate-1", TaskState.RESULT_RECEIVED)
    context = {
        "run_id": "run-1",
        "task_id": "generate-1",
        "idempotency_key": "generation:run-1:1",
        "skill_id": "generation",
        "skill_version": "0.2.0",
        "output_schema_id": "GenerationResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider": "stub",
        "model_or_tool": "stub-model",
        "input_snapshot_hash": "sha256:input",
    }
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id="generate-1",
        execution_context=context,
    )
    uow.transition_call("call-1", ExternalCallState.STARTED)
    raw_ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    uow.record_raw_and_transition(
        "call-1",
        raw_ref,
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        usage={"input_tokens": 3, "output_tokens": 2, "pricing_version": "test"},
    )
    payload = (
        _generation_payload()
        if status == "completed"
        else _non_scientific_payload(status)
    )
    result = AgentResult(
        result_id=f"result-{status}",
        external_call_id="call-1",
        run_id="run-1",
        task_id="generate-1",
        idempotency_key="generation:run-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="stub",
        model_or_tool="stub-model",
        input_snapshot_hash="sha256:input",
        status=status,
        payload=payload,
        recommended_actions=("run_deep_verification",),
        raw_artifact_ref=raw_ref,
    )
    uow.record_validated_and_submitted("call-1", payload, result)
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    return supervisor, result


# Mutation caught: treating partial/rejected/failed as completed or leaving them unapplied.
@pytest.mark.parametrize(
    ("status", "expected_event", "expected_task_state", "followup_exists"),
    [
        ("completed", "HypothesisContentCreated", "succeeded", True),
        ("partial", "AgentResultPartial", "pending", False),
        ("rejected", "AgentResultRejected", "failed", False),
        ("failed", "AgentResultFailed", "failed", False),
    ],
)
def test_handle_result_applies_each_status_with_explicit_atomic_semantics(
    tmp_path,
    status: str,
    expected_event: str,
    expected_task_state: str,
    followup_exists: bool,
) -> None:
    supervisor, result = _submitted_generation_result(tmp_path, status)

    commit = supervisor.handle_result(
        run_id="run-1",
        task_id="generate-1",
        result=result,
        expected_sequence=0,
    )

    expected_events = [expected_event, "TaskEnqueued"] if followup_exists else [expected_event]
    assert [event.event_type for event in commit.events] == expected_events
    assert supervisor.uow.task_state("generate-1") == expected_task_state
    assert supervisor.uow.external_call_state("call-1") == "domain_result_applied"
    with supervisor.uow.engine.connect() as connection:
        task_count = connection.execute(text("SELECT COUNT(*) FROM tasks")).scalar_one()
        cost_count = connection.execute(text("SELECT COUNT(*) FROM cost_entries")).scalar_one()
    assert task_count == (2 if followup_exists else 1)
    assert cost_count == 1
