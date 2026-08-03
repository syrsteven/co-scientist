import json
from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentResult
from co_scientist.domain.budget import CostEntry
from co_scientist.domain.states import ExternalCallState, RunState, TaskState
from co_scientist.domain.task import NewTask, TaskMutation
from co_scientist.domain.transitions import InvalidTransition
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.event_store import ConcurrencyConflict


def _store(tmp_path) -> SqliteUnitOfWork:
    store = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    store.create_schema()
    return store


def _execution_context(
    *, run_id: str = "r-1", task_id: str = "task-1", idempotency_key: str = "source"
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "task_id": task_id,
        "idempotency_key": idempotency_key,
        "skill_id": "generation",
        "skill_version": "0.1.0",
        "output_schema_version": 1,
        "input_snapshot_hash": "sha256:input",
    }


def _advance_task_to_result_received(store: SqliteUnitOfWork, task_id: str) -> None:
    store.transition_task(task_id, TaskState.LEASED)
    store.transition_task(task_id, TaskState.RUNNING)
    store.transition_task(task_id, TaskState.RESULT_RECEIVED)


class UnserializableResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    result_id: str
    value: object


def _prepare_replay_store(tmp_path) -> SqliteUnitOfWork:
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
            )
        ]
    )
    _advance_task_to_result_received(store, "task-1")
    return store


def _commit_replay_batch(store, expected_sequence):
    return store.commit_domain_batch(
        run_id="r-1",
        expected_sequence=expected_sequence,
        events=[
            NewEvent(event_type="ReviewCompleted", payload={"review_id": "rev-1"}),
            NewEvent(event_type="ReviewAccepted", payload={"review_id": "rev-1"}),
        ],
        task_mutations=[TaskMutation.succeed("task-1")],
        followup_tasks=[
            NewTask(
                task_id="task-2",
                run_id="r-1",
                idempotency_key="followup",
                intent_type="rank",
                payload={},
            )
        ],
        idempotency_key="source",
        cost_entries=[
            CostEntry(
                cost_entry_id="cost-1",
                run_id="r-1",
                external_call_id="call-1",
                cost_usd=Decimal("0.01"),
                pricing_version="2026-07",
            )
        ],
    )


def _assert_replay_did_not_repeat_writes(store) -> None:
    with store.engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM events), "
                "(SELECT COUNT(*) FROM tasks), "
                "(SELECT COUNT(*) FROM cost_entries), "
                "(SELECT COUNT(*) FROM idempotency_commits)"
            )
        ).one()
        current_sequence = connection.execute(
            text("SELECT current_sequence FROM runs WHERE run_id = 'r-1'")
        ).scalar_one()
    assert counts == (2, 2, 1, 1)
    assert current_sequence == 2


# Mutation caught: committing the Run row separately from its initial state/event batch.
def test_started_run_initialization_is_one_atomic_commit(tmp_path) -> None:
    store = _store(tmp_path)

    committed = store.create_started_run(
        "r-started",
        manifest={"provider": "replay"},
        event=NewEvent(event_type="RunStarted", payload={"provider": "replay"}),
        idempotency_key="start:r-started:0",
    )

    assert committed.last_sequence == 1
    assert store.run_state("r-started") == "running"
    assert [event.event_type for event in store.load("r-started")] == ["RunStarted"]


# Mutation caught: leaving an orphan created Run when initial event persistence fails.
def test_started_run_initialization_rolls_back_row_on_failure(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)

    def fail_event_insert(*_args, **_kwargs):
        raise RuntimeError("injected event failure")

    monkeypatch.setattr(store, "_insert_events", fail_event_insert)

    with pytest.raises(RuntimeError, match="injected event failure"):
        store.create_started_run(
            "r-orphan",
            manifest={},
            event=NewEvent(event_type="RunStarted", payload={}),
            idempotency_key="start:r-orphan:0",
        )

    with pytest.raises(KeyError, match="unknown run"):
        store.run_state("r-orphan")


