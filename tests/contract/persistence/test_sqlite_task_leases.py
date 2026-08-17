from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import NewTask, TaskLeaseFence
from co_scientist.events.models import NewEvent

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
EAST_8 = timezone(timedelta(hours=8))


def _store(database_url: str) -> SqliteUnitOfWork:
    return SqliteUnitOfWork(database_url)


def _create_running_store(tmp_path, *, max_model_calls: int | None = None):
    database_url = f"sqlite:///{tmp_path / 'leases.db'}"
    store = _store(database_url)
    store.create_schema()
    store.create_started_run(
        "r-1",
        manifest={
            "execution_contract_version": 3,
            "budget": {"max_model_calls": max_model_calls},
        },
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-1:0",
    )
    return database_url, store


def _task(task_id: str, *, model_calls: int = 1) -> NewTask:
    return NewTask(
        task_id=task_id,
        run_id="r-1",
        idempotency_key=f"work:{task_id}",
        intent_type="generate",
        payload={
            "subject": task_id,
            "budget_estimate": {
                "model_calls": model_calls,
                "input_tokens": 10,
                "output_tokens": 20,
                "cost_usd": "0.01",
                "hypotheses": 1,
                "matches": 0,
            },
        },
    )


# Mutation caught: selecting outside the immediate write transaction lets both workers claim.
def test_two_connections_only_one_worker_claims_the_same_task(tmp_path) -> None:
    database_url, setup = _create_running_store(tmp_path)
    setup.enqueue_tasks([_task("task-1")])

    def claim(worker_number: int):
        return _store(database_url).claim_next_task(
            run_id="r-1",
            worker_id=f"worker-{worker_number}",
            lease_token=f"token-{worker_number}",
            now=NOW,
            lease_duration=timedelta(minutes=5),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, (1, 2)))

    assert sorted(outcome.status for outcome in outcomes) == ["claimed", "no_task"]
    claimed = next(outcome.task for outcome in outcomes if outcome.status == "claimed")
    assert claimed is not None
    assert claimed.task_id == "task-1"
    assert claimed.attempt == 1
    with setup.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT state, lease_owner, lease_token, attempt, heartbeat_at, "
                "lease_expires_at FROM tasks WHERE task_id = 'task-1'"
            )
        ).one()
    assert row.state == "leased"
    assert row.lease_owner == claimed.worker_id
    assert row.lease_token == claimed.lease_token
    assert row.attempt == 1
    assert row.heartbeat_at is not None
    assert row.lease_expires_at is not None


# Mutation caught: preserving a non-UTC wall clock before SQLite discards its offset.
def test_claim_normalizes_offset_aware_now_to_utc_in_rows_results_and_events(tmp_path) -> None:
    _, store = _create_running_store(tmp_path)
    store.enqueue_tasks([_task("task-1")])
    local_now = datetime(2026, 8, 17, 18, 0, tzinfo=EAST_8)

    claimed = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=local_now,
        lease_duration=timedelta(minutes=5),
    ).task

    assert claimed is not None
    assert claimed.heartbeat_at == NOW
    assert claimed.lease_expires_at == NOW + timedelta(minutes=5)
    with store.engine.connect() as connection:
        persisted = connection.execute(
            text(
                "SELECT heartbeat_at, lease_expires_at FROM tasks "
                "WHERE task_id = 'task-1'"
            )
        ).one()
    assert str(persisted.heartbeat_at).startswith("2026-08-17 10:00:00")
    assert str(persisted.lease_expires_at).startswith("2026-08-17 10:05:00")
    event = next(
        item for item in store.load("r-1") if item.event_type == "TaskLeaseClaimed"
    )
    assert event.payload["heartbeat_at"] == "2026-08-17T10:00:00+00:00"
    assert event.payload["lease_expires_at"] == "2026-08-17T10:05:00+00:00"


