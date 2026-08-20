import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.budget import CostEntry
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.events.models import NewEvent
from tests._fenced_runtime import claim_running_task, execution_manifest, fenced_context


def _prepared_call(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'durable-budget.db'}"
    uow = SqliteUnitOfWork(database_url)
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(budget={"max_model_calls": None}),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    task = NewTask(
        task_id="task-1",
        run_id="run-1",
        idempotency_key="task-1",
        intent_type="generate",
        payload={
            "budget_estimate": {
                "model_calls": 1,
                "input_tokens": 100,
                "output_tokens": 100,
                "cost_usd": "1.00",
                "hypotheses": 3,
                "matches": 0,
            }
        },
    )
    uow.enqueue_tasks((task,))
    fence = claim_running_task(uow, run_id="run-1", task_id="task-1")
    context = fenced_context(
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "idempotency_key": "task-1",
            "skill_id": "generation",
            "skill_version": "0.2.0",
            "output_schema_id": "GenerationResultV1",
            "output_schema_version": 1,
            "research_plan_version": 1,
            "provider": "stub",
            "model_or_tool": "stub-model",
            "input_snapshot_hash": "sha256:input",
        },
        fence,
    )
    uow.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="run-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        reservation_id=fence.reservation_id,
        fence=fence,
    )
    with uow.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE external_calls SET state = 'agent_result_submitted', "
                "usage_json = :usage WHERE external_call_id = 'call-1'"
            ),
            {
                "usage": json.dumps(
                    {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "cost_usd": "0.25",
                        "pricing_version": "test-v1",
                    }
                )
            },
        )
        connection.execute(
            text("UPDATE tasks SET state = 'result_received' WHERE task_id = 'task-1'")
        )
    return database_url, uow, fence


def test_settlement_is_atomic_idempotent_and_derived_from_persisted_facts(tmp_path) -> None:
    database_url, uow, fence = _prepared_call(tmp_path)
    expected = uow.load("run-1")[-1].sequence
    events = (
        NewEvent(
            event_type="HypothesisContentCreated",
            schema_version=2,
            payload={"hypothesis_id": "h-1", "research_plan_version": 1},
        ),
    )
    costs = (
        CostEntry(
            cost_entry_id="cost:call-1",
            run_id="run-1",
            external_call_id="call-1",
            input_tokens=11,
            output_tokens=7,
            cost_usd=Decimal("0.25"),
            pricing_version="test-v1",
        ),
    )

    committed = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=expected,
        events=events,
        task_mutations=(TaskMutation.succeed("task-1"),),
        idempotency_key="apply-task-1",
        external_call_id="call-1",
        reservation_id=fence.reservation_id,
        lease_fence=fence,
        settle_reservation_id=fence.reservation_id,
        cost_entries=costs,
    )
    replayed = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=expected,
        events=events,
        task_mutations=(TaskMutation.succeed("task-1"),),
        idempotency_key="apply-task-1",
        external_call_id="call-1",
        reservation_id=fence.reservation_id,
        lease_fence=fence,
        settle_reservation_id=fence.reservation_id,
        cost_entries=costs,
    )

    snapshot = SqliteUnitOfWork(database_url).load_budget_snapshot("run-1")
    assert replayed == committed
    assert [event.event_type for event in committed.events][-1] == "BudgetSettled"
    assert snapshot.settled.model_calls == 1
    assert snapshot.settled.input_tokens == 11
    assert snapshot.settled.output_tokens == 7
    assert snapshot.settled.cost_usd == Decimal("0.25")
    assert snapshot.settled.hypotheses == 1
    assert snapshot.actively_reserved.model_calls == 0


def test_settlement_rejects_cost_totals_that_do_not_match_persisted_call_usage(tmp_path) -> None:
    _, uow, fence = _prepared_call(tmp_path)

    with pytest.raises(ValueError, match="persisted call usage"):
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=uow.load("run-1")[-1].sequence,
            events=(NewEvent(event_type="AgentResultFailed", payload={}),),
            task_mutations=(TaskMutation.succeed("task-1"),),
            idempotency_key="forged-cost",
            external_call_id="call-1",
            reservation_id=fence.reservation_id,
            lease_fence=fence,
            settle_reservation_id=fence.reservation_id,
            cost_entries=(
                CostEntry(
                    cost_entry_id="cost:call-1",
                    run_id="run-1",
                    external_call_id="call-1",
                    input_tokens=999,
                    pricing_version="test-v1",
                ),
            ),
        )


