from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.domain.task import NewTask
from co_scientist.events.models import NewEvent

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _estimate(**updates) -> dict[str, object]:
    estimate: dict[str, object] = {
        "model_calls": 1,
        "input_tokens": 100,
        "output_tokens": 200,
        "cost_usd": "0.10",
        "hypotheses": 1,
        "matches": 0,
    }
    estimate.update(updates)
    return estimate


def _setup(tmp_path, *, limit: int | None = 1):
    database_url = f"sqlite:///{tmp_path / 'budget.db'}"
    store = SqliteUnitOfWork(database_url)
    store.create_schema()
    store.create_started_run(
        "r-1",
        manifest={
            "execution_contract_version": 3,
            "budget": {
                "max_usd": None,
                "max_model_calls": limit,
                "max_input_tokens": None,
                "max_output_tokens": None,
                "max_hypotheses": None,
                "max_matches": None,
            },
        },
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-1:0",
    )
    store.enqueue_tasks(
        [
            NewTask(
                task_id=task_id,
                run_id="r-1",
                idempotency_key=f"work:{task_id}",
                intent_type="generate",
                payload={
                    "budget_estimate": _estimate()
                },
            )
            for task_id in ("task-1", "task-2")
        ]
    )
    return database_url, store


def _setup_custom(tmp_path, *, budget: dict[str, object], estimates: list[dict[str, object]]):
    database_url = f"sqlite:///{tmp_path / 'custom-budget.db'}"
    store = SqliteUnitOfWork(database_url)
    store.create_schema()
    store.create_started_run(
        "r-1",
        manifest={"execution_contract_version": 3, "budget": budget},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-1:0",
    )
    store.enqueue_tasks(
        [
            NewTask(
                task_id=f"task-{index}",
                run_id="r-1",
                idempotency_key=f"work:task-{index}",
                intent_type="generate",
                payload={"budget_estimate": estimate},
            )
            for index, estimate in enumerate(estimates, start=1)
        ]
    )
    return database_url, store


# Mutation caught: budget aggregation outside the write lock lets both final calls reserve.
def test_two_connections_only_one_task_reserves_final_model_call(tmp_path) -> None:
    database_url, store = _setup(tmp_path)

    def claim(worker_number: int):
        return SqliteUnitOfWork(database_url).claim_next_task(
            run_id="r-1",
            worker_id=f"worker-{worker_number}",
            lease_token=f"token-{worker_number}",
            now=NOW,
            lease_duration=timedelta(minutes=5),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, (1, 2)))

    assert sorted(outcome.status for outcome in outcomes) == [
        "budget_exhausted",
        "claimed",
    ]
    with store.engine.connect() as connection:
        reservations = connection.execute(
            text(
                "SELECT task_id, estimated_model_calls, state "
                "FROM budget_reservations ORDER BY task_id"
            )
        ).all()
        tasks = connection.execute(
            text("SELECT state, COUNT(*) FROM tasks GROUP BY state ORDER BY state")
        ).all()
    assert reservations == [("task-1", 1, "reserved")]
    assert tasks == [("leased", 1), ("pending", 1)]


# Mutation caught: a retry creates a second reservation or increments the task attempt twice.
def test_exact_claim_replay_returns_the_same_reservation_and_attempt(tmp_path) -> None:
    _, store = _setup(tmp_path, limit=None)
    first = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )
    replay = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )

    assert replay == first
    assert replay.task is not None
    assert replay.task.attempt == 1
    with store.engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM budget_reservations), "
                "(SELECT COUNT(*) FROM events WHERE event_type IN "
                "('TaskLeaseClaimed', 'BudgetReserved'))"
            )
        ).one()
    assert counts == (1, 2)


@pytest.mark.parametrize(
    ("mutation", "parameter"),
    [
        ("UPDATE budget_reservations SET state = :value", "released"),
        ("UPDATE budget_reservations SET state = :value", "settled"),
        ("UPDATE budget_reservations SET idempotency_key = :value", "drifted-key"),
        ("UPDATE budget_reservations SET estimated_model_calls = :value", 9),
    ],
)
# Mutation caught: same-token replay trusts a released, settled, or drifted reservation.
def test_same_token_claim_replay_rejects_non_exact_reservation(
    tmp_path, mutation: str, parameter: object
) -> None:
    _, store = _setup(tmp_path, limit=None)
    store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )
    with store.engine.begin() as connection:
        connection.execute(text(mutation), {"value": parameter})

    with pytest.raises(ValueError, match="task reservation does not exactly replay"):
        store.claim_next_task(
            run_id="r-1",
            worker_id="worker-1",
            lease_token="token-1",
            now=NOW,
            lease_duration=timedelta(minutes=5),
        )