@pytest.mark.parametrize("operation", ["claim", "heartbeat", "recovery"])
# Mutation caught: silently interpreting an ambiguous naive worker clock as UTC.
def test_runtime_lease_operations_reject_naive_now(tmp_path, operation: str) -> None:
    _, store = _create_running_store(tmp_path)
    store.enqueue_tasks([_task("task-1")])
    naive_now = datetime(2026, 8, 17, 10, 0)  # noqa: DTZ001 - intentional invalid input
    fence = None
    if operation != "claim":
        fence = store.claim_next_task(
            run_id="r-1",
            worker_id="worker-1",
            lease_token="token-1",
            now=NOW,
            lease_duration=timedelta(minutes=5),
        ).task
        assert fence is not None

    with pytest.raises(ValueError, match="now must be timezone-aware"):
        if operation == "claim":
            store.claim_next_task(
                run_id="r-1",
                worker_id="worker-1",
                lease_token="token-1",
                now=naive_now,
                lease_duration=timedelta(minutes=5),
            )
        elif operation == "heartbeat":
            store.heartbeat_task(
                fence=fence,
                now=naive_now,
                lease_duration=timedelta(minutes=5),
            )
        else:
            store.recover_expired_leases(run_id="r-1", now=naive_now)


# Mutation caught: heartbeat renews at equality while recovery expires at equality.
def test_heartbeat_rejects_lease_at_exact_expiry_boundary(tmp_path) -> None:
    _, store = _create_running_store(tmp_path)
    store.enqueue_tasks([_task("task-1")])
    claimed = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    ).task
    assert claimed is not None

    with pytest.raises(ValueError, match="stale task lease fence"):
        store.heartbeat_task(
            fence=claimed,
            now=NOW + timedelta(minutes=5),
            lease_duration=timedelta(minutes=5),
        )

    recovered = store.recover_expired_leases(
        run_id="r-1", now=NOW + timedelta(minutes=5)
    )
    assert recovered[0].action == "requeued"


# Mutation caught: lease expiry comparison uses different wall-clock offsets as different instants.
def test_recovery_compares_equivalent_offset_aware_instants_in_utc(tmp_path) -> None:
    _, store = _create_running_store(tmp_path)
    store.enqueue_tasks([_task("task-1")])
    store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=datetime(2026, 8, 17, 18, 0, tzinfo=EAST_8),
        lease_duration=timedelta(minutes=5),
    )

    assert store.recover_expired_leases(
        run_id="r-1", now=NOW + timedelta(minutes=4, seconds=59)
    ) == ()
    recovered = store.recover_expired_leases(
        run_id="r-1", now=NOW + timedelta(minutes=5)
    )
    assert recovered[0].action == "requeued"


# Mutation caught: task selection depends on insertion/connection timing instead of stable ID order.
def test_claim_selection_is_deterministic_and_intent_filtered(tmp_path) -> None:
    _, store = _create_running_store(tmp_path)
    tasks = [_task("task-z"), _task("task-a")]
    tasks[1] = tasks[1].model_copy(update={"intent_type": "reflect"})
    store.enqueue_tasks(tasks)

    outcome = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
        allowed_intents=frozenset({"reflect"}),
    )

    assert outcome.status == "claimed"
    assert outcome.task is not None
    assert outcome.task.task_id == "task-a"


