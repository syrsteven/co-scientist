from decimal import Decimal

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.budget import CostEntry
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.supervisor.orchestrator import Supervisor


def _context(*, task_id: str = "generate-1", key: str = "generation:1") -> dict[str, object]:
    return {
        "run_id": "run-1",
        "task_id": task_id,
        "idempotency_key": key,
        "skill_id": "generation",
        "skill_version": "0.2.0",
        "output_schema_id": "GenerationResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider": "stub",
        "model_or_tool": "stub-model",
        "input_snapshot_hash": "sha256:input",
    }


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
                "title": "Stopping settlement",
                "claim": "Already-submitted results may settle while stopping.",
                "mechanism_chain": ["submit", "stop", "settle"],
                "assumptions": [],
                "predictions": [],
                "falsifiers": [],
                "generation_strategy": "state fence fixture",
                "parent_content_ids": [],
                "supersedes_content_id": None,
                "content_hash": None,
            }
        ],
    }


def _submitted_generation(tmp_path) -> tuple[Supervisor, AgentResult]:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'fences.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest={},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    task = NewTask(
        task_id="generate-1",
        run_id="run-1",
        idempotency_key="generation:1",
        intent_type="generate",
        payload={},
    )
    uow.enqueue_tasks((task,))
    uow.transition_task(task.task_id, TaskState.LEASED)
    uow.transition_task(task.task_id, TaskState.RUNNING)
    uow.transition_task(task.task_id, TaskState.RESULT_RECEIVED)
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id=task.task_id,
        execution_context=_context(),
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
            "input_tokens": 3,
            "output_tokens": 2,
            "cost_usd": "0.01",
            "pricing_version": "test",
        },
    )
    payload = _generation_payload()
    result = AgentResult(
        result_id="result-1",
        external_call_id="call-1",
        run_id="run-1",
        task_id=task.task_id,
        idempotency_key=task.idempotency_key,
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
        raw_artifact_ref=raw_ref,
    )
    uow.record_validated_and_submitted("call-1", payload, result)
    return Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="minimal")), result


def _enter_state(supervisor: Supervisor, target: RunState) -> None:
    uow = supervisor.uow
    if target in {RunState.COMPLETED, RunState.COMPLETED_PARTIAL}:
        stopping = uow.commit_lifecycle_batch(
            run_id="run-1",
            expected_sequence=1,
            events=(NewEvent(event_type="RunStopping", payload={}),),
            target_run_state=RunState.STOPPING,
            idempotency_key="enter-stopping",
        )
        terminal_event = (
            "RunCompleted" if target is RunState.COMPLETED else "RunCompletedPartial"
        )
        uow.commit_lifecycle_batch(
            run_id="run-1",
            expected_sequence=stopping.last_sequence,
            events=(
                NewEvent(event_type="FinalizationCompleted", payload={}),
                NewEvent(event_type=terminal_event, payload={}),
            ),
            target_run_state=target,
            idempotency_key=f"enter-{target.value}",
        )
        return
    terminal_event = "RunFailed" if target is RunState.FAILED else "RunCancelled"
    uow.commit_lifecycle_batch(
        run_id="run-1",
        expected_sequence=1,
        events=(NewEvent(event_type=terminal_event, payload={}),),
        target_run_state=target,
        idempotency_key=f"enter-{target.value}",
    )


def _snapshot(uow: SqliteUnitOfWork) -> tuple[object, ...]:
    with uow.engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT state, current_sequence, "
                "(SELECT COUNT(*) FROM events WHERE run_id = 'run-1'), "
                "(SELECT COUNT(*) FROM tasks WHERE run_id = 'run-1'), "
                "(SELECT COUNT(*) FROM external_calls WHERE run_id = 'run-1'), "
                "(SELECT COUNT(*) FROM cost_entries WHERE run_id = 'run-1'), "
                "(SELECT state FROM tasks WHERE task_id = 'generate-1'), "
                "(SELECT state FROM external_calls WHERE external_call_id = 'call-1'), "
                "(SELECT applied_domain_sequence FROM external_calls "
                " WHERE external_call_id = 'call-1') "
                "FROM runs WHERE run_id = 'run-1'"
            )
        ).one()


def _late_task(task_id: str, *, intent_type: str = "run_initial_review") -> NewTask:
    return NewTask(
        task_id=task_id,
        run_id="run-1",
        idempotency_key=task_id,
        intent_type=intent_type,
        payload={},
    )


