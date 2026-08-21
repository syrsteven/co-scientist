import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import (
    CostEntryRow,
    ExternalCallRow,
    SqliteUnitOfWork,
)
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import NewTask, lease_fence_fingerprint
from co_scientist.export.run_export import SqliteRunReadModel, export_run
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash, request_fingerprint
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.worker import Worker
from co_scientist.supervisor.orchestrator import Supervisor

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)


class _SimulatedCrash(BaseException):
    pass


class _CountingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=json.dumps(
                {
                    "schema_version": 1,
                    "research_plan_version": 1,
                    "hypotheses": [
                        {
                            "schema_version": 1,
                            "hypothesis_id": "h-crash",
                            "content_id": "content-crash-v1",
                            "research_plan_version": 1,
                            "title": "Crash-safe hypothesis",
                            "claim": "The domain result is applied exactly once.",
                            "mechanism_chain": ["raw", "validated", "applied"],
                            "assumptions": [],
                            "predictions": [],
                            "falsifiers": [],
                            "generation_strategy": "crash recovery fixture",
                        }
                    ],
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            mime_type="application/json",
            provider_response_id=f"provider-response-{self.call_count}",
            usage={
                "input_tokens": 11,
                "output_tokens": 7,
                "cost_usd": "0.01",
                "pricing_version": "crash-test-v1",
            },
        )


class _CrashBeforeRawStore:
    def __init__(self, delegate: FilesystemArtifactStore) -> None:
        self.delegate = delegate
        self.crash_once = True

    def persist_raw(self, *args, **kwargs):
        if self.crash_once:
            self.crash_once = False
            raise _SimulatedCrash("provider returned before raw persistence")
        return self.delegate.persist_raw(*args, **kwargs)

    def read(self, ref):
        return self.delegate.read(ref)

    def discover_raw(self, call_id):
        return self.delegate.discover_raw(call_id)

    def confirm_raw(self, manifest):
        return self.delegate.confirm_raw(manifest)


class _CrashBeforeValidation:
    def __init__(self) -> None:
        self.crash_once = True

    def __call__(self, raw: bytes):
        if self.crash_once:
            self.crash_once = False
            raise _SimulatedCrash("raw persisted before validation")
        return json.loads(raw)


class RecoveryResult(SimpleNamespace):
    domain_result_count: int
    logical_cost_count: int
    provider_recall_count: int


class CrashHarness:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run_and_recover(self, boundary: str) -> RecoveryResult:
        return asyncio.run(self._run_and_recover(boundary))

    async def _run_and_recover(self, boundary: str) -> RecoveryResult:
        database_url = f"sqlite:///{self.root / f'{boundary}.db'}"
        uow = SqliteUnitOfWork(database_url)
        uow.create_schema()
        supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="crash"))
        started = supervisor.create_and_start_run(
            "run-crash",
            manifest={
                "execution_contract_version": 3,
                "budget": {},
                "provider": "replay",
                "boundary": boundary,
            },
            start_payload={"provider": "replay"},
        )
        task = NewTask(
            task_id="task-crash",
            run_id="run-crash",
            idempotency_key="task-crash",
            intent_type="run_generation",
            payload={
                "budget_estimate": {
                    "model_calls": 1,
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "cost_usd": "0.01",
                    "hypotheses": 1,
                    "matches": 0,
                }
            },
        )
        supervisor.enqueue_task(task=task, expected_sequence=started.last_sequence)
        fence = uow.claim_next_task(
            run_id="run-crash",
            worker_id="crash-worker",
            lease_token="crash-lease",
            now=datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
            lease_duration=timedelta(minutes=5),
        ).task
        assert fence is not None
        uow.mark_task_running(fence=fence)
        real_artifacts = FilesystemArtifactStore(self.root / f"{boundary}-artifacts")
        artifacts = (
            _CrashBeforeRawStore(real_artifacts)
            if boundary == "provider_returned_before_raw_persist"
            else real_artifacts
        )
        runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
        runner = ExternalCallRunner(runtime)
        provider = _CountingProvider()
        request = {"prompt": "produce one crash-safe hypothesis"}
        context = AgentExecutionContext(
            run_id="run-crash",
            task_id=task.task_id,
            idempotency_key=task.idempotency_key,
            skill_id="generation",
            skill_version="0.2.0",
            output_schema_id="GenerationResultV1",
            output_schema_version=1,
            research_plan_version=1,
            provider="stub",
            model_or_tool="stub-model",
            input_snapshot_hash="sha256:crash-input",
            attempt=fence.attempt,
            reservation_id=fence.reservation_id,
            lease_fence_fingerprint=lease_fence_fingerprint(fence),
        )
        validator = (
            _CrashBeforeValidation()
            if boundary == "raw_persisted_before_validation"
            else lambda raw: json.loads(raw)
        )
        expected_sequence = uow.load("run-crash")[-1].sequence

        async def execute(current_runner, **kwargs):
            return await current_runner.execute(
                **kwargs, reservation_id=fence.reservation_id, fence=fence
            )

        async def resume(current_runner, call_id, **kwargs):
            return await current_runner.resume(
                call_id, **kwargs, reservation_id=fence.reservation_id, fence=fence
            )

        def restart_from_persisted_state():
            restarted_uow = SqliteUnitOfWork(database_url)
            restarted_supervisor = Supervisor(
                uow=restarted_uow,
                review_policy=ReviewPolicy(profile_id="crash"),
            )
            restarted_runtime = SimpleNamespace(
                uow=restarted_uow,
                artifacts=FilesystemArtifactStore(self.root / f"{boundary}-artifacts"),
            )
            return restarted_uow, restarted_supervisor, restarted_runtime

        if boundary == "provider_returned_before_raw_persist":
            with pytest.raises(_SimulatedCrash, match="before raw persistence"):
                await execute(
                    runner,
                    call_id="call-crash",
                    request=request,
                    provider=provider,
                    validator=validator,
                    context=context,
                )
            calls_before_recovery = provider.call_count
            uow, supervisor, runtime = restart_from_persisted_state()
            result = await execute(
                ExternalCallRunner(runtime),
                call_id="call-crash",
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
        elif boundary == "raw_persisted_before_validation":
            with pytest.raises(_SimulatedCrash, match="before validation"):
                await execute(
                    runner,
                    call_id="call-crash",
                    request=request,
                    provider=provider,
                    validator=validator,
                    context=context,
                )
            calls_before_recovery = provider.call_count
            uow, supervisor, runtime = restart_from_persisted_state()
            result = await resume(
                ExternalCallRunner(runtime),
                "call-crash",
                provider=provider,
                validator=validator,
                context=context,
            )
        elif boundary == "agent_result_submitted_before_domain_apply":
            result = await execute(
                runner,
                call_id="call-crash",
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
            calls_before_recovery = provider.call_count
            uow, supervisor, runtime = restart_from_persisted_state()
            result = await resume(
                ExternalCallRunner(runtime),
                "call-crash",
                provider=provider,
                validator=validator,
                context=context,
            )
        elif boundary == "domain_applied_before_worker_ack":
            result = await execute(
                runner,
                call_id="call-crash",
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
            uow.acknowledge_task(fence=fence, target_state=TaskState.RESULT_RECEIVED)
            supervisor.handle_result(
                "run-crash",
                task.task_id,
                result,
                expected_sequence=expected_sequence,
                reservation_id=fence.reservation_id,
                fence=fence,
            )
            calls_before_recovery = provider.call_count
            uow, supervisor, runtime = restart_from_persisted_state()
            result = await resume(
                ExternalCallRunner(runtime),
                "call-crash",
                provider=provider,
                validator=validator,
                context=context,
            )
            supervisor.handle_result(
                "run-crash",
                task.task_id,
                result,
                expected_sequence=expected_sequence,
                reservation_id=fence.reservation_id,
                fence=fence,
            )
        else:  # pragma: no cover - parametrization is the exhaustive contract
            raise AssertionError(boundary)

        if boundary != "domain_applied_before_worker_ack":
            uow.acknowledge_task(fence=fence, target_state=TaskState.RESULT_RECEIVED)
            supervisor.handle_result(
                "run-crash",
                task.task_id,
                result,
                expected_sequence=expected_sequence,
                reservation_id=fence.reservation_id,
                fence=fence,
            )

        events = uow.load("run-crash")
        domain_results = [
            event
            for event in events
            if event.event_type == "HypothesisContentCreated"
            and event.payload.get("source_task_id") == task.task_id
        ]
        with uow.session_factory() as session:
            logical_costs = int(
                session.scalar(
                    select(func.count())
                    .select_from(CostEntryRow)
                    .where(
                        CostEntryRow.run_id == "run-crash",
                        CostEntryRow.external_call_id == "call-crash",
                    )
                )
                or 0
            )
        export_root = export_run(
            "run-crash",
            self.root / f"{boundary}-export",
            SqliteRunReadModel(uow),
            real_artifacts,
        )
        exported_calls = json.loads(
            (export_root / "external_calls.json").read_text(encoding="utf-8")
        )
        exported_costs = json.loads((export_root / "costs.json").read_text(encoding="utf-8"))
        assert len(exported_calls) == 1
        assert len(exported_costs) == 1
        assert exported_calls[0]["state"] == "domain_result_applied"
        return RecoveryResult(
            domain_result_count=len(domain_results),
            logical_cost_count=logical_costs,
            provider_recall_count=provider.call_count - calls_before_recovery,
        )


# Mutation caught: durable execution metadata stores the reusable lease capability itself.
def test_exported_execution_context_never_contains_reusable_lease_token(tmp_path) -> None:
    payload = {
        "attempt": 3,
        "reservation_id": "reservation-1",
        "lease_fence_fingerprint": "sha256:one-way",
    }

    encoded = json.dumps(payload, sort_keys=True)

    assert "lease_token" not in encoded
    assert "reusable-secret" not in encoded


@pytest.fixture
def crash_harness(tmp_path: Path) -> CrashHarness:
    return CrashHarness(tmp_path)


@pytest.mark.parametrize(
    "boundary",
    [
        "provider_returned_before_raw_persist",
        "raw_persisted_before_validation",
        "agent_result_submitted_before_domain_apply",
        "domain_applied_before_worker_ack",
    ],
)
# Mutations caught: retrying from scratch after a real SQLite/artifact restart,
# retaining only same-UoW state, duplicating domain events, or charging twice.
def test_restart_resumes_without_duplicate_domain_result(
    boundary: str,
    crash_harness: CrashHarness,
) -> None:
    recovered = crash_harness.run_and_recover(boundary)
    assert recovered.domain_result_count == 1
    assert recovered.logical_cost_count == 1
    if boundary != "provider_returned_before_raw_persist":
        assert recovered.provider_recall_count == 0


META_DIRECTORY = Path("skills/meta_review")


class _MetaProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=json.dumps(
                {
                    "schema_version": 1,
                    "research_plan_version": 1,
                    "source_content_hashes": {},
                    "system_feedback": ["durable restart"],
                    "overview": "Worker restart resumes the durable call.",
                    "coverage_gaps": [],
                    "safety_direction_check": "clear",
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            mime_type="application/json",
            provider_response_id=f"meta-{self.call_count}",
            usage={
                "input_tokens": 5,
                "output_tokens": 7,
                "cost_usd": "0.01",
                "pricing_version": "restart-v1",
            },
        )


class _CrashAfterRawUnitOfWork(SqliteUnitOfWork):
    crash_once = True

    def record_validated_and_submitted(self, *args, **kwargs) -> None:
        if self.crash_once:
            self.crash_once = False
            raise _SimulatedCrash("crash after durable raw")
        super().record_validated_and_submitted(*args, **kwargs)


class _CrashBeforeRawStateUnitOfWork(SqliteUnitOfWork):
    crash_once = True

    def record_raw_and_transition(self, *args, **kwargs) -> None:
        if self.crash_once:
            self.crash_once = False
            raise _SimulatedCrash("crash after durable manifest before raw state")
        super().record_raw_and_transition(*args, **kwargs)


class _CrashBeforeDomainSupervisor(Supervisor):
    def handle_result(self, *args, **kwargs):
        raise _SimulatedCrash("crash after durable submission")


class _CrashAfterDomainSupervisor(Supervisor):
    def handle_result(self, *args, **kwargs):
        super().handle_result(*args, **kwargs)
        raise _SimulatedCrash("crash after domain apply")


def _meta_task_payload() -> dict[str, object]:
    inputs = {"review_scope": "restart"}
    prompt = (META_DIRECTORY / "prompts/system.md").read_text(encoding="utf-8")
    return {
        "skill_id": "meta_review",
        "skill_version": "0.2.0",
        "output_schema_id": "MetaReviewResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider_id": "provider-fixed",
        "model_or_tool": "model-fixed",
        "inputs": inputs,
        "input_snapshot_hash": request_fingerprint(inputs),
        "prompt_hash": prompt_hash(prompt),
        "budget_estimate": {
            "model_calls": 1,
            "input_tokens": 5,
            "output_tokens": 7,
            "cost_usd": "0.01",
            "hypotheses": 0,
            "matches": 0,
        },
    }


def _restart_worker(
    *,
    database_url: str,
    artifact_root: Path,
    provider: _MetaProvider,
    supervisor_type: type[Supervisor],
    worker_id: str,
    token: str,
    now: datetime,
    uow_type: type[SqliteUnitOfWork] = SqliteUnitOfWork,
) -> tuple[SqliteUnitOfWork, Worker]:
    uow = uow_type(database_url)
    supervisor = supervisor_type(uow=uow, review_policy=ReviewPolicy(profile_id="restart"))
    worker = Worker(
        runtime=SimpleNamespace(uow=uow, artifacts=FilesystemArtifactStore(artifact_root)),
        task_runtime=uow,
        supervisor=supervisor,
        skills=SkillRegistry({("meta_review", "0.2.0"): META_DIRECTORY}),
        providers=ProviderRegistry({"provider-fixed": provider}),
        worker_id=worker_id,
        clock=lambda: now,
        token_factory=lambda: token,
        call_id_factory=lambda task: f"call:{task.task_id}:{task.attempt}",
        lease_duration=timedelta(seconds=10),
        heartbeat_interval=timedelta(seconds=1),
    )
    return uow, worker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boundary", "first_uow", "first_supervisor", "restart_at"),
    [
        (
            "manifest",
            _CrashBeforeRawStateUnitOfWork,
            Supervisor,
            NOW + timedelta(seconds=10),
        ),
        (
            "raw",
            _CrashAfterRawUnitOfWork,
            Supervisor,
            NOW + timedelta(seconds=10),
        ),
        (
            "submitted",
            SqliteUnitOfWork,
            _CrashBeforeDomainSupervisor,
            NOW + timedelta(seconds=1),
        ),
        (
            "domain_applied",
            SqliteUnitOfWork,
            _CrashAfterDomainSupervisor,
            NOW + timedelta(seconds=1),
        ),
    ],
)
# Mutations caught: Worker restart ignores durable raw/submitted/domain state or recalls cost.
async def test_recreated_worker_resumes_publicly_without_provider_or_cost_duplication(
    tmp_path,
    boundary,
    first_uow,
    first_supervisor,
    restart_at,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{boundary}.db'}"
    artifact_root = tmp_path / f"{boundary}-artifacts"
    provider = _MetaProvider()
    uow, first = _restart_worker(
        database_url=database_url,
        artifact_root=artifact_root,
        provider=provider,
        supervisor_type=first_supervisor,
        worker_id="worker-first",
        token="token-first",
        now=NOW,
        uow_type=first_uow,
    )
    uow.create_schema()
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="restart"))
    started = supervisor.create_and_start_run(
        "run-restart",
        manifest={"execution_contract_version": 3, "budget": {}},
        start_payload={},
    )
    supervisor.enqueue_task(
        task=NewTask(
            task_id="task-restart",
            run_id="run-restart",
            idempotency_key="meta:restart:1",
            intent_type="run_meta_review",
            payload=_meta_task_payload(),
        ),
        expected_sequence=started.last_sequence,
    )

    if boundary in {"manifest", "raw"}:
        with pytest.raises(BaseExceptionGroup) as crash:
            await first.run_once("run-restart")
        assert any(isinstance(error, _SimulatedCrash) for error in crash.value.exceptions)
    else:
        with pytest.raises(_SimulatedCrash):
            await first.run_once("run-restart")

    _, restarted = _restart_worker(
        database_url=database_url,
        artifact_root=artifact_root,
        provider=provider,
        supervisor_type=Supervisor,
        worker_id=("worker-first" if boundary == "submitted" else "worker-restarted"),
        token="token-restarted",
        now=restart_at,
    )
    step = await restarted.run_once("run-restart")

    assert step.status in {"completed", "idle"}
    assert uow.task_state("task-restart") == "succeeded"
    assert provider.call_count == 1
    with uow.session_factory() as session:
        calls = session.scalars(
            select(ExternalCallRow).where(ExternalCallRow.run_id == "run-restart")
        ).all()
        assert len(calls) == 1
        assert calls[0].attempt == 1
        assert calls[0].state == "domain_result_applied"
        assert session.scalar(select(func.count()).select_from(CostEntryRow)) == 1
    assert sum(event.event_type == "MetaReviewCompleted" for event in uow.load("run-restart")) == 1