def test_release_is_fenced_idempotent_and_excluded_after_restart(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'release.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.enqueue_tasks(
        (
            NewTask(
                task_id="task-1",
                run_id="run-1",
                idempotency_key="task-1",
                intent_type="generate",
                payload={"budget_estimate": {"model_calls": 1}},
            ),
        )
    )
    fence = claim_running_task(uow, run_id="run-1", task_id="task-1")
    uow.acknowledge_task(fence=fence, target_state=TaskState.FAILED)
    sequence = uow.load("run-1")[-1].sequence

    released = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=sequence,
        events=(),
        idempotency_key="release-task-1",
        lease_fence=fence,
        release_reservation_id=fence.reservation_id,
    )
    replayed = uow.commit_domain_batch(
        run_id="run-1",
        expected_sequence=sequence,
        events=(),
        idempotency_key="release-task-1",
        lease_fence=fence,
        release_reservation_id=fence.reservation_id,
    )

    assert replayed == released
    assert [event.event_type for event in released.events] == ["BudgetReleased"]
    assert SqliteUnitOfWork(uow.engine.url.render_as_string()).load_budget_snapshot(
        "run-1"
    ).actively_reserved.model_calls == 0


# Mutation caught: validating only effects that predate a release batch lets the same
# transaction persist new science while marking its reservation unused.
def test_release_rejects_new_scientific_effect_without_partial_mutation(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'release-science.db'}"
    uow = SqliteUnitOfWork(database_url)
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.enqueue_tasks(
        (
            NewTask(
                task_id="task-1",
                run_id="run-1",
                idempotency_key="task-1",
                intent_type="generate",
                payload={"budget_estimate": {"model_calls": 1, "hypotheses": 1}},
            ),
        )
    )
    fence = claim_running_task(uow, run_id="run-1", task_id="task-1")
    uow.acknowledge_task(fence=fence, target_state=TaskState.FAILED)
    before_events = tuple(uow.load("run-1"))

    with pytest.raises(ValueError, match="release.*scientific"):
        uow.commit_domain_batch(
            run_id="run-1",
            expected_sequence=before_events[-1].sequence,
            events=(
                NewEvent(
                    event_type="HypothesisContentCreated",
                    schema_version=2,
                    payload={"hypothesis_id": "forged", "research_plan_version": 1},
                ),
            ),
            idempotency_key="release-with-science",
            lease_fence=fence,
            release_reservation_id=fence.reservation_id,
        )

    reopened = SqliteUnitOfWork(database_url)
    assert tuple(reopened.load("run-1")) == before_events
    assert reopened.load_budget_snapshot("run-1").actively_reserved.model_calls == 1
    assert reopened.task_state("task-1") == "failed"


def test_provider_call_without_matching_reservation_is_rejected(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'missing-reservation.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.enqueue_tasks(
        (
            NewTask(
                task_id="task-1",
                run_id="run-1",
                idempotency_key="task-1",
                intent_type="generate",
                payload={"budget_estimate": {"model_calls": 1}},
            ),
        )
    )
    fence = claim_running_task(uow, run_id="run-1", task_id="task-1")
    context = fenced_context(
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "idempotency_key": "task-1",
            "skill_id": "generation",
            "skill_version": "0.2.0",
            "output_schema_id": "GenerationResultV1",
            "output_schema_version": 1,
            "research_plan_version": 1,
            "provider": "stub",
            "model_or_tool": "stub-model",
            "input_snapshot_hash": "sha256:input",
        },
        fence,
    )
    forged_context = context.model_dump(mode="json")
    forged_context["reservation_id"] = "missing-reservation"

    with pytest.raises(ValueError, match="reservation"):
        uow.plan_external_call(
            "call-without-reservation",
            "sha256:request",
            run_id="run-1",
            task_id="task-1",
            execution_context=forged_context,
            reservation_id="missing-reservation",
            fence=fence,
        )


def test_two_workers_cannot_reserve_past_the_same_hard_budget(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'budget-race.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest=execution_manifest(budget={"max_model_calls": 1}),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    uow.enqueue_tasks(
        tuple(
            NewTask(
                task_id=f"task-{index}",
                run_id="run-1",
                idempotency_key=f"task-{index}",
                intent_type="generate",
                payload={"budget_estimate": {"model_calls": 1}},
            )
            for index in (1, 2)
        )
    )
    barrier = threading.Barrier(2)

    def claim(index: int) -> str:
        barrier.wait()
        return uow.claim_next_task(
            run_id="run-1",
            worker_id=f"worker-{index}",
            lease_token=f"lease-{index}",
            now=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
            lease_duration=timedelta(minutes=5),
        ).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(claim, (1, 2)))

    assert statuses == ["budget_exhausted", "claimed"]
    snapshot = uow.load_budget_snapshot("run-1")
    assert snapshot.actively_reserved.model_calls == 1
    assert snapshot.hard_limit_reached
