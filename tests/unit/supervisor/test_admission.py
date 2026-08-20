import inspect
from decimal import Decimal

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.admission import AdmissionPolicy
from co_scientist.domain.review import ReviewPolicy, ReviewStage
from co_scientist.domain.states import ExternalCallState, RunState
from co_scientist.domain.task import NewTask
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.runtime.task_payload import WorkerTaskPayload
from co_scientist.supervisor.orchestrator import Supervisor
from tests._fenced_runtime import (
    acknowledge_result,
    budgeted_task,
    claim_running_task,
    execution_manifest,
    fenced_context,
)


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


def _ranking_result(*, result_id: str, prompt_hash: str, winner_id: str = "h-1") -> AgentResult:
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
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
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
        expected_sequence=1,
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
        expected_sequence=6,
        events=(
            NewEvent(
                event_type="MatchEvaluated",
                schema_version=2,
                payload={
                    **{
                        key: value
                        for key, value in first.model_dump(mode="json")["payload"].items()
                        if key not in {"schema_version", "decision_status", "winner_slot"}
                    },
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
    replayed = supervisor._rating_events_for_result("run-1", first)
    assert [event.payload["hypothesis_id"] for event in replayed] == ["h-1", "h-2"]
    conflicting = _ranking_result(
        result_id="result-2",
        prompt_hash="sha256:ranking-prompt",
        winner_id="h-2",
    )

    with pytest.raises(ValueError, match="duplicate match_id"):
        supervisor._rating_events_for_result("run-1", conflicting)


def test_supervisor_is_available_from_its_public_package() -> None:
    from co_scientist.supervisor import Supervisor as PublicSupervisor

    assert PublicSupervisor is Supervisor


def _admission_policy() -> AdmissionPolicy:
    return AdmissionPolicy(
        version="admission-v1",
        review_policy=ReviewPolicy(
            profile_id="manifest-policy",
            required_before_admission=(ReviewStage.FULL,),
        ),
        literature_novelty_required=False,
        duplicate_likelihood_threshold=0.5,
    )


def _admission_uow(tmp_path, *, filename: str = "admission.db") -> SqliteUnitOfWork:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / filename}")
    uow.create_schema()
    policy = _admission_policy()
    uow.create_started_run(
        "run-1",
        manifest={
            "admission_policies": {
                policy.version: policy.model_dump(mode="json"),
            }
        },
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=1,
        events=(
            NewEvent(
                event_type="TournamentEpochOpened",
                payload={
                    "epoch_id": "epoch-1",
                    "research_plan_version": 1,
                    "evaluation_rules_hash": "sha256:rules",
                    "ranking_prompt_hash": "sha256:prompt",
                    "judge_profile_hash": "sha256:judge",
                    "rating_policy_version": "elo-32-v1",
                    "admission_policy_version": "admission-v1",
                },
            ),
            NewEvent(
                event_type="HypothesisContentCreated",
                schema_version=2,
                payload={
                    "hypothesis_id": "h-1",
                    "content_id": "content-1",
                    "content_hash": "sha256:" + "a" * 64,
                    "research_plan_version": 1,
                    "generation_strategy": "causal contrast",
                },
            ),
            NewEvent(
                event_type="ReviewCompleted",
                schema_version=2,
                payload={
                    "review_id": "review-initial",
                    "hypothesis_id": "h-1",
                    "content_hash": "sha256:" + "a" * 64,
                    "research_plan_version": 1,
                    "stage": "initial_review",
                    "recommendation": "pass",
                    "safety_status": "passed",
                    "critical_flaws": [],
                },
            ),
            NewEvent(
                event_type="ReviewCompleted",
                schema_version=2,
                payload={
                    "review_id": "review-full",
                    "hypothesis_id": "h-1",
                    "content_hash": "sha256:" + "a" * 64,
                    "research_plan_version": 1,
                    "stage": "full_review",
                    "recommendation": "pass",
                    "safety_status": "not_assessed",
                    "critical_flaws": [],
                },
            ),
            NewEvent(
                event_type="ProximityAssessed",
                schema_version=2,
                payload={
                    "edge_id": "edge-1-2",
                    "research_plan_version": 1,
                    "left_id": "h-1",
                    "left_content_hash": "sha256:" + "a" * 64,
                    "right_id": "h-2",
                    "right_content_hash": "sha256:" + "b" * 64,
                    "similarity": 2,
                    "duplicate_likelihood": 0.1,
                    "rationale": "Distinct mechanisms.",
                },
            ),
        ),
        idempotency_key="admission-evidence",
    )
    return uow


# Mutation caught: retaining any public caller-supplied scientific verdict.
def test_admission_command_accepts_only_metadata_and_loads_manifest_evidence(tmp_path) -> None:
    uow = _admission_uow(tmp_path)
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="constructor-only"))

    assert tuple(inspect.signature(Supervisor.admit_hypothesis).parameters) == (
        "self",
        "run_id",
        "hypothesis_id",
        "expected_sequence",
        "idempotency_key",
    )
    outcome = supervisor.admit_hypothesis(
        run_id="run-1",
        hypothesis_id="h-1",
        expected_sequence=6,
        idempotency_key="admit-h-1",
    )

    assert outcome.decision.admitted
    assert outcome.entry is not None
    assert (outcome.entry.rating, outcome.entry.matches_played) == (1200.0, 0)
    assert outcome.commit is not None
    ready, entry, rating = outcome.commit.events
    assert (ready.event_type, ready.schema_version) == ("HypothesisTournamentReady", 2)
    assert ready.payload["review_ids"] == ("review-initial", "review-full")
    assert ready.payload["proximity_edge_ids"] == ("edge-1-2",)
    assert ready.payload["source_event_sequences"] == (2, 3, 4, 5, 6)
    assert entry.payload["content_hash"] == "sha256:" + "a" * 64
    assert rating.payload == {
        "epoch_id": "epoch-1",
        "hypothesis_id": "h-1",
        "rating": 1200.0,
        "rating_policy_version": "elo-32-v1",
    }