# Mutation caught: token-only fencing permits a delayed prior attempt to mutate a new lease.
def test_old_token_and_attempt_cannot_heartbeat_run_or_acknowledge(tmp_path) -> None:
    _, store = _create_running_store(tmp_path)
    store.enqueue_tasks([_task("task-1")])
    first = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-old",
        now=NOW,
        lease_duration=timedelta(seconds=30),
    ).task
    assert first is not None
    recovery = store.recover_expired_leases(
        run_id="r-1", now=NOW + timedelta(seconds=31)
    )
    assert recovery[0].action == "requeued"
    second = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-2",
        lease_token="token-new",
        now=NOW + timedelta(seconds=32),
        lease_duration=timedelta(minutes=5),
    ).task
    assert second is not None
    assert second.attempt == 2
    stale = TaskLeaseFence(
        run_id="r-1", task_id="task-1", lease_token="token-old", attempt=1
    )

    with pytest.raises(ValueError, match="stale task lease fence"):
        store.heartbeat_task(
            fence=stale,
            now=NOW + timedelta(seconds=33),
            lease_duration=timedelta(minutes=5),
        )
    with pytest.raises(ValueError, match="stale task lease fence"):
        store.mark_task_running(fence=stale)
    with pytest.raises(ValueError, match="stale task lease fence"):
        store.acknowledge_task(fence=stale, target_state=TaskState.RESULT_RECEIVED)

    running = store.mark_task_running(fence=second)
    heartbeat = store.heartbeat_task(
        fence=second,
        now=NOW + timedelta(seconds=34),
        lease_duration=timedelta(minutes=10),
    )
    store.acknowledge_task(fence=second, target_state=TaskState.RESULT_RECEIVED)
    assert running.attempt == 2
    assert heartbeat.lease_expires_at == NOW + timedelta(minutes=10, seconds=34)
    assert store.task_state("task-1") == "result_received"


# Mutation caught: recovery reuses an expired token or ignores max-attempt exhaustion.
def test_expiry_requeues_below_max_and_exhausts_at_max_attempts(tmp_path) -> None:
    _, store = _create_running_store(tmp_path)
    store.enqueue_tasks([_task("task-1")])
    with store.engine.begin() as connection:
        connection.execute(
            text("UPDATE tasks SET max_attempts = 2 WHERE task_id = 'task-1'")
        )

    first = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(seconds=10),
    ).task
    assert first is not None
    assert store.recover_expired_leases(
        run_id="r-1", now=NOW + timedelta(seconds=11)
    )[0].action == "requeued"
    assert store.task_state("task-1") == "pending"

    second = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-2",
        lease_token="token-2",
        now=NOW + timedelta(seconds=12),
        lease_duration=timedelta(seconds=10),
    ).task
    assert second is not None
    recovered = store.recover_expired_leases(
        run_id="r-1", now=NOW + timedelta(seconds=23)
    )

    assert [item.model_dump() for item in recovered] == [
        {"task_id": "task-1", "expired_attempt": 2, "action": "exhausted"}
    ]
    assert store.task_state("task-1") == "failed"
    event_types = [event.event_type for event in store.load("r-1")]
    assert event_types[-2:] == ["TaskLeaseExpired", "TaskLeaseExhausted"]


# Mutation caught: finalization bypasses reservations by relying on an implicit estimate.
def test_stopping_finalization_claim_requires_and_reserves_explicit_zero_estimate(tmp_path) -> None:
    _, store = _create_running_store(tmp_path, max_model_calls=0)
    store.commit_lifecycle_batch(
        run_id="r-1",
        expected_sequence=1,
        events=(NewEvent(event_type="RunStopping", payload={}),),
        target_run_state="stopping",
        followup_tasks=(
            NewTask(
                task_id="task-final",
                run_id="r-1",
                idempotency_key="finalize:r-1",
                intent_type="finalize_run",
                payload={
                    "budget_estimate": {
                        "model_calls": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": "0",
                        "hypotheses": 0,
                        "matches": 0,
                    }
                },
            ),
        ),
        idempotency_key="stop:r-1",
    )

    outcome = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-final",
        lease_token="token-final",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "claimed"
    assert outcome.task is not None
    with store.engine.connect() as connection:
        estimate = connection.execute(
            text(
                "SELECT estimated_model_calls, estimated_input_tokens, "
                "estimated_output_tokens, estimated_cost_usd, estimated_hypotheses, "
                "estimated_matches FROM budget_reservations WHERE task_id = 'task-final'"
            )
        ).one()
    assert tuple(estimate) == (0, 0, 0, "0", 0, 0)
