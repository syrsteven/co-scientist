import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.fake import FakeLLMProvider
from co_scientist.adapters.llm.replay import ReplayLLMProvider, ReplayMiss
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import SkillExecutor, build_skill_request
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.admission import AdmissionPolicy
from co_scientist.domain.review import (
    ReviewPolicy,
    ReviewStage,
)
from co_scientist.domain.states import RunState
from co_scientist.domain.task import NewTask
from co_scientist.domain.tournament import TournamentEpoch
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.runtime.external_calls import (
    ExternalCallRunner,
    prompt_hash,
    request_fingerprint,
)
from co_scientist.supervisor.orchestrator import Supervisor
from tests._fenced_runtime import (
    acknowledge_result,
    budgeted_task,
    claim_running_task,
    execution_manifest,
    fenced_context,
)

_OUTPUT_SCHEMAS = {
    "generation": "GenerationResultV1",
    "reflection": "ReflectionResultV1",
    "ranking": "RankingResultV1",
    "proximity": "ProximityResultV1",
    "evolution": "EvolutionResultV1",
    "meta_review": "MetaReviewResultV1",
}


def _create_running(uow: SqliteUnitOfWork, run_id: str = "run-1") -> None:
    uow.create_started_run(
        run_id,
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key=f"start:{run_id}:0",
    )


def test_supervisor_revalidates_persisted_schema_invalid_agent_result_before_effects(
    tmp_path: Path,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'malformed-supervisor.db'}")
    uow.create_schema()
    _create_running(uow)
    task = budgeted_task(
        NewTask(
            task_id="generation-task",
            run_id="run-1",
            idempotency_key="generation:run-1:1",
            intent_type="generate",
            payload={},
        )
    )
    uow.enqueue_tasks([task])
    claimed = claim_running_task(uow, run_id="run-1", task_id=task.task_id)
    context = fenced_context(
        {
            "run_id": "run-1",
            "task_id": task.task_id,
            "idempotency_key": task.idempotency_key,
            "skill_id": "generation",
            "skill_version": "0.2.0",
            "output_schema_id": "GenerationResultV1",
            "output_schema_version": 1,
            "research_plan_version": 1,
            "provider": "fake",
            "model_or_tool": "fake-v1",
            "input_snapshot_hash": "sha256:input",
            "prompt_hash": "sha256:prompt",
        },
        claimed,
    ).model_dump(mode="json")
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id=task.task_id,
        execution_context=context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.transition_call("call-1", "started", reservation_id=claimed.reservation_id, fence=claimed)
    raw_ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    uow.record_raw_and_transition(
        "call-1",
        raw_ref,
        "raw_response_persisted",
        usage={"input_tokens": 9, "output_tokens": 4, "cost_usd": "0.01"},
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    malformed_payload = {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [{"hypothesis_id": "h-1", "content_id": "c-1"}],
    }
    forged = AgentResult.model_construct(
        result_id="result-1",
        external_call_id="call-1",
        status="completed",
        payload=malformed_payload,
        raw_artifact_ref=raw_ref,
        **context,
    )
    uow.record_validated_and_submitted(
        "call-1",
        malformed_payload,
        forged,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    acknowledge_result(uow, claimed)

    with pytest.raises(ValidationError):
        Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal")).handle_result(
            "run-1",
            task.task_id,
            forged,
            expected_sequence=uow.load("run-1")[-1].sequence,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    assert not any(event.event_type == "HypothesisContentCreated" for event in uow.load("run-1"))
    assert uow.task_state(task.task_id) == "result_received"
    assert uow.external_call_state("call-1") == "agent_result_submitted"
    with uow.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM tasks")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM cost_entries")).scalar_one() == 0


def _valid_ranking_payload() -> dict[str, object]:
    ranking_prompt = Path("skills/ranking/prompts/system.md").read_text(encoding="utf-8")
    return {
        "schema_version": 1,
        "match_id": "match-1",
        "epoch_id": "epoch-1",
        "left_id": "h-1",
        "left_content_hash": "sha256:" + "a" * 64,
        "right_id": "h-2",
        "right_content_hash": "sha256:" + "b" * 64,
        "decision_status": "inconclusive",
        "winner_slot": None,
        "research_plan_version": 1,
        "evaluation_rules_hash": "sha256:rules",
        "ranking_prompt_hash": prompt_hash(ranking_prompt),
        "judge_profile_hash": "sha256:judge",
        "rating_policy_version": "elo-32-v1",
        "admission_policy_version": "admission-v1",
        "dimension_reasons": {},
        "confidence": 0.8,
        "unresolved_disagreements": [],
    }


def _valid_generation_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [
            {
                "schema_version": 1,
                "hypothesis_id": "h-1",
                "content_id": "c-1",
                "research_plan_version": 1,
                "title": "Mechanical gate",
                "claim": "Capsule strain precedes EMT commitment.",
                "mechanism_chain": ["strain", "YAP", "cell fate"],
                "assumptions": ["strain is sensed before commitment"],
                "predictions": ["normalizing strain reduces fibrosis"],
                "falsifiers": ["cell fate changes before strain"],
                "generation_strategy": "causal contrast",
            }
        ],
    }


