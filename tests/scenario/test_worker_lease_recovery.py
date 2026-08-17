import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import ExternalCallState, TaskState
from co_scientist.domain.task import (
    NewTask,
    TaskLeaseFence,
    lease_fence_fingerprint,
)
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.runtime.external_calls import request_fingerprint
from co_scientist.supervisor.orchestrator import Supervisor

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)


def _setup(tmp_path):
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'recovery.db'}")
    uow.create_schema()
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="recovery"))
    supervisor.create_and_start_run(
        "r-1",
        manifest={"execution_contract_version": 3, "budget": {}},
        start_payload={},
    )
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="generation:r-1:1",
                intent_type="run_generation",
                payload={
                    "budget_estimate": {
                        "model_calls": 1,
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cost_usd": "0.01",
                        "hypotheses": 1,
                        "matches": 0,
                    }
                },
            )
        ]
    )
    first = uow.claim_next_task(
        run_id="r-1",
        worker_id="worker-old",
        lease_token="old-secret",
        now=NOW,
        lease_duration=timedelta(seconds=10),
    ).task
    assert first is not None
    uow.mark_task_running(fence=first)
    return uow, supervisor, first


def _context(fence, reservation_id: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        run_id=fence.run_id,
        task_id=fence.task_id,
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="provider-fixed",
        model_or_tool="model-fixed",
        input_snapshot_hash="sha256:input",
        attempt=fence.attempt,
        reservation_id=reservation_id,
        lease_fence_fingerprint=lease_fence_fingerprint(fence),
    )


# Mutations caught: validating a fence outside the write transaction, checking token but not
# attempt, or allowing an old worker to persist raw/validation/submission/domain/ack writes.
def test_reclaimed_task_rejects_every_old_worker_write_boundary(tmp_path) -> None:
    uow, supervisor, first = _setup(tmp_path)
    context = _context(first, first.reservation_id)
    uow.plan_external_call(
        "call-old",
        request_fingerprint({"prompt": "old"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        attempt=first.attempt,
        provider=context.provider,
        model_or_tool=context.model_or_tool,
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.transition_call("call-old", ExternalCallState.STARTED, fence=first)
    uow.recover_expired_leases(run_id="r-1", now=NOW + timedelta(seconds=10))
    second = uow.claim_next_task(
        run_id="r-1",
        worker_id="worker-new",
        lease_token="new-secret",
        now=NOW + timedelta(seconds=11),
        lease_duration=timedelta(minutes=5),
    ).task
    assert second is not None and second.attempt == 2
    uow.mark_task_running(fence=second)
    stale = TaskLeaseFence(
        run_id=first.run_id,
        task_id=first.task_id,
        lease_token=first.lease_token,
        attempt=first.attempt,
    )
    ref = ArtifactRef(
        path="raw/old.json",
        sha256="sha256:" + "0" * 64,
        byte_length=2,
        mime_type="application/json",
    )

    mutations = (
        lambda: uow.record_raw_and_transition(
            "call-old", ref, ExternalCallState.RAW_RESPONSE_PERSISTED, fence=stale
        ),
        lambda: uow.record_validated("call-old", {"forged": True}, fence=stale),
        lambda: uow.record_submitted_result(
            "call-old",
            AgentResult.model_construct(
                result_id="forged",
                external_call_id="call-old",
                raw_artifact_ref=ref,
                status="completed",
                payload={"forged": True},
                **context.model_dump(),
            ),
            fence=stale,
        ),
        lambda: supervisor.handle_result(
            "r-1",
            "task-1",
            AgentResult.model_construct(
                result_id="forged",
                external_call_id="call-old",
                raw_artifact_ref=ref,
                status="completed",
                payload={"forged": True},
                **context.model_dump(),
            ),
            expected_sequence=uow.load("r-1")[-1].sequence,
            reservation_id=first.reservation_id,
            fence=stale,
        ),
        lambda: uow.acknowledge_task(fence=stale, target_state=TaskState.RESULT_RECEIVED),
    )
    for mutation in mutations:
        with pytest.raises(ValueError, match="stale task lease fence"):
            mutation()

    assert uow.external_call_state("call-old") == "started"
    assert uow.task_state("task-1") == "running"
    with uow.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM cost_entries")).scalar_one() == 0
    assert not any(event.event_type.startswith("Hypothesis") for event in uow.load("r-1"))


# Mutation caught: a retry allocates a second logical reservation or reuses call identity.
def test_reclaim_reuses_reservation_but_requires_new_attempt_token_and_call_identity(
    tmp_path,
) -> None:
    uow, _, first = _setup(tmp_path)
    uow.recover_expired_leases(run_id="r-1", now=NOW + timedelta(seconds=10))
    second = uow.claim_next_task(
        run_id="r-1",
        worker_id="worker-new",
        lease_token="new-secret",
        now=NOW + timedelta(seconds=11),
        lease_duration=timedelta(minutes=5),
    ).task
    assert second is not None
    uow.mark_task_running(fence=second)
    context = _context(second, second.reservation_id)
    uow.plan_external_call(
        "call-new",
        request_fingerprint({"prompt": "new"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        attempt=second.attempt,
        reservation_id=second.reservation_id,
        fence=second,
    )

    assert second.reservation_id == first.reservation_id
    assert second.attempt == first.attempt + 1
    assert second.lease_token != first.lease_token
    with uow.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT external_call_id, version FROM budget_reservations "
                "WHERE reservation_id = :reservation_id"
            ),
            {"reservation_id": first.reservation_id},
        ).one()
    assert row.external_call_id == "call-new"
    assert row.version >= 2


# Mutation caught: reusable lease secrets leak into durable event/export surfaces.
def test_lease_events_store_only_one_way_fingerprints(tmp_path) -> None:
    uow, _, _ = _setup(tmp_path)

    serialized = json.dumps(
        [event.model_dump(mode="json") for event in uow.load("r-1")], sort_keys=True
    )

    assert "old-secret" not in serialized
    assert "lease_fence_fingerprint" in serialized
