import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import CostEntryRow, SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import NewTask
from co_scientist.export.run_export import SqliteRunReadModel, export_run
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner
from co_scientist.supervisor.orchestrator import Supervisor


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
                    "hypotheses": [
                        {
                            "hypothesis_id": "h-crash",
                            "content_id": "content-crash-v1",
                            "title": "Crash-safe hypothesis",
                            "claim": "The domain result is applied exactly once.",
                            "mechanism_chain": ["raw", "validated", "applied"],
                            "assumptions": [],
                            "predictions": [],
                            "falsifiers": [],
                            "content_hash": "sha256:crash-content",
                        }
                    ]
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
        uow = SqliteUnitOfWork(f"sqlite:///{self.root / f'{boundary}.db'}")
        uow.create_schema()
        supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="crash"))
        started = supervisor.create_and_start_run(
            "run-crash",
            manifest={"provider": "replay", "boundary": boundary},
            start_payload={"provider": "replay"},
        )
        task = NewTask(
            task_id="task-crash",
            run_id="run-crash",
            idempotency_key="task-crash",
            intent_type="run_generation",
            payload={},
        )
        scheduled = supervisor.enqueue_task(task=task, expected_sequence=started.last_sequence)
        uow.transition_task(task.task_id, TaskState.LEASED)
        uow.transition_task(task.task_id, TaskState.RUNNING)
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
            skill_version="0.1.0",
            output_schema_version=1,
            input_snapshot_hash="sha256:crash-input",
        )
        validator = (
            _CrashBeforeValidation()
            if boundary == "raw_persisted_before_validation"
            else lambda raw: json.loads(raw)
        )
        expected_sequence = scheduled.last_sequence

        if boundary == "provider_returned_before_raw_persist":
            with pytest.raises(_SimulatedCrash, match="before raw persistence"):
                await runner.execute(
                    call_id="call-crash",
                    request=request,
                    provider=provider,
                    validator=validator,
                    context=context,
                )
            calls_before_recovery = provider.call_count
            result = await ExternalCallRunner(runtime).execute(
                call_id="call-crash",
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
        elif boundary == "raw_persisted_before_validation":
            with pytest.raises(_SimulatedCrash, match="before validation"):
                await runner.execute(
                    call_id="call-crash",
                    request=request,
                    provider=provider,
                    validator=validator,
                    context=context,
                )
            calls_before_recovery = provider.call_count
            result = await ExternalCallRunner(runtime).resume(
                "call-crash",
                provider=provider,
                validator=validator,
                context=context,
            )
        elif boundary == "agent_result_submitted_before_domain_apply":
            result = await runner.execute(
                call_id="call-crash",
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
            calls_before_recovery = provider.call_count
            result = await ExternalCallRunner(runtime).resume(
                "call-crash",
                provider=provider,
                validator=validator,
                context=context,
            )
        elif boundary == "domain_applied_before_worker_ack":
            result = await runner.execute(
                call_id="call-crash",
                request=request,
                provider=provider,
                validator=validator,
                context=context,
            )
            uow.transition_task(task.task_id, TaskState.RESULT_RECEIVED)
            supervisor.handle_result(
                "run-crash",
                task.task_id,
                result,
                expected_sequence=expected_sequence,
            )
            calls_before_recovery = provider.call_count
            result = await ExternalCallRunner(runtime).resume(
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
            )
        else:  # pragma: no cover - parametrization is the exhaustive contract
            raise AssertionError(boundary)

        if boundary != "domain_applied_before_worker_ack":
            uow.transition_task(task.task_id, TaskState.RESULT_RECEIVED)
            supervisor.handle_result(
                "run-crash",
                task.task_id,
                result,
                expected_sequence=expected_sequence,
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
                    select(func.count()).select_from(CostEntryRow).where(
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
# Mutations caught: retrying from scratch after durable raw/submission/domain state,
# duplicating domain events, or charging twice after an acknowledgement crash.
def test_restart_resumes_without_duplicate_domain_result(
    boundary: str,
    crash_harness: CrashHarness,
) -> None:
    recovered = crash_harness.run_and_recover(boundary)
    assert recovered.domain_result_count == 1
    assert recovered.logical_cost_count == 1
    if boundary != "provider_returned_before_raw_persist":
        assert recovered.provider_recall_count == 0