def _attempt_terminal_mutation(
    mutation: str, supervisor: Supervisor, result: AgentResult, sequence: int
) -> None:
    uow = supervisor.uow
    if mutation == "supervisor_enqueue":
        supervisor.enqueue_task(task=_late_task("supervisor-late"), expected_sequence=sequence)
    elif mutation == "uow_enqueue":
        uow.enqueue_tasks((_late_task("uow-late"),))
    elif mutation == "followup":
        task = _late_task("followup-late")
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=sequence,
            events=(NewEvent(event_type="TaskEnqueued", payload=task.model_dump(mode="json")),),
            followup_tasks=(task,),
            idempotency_key="late-followup",
        )
    elif mutation == "call_plan":
        uow.plan_external_call(
            "call-late",
            "sha256:late",
            run_id="run-1",
            task_id="generate-1",
            execution_context=_context(),
        )
    elif mutation == "scientific_event":
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="ReviewCompleted",
                    schema_version=2,
                    payload={"hypothesis_id": "h-1", "review_id": "late"},
                ),
            ),
            idempotency_key="late-science",
        )
    elif mutation == "direct_append":
        uow.append(
            "run-1",
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="ReviewCompleted",
                    schema_version=2,
                    payload={"hypothesis_id": "h-1", "review_id": "late"},
                ),
            ),
        )
    elif mutation == "run_science_batch":
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="ResearchPlanAccepted",
                    payload={"version": 2, "action": "new_epoch"},
                ),
            ),
            idempotency_key="late-plan-science",
        )
    elif mutation == "run_science_direct":
        uow.append(
            "run-1",
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="TournamentEpochClosed",
                    payload={"epoch_id": "epoch-1", "plan_version": 1},
                ),
            ),
        )
    elif mutation == "result_application":
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=sequence,
            events=(
                NewEvent(
                    event_type="HypothesisContentCreated",
                    schema_version=2,
                    payload={"hypothesis_id": "h-1", "content_id": "late"},
                ),
            ),
            task_mutations=(TaskMutation.succeed("generate-1"),),
            external_call_id=result.external_call_id,
            idempotency_key=result.idempotency_key,
        )
    elif mutation == "cost":
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=sequence,
            events=(NewEvent(event_type="AgentResultFailed", payload={}),),
            cost_entries=(
                CostEntry(
                    cost_entry_id="cost-late",
                    run_id="run-1",
                    external_call_id="call-1",
                    cost_usd=Decimal("0.01"),
                    pricing_version="test",
                ),
            ),
            idempotency_key="late-cost",
        )
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize(
    "terminal_state",
    [
        RunState.COMPLETED,
        RunState.COMPLETED_PARTIAL,
        RunState.FAILED,
        RunState.CANCELLED,
    ],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "supervisor_enqueue",
        "uow_enqueue",
        "followup",
        "call_plan",
        "scientific_event",
        "direct_append",
        "run_science_batch",
        "run_science_direct",
        "result_application",
        "cost",
    ],
)
# Mutations caught: allowing any post-terminal write through Supervisor or direct UoW APIs.
def test_terminal_states_reject_every_run_mutation_without_side_effects(
    tmp_path, terminal_state: RunState, mutation: str
) -> None:
    supervisor, result = _submitted_generation(tmp_path)
    _enter_state(supervisor, terminal_state)
    before = _snapshot(supervisor.uow)
    sequence = int(before[1])

    with pytest.raises(ValueError, match=terminal_state.value):
        _attempt_terminal_mutation(mutation, supervisor, result, sequence)

    assert _snapshot(supervisor.uow) == before


# Mutations caught: rejecting an already-submitted result in stopping or leaking its
# exploration follow-ups after settlement.
def test_stopping_settles_submitted_result_without_exploration_followups(tmp_path) -> None:
    supervisor, result = _submitted_generation(tmp_path)
    stopping = supervisor.uow.commit_lifecycle_batch(
        run_id="run-1",
        expected_sequence=1,
        events=(NewEvent(event_type="RunStopping", payload={}),),
        target_run_state=RunState.STOPPING,
        idempotency_key="enter-stopping",
    )

    committed = supervisor.handle_result(
        "run-1",
        "generate-1",
        result,
        expected_sequence=stopping.last_sequence,
    )

    assert [event.event_type for event in committed.events] == [
        "HypothesisContentCreated"
    ]
    assert supervisor.uow.run_state("run-1") == "stopping"
    assert supervisor.uow.task_state("generate-1") == "succeeded"
    assert supervisor.uow.external_call_state("call-1") == "domain_result_applied"
    with supervisor.uow.engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM tasks WHERE run_id = 'run-1'")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM cost_entries WHERE run_id = 'run-1'")
        ).scalar_one() == 1