def _event_result(
    *, skill_id: str, output_schema_id: str, payload: dict[str, object]
) -> AgentResult:
    return AgentResult(
        result_id="result-1",
        external_call_id="call-1",
        run_id="run-1",
        task_id="task-1",
        idempotency_key="task-1",
        skill_id=skill_id,
        skill_version="0.2.0",
        output_schema_id=output_schema_id,
        output_schema_version=1,
        research_plan_version=1,
        provider="fake",
        model_or_tool="fake-v1",
        input_snapshot_hash="sha256:input",
        prompt_hash="sha256:prompt",
        status="completed",
        payload=payload,
        raw_artifact_ref=ArtifactRef(
            path="raw/call-1/digest",
            sha256="sha256:digest",
            mime_type="application/json",
            byte_length=2,
        ),
    )


def test_reflection_builds_v2_review_and_independent_v1_novelty_events() -> None:
    novelty = {
        "assessment_id": "novelty-1",
        "hypothesis_id": "h-1",
        "content_hash": "sha256:content",
        "research_plan_version": 1,
        "verdict": "novel",
        "closest_prior_work_ids": ["paper-1"],
        "evidence_ids": ["evidence-1"],
    }
    payload = {
        "schema_version": 1,
        "research_plan_version": 1,
        "review_id": "review-1",
        "hypothesis_id": "h-1",
        "content_hash": "sha256:content",
        "stage": "full_review",
        "recommendation": "pass",
        "safety_status": "passed",
        "dimension_scores": {"novelty": 0.9},
        "critical_flaws": [],
        "evidence_ids": ["evidence-1"],
        "novelty_assessment": novelty,
    }

    review, novelty_event = Supervisor._events_for_result(
        _event_result(
            skill_id="reflection",
            output_schema_id="ReflectionResultV1",
            payload=payload,
        )
    )

    assert (review.event_type, review.schema_version) == ("ReviewCompleted", 2)
    assert review.model_dump(mode="json")["payload"] == {
        "research_plan_version": 1,
        "review_id": "review-1",
        "hypothesis_id": "h-1",
        "content_hash": "sha256:content",
        "stage": "full_review",
        "recommendation": "pass",
        "safety_status": "passed",
        "dimension_scores": {"novelty": 0.9},
        "critical_flaws": [],
        "evidence_ids": ["evidence-1"],
        "source_result_id": "result-1",
        "source_task_id": "task-1",
        "status": "completed",
    }
    assert (novelty_event.event_type, novelty_event.schema_version) == (
        "NoveltyAssessmentRecorded",
        1,
    )
    assert novelty_event.model_dump(mode="json")["payload"] == {
        **novelty,
        "source_result_id": "result-1",
        "source_task_id": "task-1",
        "status": "completed",
    }


@pytest.mark.parametrize(
    ("skill_id", "schema_id", "payload", "event_type", "expected_payload"),
    [
        (
            "ranking",
            "RankingResultV1",
            {
                **_valid_ranking_payload(),
                "decision_status": "decisive",
                "winner_slot": 2,
            },
            "MatchEvaluated",
            {
                key: value
                for key, value in _valid_ranking_payload().items()
                if key not in {"schema_version", "decision_status", "winner_slot"}
            }
            | {"decision": "decisive", "winner_id": "h-2"},
        ),
        (
            "proximity",
            "ProximityResultV1",
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "edge_id": "edge-1",
                "left_id": "h-1",
                "left_content_hash": "sha256:" + "a" * 64,
                "right_id": "h-2",
                "right_content_hash": "sha256:" + "b" * 64,
                "similarity": 2,
                "mechanism_overlap": ["YAP"],
                "duplicate_likelihood": 0.1,
                "cluster_suggestion": "distinct",
                "rationale": "Mechanisms differ.",
                "access_issues": [],
            },
            "ProximityAssessed",
            {
                "research_plan_version": 1,
                "edge_id": "edge-1",
                "left_id": "h-1",
                "left_content_hash": "sha256:" + "a" * 64,
                "right_id": "h-2",
                "right_content_hash": "sha256:" + "b" * 64,
                "similarity": 2,
                "mechanism_overlap": ["YAP"],
                "duplicate_likelihood": 0.1,
                "cluster_suggestion": "distinct",
                "rationale": "Mechanisms differ.",
                "access_issues": [],
            },
        ),
        (
            "meta_review",
            "MetaReviewResultV1",
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "source_content_hashes": {"h-1": "sha256:" + "a" * 64},
                "system_feedback": ["Add early timepoints."],
                "overview": "Coverage is broad.",
                "coverage_gaps": ["No early timepoint."],
                "safety_direction_check": "clear",
            },
            "MetaReviewCompleted",
            {
                "research_plan_version": 1,
                "source_content_hashes": {"h-1": "sha256:" + "a" * 64},
                "system_feedback": ["Add early timepoints."],
                "overview": "Coverage is broad.",
                "coverage_gaps": ["No early timepoint."],
                "safety_direction_check": "clear",
            },
        ),
    ],
)
def test_scientific_results_build_explicit_v2_events(
    skill_id: str,
    schema_id: str,
    payload: dict[str, object],
    event_type: str,
    expected_payload: dict[str, object],
) -> None:
    (event,) = Supervisor._events_for_result(
        _event_result(skill_id=skill_id, output_schema_id=schema_id, payload=payload)
    )

    assert (event.event_type, event.schema_version) == (event_type, 2)
    assert event.model_dump(mode="json")["payload"] == {
        **expected_payload,
        "source_result_id": "result-1",
        "source_task_id": "task-1",
        "status": "completed",
    }


