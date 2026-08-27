from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.fake import FakeLLMProvider
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import LiteratureToolExecutor, SkillExecutor
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import ExternalCallState, TaskState
from co_scientist.domain.task import NewTask
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash, request_fingerprint
from co_scientist.skills.loader import core_skill_directory
from co_scientist.supervisor.orchestrator import Supervisor
from tests._fenced_runtime import claim_running_task, fenced_context

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _running_executor(
    tmp_path: Path,
    *,
    skill_id: str,
    schema_id: str,
    inputs: dict[str, object],
    response: bytes,
    budget: dict[str, object] | None = None,
) -> tuple[SqliteUnitOfWork, ExternalCallRunner, FakeLLMProvider, object, AgentExecutionContext]:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / f'{skill_id}.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest={"execution_contract_version": 3, "budget": budget or {}},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    directory = core_skill_directory(skill_id)
    task = NewTask(
        task_id=f"task-{skill_id}",
        run_id="run-1",
        idempotency_key=f"task:{skill_id}",
        intent_type=f"run_{skill_id}",
        payload={
            "skill_id": skill_id,
            "skill_version": "0.2.0",
            "output_schema_id": schema_id,
            "output_schema_version": 1,
            "research_plan_version": 1,
            "provider_id": "fake",
            "model_or_tool": "fake-v1",
            "inputs": inputs,
            "input_snapshot_hash": request_fingerprint(inputs),
            "prompt_hash": prompt_hash(
                (directory / "prompts/system.md").read_text(encoding="utf-8")
            ),
            "budget_estimate": {
                "model_calls": 1,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": "0",
                "hypotheses": 0,
                "matches": 0,
            },
        },
    )
    uow.enqueue_tasks((task,))
    claimed = claim_running_task(uow, run_id="run-1", task_id=task.task_id)
    context = fenced_context(
        AgentExecutionContext(
            run_id="run-1",
            task_id=task.task_id,
            idempotency_key=task.idempotency_key,
            skill_id=skill_id,
            skill_version="0.2.0",
            output_schema_id=schema_id,
            output_schema_version=1,
            research_plan_version=1,
            provider="fake",
            model_or_tool="fake-v1",
            input_snapshot_hash=request_fingerprint(inputs),
            prompt_hash=prompt_hash(
                (directory / "prompts/system.md").read_text(encoding="utf-8")
            ),
        ),
        claimed,
    )
    runner = ExternalCallRunner(
        SimpleNamespace(
            uow=uow,
            artifacts=FilesystemArtifactStore(tmp_path / f"{skill_id}-artifacts"),
        )
    )
    return uow, runner, FakeLLMProvider([response]), claimed, context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("skill_id", "schema_id", "inputs", "payload"),
    [
        (
            "reflection",
            "ReflectionResultV1",
            {
                "hypothesis_id": "h-scheduled",
                "content_hash": HASH_A,
                "review_stage": "initial_review",
            },
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "review_id": "review-tampered",
                "hypothesis_id": "h-other",
                "content_hash": HASH_B,
                "stage": "initial_review",
                "recommendation": "pass",
                "safety_status": "passed",
                "dimension_scores": {},
                "critical_flaws": [],
                "evidence_ids": [],
            },
        ),
        (
            "proximity",
            "ProximityResultV1",
            {
                "edge_id": "edge-scheduled",
                "left_id": "h-1",
                "left_content_hash": HASH_A,
                "right_id": "h-2",
                "right_content_hash": HASH_B,
            },
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "edge_id": "edge-other",
                "left_id": "h-2",
                "left_content_hash": HASH_B,
                "right_id": "h-3",
                "right_content_hash": HASH_C,
                "similarity": 2,
                "mechanism_overlap": [],
                "duplicate_likelihood": 0.1,
                "cluster_suggestion": "distinct",
                "rationale": "A schema-valid result for another existing pair.",
                "access_issues": [],
            },
        ),
        (
            "ranking",
            "RankingResultV1",
            {
                "match_id": "match-scheduled",
                "epoch_id": "epoch-1",
                "left_id": "h-1",
                "left_content_hash": HASH_A,
                "right_id": "h-2",
                "right_content_hash": HASH_B,
                "research_plan_version": 1,
                "evaluation_rules_hash": "sha256:rules",
                "ranking_prompt_hash": "sha256:ranking",
                "judge_profile_hash": "sha256:judge",
                "rating_policy_version": "elo-32-v1",
                "admission_policy_version": "admission-v1",
            },
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "match_id": "match-other",
                "epoch_id": "epoch-1",
                "left_id": "h-2",
                "left_content_hash": HASH_B,
                "right_id": "h-3",
                "right_content_hash": HASH_C,
                "evaluation_rules_hash": "sha256:rules",
                "ranking_prompt_hash": "sha256:ranking",
                "judge_profile_hash": "sha256:judge",
                "rating_policy_version": "elo-32-v1",
                "admission_policy_version": "admission-v1",
                "decision_status": "inconclusive",
                "winner_slot": None,
                "dimension_reasons": {},
                "confidence": 0.8,
                "unresolved_disagreements": [],
            },
        ),
    ],
)
async def test_schema_valid_result_for_different_task_inputs_fails_raw_first(
    tmp_path: Path,
    skill_id: str,
    schema_id: str,
    inputs: dict[str, object],
    payload: dict[str, object],
) -> None:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    uow, runner, provider, claimed, context = _running_executor(
        tmp_path,
        skill_id=skill_id,
        schema_id=schema_id,
        inputs=inputs,
        response=raw,
    )

    with pytest.raises(ValueError, match="task inputs"):
        await SkillExecutor(runner, provider).execute(
            call_id=f"call-{skill_id}",
            skill_directory=core_skill_directory(skill_id),
            inputs=inputs,
            context=context,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    call = uow.get_external_call(f"call-{skill_id}")
    assert call.state is ExternalCallState.VALIDATION_FAILED
    assert call.raw_artifact_ref is not None
    assert call.validated_payload is None


@pytest.mark.asyncio
async def test_invalid_attempt_consumes_hard_call_limit_before_retry(tmp_path: Path) -> None:
    inputs: dict[str, object] = {
        "hypothesis_id": "h-scheduled",
        "content_hash": HASH_A,
        "review_stage": "initial_review",
    }
    payload = {
        "schema_version": 1,
        "research_plan_version": 1,
        "review_id": "review-other",
        "hypothesis_id": "h-other",
        "content_hash": HASH_B,
        "stage": "initial_review",
        "recommendation": "pass",
        "safety_status": "passed",
        "dimension_scores": {},
        "critical_flaws": [],
        "evidence_ids": [],
    }
    uow, runner, provider, claimed, context = _running_executor(
        tmp_path,
        skill_id="reflection",
        schema_id="ReflectionResultV1",
        inputs=inputs,
        response=json.dumps(payload).encode(),
        budget={"max_model_calls": 1},
    )
    with pytest.raises(ValueError, match="task inputs"):
        await SkillExecutor(runner, provider).execute(
            call_id="call-attempt-1",
            skill_directory=core_skill_directory("reflection"),
            inputs=inputs,
            context=context,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    recovery = uow.recover_expired_leases(
        run_id="run-1", now=claimed.lease_expires_at + timedelta(seconds=1)
    )
    assert recovery[0].action == "requeued"
    retry = uow.claim_next_task(
        run_id="run-1",
        worker_id="retry-worker",
        lease_token="retry-token",
        now=claimed.lease_expires_at + timedelta(seconds=2),
        lease_duration=timedelta(minutes=5),
    )

    assert retry.status == "budget_exhausted"
    assert retry.task is None
    assert provider.call_count == 1
    assert uow.task_state(claimed.task_id) == "failed"
    snapshot = uow.load_budget_snapshot("run-1")
    assert snapshot.settled.model_calls == 1
    assert snapshot.actively_reserved.model_calls == 0
    assert snapshot.hard_limit_reached is True
    assert not any(
        event.event_type.startswith(("Hypothesis", "Review", "Proximity", "Match"))
        for event in uow.load("run-1")
    )


@pytest.mark.asyncio
async def test_literature_summary_rejects_sources_outside_scheduled_pmids_raw_first(
    tmp_path: Path,
) -> None:
    inputs: dict[str, object] = {
        "query": "lens regeneration",
        "pmids": ["9999"],
    }
    raw = Path("tests/scenario/fixtures/pubmed_summary_lens.json").read_bytes()
    uow, runner, provider, claimed, context = _running_executor(
        tmp_path,
        skill_id="meta_review",
        schema_id="MetaReviewResultV1",
        inputs=inputs,
        response=raw,
    )

    with pytest.raises(ValueError, match="task inputs"):
        await LiteratureToolExecutor(runner, provider).execute(
            call_id="call-literature",
            operation="summary",
            inputs=inputs,
            context=context,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    call = uow.get_external_call("call-literature")
    assert call.state is ExternalCallState.VALIDATION_FAILED
    assert call.raw_artifact_ref is not None
    assert call.validated_payload is None


def test_supervisor_rejects_durably_submitted_result_for_other_hypothesis(
    tmp_path: Path,
) -> None:
    inputs = {
        "hypothesis_id": "h-scheduled",
        "content_hash": HASH_A,
        "review_stage": "initial_review",
    }
    payload = {
        "schema_version": 1,
        "research_plan_version": 1,
        "review_id": "review-other",
        "hypothesis_id": "h-other",
        "content_hash": HASH_B,
        "stage": "initial_review",
        "recommendation": "pass",
        "safety_status": "passed",
        "dimension_scores": {},
        "critical_flaws": [],
        "evidence_ids": [],
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    uow, _runner, _provider, claimed, context = _running_executor(
        tmp_path,
        skill_id="reflection",
        schema_id="ReflectionResultV1",
        inputs=inputs,
        response=raw,
    )
    uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=uow.load("run-1")[-1].sequence,
        events=(
            NewEvent(
                event_type="HypothesisContentCreated",
                schema_version=2,
                payload={"hypothesis_id": "h-scheduled", "content_hash": HASH_A},
            ),
            NewEvent(
                event_type="HypothesisContentCreated",
                schema_version=2,
                payload={"hypothesis_id": "h-other", "content_hash": HASH_B},
            ),
        ),
        idempotency_key="seed:contents",
    )
    ref = ArtifactRef(
        path="raw/call-reflection/digest",
        sha256="sha256:" + "d" * 64,
        mime_type="application/json",
        byte_length=len(raw),
    )
    uow.plan_external_call(
        "call-reflection",
        "sha256:request",
        run_id="run-1",
        task_id=claimed.task_id,
        execution_context=context.model_dump(mode="json"),
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.transition_call(
        "call-reflection",
        ExternalCallState.STARTED,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.record_raw_and_transition(
        "call-reflection",
        ref,
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    result = AgentResult(
        result_id="result-other",
        external_call_id="call-reflection",
        status="completed",
        payload=payload,
        raw_artifact_ref=ref,
        **context.model_dump(),
    )
    uow.record_validated_and_submitted(
        "call-reflection",
        payload,
        result,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )
    uow.acknowledge_task(fence=claimed, target_state=TaskState.RESULT_RECEIVED)
    before = tuple(event.sequence for event in uow.load("run-1"))

    with pytest.raises(ValueError, match="task inputs"):
        Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal")).handle_result(
            "run-1",
            claimed.task_id,
            result,
            expected_sequence=uow.load("run-1")[-1].sequence,
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    assert tuple(event.sequence for event in uow.load("run-1")) == before
    with uow.engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM events WHERE event_type = 'ReviewCompleted'")
        ).scalar_one() == 0
