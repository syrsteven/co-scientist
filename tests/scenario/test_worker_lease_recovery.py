import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
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
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import prompt_hash, request_fingerprint
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.worker import Worker
from co_scientist.skills.loader import core_skill_directory
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
    uow.transition_call(
        "call-old",
        ExternalCallState.STARTED,
        reservation_id=first.reservation_id,
        fence=first,
    )
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
            "call-old",
            ref,
            ExternalCallState.RAW_RESPONSE_PERSISTED,
            reservation_id=first.reservation_id,
            fence=stale,
        ),
        lambda: uow.record_validated(
            "call-old",
            {"forged": True},
            reservation_id=first.reservation_id,
            fence=stale,
        ),
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
            reservation_id=first.reservation_id,
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


# Mutation caught: same-owner process restart increments attempt or leaves old token valid.
def test_same_owner_adopts_durable_call_with_fresh_token_and_invalidates_old_fence(
    tmp_path,
) -> None:
    uow, _, first = _setup(tmp_path)
    context = _context(first, first.reservation_id)
    uow.plan_external_call(
        "call-adopt",
        request_fingerprint({"prompt": "adopt"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.transition_call(
        "call-adopt",
        ExternalCallState.STARTED,
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.record_raw_and_transition(
        "call-adopt",
        ArtifactRef(
            path="raw/adopt.json",
            sha256="sha256:" + "2" * 64,
            byte_length=2,
            mime_type="application/json",
        ),
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        reservation_id=first.reservation_id,
        fence=first,
    )

    adopted = uow.adopt_recoverable_task(
        run_id="r-1",
        worker_id="worker-old",
        lease_token="fresh-secret",
        now=NOW + timedelta(seconds=1),
        lease_duration=timedelta(minutes=5),
    ).task

    assert adopted is not None
    assert adopted.attempt == first.attempt
    assert adopted.reservation_id == first.reservation_id
    with pytest.raises(ValueError, match="stale task lease fence"):
        uow.heartbeat_task(
            fence=first,
            now=NOW + timedelta(seconds=2),
            lease_duration=timedelta(minutes=5),
        )
    uow.heartbeat_task(
        fence=adopted,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=5),
    )


def test_unrelated_worker_cannot_adopt_live_recoverable_lease(tmp_path) -> None:
    uow, _, first = _setup(tmp_path)
    context = _context(first, first.reservation_id)
    uow.plan_external_call(
        "call-live",
        request_fingerprint({"prompt": "live"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.transition_call(
        "call-live",
        ExternalCallState.STARTED,
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.record_raw_and_transition(
        "call-live",
        ArtifactRef(
            path="raw/live.json",
            sha256="sha256:" + "4" * 64,
            byte_length=2,
            mime_type="application/json",
        ),
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        reservation_id=first.reservation_id,
        fence=first,
    )

    outcome = uow.adopt_recoverable_task(
        run_id="r-1",
        worker_id="worker-unrelated",
        lease_token="unrelated-secret",
        now=NOW + timedelta(seconds=1),
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "no_task"
    uow.heartbeat_task(
        fence=first,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(seconds=10),
    )


def test_unrelated_worker_adopts_expired_durable_lease_without_new_attempt(tmp_path) -> None:
    uow, _, first = _setup(tmp_path)
    context = _context(first, first.reservation_id)
    uow.plan_external_call(
        "call-expired",
        request_fingerprint({"prompt": "expired"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.transition_call(
        "call-expired",
        ExternalCallState.STARTED,
        reservation_id=first.reservation_id,
        fence=first,
    )

    outcome = uow.adopt_recoverable_task(
        run_id="r-1",
        worker_id="worker-unrelated",
        lease_token="expired-secret",
        now=NOW + timedelta(seconds=10),
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "claimed"
    assert outcome.task is not None
    assert outcome.task.attempt == first.attempt
    assert outcome.task.reservation_id == first.reservation_id
    assert uow.get_external_call("call-expired").attempt == first.attempt
    with pytest.raises(ValueError, match="stale task lease fence"):
        uow.heartbeat_task(
            fence=first,
            now=NOW + timedelta(seconds=11),
            lease_duration=timedelta(minutes=5),
        )


def test_recoverable_call_adoption_respects_paused_run_fence(tmp_path) -> None:
    uow, supervisor, first = _setup(tmp_path)
    context = _context(first, first.reservation_id)
    uow.plan_external_call(
        "call-paused",
        request_fingerprint({"prompt": "paused"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.transition_call(
        "call-paused",
        ExternalCallState.STARTED,
        reservation_id=first.reservation_id,
        fence=first,
    )
    uow.record_raw_and_transition(
        "call-paused",
        ArtifactRef(
            path="raw/paused.json",
            sha256="sha256:" + "3" * 64,
            byte_length=2,
            mime_type="application/json",
        ),
        ExternalCallState.RAW_RESPONSE_PERSISTED,
        reservation_id=first.reservation_id,
        fence=first,
    )
    supervisor.pause_run("r-1", expected_sequence=uow.load("r-1")[-1].sequence)

    outcome = uow.adopt_recoverable_task(
        run_id="r-1",
        worker_id="worker-new",
        lease_token="new-secret",
        now=NOW + timedelta(seconds=1),
        lease_duration=timedelta(minutes=5),
    )

    assert outcome.status == "paused"
    uow.heartbeat_task(
        fence=first,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=5),
    )


# Mutation caught: reusable lease secrets leak into durable event/export surfaces.
def test_lease_events_store_only_one_way_fingerprints(tmp_path) -> None:
    uow, _, _ = _setup(tmp_path)

    serialized = json.dumps(
        [event.model_dump(mode="json") for event in uow.load("r-1")], sort_keys=True
    )

    assert "old-secret" not in serialized
    assert "lease_fence_fingerprint" in serialized


@pytest.mark.parametrize(
    "operation",
    ["started", "failure", "raw", "validation", "submission", "atomic_submission"],
)
# Mutation caught: a call write trusts token/attempt after reservation binding changes.
def test_every_external_call_write_rechecks_exact_reservation_binding(
    tmp_path, operation: str
) -> None:
    uow, _, fence = _setup(tmp_path)
    context = _context(fence, fence.reservation_id)
    uow.plan_external_call(
        "call-reservation",
        request_fingerprint({"prompt": "reservation"}),
        run_id="r-1",
        task_id="task-1",
        execution_context=context.model_dump(mode="json"),
        reservation_id=fence.reservation_id,
        fence=fence,
    )
    ref = ArtifactRef(
        path="raw/reservation.json",
        sha256="sha256:" + "1" * 64,
        byte_length=2,
        mime_type="application/json",
    )
    payload = {"schema_version": 1, "research_plan_version": 1, "hypotheses": []}
    result = AgentResult.model_construct(
        result_id="result-reservation",
        external_call_id="call-reservation",
        raw_artifact_ref=ref,
        status="completed",
        payload=payload,
        **context.model_dump(),
    )
    if operation in {"raw", "validation", "submission", "atomic_submission"}:
        uow.transition_call(
            "call-reservation",
            ExternalCallState.STARTED,
            reservation_id=fence.reservation_id,
            fence=fence,
        )
    if operation in {"validation", "submission", "atomic_submission"}:
        uow.record_raw_and_transition(
            "call-reservation",
            ref,
            ExternalCallState.RAW_RESPONSE_PERSISTED,
            reservation_id=fence.reservation_id,
            fence=fence,
        )
    if operation == "submission":
        uow.record_validated(
            "call-reservation",
            payload,
            reservation_id=fence.reservation_id,
            fence=fence,
        )
    with uow.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE budget_reservations SET external_call_id = 'foreign-call' "
                "WHERE reservation_id = :reservation_id"
            ),
            {"reservation_id": fence.reservation_id},
        )

    mutations = {
        "started": lambda: uow.transition_call(
            "call-reservation",
            ExternalCallState.STARTED,
            reservation_id=fence.reservation_id,
            fence=fence,
        ),
        "failure": lambda: uow.transition_call(
            "call-reservation",
            ExternalCallState.FAILED_BEFORE_RESPONSE,
            reservation_id=fence.reservation_id,
            fence=fence,
        ),
        "raw": lambda: uow.record_raw_and_transition(
            "call-reservation",
            ref,
            ExternalCallState.RAW_RESPONSE_PERSISTED,
            reservation_id=fence.reservation_id,
            fence=fence,
        ),
        "validation": lambda: uow.record_validated(
            "call-reservation",
            payload,
            reservation_id=fence.reservation_id,
            fence=fence,
        ),
        "submission": lambda: uow.record_submitted_result(
            "call-reservation",
            result,
            reservation_id=fence.reservation_id,
            fence=fence,
        ),
        "atomic_submission": lambda: uow.record_validated_and_submitted(
            "call-reservation",
            payload,
            result,
            reservation_id=fence.reservation_id,
            fence=fence,
        ),
    }
    before = uow.external_call_state("call-reservation")

    with pytest.raises(ValueError, match="reservation"):
        mutations[operation]()

    assert uow.external_call_state("call-reservation") == before


class _InvalidProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=b"{}",
            mime_type="application/json",
            provider_response_id=f"invalid-{self.call_count}",
            usage={"input_tokens": 1, "output_tokens": 1, "cost_usd": "0.01"},
        )


@pytest.mark.asyncio
# Mutations caught: invalid typed output stops after one attempt, erases attempt
# usage by rebinding one reservation, or pollutes the scientific stream.
async def test_real_workers_exhaust_invalid_output_without_scientific_pollution(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'invalid-exhaustion.db'}"
    uow = SqliteUnitOfWork(database_url)
    uow.create_schema()
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="invalid"))
    started = supervisor.create_and_start_run(
        "run-invalid",
        manifest={"execution_contract_version": 3, "budget": {}},
        start_payload={},
    )
    skill_directory = core_skill_directory("generation")
    inputs = {"research_question": "reject malformed output"}
    supervisor.enqueue_task(
        task=NewTask(
            task_id="task-invalid",
            run_id="run-invalid",
            idempotency_key="generation:invalid:1",
            intent_type="run_generation",
            payload={
                "skill_id": "generation",
                "skill_version": "0.2.0",
                "output_schema_id": "GenerationResultV1",
                "output_schema_version": 1,
                "research_plan_version": 1,
                "provider_id": "provider-invalid",
                "model_or_tool": "model-invalid",
                "inputs": inputs,
                "input_snapshot_hash": request_fingerprint(inputs),
                "prompt_hash": prompt_hash(
                    (skill_directory / "prompts/system.md").read_text(encoding="utf-8")
                ),
                "budget_estimate": {
                    "model_calls": 1,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": "0.01",
                    "hypotheses": 1,
                    "matches": 0,
                },
            },
        ),
        expected_sequence=started.last_sequence,
    )
    provider = _InvalidProvider()

    def worker(attempt: int, now: datetime) -> Worker:
        current = SqliteUnitOfWork(database_url)
        return Worker(
            runtime=SimpleNamespace(
                uow=current,
                artifacts=FilesystemArtifactStore(tmp_path / "invalid-artifacts"),
            ),
            task_runtime=current,
            supervisor=Supervisor(uow=current, review_policy=ReviewPolicy(profile_id="invalid")),
            skills=SkillRegistry({("generation", "0.2.0"): skill_directory}),
            providers=ProviderRegistry({"provider-invalid": provider}),
            worker_id=f"worker-{attempt}",
            clock=lambda: now,
            token_factory=lambda: f"token-{attempt}",
            call_id_factory=lambda task: f"call-invalid-{task.attempt}",
            lease_duration=timedelta(seconds=10),
            heartbeat_interval=timedelta(seconds=1),
        )

    for attempt in range(1, 4):
        with pytest.raises(ExceptionGroup):
            await worker(attempt, NOW + timedelta(seconds=11 * (attempt - 1))).run_once(
                "run-invalid"
            )

    exhausted = await worker(4, NOW + timedelta(seconds=33)).run_once("run-invalid")

    assert exhausted.status == "exhausted"
    assert provider.call_count == 3
    assert uow.task_state("task-invalid") == "failed"
    with uow.engine.connect() as connection:
        call_ids = (
            connection.execute(
                text(
                    "SELECT external_call_id FROM external_calls "
                    "WHERE run_id = 'run-invalid' ORDER BY attempt"
                )
            )
            .scalars()
            .all()
        )
        costs = connection.execute(
            text(
                "SELECT external_call_id, input_tokens, output_tokens, cost_usd "
                "FROM cost_entries WHERE run_id = 'run-invalid' ORDER BY external_call_id"
            )
        ).all()
        reservation = connection.execute(
            text(
                "SELECT state, actual_model_calls, actual_input_tokens, "
                "actual_output_tokens, actual_cost_usd FROM budget_reservations "
                "WHERE task_id = 'task-invalid'"
            )
        ).one()
    assert call_ids == ["call-invalid-1", "call-invalid-2", "call-invalid-3"]
    assert costs == [
        ("call-invalid-1", 1, 1, "0.01"),
        ("call-invalid-2", 1, 1, "0.01"),
        ("call-invalid-3", 1, 1, "0.01"),
    ]
    assert reservation == ("settled", 3, 3, 3, "0.03")
    attempt_failures = [
        event
        for event in uow.load("run-invalid")
        if event.event_type == "ExternalCallAttemptFailed"
    ]
    assert [event.payload["external_call_id"] for event in attempt_failures] == call_ids
    assert not any(
        event.event_type.startswith(("Hypothesis", "Review", "Match"))
        for event in uow.load("run-invalid")
    )