@pytest.mark.parametrize(
    ("limit_field", "estimate_field", "limit", "estimate"),
    [
        ("max_model_calls", "model_calls", 1, 2),
        ("max_input_tokens", "input_tokens", 100, 101),
        ("max_output_tokens", "output_tokens", 200, 201),
        ("max_usd", "cost_usd", "1.00", "1.01"),
        ("max_hypotheses", "hypotheses", 1, 2),
        ("max_matches", "matches", 1, 2),
    ],
)
# Mutation caught: a claim-time budget dimension is omitted or mapped to the wrong estimate field.
def test_claim_enforces_each_budget_limit(
    tmp_path,
    limit_field: str,
    estimate_field: str,
    limit: object,
    estimate: object,
) -> None:
    _, store = _setup_custom(
        tmp_path,
        budget={limit_field: limit},
        estimates=[_estimate(**{estimate_field: estimate})],
    )

    outcome = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "budget_exhausted"
    assert store.task_state("task-1") == "pending"


# Mutation caught: settled reservations continue contributing their estimate instead of actuals.
def test_claim_aggregates_settled_actual_usage(tmp_path) -> None:
    _, store = _setup_custom(
        tmp_path,
        budget={"max_model_calls": 6},
        estimates=[_estimate(model_calls=1), _estimate(model_calls=2)],
    )
    store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )
    with store.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE budget_reservations SET state = 'settled', "
                "external_call_id = 'call-1', actual_model_calls = 5"
            )
        )

    outcome = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-2",
        lease_token="token-2",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "budget_exhausted"
    assert store.task_state("task-2") == "pending"


# Mutation caught: released reservations remain in active budget aggregation.
def test_claim_excludes_released_reservations_from_usage(tmp_path) -> None:
    _, store = _setup_custom(
        tmp_path,
        budget={"max_model_calls": 5},
        estimates=[_estimate(model_calls=5), _estimate(model_calls=5)],
    )
    store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )
    with store.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE budget_reservations SET state = 'released' "
                "WHERE task_id = 'task-1'"
            )
        )
        connection.execute(
            text(
                "UPDATE tasks SET state = 'failed', lease_owner = NULL, lease_token = NULL, "
                "heartbeat_at = NULL, lease_expires_at = NULL WHERE task_id = 'task-1'"
            )
        )

    outcome = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-2",
        lease_token="token-2",
        now=NOW,
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "claimed"
    assert outcome.task is not None and outcome.task.task_id == "task-2"


# Mutation caught: recovery creates a second reservation instead of reusing the exact active row.
def test_reclaim_after_recovery_reuses_the_same_reservation(tmp_path) -> None:
    _, store = _setup_custom(
        tmp_path,
        budget={"max_model_calls": 1},
        estimates=[_estimate(model_calls=1)],
    )
    first = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-1",
        lease_token="token-1",
        now=NOW,
        lease_duration=timedelta(seconds=10),
    ).task
    assert first is not None
    store.recover_expired_leases(run_id="r-1", now=NOW + timedelta(seconds=10))

    second = store.claim_next_task(
        run_id="r-1",
        worker_id="worker-2",
        lease_token="token-2",
        now=NOW + timedelta(seconds=11),
        lease_duration=timedelta(minutes=5),
    ).task

    assert second is not None
    assert second.reservation_id == first.reservation_id
    assert second.attempt == 2
    with store.engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM budget_reservations")
        ).scalar_one()
    assert count == 1


@pytest.mark.parametrize("failure_point", ["reservation", "event"])
# Mutation caught: claim commits lease/attempt/sequence before every reservation/event write succeeds.
def test_claim_failure_rolls_back_lease_reservation_events_and_run_sequence(
    tmp_path, monkeypatch, failure_point: str
) -> None:
    _, store = _setup(tmp_path, limit=None)

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"injected {failure_point} failure")

    target = "_insert_budget_reservation" if failure_point == "reservation" else "_insert_events"
    monkeypatch.setattr(store, target, fail)

    with pytest.raises(RuntimeError, match=f"injected {failure_point} failure"):
        store.claim_next_task(
            run_id="r-1",
            worker_id="worker-1",
            lease_token="token-1",
            now=NOW,
            lease_duration=timedelta(minutes=5),
        )

    with store.engine.connect() as connection:
        task = connection.execute(
            text(
                "SELECT state, lease_owner, lease_token, heartbeat_at, lease_expires_at, attempt "
                "FROM tasks WHERE task_id = 'task-1'"
            )
        ).one()
        reservation_count = connection.execute(
            text("SELECT COUNT(*) FROM budget_reservations")
        ).scalar_one()
        event_count = connection.execute(text("SELECT COUNT(*) FROM events")).scalar_one()
        sequence = connection.execute(
            text("SELECT current_sequence FROM runs WHERE run_id = 'r-1'")
        ).scalar_one()
    assert tuple(task) == ("pending", None, None, None, None, 0)
    assert reservation_count == 0
    assert event_count == 1
    assert sequence == 1