# Mutation caught: committing against a sequence newer than the evidence snapshot.
def test_admission_sequence_race_fails_with_normal_concurrency_error(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'admission-race.db'}"
    uow = _admission_uow(tmp_path, filename="admission-race.db")
    competing = SqliteUnitOfWork(database_url)
    original_load = uow.load
    load_count = 0

    def load_then_advance(run_id: str, after_sequence: int = 0):
        nonlocal load_count
        load_count += 1
        events = original_load(run_id, after_sequence)
        competing.commit_domain_batch(
            run_id=run_id,
            expected_sequence=6,
            events=(
                NewEvent(
                    event_type="HypothesisContentCreated",
                    schema_version=2,
                    payload={
                        "hypothesis_id": "h-1",
                        "content_id": "content-2",
                        "content_hash": "sha256:" + "c" * 64,
                        "research_plan_version": 1,
                        "generation_strategy": "revision",
                    },
                ),
            ),
            idempotency_key="competing-revision",
        )
        return events

    monkeypatch.setattr(uow, "load", load_then_advance)
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))

    with pytest.raises(ConcurrencyConflict, match="expected 6, got 7"):
        supervisor.admit_hypothesis(
            run_id="run-1",
            hypothesis_id="h-1",
            expected_sequence=6,
            idempotency_key="admit-racing-h-1",
        )

    assert load_count == 1
    assert not any(
        event.event_type == "HypothesisTournamentReady" for event in original_load("run-1")
    )