# Mutation caught: returning a prior lifecycle commit before checking a stale sequence.
def test_lifecycle_batch_checks_sequence_before_idempotent_replay(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_started_run(
        "r-1",
        manifest={},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-1:0",
    )
    store.commit_lifecycle_batch(
        run_id="r-1",
        expected_sequence=1,
        events=[NewEvent(event_type="RunPausing", payload={})],
        target_run_state=RunState.PAUSING,
        idempotency_key="pause-request:r-1:1",
    )

    with pytest.raises(ConcurrencyConflict, match="expected 1, got 2"):
        store.commit_lifecycle_batch(
            run_id="r-1",
            expected_sequence=1,
            events=[NewEvent(event_type="RunPausing", payload={})],
            target_run_state=RunState.PAUSING,
            idempotency_key="pause-request:r-1:1",
        )


def test_exact_idempotency_replay_returns_prior_commit_for_stale_sequence(tmp_path) -> None:
    store = _prepare_replay_store(tmp_path)
    committed = _commit_replay_batch(store, expected_sequence=0)

    replayed = _commit_replay_batch(store, expected_sequence=0)

    assert replayed == committed
    _assert_replay_did_not_repeat_writes(store)


def test_exact_idempotency_replay_returns_prior_commit_for_current_sequence(tmp_path) -> None:
    store = _prepare_replay_store(tmp_path)
    committed = _commit_replay_batch(store, expected_sequence=0)

    replayed = _commit_replay_batch(store, expected_sequence=2)

    assert replayed == committed
    _assert_replay_did_not_repeat_writes(store)


def test_idempotency_key_reuse_with_different_batch_is_rejected(tmp_path) -> None:
    store = _prepare_replay_store(tmp_path)
    _commit_replay_batch(store, expected_sequence=0)

    with pytest.raises(ValueError, match="idempotency key reused with a different batch"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=0,
            events=[NewEvent(event_type="ReviewCompleted", payload={"review_id": "different"})],
            idempotency_key="source",
        )

    _assert_replay_did_not_repeat_writes(store)


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
    _advance_task_to_result_received(store, "task-1")
    store.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="r-1",
        task_id="task-1",
        provider="stub",
        model_or_tool="stub-model",
        execution_context=_execution_context(),
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


# Mutation caught: dropping the durable Run transition from an otherwise successful batch.
def test_domain_batch_persists_validated_run_transition(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={})

    store.commit_domain_batch(
        run_id="r-1",
        expected_sequence=0,
        events=[NewEvent(event_type="RunStarted", payload={})],
        target_run_state=RunState.RUNNING,
        idempotency_key="start:r-1",
    )

    assert store.run_state("r-1") == "running"


# Mutation caught: assigning TaskRow.state directly instead of consulting transition_task.
def test_invalid_task_mutation_rolls_back_the_domain_batch(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={})
    store.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="task-1",
                intent_type="finalize_run",
                payload={},
            )
        ]
    )

    with pytest.raises(InvalidTransition, match="pending.*succeeded"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=0,
            events=[NewEvent(event_type="FinalizationCompleted", payload={})],
            task_mutations=[TaskMutation.succeed("task-1")],
            idempotency_key="finalize:r-1",
        )

    assert store.load("r-1") == []
    assert store.task_state("task-1") == "pending"


# Mutation caught: committing RunRow.state before a later follow-up insert fails.
def test_failed_domain_batch_rolls_back_run_transition(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={})
    started = store.commit_domain_batch(
        run_id="r-1",
        expected_sequence=0,
        events=[NewEvent(event_type="RunStarted", payload={})],
        target_run_state=RunState.RUNNING,
        idempotency_key="start:r-1",
    )
    store.enqueue_tasks(
        [
            NewTask(
                task_id="existing",
                run_id="r-1",
                idempotency_key="duplicate",
                intent_type="existing",
                payload={},
            )
        ]
    )

    with pytest.raises(IntegrityError):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=started.last_sequence,
            events=[NewEvent(event_type="RunStopping", payload={})],
            target_run_state=RunState.STOPPING,
            followup_tasks=[
                NewTask(
                    task_id="duplicate",
                    run_id="r-1",
                    idempotency_key="duplicate",
                    intent_type="finalize_run",
                    payload={},
                )
            ],
            idempotency_key="stop:r-1",
        )

    assert store.run_state("r-1") == "running"
    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]


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
    _advance_task_to_result_received(store, "task-1")

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


