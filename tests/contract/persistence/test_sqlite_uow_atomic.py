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


def _create_running(
    store: SqliteUnitOfWork, run_id: str, *, manifest: dict[str, object] | None = None
) -> None:
    resolved_manifest = {"execution_contract_version": 3, "budget": {}}
    resolved_manifest.update(manifest or {})
    store.create_started_run(
        run_id,
        manifest=resolved_manifest,
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key=f"start:{run_id}:0",
    )


def _execution_context(
    *, run_id: str = "r-1", task_id: str = "task-1", idempotency_key: str = "source"
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "task_id": task_id,
        "idempotency_key": idempotency_key,
        "skill_id": "generation",
        "skill_version": "0.2.0",
        "output_schema_id": "GenerationResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider": "stub",
        "model_or_tool": "stub-model",
        "input_snapshot_hash": "sha256:input",
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
                "title": "Atomic result",
                "claim": "Typed results remain atomic with their call transition.",
                "mechanism_chain": ["validate", "persist", "submit"],
                "assumptions": [],
                "predictions": [],
                "falsifiers": [],
                "generation_strategy": "atomicity fixture",
                "parent_content_ids": [],
                "supersedes_content_id": None,
                "content_hash": None,
            }
        ],
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
    _create_running(store, "r-1")
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
            NewEvent(
                event_type="ReviewCompleted",
                schema_version=2,
                payload={"review_id": "rev-1"},
            ),
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
    assert counts == (3, 2, 1, 2)
    assert current_sequence == 3


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


# Mutation caught: retrying exact run initialization by attempting a second Run insert.
def test_started_run_initialization_exact_retry_returns_original_commit(tmp_path) -> None:
    store = _store(tmp_path)
    event = NewEvent(
        event_type="RunStarted",
        schema_version=1,
        payload={"provider": "replay", "nested": {"profile": ["core", "preview"]}},
    )

    committed = store.create_started_run(
        "r-started",
        manifest={"provider": "replay", "profile": {"name": "core"}},
        event=event,
        idempotency_key="start:r-started:0",
    )
    replayed = store.create_started_run(
        "r-started",
        manifest={"profile": {"name": "core"}, "provider": "replay"},
        event=event,
        idempotency_key="start:r-started:0",
    )

    assert replayed == committed
    assert len(store.load("r-started")) == 1