# Mutation caught: accepting an ahead token after a concurrent revision fills that sequence.
def test_admission_rejects_expected_sequence_ahead_of_loaded_evidence_tip(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'admission-ahead-race.db'}"
    uow = _admission_uow(tmp_path, filename="admission-ahead-race.db")
    competing = SqliteUnitOfWork(database_url)
    original_load = uow.load

    def load_then_advance(run_id: str, after_sequence: int = 0):
        events = original_load(run_id, after_sequence)
        competing.commit_domain_batch(
            run_id=run_id,
            expected_sequence=6,
            events=(
                NewEvent(
                    event_type="HypothesisContentCreated",
                    schema_version=2,
                    payload={
                        "hypothesis_id": "h-1",
                        "content_id": "content-2",
                        "content_hash": "sha256:" + "c" * 64,
                        "research_plan_version": 1,
                        "generation_strategy": "revision",
                    },
                ),
            ),
            idempotency_key="competing-ahead-revision",
        )
        return events

    monkeypatch.setattr(uow, "load", load_then_advance)
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))

    with pytest.raises(ConcurrencyConflict, match="expected 7, got 6"):
        supervisor.admit_hypothesis(
            run_id="run-1",
            hypothesis_id="h-1",
            expected_sequence=7,
            idempotency_key="admit-ahead-racing-h-1",
        )

    assert not any(
        event.event_type == "HypothesisTournamentReady" for event in original_load("run-1")
    )


# Mutation caught: evaluating mutable Run state before replaying a successful admission key.
def test_admission_same_key_replays_original_outcome_after_stream_and_state_advance(
    tmp_path,
) -> None:
    uow = _admission_uow(tmp_path, filename="admission-replay.db")
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    first = supervisor.admit_hypothesis(
        run_id="run-1",
        hypothesis_id="h-1",
        expected_sequence=6,
        idempotency_key="admit-replay-h-1",
    )
    assert first.commit is not None
    advanced = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=first.commit.last_sequence,
        events=(
            NewEvent(
                event_type="HypothesisContentCreated",
                schema_version=2,
                payload={
                    "hypothesis_id": "h-1",
                    "content_id": "content-2",
                    "content_hash": "sha256:" + "c" * 64,
                    "research_plan_version": 1,
                    "generation_strategy": "permitted task-2 revision",
                },
            ),
        ),
        idempotency_key="advance-after-admission",
    )
    uow.commit_lifecycle_batch(
        run_id="run-1",
        expected_sequence=advanced.last_sequence,
        events=(NewEvent(event_type="RunStopping", payload={}),),
        target_run_state=RunState.STOPPING,
        idempotency_key="stop-after-admission",
    )

    replayed = supervisor.admit_hypothesis(
        run_id="run-1",
        hypothesis_id="h-1",
        expected_sequence=6,
        idempotency_key="admit-replay-h-1",
    )

    assert replayed == first


# Mutation caught: replaying an admission key for a different hypothesis.
def test_admission_replay_validates_original_hypothesis_ownership(tmp_path) -> None:
    uow = _admission_uow(tmp_path, filename="admission-replay-owner.db")
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    first = supervisor.admit_hypothesis(
        run_id="run-1",
        hypothesis_id="h-1",
        expected_sequence=6,
        idempotency_key="admit-owned-by-h-1",
    )
    assert first.commit is not None

    with pytest.raises(ValueError, match="different admission"):
        supervisor.admit_hypothesis(
            run_id="run-1",
            hypothesis_id="h-2",
            expected_sequence=first.commit.last_sequence,
            idempotency_key="admit-owned-by-h-1",
        )


# Mutation caught: inserting a task without atomic, full Supervisor creator provenance.
def test_supervisor_enqueue_task_atomically_persists_full_provenance(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'enqueue.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest={},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    task = NewTask(
        task_id="generate-1",
        run_id="run-1",
        idempotency_key="generation:run-1:1",
        intent_type="generate",
        payload={"research_goal": "regeneration"},
    )

    commit = supervisor.enqueue_task(task=task, expected_sequence=1)

    assert [event.event_type for event in commit.events] == ["TaskEnqueued"]
    assert commit.events[0].payload == task.model_dump(mode="json")
    assert uow.task_state(task.task_id) == "pending"