def test_supervisor_rejects_persisted_noncanonical_skill_schema_pair_before_effects(
    tmp_path: Path,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'schema-routing.db'}")
    uow.create_schema()
    _create_running(uow)
    task = budgeted_task(
        NewTask(
            task_id="task-1",
            run_id="run-1",
            idempotency_key="task-1",
            intent_type="run_reflection",
            payload={},
        )
    )
    uow.enqueue_tasks([task])
    claimed = claim_running_task(uow, run_id="run-1", task_id=task.task_id)
    valid_context = fenced_context(
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "idempotency_key": "task-1",
            "skill_id": "generation",
            "skill_version": "0.2.0",
            "output_schema_id": "GenerationResultV1",
            "output_schema_version": 1,
            "research_plan_version": 1,
            "provider": "fake",
            "model_or_tool": "fake-v1",
            "input_snapshot_hash": "sha256:input",
            "prompt_hash": "sha256:prompt",
        },
        claimed,
    ).model_dump(mode="json")
    context = {**valid_context, "skill_id": "reflection"}
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id="task-1",
        execution_context=valid_context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    with uow.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE external_calls SET execution_context_json = :context "
                "WHERE external_call_id = 'call-1'"
            ),
            {"context": json.dumps(context, separators=(",", ":"), sort_keys=True)},
        )
    uow.transition_call("call-1", "started", reservation_id=claimed.reservation_id, fence=claimed)
    raw_ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    uow.record_raw_and_transition(
        "call-1",
        raw_ref,
        "raw_response_persisted",
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    forged = AgentResult.model_construct(
        result_id="result-1",
        external_call_id="call-1",
        status="completed",
        payload=_valid_generation_payload(),
        raw_artifact_ref=raw_ref,
        **context,
    )
    uow.record_validated_and_submitted(
        "call-1",
        _valid_generation_payload(),
        forged,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    acknowledge_result(uow, claimed)

    with pytest.raises(ValueError, match="canonical skill contract"):
        Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal")).handle_result(
            "run-1",
            "task-1",
            forged,
            expected_sequence=uow.load("run-1")[-1].sequence,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    assert not any(event.event_type == "HypothesisContentCreated" for event in uow.load("run-1"))
    assert uow.task_state("task-1") == "result_received"


async def _execute_ranking_result(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    active_epoch: bool = True,
    admitted_ids: frozenset[str] = frozenset({"h-1", "h-2"}),
) -> tuple[SqliteUnitOfWork, Exception | None]:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'ranking-validation.db'}")
    uow.create_schema()
    _create_running(uow)
    expected_sequence = 1
    if active_epoch:
        epoch = TournamentEpoch(
            epoch_id="epoch-1",
            research_plan_version=1,
            evaluation_rules_hash="sha256:rules",
            ranking_prompt_hash=str(_valid_ranking_payload()["ranking_prompt_hash"]),
            judge_profile_hash="sha256:judge",
            rating_policy_version="elo-32-v1",
            admission_policy_version="admission-v1",
            anchor_set_id="anchors-1",
        )
        seed_events = [NewEvent(event_type="TournamentEpochOpened", payload=epoch.model_dump())]
        for hypothesis_id in ("h-1", "h-2"):
            if hypothesis_id not in admitted_ids:
                continue
            seed_events.extend(
                (
                    NewEvent(
                        event_type="TournamentEntryCreated",
                        payload={
                            "epoch_id": "epoch-1",
                            "hypothesis_id": hypothesis_id,
                            "rating": 1200.0,
                        },
                    ),
                    NewEvent(
                        event_type="InitialRatingAssigned",
                        payload={
                            "epoch_id": "epoch-1",
                            "hypothesis_id": hypothesis_id,
                            "rating": 1200.0,
                        },
                    ),
                )
            )
        seeded = uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=1,
            events=tuple(seed_events),
            idempotency_key="ranking-seed",
        )
        expected_sequence = seeded.last_sequence
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal"))
    task = budgeted_task(
        NewTask(
            task_id="ranking-task",
            run_id="run-1",
            idempotency_key="ranking-task",
            intent_type="run_ranking",
            payload={},
        )
    )
    scheduled = supervisor.enqueue_task(task=task, expected_sequence=expected_sequence)
    expected_sequence = scheduled.last_sequence
    claimed = claim_running_task(uow, run_id="run-1", task_id=task.task_id)
    expected_sequence = uow.load("run-1")[-1].sequence
    runner = ExternalCallRunner(
        SimpleNamespace(
            uow=uow,
            artifacts=FilesystemArtifactStore(tmp_path / "ranking-artifacts"),
        )
    )
    try:
        result = await SkillExecutor(
            runner,
            FakeLLMProvider(
                [json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")]
            ),
        ).execute(
            call_id="ranking-call",
            skill_directory=Path("skills/ranking"),
            inputs={"comparison": "h-1 versus h-2"},
            context=fenced_context(
                AgentExecutionContext(
                    run_id="run-1",
                    task_id=task.task_id,
                    idempotency_key=task.idempotency_key,
                    skill_id="ranking",
                    skill_version="0.2.0",
                    output_schema_id="RankingResultV1",
                    output_schema_version=1,
                    research_plan_version=1,
                    provider="fake",
                    model_or_tool="fake-v1",
                    input_snapshot_hash="sha256:input",
                ),
                claimed,
            ),
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )
    except Exception as caught:  # noqa: BLE001 - fail-closed result is asserted below
        return uow, caught
    acknowledge_result(uow, claimed)
    error: Exception | None = None
    try:
        supervisor.handle_result(
            "run-1",
            task.task_id,
            result,
            expected_sequence=expected_sequence,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )
    except Exception as caught:  # noqa: BLE001 - fail-closed result is asserted below
        error = caught
    return uow, error


_INCOMPLETE_OR_INVALID_RANKING_CASES = [
    ("missing_match_id", "match_id", None, True),
    ("missing_epoch_id", "epoch_id", None, True),
    ("missing_left_id", "left_id", None, True),
    ("missing_right_id", "right_id", None, True),
    ("missing_decision", "decision_status", None, True),
    ("missing_plan", "research_plan_version", None, True),
    ("missing_rules", "evaluation_rules_hash", None, True),
    ("missing_prompt", "ranking_prompt_hash", None, True),
    ("missing_judge", "judge_profile_hash", None, True),
    ("missing_rating_policy", "rating_policy_version", None, True),
    ("missing_admission_policy", "admission_policy_version", None, True),
    ("wrong_plan", "research_plan_version", 2, True),
    ("wrong_rules", "evaluation_rules_hash", "sha256:wrong", True),
    ("wrong_prompt", "ranking_prompt_hash", "sha256:wrong", True),
    ("wrong_judge", "judge_profile_hash", "sha256:wrong", True),
    ("wrong_rating_policy", "rating_policy_version", "elo-wrong", True),
    ("wrong_admission_policy", "admission_policy_version", "admission-wrong", True),
    ("no_active_epoch", None, None, False),
]


@pytest.mark.parametrize(
    ("case", "field", "replacement", "active_epoch"),
    _INCOMPLETE_OR_INVALID_RANKING_CASES,
    ids=[case[0] for case in _INCOMPLETE_OR_INVALID_RANKING_CASES],
)
# Mutation caught: deriving MatchEvaluated before validating the complete ranking contract.
@pytest.mark.asyncio
async def test_completed_ranking_fails_closed_before_match_event(
    tmp_path: Path,
    case: str,
    field: str | None,
    replacement: object,
    active_epoch: bool,
) -> None:
    del case
    payload = _valid_ranking_payload()
    if field is not None and replacement is None:
        del payload[field]
    elif field is not None:
        payload[field] = replacement

    uow, error = await _execute_ranking_result(
        tmp_path,
        payload,
        active_epoch=active_epoch,
    )
    event_types = [event.event_type for event in uow.load("run-1")]

    assert "MatchEvaluated" not in event_types
    assert "RatingUpdated" not in event_types
    assert error is not None
    assert uow.task_state("ranking-task") in {"running", "result_received"}
    assert uow.external_call_state("ranking-call") in {
        "validation_failed",
        "agent_result_submitted",
    }


# Mutation caught: emitting two RatingUpdated events for one self-matched hypothesis.
@pytest.mark.asyncio
async def test_supervisor_rejects_self_match_without_event_pollution(tmp_path: Path) -> None:
    payload = _valid_ranking_payload()
    payload.update(
        {
            "right_id": "h-1",
            "decision_status": "decisive",
            "winner_slot": 1,
        }
    )

    uow, error = await _execute_ranking_result(tmp_path, payload)
    event_types = [event.event_type for event in uow.load("run-1")]

    assert "MatchEvaluated" not in event_types
    assert "RatingUpdated" not in event_types
    assert error is not None
    assert uow.task_state("ranking-task") == "running"
    assert uow.external_call_state("ranking-call") == "validation_failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("match_id", ""),
        ("epoch_id", ""),
        ("left_id", ""),
        ("right_id", ""),
        ("epoch_id", "bogus-epoch"),
    ],
    ids=["empty-match", "empty-epoch", "empty-left", "empty-right", "bogus-epoch"],
)
# Mutation caught: accepting empty identity or a non-active epoch after contract hashes match.
@pytest.mark.asyncio
async def test_supervisor_rejects_empty_identity_and_bogus_epoch_before_events(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = _valid_ranking_payload()
    payload[field] = value

    uow, error = await _execute_ranking_result(tmp_path, payload)
    event_types = [event.event_type for event in uow.load("run-1")]

    assert "MatchEvaluated" not in event_types
    assert "RatingUpdated" not in event_types
    assert error is not None
    assert uow.task_state("ranking-task") in {"running", "result_received"}
    assert uow.external_call_state("ranking-call") in {
        "validation_failed",
        "agent_result_submitted",
    }


@pytest.mark.parametrize("decision", ["inconclusive", "invalid", "needs_tiebreaker"])
@pytest.mark.parametrize("unadmitted_id", ["h-1", "h-2"], ids=["left", "right"])
# Mutation caught: checking participant admission only on the decisive rating branch.
@pytest.mark.asyncio
async def test_non_decisive_ranking_rejects_unadmitted_participant_without_events(
    tmp_path: Path,
    decision: str,
    unadmitted_id: str,
) -> None:
    payload = _valid_ranking_payload()
    payload["decision_status"] = decision
    admitted_ids = frozenset({"h-1", "h-2"} - {unadmitted_id})

    uow, error = await _execute_ranking_result(
        tmp_path,
        payload,
        admitted_ids=admitted_ids,
    )
    event_types = [event.event_type for event in uow.load("run-1")]

    assert "MatchEvaluated" not in event_types
    assert "RatingUpdated" not in event_types
    assert error is not None
    assert uow.task_state("ranking-task") == "result_received"
    assert uow.external_call_state("ranking-call") == "agent_result_submitted"


# Mutation caught: modifying raw bytes, violating FIFO order, or returning unstable fake IDs.
@pytest.mark.asyncio
async def test_fake_provider_returns_queued_raw_responses_in_order() -> None:
    provider = FakeLLMProvider([b'{"step":1}', b'{"step":2}'])

    first = await provider.invoke({"request": 1})
    second = await provider.invoke({"request": 2})

    assert (first.body, first.mime_type, first.provider_response_id) == (
        b'{"step":1}',
        "application/json",
        "fake-1",
    )
    assert (second.body, second.provider_response_id) == (b'{"step":2}', "fake-2")
    assert provider.call_count == 2


# Mutation caught: replaying by dict insertion order or returning a response for an unknown request.
@pytest.mark.asyncio
async def test_replay_provider_uses_canonical_fingerprint_and_fails_closed() -> None:
    recorded_request = {"skill": "generation", "input": {"b": 2, "a": 1}}
    fingerprint = request_fingerprint(recorded_request)
    provider = ReplayLLMProvider({fingerprint: b'{"hypotheses":[]}'})

    replayed = await provider.invoke({"input": {"a": 1, "b": 2}, "skill": "generation"})

    assert replayed.body == b'{"hypotheses":[]}'
    assert replayed.provider_response_id == f"replay-{fingerprint[:12]}"
    missing_request = {"skill": "reflection"}
    missing_fingerprint = request_fingerprint(missing_request)
    with pytest.raises(ReplayMiss, match=missing_fingerprint[:12]):
        await provider.invoke(missing_request)


# Mutation caught: bypassing ExternalCallRunner or changing the canonical skill request contract.
@pytest.mark.asyncio
async def test_skill_executor_uses_raw_first_runner_and_returns_agent_result(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'executor.db'}")
    uow.create_schema()
    _create_running(uow)
    uow.enqueue_tasks(
        [
            budgeted_task(
                NewTask(
                    task_id="task-1",
                    run_id="run-1",
                    idempotency_key="generation:run-1:1",
                    intent_type="generate",
                    payload={},
                )
            )
        ]
    )
    claimed = claim_running_task(uow, run_id="run-1", task_id="task-1")
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = ExternalCallRunner(SimpleNamespace(uow=uow, artifacts=artifacts))
    expected_request = build_skill_request(
        skill_directory=Path("skills/generation"),
        inputs={"research_goal": "test regeneration"},
        model="replay-v1",
    )
    raw_body = json.dumps(_valid_generation_payload(), separators=(",", ":")).encode()
    provider = ReplayLLMProvider({request_fingerprint(expected_request): raw_body})
    context = fenced_context(
        AgentExecutionContext(
            run_id="run-1",
            task_id="task-1",
            idempotency_key="generation:run-1:1",
            skill_id="generation",
            skill_version="0.2.0",
            output_schema_id="GenerationResultV1",
            output_schema_version=1,
            research_plan_version=1,
            provider="replay",
            model_or_tool="replay-v1",
            input_snapshot_hash="sha256:input",
        ),
        claimed,
    )

    result = await SkillExecutor(runner, provider).execute(
        call_id="call-1",
        skill_directory=Path("skills/generation"),
        inputs={"research_goal": "test regeneration"},
        context=context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )

    assert result.payload["schema_version"] == 1
    assert result.payload["hypotheses"][0]["hypothesis_id"] == "h-1"
    assert result.raw_artifact_ref.path.startswith("raw/call-1/")
    assert artifacts.read(result.raw_artifact_ref) == raw_body
    assert uow.external_call_state("call-1") == "agent_result_submitted"
    expected_prompt_hash = (
        "sha256:" + hashlib.sha256(expected_request["system_prompt"].encode("utf-8")).hexdigest()
    )
    assert result.prompt_hash == expected_prompt_hash
    assert uow.get_external_call("call-1").execution_context == {
        **context.model_dump(mode="json"),
        "prompt_hash": expected_prompt_hash,
    }


@pytest.mark.parametrize(
    ("context_override", "message"),
    [
        ({"skill_id": "reflection"}, "canonical skill contract"),
        ({"skill_version": "0.1.0"}, "canonical skill contract"),
        ({"output_schema_version": 2}, "unknown output schema"),
    ],
)
# Mutation caught: allowing execution context identity or schema version to drift from a skill.
@pytest.mark.asyncio
async def test_skill_executor_rejects_incompatible_context_before_provider_call(
    tmp_path,
    context_override,
    message: str,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'context.db'}")
    uow.create_schema()
    _create_running(uow)
    uow.enqueue_tasks(
        [
            budgeted_task(
                NewTask(
                    task_id="task-1",
                    run_id="run-1",
                    idempotency_key="generation:run-1:1",
                    intent_type="generate",
                    payload={},
                )
            )
        ]
    )
    claimed = claim_running_task(uow, run_id="run-1", task_id="task-1")
    runner = ExternalCallRunner(
        SimpleNamespace(
            uow=uow,
            artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
    )
    provider = FakeLLMProvider([b'{"hypotheses":[]}'])
    context_data = {
        "run_id": "run-1",
        "task_id": "task-1",
        "idempotency_key": "generation:run-1:1",
        "skill_id": "generation",
        "skill_version": "0.2.0",
        "output_schema_id": "GenerationResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider": "fake",
        "model_or_tool": "fake-v1",
        "input_snapshot_hash": "sha256:input",
        **context_override,
    }

    with pytest.raises(ValueError, match=message):
        await SkillExecutor(runner, provider).execute(
            call_id="call-1",
            skill_directory=Path("skills/generation"),
            inputs={},
            context=fenced_context(AgentExecutionContext(**context_data), claimed),
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    assert provider.call_count == 0


@pytest.mark.parametrize(
    ("raw_body", "error_type", "message"),
    [
        (b"[]", TypeError, "JSON object"),
        (b'{"score":NaN}', ValueError, "invalid JSON constant"),
    ],
)
# Mutation caught: accepting a non-object or non-standard constant as strict skill JSON.
@pytest.mark.asyncio
async def test_skill_executor_rejects_non_object_or_nonstandard_json_after_raw_persistence(
    tmp_path,
    raw_body: bytes,
    error_type: type[Exception],
    message: str,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'strict-json.db'}")
    uow.create_schema()
    _create_running(uow)
    uow.enqueue_tasks(
        [
            budgeted_task(
                NewTask(
                    task_id="task-1",
                    run_id="run-1",
                    idempotency_key="generation:run-1:1",
                    intent_type="generate",
                    payload={},
                )
            )
        ]
    )
    claimed = claim_running_task(uow, run_id="run-1", task_id="task-1")
    runner = ExternalCallRunner(
        SimpleNamespace(
            uow=uow,
            artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
    )

    with pytest.raises(error_type, match=message):
        await SkillExecutor(runner, FakeLLMProvider([raw_body])).execute(
            call_id="call-1",
            skill_directory=Path("skills/generation"),
            inputs={},
            context=fenced_context(
                AgentExecutionContext(
                    run_id="run-1",
                    task_id="task-1",
                    idempotency_key="generation:run-1:1",
                    skill_id="generation",
                    skill_version="0.2.0",
                    output_schema_id="GenerationResultV1",
                    output_schema_version=1,
                    research_plan_version=1,
                    provider="fake",
                    model_or_tool="fake-v1",
                    input_snapshot_hash="sha256:input",
                ),
                claimed,
            ),
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    assert uow.external_call_state("call-1") == "validation_failed"


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _CoreHarness:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _enrich_payloads(responses: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        for response in responses:
            payload = copy.deepcopy(response["payload"])
            if response["skill"] == "ranking":
                ranking_prompt = Path("skills/ranking/prompts/system.md").read_text(
                    encoding="utf-8"
                )
                payload["ranking_prompt_hash"] = prompt_hash(ranking_prompt)
            payloads.append(payload)
        return payloads

    @staticmethod
    def _task_id(index: int, response: dict) -> str:
        if response["skill"] == "reflection":
            return f"run-1:review:{response['stage']}:{response['hypothesis_id']}"
        return f"scenario:{response['skill']}:{index}"

    @staticmethod
    def _persisted_task_ids(uow: SqliteUnitOfWork) -> set[str]:
        with uow.engine.connect() as connection:
            rows = connection.execute(text("SELECT task_id FROM tasks")).all()
        return {row.task_id for row in rows}

    @staticmethod
    def _admit_ranking_participants(
        *,
        supervisor: Supervisor,
        payload: dict,
        expected_sequence: int,
    ) -> int:
        for hypothesis_id in (payload["left_id"], payload["right_id"]):
            admission = supervisor.admit_hypothesis(
                run_id="run-1",
                hypothesis_id=hypothesis_id,
                expected_sequence=expected_sequence,
                idempotency_key=f"admit:epoch-1:{hypothesis_id}",
            )
            if admission.entry is None or admission.commit is None:
                raise AssertionError(f"ranking participant admission failed: {admission.decision}")
            expected_sequence = admission.commit.last_sequence
        return expected_sequence

    def run_trace(self, trace_path: str) -> SimpleNamespace:
        return asyncio.run(self._run_trace(Path(trace_path)))

    async def _run_trace(self, trace_path: Path) -> SimpleNamespace:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if trace["trace_version"] != 1:
            raise ValueError("unsupported core trace version")
        responses = trace["responses"]
        payloads = self._enrich_payloads(responses)

        uow = SqliteUnitOfWork(f"sqlite:///{self.root / 'core-loop.db'}")
        uow.create_schema()
        admission_policy = AdmissionPolicy(
            version="admission-v1",
            review_policy=ReviewPolicy(
                profile_id="core-trace",
                required_before_admission=(ReviewStage.FULL,),
            ),
            literature_novelty_required=trace["policy"]["novelty_required"],
            duplicate_likelihood_threshold=trace["policy"]["duplicate_likelihood_threshold"],
        )
        uow.create_run(
            "run-1",
            manifest={
                **execution_manifest(),
                "trace_version": 1,
                "admission_policies": {
                    admission_policy.version: admission_policy.model_dump(mode="json")
                },
            },
        )
        state_history = [uow.run_state("run-1")]
        epoch = TournamentEpoch(
            epoch_id="epoch-1",
            research_plan_version=1,
            evaluation_rules_hash="sha256:rules",
            ranking_prompt_hash=prompt_hash(
                Path("skills/ranking/prompts/system.md").read_text(encoding="utf-8")
            ),
            judge_profile_hash="sha256:judge",
            rating_policy_version="elo-32-v1",
            admission_policy_version="admission-v1",
            anchor_set_id="anchors-1",
        )
        started = uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=0,
            events=(
                NewEvent(event_type="RunStarted", payload={}),
                NewEvent(
                    event_type="TournamentEpochOpened",
                    payload=epoch.model_dump(mode="json"),
                ),
            ),
            target_run_state=RunState.RUNNING,
            idempotency_key="start:run-1",
        )
        state_history.append(uow.run_state("run-1"))
        expected_sequence = started.last_sequence
        supervisor = Supervisor(
            uow=uow,
            review_policy=ReviewPolicy(
                profile_id="core-trace",
                required_before_admission=(ReviewStage.FULL,),
            ),
        )
        provider = FakeLLMProvider(
            [
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                for payload in payloads
            ]
        )
        runner = ExternalCallRunner(
            SimpleNamespace(
                uow=uow,
                artifacts=FilesystemArtifactStore(self.root / "artifacts"),
            )
        )

        for index, (response, payload) in enumerate(zip(responses, payloads, strict=True)):
            if response["skill"] == "ranking":
                expected_sequence = self._admit_ranking_participants(
                    supervisor=supervisor,
                    payload=payload,
                    expected_sequence=expected_sequence,
                )
            task_id = self._task_id(index, response)
            try:
                uow.task_state(task_id)
            except KeyError:
                scheduled = supervisor.enqueue_task(
                    task=budgeted_task(
                        NewTask(
                            task_id=task_id,
                            run_id="run-1",
                            idempotency_key=task_id,
                            intent_type=f"run_{response['skill']}",
                            payload={
                                key: value for key, value in response.items() if key != "payload"
                            },
                        )
                    ),
                    expected_sequence=expected_sequence,
                )
                expected_sequence = scheduled.last_sequence
            claimed = claim_running_task(uow, run_id="run-1", task_id=task_id)
            expected_sequence = uow.load("run-1")[-1].sequence
            inputs = {
                "trace_index": index,
                **{key: value for key, value in response.items() if key != "payload"},
            }
            input_hash = _content_hash(inputs)
            result = await SkillExecutor(runner, provider).execute(
                call_id=f"call-{index}",
                skill_directory=Path("skills") / response["skill"],
                inputs=inputs,
                context=fenced_context(
                    AgentExecutionContext(
                        run_id="run-1",
                        task_id=task_id,
                        idempotency_key=task_id,
                        skill_id=response["skill"],
                        skill_version="0.2.0",
                        output_schema_id=_OUTPUT_SCHEMAS[response["skill"]],
                        output_schema_version=1,
                        research_plan_version=1,
                        provider="fake",
                        model_or_tool="fake-v1",
                        input_snapshot_hash=input_hash,
                    ),
                    claimed,
                ),
                reservation_id=claimed.reservation_id,
                fence=claimed,
            )
            acknowledge_result(uow, claimed)
            committed = supervisor.handle_result(
                run_id="run-1",
                task_id=task_id,
                result=result,
                expected_sequence=expected_sequence,
                reservation_id=claimed.reservation_id,
                fence=claimed,
            )
            expected_sequence = committed.last_sequence

        events = uow.load("run-1")
        child_events = [
            event
            for event in events
            if event.event_type == "HypothesisContentCreated"
            and event.payload.get("parent_content_ids")
        ]
        if len(child_events) != 1:
            raise ValueError("expected exactly one committed Evolution child")
        child_payload = child_events[0].payload
        child_id = child_payload.get("hypothesis_id")
        child_content_hash = child_payload.get("content_hash")
        if child_id is None or child_content_hash is None:
            raise ValueError("committed Evolution child identity is incomplete")
        if not isinstance(child_id, str) or not isinstance(child_content_hash, str):
            raise TypeError("committed Evolution child identity must be strings")
        admission = supervisor.admit_hypothesis(
            run_id="run-1",
            hypothesis_id=child_id,
            expected_sequence=expected_sequence,
            idempotency_key=f"admit:epoch-1:{child_id}",
        )
        if admission.entry is None or admission.commit is None:
            raise AssertionError(f"child admission failed: {admission.decision}")
        expected_sequence = admission.commit.last_sequence

        finalization = NewTask(
            task_id="finalize:run-1",
            run_id="run-1",
            idempotency_key="finalize:run-1",
            intent_type="finalize_run",
            payload={"reason": "trace_exhausted", "budget_estimate": {}},
        )
        uow.commit_lifecycle_batch(
            run_id="run-1",
            expected_sequence=expected_sequence,
            events=(
                NewEvent(
                    event_type="StopPolicyTriggered",
                    payload={"checkpoint_id": "fixture", "reason": "trace_exhausted"},
                ),
                NewEvent(
                    event_type="RunStopping",
                    payload={"checkpoint_id": "fixture", "reason": "trace_exhausted"},
                ),
                NewEvent(
                    event_type="FinalizationRequested",
                    payload={"checkpoint_id": "fixture", "task_id": finalization.task_id},
                ),
                NewEvent(
                    event_type="TaskEnqueued",
                    payload=finalization.model_dump(mode="json"),
                ),
            ),
            target_run_state=RunState.STOPPING,
            followup_tasks=(finalization,),
            idempotency_key="fixture-finalization",
        )
        state_history.append(uow.run_state("run-1"))
        fence = claim_running_task(uow, run_id="run-1", task_id=finalization.task_id)
        acknowledge_result(uow, fence)
        supervisor.complete_finalization(
            run_id="run-1",
            expected_sequence=uow.load("run-1")[-1].sequence,
            lease_fence=fence,
        )
        state_history.append(uow.run_state("run-1"))
        committed_events = uow.load("run-1")
        return SimpleNamespace(
            final_state=uow.run_state("run-1"),
            state_history=state_history,
            persisted_task_ids=self._persisted_task_ids(uow),
            task_enqueued_events=tuple(
                event for event in committed_events if event.event_type == "TaskEnqueued"
            ),
            child=SimpleNamespace(initial_rating=admission.entry.rating),
        )


@pytest.fixture
def core_harness(tmp_path) -> _CoreHarness:
    return _CoreHarness(tmp_path)


# Mutation caught: bypassing the real core loop, leaking task authority, skipping stopping,
# or carrying a parent rating into the evolved child.
def test_fake_trace_reaches_finalization_without_agent_created_tasks(core_harness) -> None:
    result = core_harness.run_trace("tests/scenario/fixtures/core_loop_trace.json")
    assert result.final_state == "completed"
    assert result.state_history[-2:] == ["stopping", "completed"]
    assert result.persisted_task_ids == {
        event.payload["task_id"] for event in result.task_enqueued_events
    }
    assert all(event.payload["created_by"] == "supervisor" for event in result.task_enqueued_events)
    assert result.child.initial_rating == 1200.0


def _write_trace_variant(tmp_path: Path, mutate) -> Path:
    trace = json.loads(
        Path("tests/scenario/fixtures/core_loop_trace.json").read_text(encoding="utf-8")
    )
    mutate(trace)
    destination = tmp_path / "trace.json"
    destination.write_text(json.dumps(trace), encoding="utf-8")
    return destination


@pytest.mark.parametrize("missing_field", ["safety_status", "duplicate_likelihood"])
# Mutation caught: admitting when a required scientific verdict is absent from committed results.
def test_fake_trace_fails_closed_when_admission_evidence_is_missing(
    core_harness,
    tmp_path: Path,
    missing_field: str,
) -> None:
    def remove_field(trace: dict) -> None:
        if missing_field == "safety_status":
            response = next(
                item
                for item in trace["responses"]
                if item.get("hypothesis_id") == "h-3" and item.get("stage") == "initial_review"
            )
        else:
            response = next(
                item
                for item in trace["responses"]
                if item["skill"] == "proximity" and item["payload"].get("left_id") == "h-3"
            )
        response["payload"].pop(missing_field)

    trace_path = _write_trace_variant(tmp_path, remove_field)

    with pytest.raises(ValueError, match=missing_field):
        core_harness.run_trace(str(trace_path))


# Mutation caught: ignoring the committed duplicate likelihood or its explicit policy threshold.
def test_fake_trace_rejects_child_at_or_above_duplicate_threshold(
    core_harness,
    tmp_path: Path,
) -> None:
    def mark_duplicate(trace: dict) -> None:
        response = next(
            item
            for item in trace["responses"]
            if item["skill"] == "proximity" and item["payload"].get("left_id") == "h-3"
        )
        response["payload"]["duplicate_likelihood"] = 0.5

    trace_path = _write_trace_variant(tmp_path, mark_duplicate)

    with pytest.raises(AssertionError, match="child admission failed"):
        core_harness.run_trace(str(trace_path))