# Mutation caught: coupling initialization replay to the Run's current tip/state
# instead of the durable sequence-1 initialization anchors.
def test_started_run_initialization_exact_retry_survives_legitimate_advancement(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    event = NewEvent(event_type="RunStarted", payload={"provider": "replay"})
    committed = store.create_started_run(
        "r-started",
        manifest={"provider": "replay"},
        event=event,
        idempotency_key="start:r-started:0",
    )
    store.commit_domain_batch(
        run_id="r-started",
        expected_sequence=1,
        events=(
            NewEvent(
                event_type="TournamentEpochOpened",
                payload={"epoch_id": "epoch-1", "research_plan_version": 1},
            ),
        ),
        idempotency_key="open:epoch-1",
    )

    replayed = store.create_started_run(
        "r-started",
        manifest={"provider": "replay"},
        event=event,
        idempotency_key="start:r-started:0",
    )

    assert replayed == committed
    assert store.run_state("r-started") == "running"
    assert [item.event_type for item in store.load("r-started")] == [
        "RunStarted",
        "TournamentEpochOpened",
    ]


@pytest.mark.parametrize(
    ("manifest", "event"),
    [
        (
            {"provider": "changed"},
            NewEvent(event_type="RunStarted", payload={"provider": "replay"}),
        ),
        (
            {"provider": "replay"},
            NewEvent(event_type="RunStarted", payload={"provider": "changed"}),
        ),
        (
            {"provider": "replay"},
            NewEvent(
                event_type="RunStarted",
                schema_version=2,
                payload={"provider": "replay"},
            ),
        ),
    ],
)
# Mutation caught: omitting manifest, start payload, or event version from initialization identity.
def test_started_run_initialization_rejects_changed_fingerprint(
    tmp_path, manifest: dict[str, object], event: NewEvent
) -> None:
    store = _store(tmp_path)
    store.create_started_run(
        "r-started",
        manifest={"provider": "replay"},
        event=NewEvent(event_type="RunStarted", payload={"provider": "replay"}),
        idempotency_key="start:r-started:0",
    )

    with pytest.raises(ValueError, match="run initialization conflicts with existing state"):
        store.create_started_run(
            "r-started",
            manifest=manifest,
            event=event,
            idempotency_key="start:r-started:0",
        )


# Mutation caught: treating an orphan Run row as an idempotent initialized Run.
def test_started_run_initialization_rejects_orphan_existing_run(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_run("r-orphan", manifest={"provider": "replay"})

    with pytest.raises(ValueError, match="run initialization conflicts with existing state"):
        store.create_started_run(
            "r-orphan",
            manifest={"provider": "replay"},
            event=NewEvent(event_type="RunStarted", payload={"provider": "replay"}),
            idempotency_key="start:r-orphan:0",
        )


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


@pytest.mark.parametrize(
    "event_type",
    [
        "ResearchPlanAccepted",
        "TournamentEpochOpened",
        "TournamentEpochClosed",
        "RunForkRequired",
    ],
)
# Mutation caught: omitting run-level scientific control events from the closed
# version contract.
def test_run_scientific_control_events_reject_unsupported_versions(
    tmp_path, event_type: str
) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")

    with pytest.raises(ValueError, match=f"{event_type} v2"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=1,
            events=(NewEvent(event_type=event_type, schema_version=2, payload={}),),
            idempotency_key=f"unsupported:{event_type}",
        )

    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]


# Mutation caught: changing the Run row state without the matching durable
# lifecycle event in the same transaction.
def test_run_transition_requires_its_matching_lifecycle_event(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")

    with pytest.raises(ValueError, match="stopping.*RunStopping"):
        store.commit_lifecycle_batch(
            run_id="r-1",
            expected_sequence=1,
            events=(NewEvent(event_type="AgentRecommendedActions", payload={}),),
            target_run_state=RunState.STOPPING,
            idempotency_key="invalid-stop",
        )

    assert store.run_state("r-1") == "running"
    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]


# Mutation caught: appending a lifecycle event without applying its matching Run
# row transition.
def test_lifecycle_event_requires_its_matching_transition(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")

    with pytest.raises(ValueError, match="RunStopping.*stopping"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=1,
            events=(NewEvent(event_type="RunStopping", payload={}),),
            idempotency_key="event-only-stop",
        )

    assert store.run_state("r-1") == "running"
    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]


# Mutation caught: bypassing lifecycle coupling through the lower-level event-store
# append surface for an existing durable Run.
def test_direct_append_rejects_lifecycle_event_without_transition(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")

    with pytest.raises(ValueError, match="RunStopping.*stopping"):
        store.append(
            "r-1",
            expected_sequence=1,
            events=(NewEvent(event_type="RunStopping", payload={}),),
        )

    assert store.run_state("r-1") == "running"
    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]


# Mutation caught: accepting a different lifecycle event merely because a valid
# target transition was also present.
def test_run_transition_rejects_mismatched_lifecycle_event(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")

    with pytest.raises(ValueError, match="RunPaused.*paused"):
        store.commit_lifecycle_batch(
            run_id="r-1",
            expected_sequence=1,
            events=(NewEvent(event_type="RunPaused", payload={}),),
            target_run_state=RunState.STOPPING,
            idempotency_key="mismatched-stop",
        )

    assert store.run_state("r-1") == "running"
    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]


def test_exact_idempotency_replay_returns_prior_commit_for_stale_sequence(tmp_path) -> None:
    store = _prepare_replay_store(tmp_path)
    committed = _commit_replay_batch(store, expected_sequence=1)

    replayed = _commit_replay_batch(store, expected_sequence=1)

    assert replayed == committed
    _assert_replay_did_not_repeat_writes(store)


def test_exact_idempotency_replay_returns_prior_commit_for_current_sequence(tmp_path) -> None:
    store = _prepare_replay_store(tmp_path)
    committed = _commit_replay_batch(store, expected_sequence=1)

    replayed = _commit_replay_batch(store, expected_sequence=3)

    assert replayed == committed
    _assert_replay_did_not_repeat_writes(store)


def test_idempotency_key_reuse_with_different_batch_is_rejected(tmp_path) -> None:
    store = _prepare_replay_store(tmp_path)
    _commit_replay_batch(store, expected_sequence=1)

    with pytest.raises(ValueError, match="idempotency key reused with a different batch"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=1,
            events=[
                NewEvent(
                    event_type="ReviewCompleted",
                    schema_version=2,
                    payload={"review_id": "different"},
                )
            ],
            idempotency_key="source",
        )

    _assert_replay_did_not_repeat_writes(store)


def test_domain_batch_commits_events_task_followup_cost_call_and_run_sequence(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1", manifest={"goal": "discover"})
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
        expected_sequence=1,
        events=[
            NewEvent(
                event_type="ReviewCompleted",
                schema_version=2,
                payload={"review_id": "rev-1"},
            )
        ],
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

    assert result.last_sequence == 2
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
            text(
                "SELECT last_sequence FROM idempotency_commits "
                "WHERE run_id = 'r-1' AND idempotency_key = 'source'"
            )
        ).scalar_one()
        call_sequence = connection.execute(
            text("SELECT applied_domain_sequence FROM external_calls WHERE external_call_id = 'call-1'")
        ).scalar_one()
    assert run.current_sequence == 2
    assert json.loads(run.manifest_json) == {
        "budget": {},
        "execution_contract_version": 3,
        "goal": "discover",
    }
    assert cost == (11, 7, "0.0123")
    assert committed == 2
    assert call_sequence == 2


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
    _create_running(store, "r-1")
    store.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="task-1",
                intent_type="reflect",
                payload={},
            )
        ]
    )

    with pytest.raises(InvalidTransition, match="pending.*succeeded"):
        store.commit_domain_batch(
            run_id="r-1",
            expected_sequence=1,
            events=[NewEvent(event_type="FinalizationCompleted", payload={})],
            task_mutations=[TaskMutation.succeed("task-1")],
            idempotency_key="finalize:r-1",
        )

    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]
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
    _create_running(store, "r-1")
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
            expected_sequence=1,
            events=[
                NewEvent(
                    event_type="ReviewCompleted",
                    schema_version=2,
                    payload={"review_id": "rev-1"},
                )
            ],
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

    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]
    assert store.task_state("task-1") == "result_received"
    with store.engine.connect() as connection:
        current_sequence = connection.execute(
            text("SELECT current_sequence FROM runs WHERE run_id = 'r-1'")
        ).scalar_one()
        commit_count = connection.execute(text("SELECT COUNT(*) FROM idempotency_commits")).scalar_one()
    assert current_sequence == 1
    assert commit_count == 1


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
    _create_running(store, "r-1")
    _create_running(store, "r-2")
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
            expected_sequence=1,
            events=[
                NewEvent(
                    event_type="ReviewCompleted", schema_version=2, payload={}
                )
            ],
            task_mutations=task_mutations,
            followup_tasks=followup_tasks,
            idempotency_key=f"source:{foreign_write}",
            external_call_id=external_call_id,
            cost_entries=cost_entries,
        )

    assert [event.event_type for event in store.load("r-1")] == ["RunStarted"]
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
    assert run_sequence == 1
    assert counts == (2, 0, 2)


