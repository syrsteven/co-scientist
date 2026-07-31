import json
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.budget import CostEntry
from co_scientist.domain.states import ExternalCallState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.events.models import NewEvent


def _store(tmp_path) -> SqliteUnitOfWork:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()
    return store


def test_domain_batch_commits_events_task_followup_cost_call_and_run_sequence(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={"goal": "discover"})
    store.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="source",
                intent_type="reflect",
                payload={"candidate": "h-1"},
            )
        ]
    )
    store.transition_task("task-1", TaskState.RESULT_RECEIVED)
    store.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="r-1",
        task_id="task-1",
        provider="stub",
        model_or_tool="stub-model",
    )
    store.transition_call("call-1", ExternalCallState.STARTED)
    store.transition_call("call-1", ExternalCallState.RAW_RESPONSE_PERSISTED)
    store.transition_call("call-1", ExternalCallState.VALIDATED)
    store.transition_call("call-1", ExternalCallState.AGENT_RESULT_SUBMITTED)

    result = store.commit_domain_batch(
        run_id="r-1",
        expected_sequence=0,
        events=[NewEvent(event_type="ReviewCompleted", payload={"review_id": "rev-1"})],
        task_mutations=[TaskMutation.succeed("task-1")],
        followup_tasks=[
            NewTask(
                task_id="task-2",
                run_id="r-1",
                idempotency_key="followup",
                intent_type="rank",
                payload={"hypothesis_id": "h-1"},
            )
        ],
        idempotency_key="source",
        external_call_id="call-1",
        cost_entries=[
            CostEntry(
                cost_entry_id="cost-1",
                run_id="r-1",
                external_call_id="call-1",
                input_tokens=11,
                output_tokens=7,
                cost_usd=Decimal("0.0123"),
                pricing_version="2026-07",
            )
        ],
    )

    assert result.last_sequence == 1
    assert [event.event_type for event in result.events] == ["ReviewCompleted"]
    assert store.task_state("task-1") == "succeeded"
    assert store.task_state("task-2") == "pending"
    assert store.external_call_state("call-1") == "domain_result_applied"
    with store.engine.connect() as connection:
        run = connection.execute(
            text("SELECT current_sequence, manifest_json FROM runs WHERE run_id = 'r-1'")
        ).one()
        cost = connection.execute(
            text("SELECT input_tokens, output_tokens, cost_usd FROM cost_entries")
        ).one()
        committed = connection.execute(
            text("SELECT last_sequence FROM idempotency_commits WHERE run_id = 'r-1'")
        ).scalar_one()
        call_sequence = connection.execute(
            text("SELECT applied_domain_sequence FROM external_calls WHERE external_call_id = 'call-1'")
        ).scalar_one()
    assert run.current_sequence == 1
    assert json.loads(run.manifest_json) == {"goal": "discover"}
    assert cost == (11, 7, "0.0123")
    assert committed == 1
    assert call_sequence == 1


def test_failed_followup_insert_rolls_back_only_the_domain_batch(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={})
    store.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="source",
                intent_type="reflect",
                payload={},
            ),
            NewTask(
                task_id="existing",
                run_id="r-1",
                idempotency_key="followup",
                intent_type="rank",
                payload={},
            ),
        ]
    )
    store.transition_task("task-1", TaskState.RESULT_RECEIVED)

    with pytest.raises(IntegrityError):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=0,
            events=[NewEvent(event_type="ReviewCompleted", payload={"review_id": "rev-1"})],
            task_mutations=[TaskMutation.succeed("task-1")],
            followup_tasks=[
                NewTask(
                    task_id="duplicate",
                    run_id="r-1",
                    idempotency_key="followup",
                    intent_type="rank",
                    payload={},
                )
            ],
            idempotency_key="source",
            external_call_id=None,
            cost_entries=(),
        )

    assert store.load("r-1") == []
    assert store.task_state("task-1") == "result_received"
    with store.engine.connect() as connection:
        current_sequence = connection.execute(
            text("SELECT current_sequence FROM runs WHERE run_id = 'r-1'")
        ).scalar_one()
        commit_count = connection.execute(text("SELECT COUNT(*) FROM idempotency_commits")).scalar_one()
    assert current_sequence == 0
    assert commit_count == 0