def test_unknown_run_domain_batch_rolls_back_every_attempted_write(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(KeyError, match="unknown run"):
        store.commit_domain_batch(
            run_id="missing",
            expected_sequence=0,
            events=[NewEvent(event_type="ReviewCompleted", payload={})],
            followup_tasks=[
                NewTask(
                    task_id="task-1",
                    run_id="missing",
                    idempotency_key="followup",
                    intent_type="rank",
                    payload={},
                )
            ],
            idempotency_key="source",
            cost_entries=[
                CostEntry(
                    cost_entry_id="cost-1",
                    run_id="missing",
                    external_call_id="call-1",
                    cost_usd=Decimal("0.01"),
                    pricing_version="2026-07",
                )
            ],
        )

    assert store.load("missing") == []
    with store.engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM tasks), "
                "(SELECT COUNT(*) FROM cost_entries), "
                "(SELECT COUNT(*) FROM idempotency_commits)"
            )
        ).one()
    assert counts == (0, 0, 0)


@pytest.mark.parametrize(
    "foreign_write",
    ["task_mutation", "external_call", "followup_task", "cost_entry"],
)
def test_cross_run_batch_member_rolls_back_the_whole_batch(tmp_path, foreign_write) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={})
    store.create_run("r-2", manifest={})
    store.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="source-1",
                intent_type="reflect",
                payload={},
            ),
            NewTask(
                task_id="task-2",
                run_id="r-2",
                idempotency_key="source-2",
                intent_type="reflect",
                payload={},
            ),
        ]
    )
    _advance_task_to_result_received(store, "task-2")
    store.plan_external_call(
        "call-2",
        "sha256:request",
        run_id="r-2",
        task_id="task-2",
        execution_context=_execution_context(
            run_id="r-2", task_id="task-2", idempotency_key="source-2"
        ),
    )
    store.transition_call("call-2", ExternalCallState.STARTED)
    store.transition_call("call-2", ExternalCallState.RAW_RESPONSE_PERSISTED)
    store.transition_call("call-2", ExternalCallState.VALIDATED)
    store.transition_call("call-2", ExternalCallState.AGENT_RESULT_SUBMITTED)

    task_mutations = (
        [TaskMutation.succeed("task-2")] if foreign_write == "task_mutation" else []
    )
    external_call_id = "call-2" if foreign_write == "external_call" else None
    followup_tasks = (
        [
            NewTask(
                task_id="foreign-followup",
                run_id="r-2",
                idempotency_key="followup",
                intent_type="rank",
                payload={},
            )
        ]
        if foreign_write == "followup_task"
        else []
    )
    cost_entries = (
        [
            CostEntry(
                cost_entry_id="foreign-cost",
                run_id="r-2",
                external_call_id="call-2",
                cost_usd=Decimal("0.01"),
                pricing_version="2026-07",
            )
        ]
        if foreign_write == "cost_entry"
        else []
    )

    with pytest.raises(ValueError, match="does not belong to run r-1"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=0,
            events=[NewEvent(event_type="ReviewCompleted", payload={})],
            task_mutations=task_mutations,
            followup_tasks=followup_tasks,
            idempotency_key=f"source:{foreign_write}",
            external_call_id=external_call_id,
            cost_entries=cost_entries,
        )

    assert store.load("r-1") == []
    assert store.task_state("task-2") == "result_received"
    assert store.external_call_state("call-2") == "agent_result_submitted"
    with store.engine.connect() as connection:
        run_sequence = connection.execute(
            text("SELECT current_sequence FROM runs WHERE run_id = 'r-1'")
        ).scalar_one()
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM tasks), "
                "(SELECT COUNT(*) FROM cost_entries), "
                "(SELECT COUNT(*) FROM idempotency_commits)"
            )
        ).one()
    assert run_sequence == 0
    assert counts == (2, 0, 0)