# Mutation caught: allowing non-finalization work creation while a Run is stopping.
def test_stopping_allows_only_finalize_run_task_creation(tmp_path) -> None:
    supervisor, _ = _submitted_generation(tmp_path)
    supervisor.uow.commit_lifecycle_batch(
        run_id="run-1",
        expected_sequence=1,
        events=(NewEvent(event_type="RunStopping", payload={}),),
        target_run_state=RunState.STOPPING,
        idempotency_key="enter-stopping",
    )

    with pytest.raises(ValueError, match="stopping.*exploration"):
        supervisor.uow.enqueue_tasks((_late_task("late-exploration"),))

    finalization = _late_task("finalize:run-1", intent_type="finalize_run")
    supervisor.uow.enqueue_tasks((finalization,))

    assert supervisor.uow.task_state(finalization.task_id) == "pending"


# Mutation caught: treating a paused Run as eligible for new finalization work.
def test_paused_run_preserves_work_without_creating_new_tasks(tmp_path) -> None:
    supervisor, _ = _submitted_generation(tmp_path)
    pausing = supervisor.uow.commit_lifecycle_batch(
        run_id="run-1",
        expected_sequence=1,
        events=(NewEvent(event_type="RunPausing", payload={}),),
        target_run_state=RunState.PAUSING,
        idempotency_key="enter-pausing",
    )
    supervisor.uow.commit_lifecycle_batch(
        run_id="run-1",
        expected_sequence=pausing.last_sequence,
        events=(NewEvent(event_type="RunPaused", payload={}),),
        target_run_state=RunState.PAUSED,
        idempotency_key="enter-paused",
    )
    before = _snapshot(supervisor.uow)

    with pytest.raises(ValueError, match="paused.*enqueue_finalization_task"):
        supervisor.uow.enqueue_tasks(
            (_late_task("finalize:paused", intent_type="finalize_run"),)
        )

    assert _snapshot(supervisor.uow) == before


@pytest.mark.parametrize("surface", ["supervisor", "uow"])
# Mutation caught: allowing a finalization task to be created while still running.
def test_running_rejects_direct_finalization_task_creation(tmp_path, surface: str) -> None:
    supervisor, _ = _submitted_generation(tmp_path)
    before = _snapshot(supervisor.uow)
    task = _late_task(f"finalize:{surface}", intent_type="finalize_run")

    with pytest.raises(ValueError, match="running.*enqueue_finalization_task"):
        if surface == "supervisor":
            supervisor.enqueue_task(task=task, expected_sequence=1)
        else:
            supervisor.uow.enqueue_tasks((task,))

    assert _snapshot(supervisor.uow) == before


# Mutation caught: authorizing exploration against the pre-transition running state
# even though the same transaction enters stopping.
def test_stop_transition_rejects_mixed_exploration_followup_without_side_effects(
    tmp_path,
) -> None:
    supervisor, _ = _submitted_generation(tmp_path)
    before = _snapshot(supervisor.uow)
    exploration = _late_task("late-stop-exploration")

    with pytest.raises(ValueError, match="stopping.*exploration"):
        supervisor.uow.commit_lifecycle_batch(
            run_id="run-1",
            expected_sequence=1,
            events=(
                NewEvent(event_type="RunStopping", payload={}),
                NewEvent(
                    event_type="TaskEnqueued",
                    payload=exploration.model_dump(mode="json"),
                ),
            ),
            target_run_state=RunState.STOPPING,
            followup_tasks=(exploration,),
            idempotency_key="mixed-stop",
        )

    assert _snapshot(supervisor.uow) == before


# Mutation caught: evaluating the authorized stop/finalization batch as running
# instead of against its effective stopping state.
def test_stop_transition_accepts_only_its_authorized_finalization_task(tmp_path) -> None:
    supervisor, _ = _submitted_generation(tmp_path)

    committed = supervisor.request_normal_completion("run-1", expected_sequence=1)

    assert [event.event_type for event in committed.events] == [
        "RunStopping",
        "FinalizationRequested",
        "TaskEnqueued",
    ]
    assert supervisor.uow.run_state("run-1") == "stopping"
    assert supervisor.uow.task_state("finalize:run-1") == "pending"