def test_external_call_plan_requires_real_run_and_task_ownership(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")
    _create_running(store, "r-2")
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
    _create_running(store, "r-1")
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
    _create_running(store, "r-1")
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
        payload=_valid_generation_payload(),
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
    assert call.validated_payload == _valid_generation_payload()
    assert call.agent_result == result.model_dump(mode="json")


def test_atomic_result_serialization_failure_leaves_raw_call_recoverable(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")
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
    _create_running(store, "r-1")
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
        payload=_valid_generation_payload(),
        raw_artifact_ref=ref,
        **context,
    )

    with pytest.raises(ValueError, match="does not match external call"):
        store.record_validated_and_submitted(
            "call-1", _valid_generation_payload(), mismatched
        )

    call = store.get_external_call("call-1")
    assert call.state == "raw_response_persisted"
    assert call.validated_payload is None
    assert call.agent_result is None


# Mutation caught: omitting prompt_hash from persisted-call/result trace matching.
def test_atomic_result_rejects_prompt_hash_mismatch_without_advancing(tmp_path) -> None:
    store = _store(tmp_path)
    _create_running(store, "r-1")
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
    context = {**_execution_context(), "prompt_hash": "sha256:expected-prompt"}
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
        external_call_id="call-1",
        status="completed",
        payload=_valid_generation_payload(),
        raw_artifact_ref=ref,
        **{**context, "prompt_hash": "sha256:different-prompt"},
    )

    with pytest.raises(ValueError, match="does not match external call"):
        store.record_validated_and_submitted(
            "call-1", _valid_generation_payload(), mismatched
        )

    call = store.get_external_call("call-1")
    assert call.state == "raw_response_persisted"
    assert call.validated_payload is None
    assert call.agent_result is None
