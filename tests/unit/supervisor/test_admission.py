from decimal import Decimal

from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.review import NoveltyAssessment, NoveltyVerdict, ReviewPolicy
from co_scientist.domain.states import ExternalCallState, TaskState
from co_scientist.domain.task import NewTask
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.supervisor.orchestrator import Supervisor, evaluate_admission


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
    uow.transition_task("generate-1", TaskState.RESULT_RECEIVED)
    context = {
        "run_id": "run-1",
        "task_id": "generate-1",
        "idempotency_key": "generation:run-1:1",
        "skill_id": "generation",
        "skill_version": "0.1.0",
        "output_schema_version": 1,
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
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "h-1",
                "content_hash": "sha256:content",
                "title": "Candidate",
            }
        ]
    }
    result = AgentResult(
        result_id="result-1",
        external_call_id="call-1",
        run_id="run-1",
        task_id="generate-1",
        idempotency_key="generation:run-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
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

    assert [event.event_type for event in commit.events] == ["HypothesisContentCreated"]
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