def test_handle_result_atomically_applies_policy_owned_work_and_ignores_agent_actions(
    tmp_path,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'supervisor.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.enqueue_tasks(
        [
            budgeted_task(
                NewTask(
                    task_id="generate-1",
                    run_id="run-1",
                    idempotency_key="generation:run-1:1",
                    intent_type="generate",
                    payload={},
                )
            )
        ]
    )
    claimed = claim_running_task(uow, run_id="run-1", task_id="generate-1")
    context = fenced_context(
        {
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
        },
        claimed,
    ).model_dump(mode="json")
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id="generate-1",
        execution_context=context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.transition_call(
        "call-1",
        ExternalCallState.STARTED,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
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
        reservation_id=claimed.reservation_id,
        fence=claimed,
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
        attempt=claimed.attempt,
        reservation_id=claimed.reservation_id,
        lease_fence_fingerprint=context["lease_fence_fingerprint"],
        status="completed",
        payload=payload,
        recommended_actions=("run_deep_verification",),
        raw_artifact_ref=raw_ref,
    )
    uow.record_validated_and_submitted(
        "call-1",
        payload,
        result,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    acknowledge_result(uow, claimed)

    commit = Supervisor(
        uow=uow,
        review_policy=ReviewPolicy(profile_id="minimal"),
    ).handle_result(
        run_id="run-1",
        task_id="generate-1",
        result=result,
        expected_sequence=uow.load("run-1")[-1].sequence,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )

    assert [event.event_type for event in commit.events] == [
        "HypothesisContentCreated",
        "TaskEnqueued",
        "BudgetSettled",
    ]
    followup_event = commit.events[1].payload
    assert {
        key: followup_event[key]
        for key in ("task_id", "run_id", "idempotency_key", "intent_type", "created_by")
    } == {
        "task_id": "run-1:review:initial_review:h-1",
        "run_id": "run-1",
        "idempotency_key": "run-1:review:initial_review:h-1",
        "intent_type": "run_initial_review",
        "created_by": "supervisor",
    }
    followup_payload = WorkerTaskPayload.model_validate(followup_event["payload"])
    assert followup_payload.skill_id == "reflection"
    assert followup_payload.provider_id == "stub"
    assert followup_payload.inputs == {
        "hypothesis_id": "h-1",
        "content_hash": commit.events[0].payload["content_hash"],
        "review_stage": "initial_review",
    }
    assert uow.task_state("generate-1") == "succeeded"
    assert uow.task_state("run-1:review:initial_review:h-1") == "pending"
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
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.enqueue_tasks(
        [
            budgeted_task(
                NewTask(
                    task_id="generate-1",
                    run_id="run-1",
                    idempotency_key="generation:run-1:1",
                    intent_type="generate",
                    payload={},
                )
            )
        ]
    )
    claimed = claim_running_task(uow, run_id="run-1", task_id="generate-1")
    context = fenced_context(
        {
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
        },
        claimed,
    ).model_dump(mode="json")
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id="generate-1",
        execution_context=context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.transition_call(
        "call-1",
        ExternalCallState.STARTED,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
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
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    payload = _generation_payload() if status == "completed" else _non_scientific_payload(status)
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
        attempt=claimed.attempt,
        reservation_id=claimed.reservation_id,
        lease_fence_fingerprint=context["lease_fence_fingerprint"],
        status=status,
        payload=payload,
        recommended_actions=("run_deep_verification",),
        raw_artifact_ref=raw_ref,
    )
    uow.record_validated_and_submitted(
        "call-1",
        payload,
        result,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    acknowledge_result(uow, claimed)
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    return supervisor, result, claimed


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
    supervisor, result, claimed = _submitted_generation_result(tmp_path, status)

    commit = supervisor.handle_result(
        run_id="run-1",
        task_id="generate-1",
        result=result,
        expected_sequence=supervisor.uow.load("run-1")[-1].sequence,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )

    expected_events = (
        [expected_event, "TaskEnqueued", "BudgetSettled"]
        if followup_exists
        else [expected_event, "BudgetSettled"]
    )
    assert [event.event_type for event in commit.events] == expected_events
    assert supervisor.uow.task_state("generate-1") == expected_task_state
    assert supervisor.uow.external_call_state("call-1") == "domain_result_applied"
    with supervisor.uow.engine.connect() as connection:
        task_count = connection.execute(text("SELECT COUNT(*) FROM tasks")).scalar_one()
        cost_count = connection.execute(text("SELECT COUNT(*) FROM cost_entries")).scalar_one()
    assert task_count == (2 if followup_exists else 1)
    assert cost_count == 1