def test_external_call_plan_requires_real_run_and_task_ownership(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-1", manifest={})
    store.create_run("r-2", manifest={})
    store.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="source",
                intent_type="reflect",
                payload={},
            )
        ]
    )

    with pytest.raises(ValueError, match="does not belong to run r-2"):
        store.plan_external_call(
            "call-1",
            "sha256:request",
            run_id="r-2",
            task_id="task-1",
            execution_context=_execution_context(run_id="r-2"),
        )

    with pytest.raises(KeyError, match="unknown task"):
        store.plan_external_call(
            "call-2",
            "sha256:request",
            run_id="r-1",
            task_id="missing",
            execution_context=_execution_context(task_id="missing"),
        )


def test_external_call_plan_rejects_execution_context_mismatch(tmp_path) -> None:
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
            )
        ]
    )

    with pytest.raises(ValueError, match="execution context"):
        store.plan_external_call(
            "call-1",
            "sha256:request",
            run_id="r-1",
            task_id="task-1",
            execution_context=_execution_context(run_id="different"),
        )


def test_validated_payload_and_full_result_commit_atomically(tmp_path) -> None:
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
            )
        ]
    )
    context = _execution_context()
    store.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="r-1",
        task_id="task-1",
        execution_context=context,
    )
    store.transition_call("call-1", "started")
    ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    store.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    result = AgentResult(
        result_id="result-1",
        external_call_id="call-1",
        status="completed",
        payload={"nested": {"values": [1, 2]}},
        raw_artifact_ref=ref,
        **context,
    )

    store.record_validated_and_submitted("call-1", result.payload, result)

    call = store.get_external_call("call-1")
    assert call.state == "agent_result_submitted"
    assert call.run_id == "r-1"
    assert call.task_id == "task-1"
    assert call.request_fingerprint == "sha256:request"
    assert call.execution_context == context
    assert call.validated_payload == {"nested": {"values": [1, 2]}}
    assert call.agent_result == result.model_dump(mode="json")


def test_atomic_result_serialization_failure_leaves_raw_call_recoverable(tmp_path) -> None:
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
            )
        ]
    )
    store.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="r-1",
        task_id="task-1",
        execution_context=_execution_context(),
    )
    store.transition_call("call-1", "started")
    ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    store.record_raw_and_transition("call-1", ref, "raw_response_persisted")

    with pytest.raises(Exception, match="serialize|serializ"):
        store.record_validated_and_submitted(
            "call-1",
            {"hypotheses": []},
            UnserializableResult(result_id="result-1", value=object()),
        )

    call = store.get_external_call("call-1")
    assert call.state == "raw_response_persisted"
    assert call.validated_payload is None
    assert call.agent_result is None


def test_atomic_result_rejects_traceability_mismatch_without_advancing(tmp_path) -> None:
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
            )
        ]
    )
    context = _execution_context()
    store.plan_external_call(
        "call-1",
        "sha256:request",
        run_id="r-1",
        task_id="task-1",
        execution_context=context,
    )
    store.transition_call("call-1", "started")
    ref = ArtifactRef(
        path="raw/call-1/digest",
        sha256="sha256:digest",
        mime_type="application/json",
        byte_length=2,
    )
    store.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    mismatched = AgentResult(
        result_id="result-1",
        external_call_id="different-call",
        status="completed",
        payload={"hypotheses": []},
        raw_artifact_ref=ref,
        **context,
    )

    with pytest.raises(ValueError, match="does not match external call"):
        store.record_validated_and_submitted("call-1", {"hypotheses": []}, mismatched)

    call = store.get_external_call("call-1")
    assert call.state == "raw_response_persisted"
    assert call.validated_payload is None
    assert call.agent_result is None
