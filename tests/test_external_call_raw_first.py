import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.fake import FakeLLMProvider
from co_scientist.adapters.llm.output_errors import DomainValidationError
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import SkillExecutor
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.task import NewTask, TaskLeaseFence, lease_fence_fingerprint
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint
from co_scientist.runtime.transport_observability import failure_diagnostic_for_exception
from co_scientist.skills.loader import core_skill_directory, load_skill


class StubProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=json.dumps(_valid_generation_payload(), separators=(",", ":")).encode(),
            mime_type="application/json",
            provider_response_id="stub-1",
            usage={"tokens": {"input": 7}},
        )


class ProviderWithoutResponse:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        raise RuntimeError("provider unavailable")


def test_capture_configuration_hash_normalizes_decimal_prices_only():
    from decimal import Decimal

    from co_scientist.runtime.external_calls import provider_configuration_fingerprint

    assert provider_configuration_fingerprint({"price": Decimal("0.123400")}) == (
        provider_configuration_fingerprint({"price": "0.123400"}))
    assert provider_configuration_fingerprint({"price": Decimal("0.123400")}) != (
        provider_configuration_fingerprint({"price": Decimal("0.123401")}))
    with pytest.raises(TypeError):
        request_fingerprint({"price": Decimal("0.123400")})


@pytest.mark.asyncio
async def test_capture_revision_is_explicit_and_legacy_profile_is_isolated(tmp_path):
    import httpx

    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider

    _, _, runtime = _runtime(tmp_path)
    runner = ExternalCallRunner(runtime)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (
            httpx.Response(200)))) as client:
        legacy = NativeJSONProvider(client, provider="deepseek", api_key="offline-only")
        controlled = NativeJSONProvider(client, provider="deepseek", api_key="offline-only",
                                        response_capture_version=2)
        assert not runner._http_capture_enabled(legacy, "r-1")
        assert runner._http_capture_enabled(controlled, "r-1")
        with pytest.raises(ValueError, match="unsupported response capture version"):
            NativeJSONProvider(client, provider="deepseek", api_key="offline-only",
                               response_capture_version=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(503, b'busy'), (200, b'not-json'),
    (200, b'{"model":"test","usage":{"prompt_tokens":"bad","completion_tokens":1}}'),
    (200, b'{"model":"wrong","usage":{"prompt_tokens":1,"completion_tokens":1}}'),
    (200, b'{"model":"test","usage":{"prompt_tokens":1,"completion_tokens":1}}')])
async def test_native_capture_failure_keeps_http_evidence_without_cost(tmp_path, status, body):
    import httpx
    from sqlalchemy import select

    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.adapters.persistence.sqlite import CostEntryRow
    from co_scientist.runtime.external_calls import prompt_hash

    uow, artifacts, runtime = _runtime(tmp_path)
    context = _context().model_copy(update={"provider": "deepseek", "model_or_tool": "test",
        "prompt_hash": prompt_hash("science")})
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, content=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = NativeJSONProvider(client, provider="deepseek", api_key="offline-secret",
                                      response_capture_version=2)
        with pytest.raises((httpx.HTTPStatusError, ValueError)):
            await _execute(ExternalCallRunner(runtime), call_id="call-capture", request={"model": "test",
                "system_prompt": "science", "user_prompt": "goal", "json_schema": {}},
                provider=provider, validator=lambda raw: {}, context=context)
        call = uow.external_call_for_task_attempt(run_id="r-1", task_id="task-1", attempt=1)
        assert call.state.value == "accounting_incomplete_v2"
        assert call.raw_artifact_ref is None
        capture = artifacts.discover_raw(call.external_call_id + ":http-v2")
        assert capture is not None and artifacts.read(capture.artifact_ref) == body
        with uow.session_factory() as session:
            assert session.execute(select(CostEntryRow)).scalars().all() == []
        with pytest.raises((httpx.HTTPStatusError, ValueError)):
            await ExternalCallRunner(runtime).resume(call.external_call_id, provider=provider,
                validator=lambda raw: {}, context=context, **_lease_kwargs())
        assert len(requests) == 1


class FailingArtifactStore:
    def persist_raw(self, call_id, data, mime_type, **metadata):
        raise OSError("artifact store unavailable")


class AtomicResultFailingUnitOfWork(SqliteUnitOfWork):
    def record_validated_and_submitted(self, call_id, payload, result, **metadata) -> None:
        raise RuntimeError("database unavailable")


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
                "title": "Mechanical gate",
                "claim": "Capsule strain precedes EMT commitment.",
                "mechanism_chain": ["strain", "YAP", "cell fate"],
                "assumptions": ["strain is sensed before commitment"],
                "predictions": ["normalizing strain reduces fibrosis"],
                "falsifiers": ["cell fate changes before strain"],
                "generation_strategy": "causal contrast",
            }
        ],
    }


def _context(
    *, run_id: str = "r-1", task_id: str = "task-1"
) -> AgentExecutionContext:
    fence = _fence(run_id=run_id, task_id=task_id)
    return AgentExecutionContext(
        run_id=run_id,
        task_id=task_id,
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="stub",
        model_or_tool="stub-v1",
        input_snapshot_hash="sha256:input",
        attempt=fence.attempt,
        reservation_id=_reservation_id(run_id, "generation:r-1:1"),
        lease_fence_fingerprint=lease_fence_fingerprint(fence),
    )


def _reservation_id(run_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{idempotency_key}".encode()).hexdigest()
    return f"reservation-{digest}"


def _fence(*, run_id: str = "r-1", task_id: str = "task-1") -> TaskLeaseFence:
    return TaskLeaseFence(
        run_id=run_id, task_id=task_id, lease_token="raw-first-lease", attempt=1
    )


def _lease_kwargs() -> dict[str, object]:
    return {
        "reservation_id": _reservation_id("r-1", "generation:r-1:1"),
        "fence": _fence(),
    }


async def _execute(runner, **kwargs):
    return await runner.execute(**kwargs, **_lease_kwargs())


def _runtime(tmp_path, *, uow_type=SqliteUnitOfWork, artifacts=None):
    uow = uow_type(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    uow.create_started_run(
        "r-1",
        manifest={"execution_contract_version": 3, "budget": {}},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-1:0",
    )
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="generation:r-1:1",
                intent_type="generate",
                payload={
                    "budget_estimate": {
                        "model_calls": 1,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": "0",
                        "hypotheses": 0,
                        "matches": 0,
                    }
                },
            )
        ]
    )
    claimed = uow.claim_next_task(
        run_id="r-1",
        worker_id="raw-first-worker",
        lease_token="raw-first-lease",
        now=datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
        lease_duration=timedelta(minutes=5),
    ).task
    assert claimed is not None
    uow.mark_task_running(fence=claimed)
    artifact_store = artifacts or FilesystemArtifactStore(tmp_path / "artifacts")
    return uow, artifact_store, SimpleNamespace(uow=uow, artifacts=artifact_store)


def _captured_native_case(tmp_path, *, artifacts=None, uow_type=SqliteUnitOfWork):
    from co_scientist.runtime.external_calls import prompt_hash

    uow, store, runtime = _runtime(tmp_path, artifacts=artifacts, uow_type=uow_type)
    context = _context().model_copy(update={"provider": "deepseek",
        "model_or_tool": "deepseek-flash", "prompt_hash": prompt_hash("science")})
    request = {"model": "deepseek-flash", "system_prompt": "science",
               "user_prompt": "goal", "json_schema": {}}
    generation = {"max_tokens": 64, "thinking": "disabled", "reasoning_effort": "low",
        "pilot_pricing": {"version": "offline-frozen", "checked_at": "2026-10-10",
            "source_url": "https://example.invalid/pricing", "model": "deepseek-flash",
            "input_usd_per_million": "0.30", "output_usd_per_million": "1.20",
            "reserve_usd_per_call": "1"}}
    return uow, store, runtime, context, request, generation


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "domain", "pricing", "usage", "model"])
async def test_capture_accounting_authority_boundary(tmp_path, monkeypatch, failure):
    import httpx
    from sqlalchemy import select

    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.adapters.persistence.sqlite import CostEntryRow
    from co_scientist.domain.pilot_pricing import DeepSeekPilotPricing

    uow, store, runtime, context, request, generation = _captured_native_case(tmp_path)
    envelope = {"id": "response-offline", "model": "deepseek-flash",
                "usage": {"prompt_tokens": 5, "completion_tokens": 2,
                          "prompt_cache_hit_tokens": 1}}
    if failure == "usage":
        envelope["usage"]["prompt_cache_hit_tokens"] = 99
    if failure == "model":
        envelope["model"] = "unexpected"
    if failure == "pricing":
        def broken_price(self, **kwargs):
            raise ValueError("offline pricing fault")
        monkeypatch.setattr(DeepSeekPilotPricing, "conservative_cost", broken_price)
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=envelope, headers={"x-request-id": "r-safe",
            "set-cookie": "secret-cookie", "authorization": "secret-response"})
    def validate(raw):
        call = uow.get_external_call("capture-valid")
        assert call.state.value == "raw_response_persisted"
        assert store.discover_raw("capture-valid:http-v2") is not None
        if failure == "domain":
            raise ValueError("scientific domain invalid")
        return _valid_generation_payload()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = NativeJSONProvider(client, provider="deepseek", api_key="offline-secret",
                                      generation=generation, response_capture_version=2)
        kwargs = {"call_id": "capture-valid", "request": request, "provider": provider,
                  "validator": validate, "context": context}
        if failure:
            with pytest.raises(ValueError):
                await _execute(ExternalCallRunner(runtime), **kwargs)
        else:
            result = await _execute(ExternalCallRunner(runtime), **kwargs)
            again = await _execute(ExternalCallRunner(runtime), **kwargs)
            assert again.result_id == result.result_id
        call = uow.get_external_call("capture-valid")
        capture = store.discover_raw("capture-valid:http-v2")
        assert capture.usage["headers"] == {"x-request-id": "r-safe",
            "content-type": "application/json", "content-length": str(len(
                store.read(capture.artifact_ref)))}
        assert "offline-secret" not in capture.model_dump_json()
        with uow.session_factory() as session:
            costs = session.scalars(select(CostEntryRow)).all()
            if failure in {"pricing", "usage", "model"}:
                assert call.state.value == "accounting_incomplete_v2"
                assert not costs and call.raw_artifact_ref is None
            else:
                assert len(costs) == 1 and str(costs[0].cost_usd) != "0"
        assert len(calls) == 1

        if failure is None:
            from co_scientist.domain.states import TaskState
            from co_scientist.domain.task import TaskMutation

            uow.acknowledge_task(fence=_fence(), target_state=TaskState.RESULT_RECEIVED)
            batch = {"run_id": "r-1", "expected_sequence": uow.load("r-1")[-1].sequence,
                "events": (NewEvent(event_type="OfflineCaptureApplied", payload={}),),
                "task_mutations": (TaskMutation.succeed("task-1"),),
                "idempotency_key": "capture-apply-once", "external_call_id": "capture-valid",
                "reservation_id": context.reservation_id, "lease_fence": _fence(),
                "settle_reservation_id": context.reservation_id}
            committed = uow.commit_domain_batch(**batch)
            assert uow.commit_domain_batch(**batch) == committed
            assert sum(e.event_type == "BudgetSettled" for e in uow.load("r-1")) == 1
            assert uow.load_budget_snapshot("r-1").settled.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["before_capture", "capture_commit", "domain_raw_write",
                                      "domain_raw_commit", "after_accounting"])
async def test_capture_crash_boundaries_no_resend(tmp_path, boundary):
    import httpx
    from sqlalchemy import select

    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.adapters.persistence.sqlite import CostEntryRow
    from co_scientist.ports.external_provider import HTTPResponseCaptureError

    class FaultStore(FilesystemArtifactStore):
        fired = False
        def persist_raw(self, call_id, *args, **kwargs):
            if boundary == "before_capture" and call_id.endswith(":http-v2") and not self.fired:
                self.fired = True
                raise OSError("offline capture write fault")
            if boundary == "domain_raw_write" and not call_id.endswith(":http-v2") and not self.fired:
                self.fired = True
                raise OSError("offline domain raw write fault")
            return super().persist_raw(call_id, *args, **kwargs)
    class FaultUow(SqliteUnitOfWork):
        fired = False
        def record_http_capture_v2(self, *args, **kwargs):
            if boundary == "capture_commit" and not self.fired:
                self.fired = True
                raise RuntimeError("offline capture metadata fault")
            return super().record_http_capture_v2(*args, **kwargs)
        def record_raw_and_transition(self, *args, **kwargs):
            if boundary == "domain_raw_commit" and not self.fired:
                self.fired = True
                raise RuntimeError("offline accounting transaction fault")
            return super().record_raw_and_transition(*args, **kwargs)
        def record_validated_and_submitted(self, *args, **kwargs):
            if boundary == "after_accounting" and not self.fired:
                self.fired = True
                raise RuntimeError("offline result transaction fault")
            return super().record_validated_and_submitted(*args, **kwargs)
    store = FaultStore(tmp_path / "artifacts")
    uow, _, runtime, context, request, generation = _captured_native_case(
        tmp_path, artifacts=store, uow_type=FaultUow)
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json={"model": "deepseek-flash",
            "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = NativeJSONProvider(client, provider="deepseek", api_key="offline-secret",
                                      generation=generation, response_capture_version=2)
        with pytest.raises((HTTPResponseCaptureError, RuntimeError, OSError)):
            await _execute(ExternalCallRunner(runtime), call_id="capture-crash", request=request,
                           provider=provider, validator=lambda raw: _valid_generation_payload(),
                           context=context)
        kwargs = dict(provider=provider, validator=lambda raw: _valid_generation_payload(),
                      context=context, **_lease_kwargs())
        recovered_runtime = SimpleNamespace(uow=SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}"),
            artifacts=FilesystemArtifactStore(tmp_path / "artifacts"))
        recovered_runner = ExternalCallRunner(recovered_runtime)
        if boundary == "before_capture":
            with pytest.raises(ValueError, match="DELIVERY_UNKNOWN"):
                await recovered_runner.resume("capture-crash", **kwargs)
            with uow.session_factory() as session:
                assert session.scalars(select(CostEntryRow)).all() == []
        else:
            result = await recovered_runner.resume("capture-crash", **kwargs)
            assert (await recovered_runner.resume("capture-crash", **kwargs)).result_id \
                == result.result_id
            with uow.session_factory() as session:
                assert len(session.scalars(select(CostEntryRow)).all()) == 1
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["task", "attempt", "fingerprint", "provider", "fence"])
async def test_capture_replay_rejects_stale_authority(tmp_path, mismatch):
    import httpx

    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.runtime.external_calls import prompt_hash

    uow, _, runtime = _runtime(tmp_path)
    context = _context().model_copy(update={"provider": "deepseek", "model_or_tool": "test",
        "prompt_hash": prompt_hash("science")})
    request = {"model": "test", "system_prompt": "science", "user_prompt": "goal",
               "json_schema": {}}
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, content=b"invalid-json")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = NativeJSONProvider(client, provider="deepseek", api_key="offline-secret",
                                      response_capture_version=2)
        runner = ExternalCallRunner(runtime)
        with pytest.raises(ValueError):
            await _execute(runner, call_id="tamper-capture", request=request,
                provider=provider, validator=lambda raw: {}, context=context)
        altered = context
        fence = _fence()
        if mismatch == "task":
            altered = context.model_copy(update={"task_id": "other"})
        elif mismatch == "attempt":
            altered = context.model_copy(update={"attempt": 2})
        elif mismatch == "provider":
            provider = NativeJSONProvider(client, provider="qwen", api_key="offline-secret",
                                          response_capture_version=2)
        elif mismatch == "fence":
            fence = fence.model_copy(update={"lease_token": "stale-fence"})
        if mismatch == "fingerprint":
            with pytest.raises(ValueError, match="fingerprint"):
                await _execute(runner, call_id="tamper-capture",
                    request={**request, "user_prompt": "changed"}, provider=provider,
                    validator=lambda raw: {}, context=context)
        else:
            with pytest.raises(ValueError):
                await runner.resume("tamper-capture", provider=provider,
                    validator=lambda raw: {}, context=altered,
                    reservation_id=context.reservation_id, fence=fence)
        assert uow.get_external_call("tamper-capture").raw_artifact_ref is None
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connect", "body", "bounded_json", "bounded_status"])
async def test_production_transport_capture_and_incomplete_delivery(tmp_path, failure):
    import httpx
    from sqlalchemy import select

    from co_scientist.adapters.llm.multi_provider import NativeJSONProvider
    from co_scientist.adapters.persistence.sqlite import CostEntryRow
    from co_scientist.domain.dispatch_limits import DispatchLimits
    from co_scientist.domain.pilot_pricing import DeepSeekPilotPricing
    from co_scientist.runtime.bounded_transport import BoundedTransport, DispatchLimitError

    uow, store, runtime, context, request, generation = _captured_native_case(tmp_path)
    generation["pilot_pricing"]["input_token_limit"] = 10000
    pricing = DeepSeekPilotPricing.model_validate(generation["pilot_pricing"])
    limits = DispatchLimits(max_model_calls=1, max_literature_calls=0, max_input_tokens=10000,
        max_output_tokens=64, max_usd="1", max_wall_seconds=10,
        output_tokens_per_call=64, pricing=pricing)
    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadError("offline incomplete response")
        async def aclose(self):
            pass
    calls = []
    def handle(req):
        calls.append(req)
        if failure == "connect":
            raise httpx.ConnectError("offline connection failure")
        if failure == "body":
            return httpx.Response(200, stream=BrokenBody())
        return httpx.Response(503 if failure == "bounded_status" else 200, content=b"not-json")
    transport = BoundedTransport(tmp_path / "dispatch", limits, inner=httpx.MockTransport(handle))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NativeJSONProvider(client, provider="deepseek", api_key="offline-secret",
                                      generation=generation, response_capture_version=2)
        with pytest.raises((httpx.ConnectError, httpx.ReadError, DispatchLimitError)):
            await _execute(ExternalCallRunner(runtime), call_id="bounded-capture", request=request,
                context=context, provider=provider, validator=lambda raw: _valid_generation_payload())
        call = uow.get_external_call("bounded-capture")
        capture = store.discover_raw("bounded-capture:http-v2")
        if failure in {"connect", "body"}:
            assert capture is None and call.state.value == "failed_before_response"
        else:
            assert capture is not None and call.state.value == "accounting_incomplete_v2"
            assert store.read(capture.artifact_ref) == b"not-json"
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            # execute on the same identity cannot accidentally resend, even outside a baseline run.
            await _execute(ExternalCallRunner(runtime), call_id="bounded-capture", request=request,
                context=context, provider=provider, validator=lambda raw: _valid_generation_payload())
        with uow.session_factory() as session:
            assert not session.scalars(select(CostEntryRow)).all()
        assert len(calls) == 1


@pytest.mark.parametrize(
    ("skill_id", "schema_id", "malformed_payload"),
    [
        (
            "generation",
            "GenerationResultV1",
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "hypotheses": [{"hypothesis_id": "h-1"}],
            },
        ),
        (
            "reflection",
            "ReflectionResultV1",
            {
                "schema_version": 1,
                "research_plan_version": 1,
                "review_id": "review-1",
                "hypothesis_id": "h-1",
                "content_hash": "sha256:" + "a" * 64,
                "stage": "initial_review",
                "recommendation": "pass",
                "safety_status": "not_assessed",
            },
        ),
        (
            "claim_decomposition",
            "ClaimDecompositionResultV1",
            {"schema_version": 1, "research_plan_version": 1,
             "hypothesis_id": "h-1", "claims": [{"claim_id": "c-1"}]},
        ),
    ],
)
@pytest.mark.asyncio
async def test_skill_executor_rejects_malformed_scientific_json_after_raw_persistence(
    tmp_path: Path,
    skill_id: str,
    schema_id: str,
    malformed_payload: dict[str, object],
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / f'{skill_id}.db'}")
    uow.create_schema()
    uow.create_started_run(
        "run-1",
        manifest={"execution_contract_version": 3, "budget": {}},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:run-1:0",
    )
    task_id = f"{skill_id}-task"
    uow.enqueue_tasks(
        [
            NewTask(
                task_id=task_id,
                run_id="run-1",
                idempotency_key=f"{skill_id}:run-1:1",
                intent_type=f"run_{skill_id}",
                payload={
                    "budget_estimate": {
                        "model_calls": 1,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": "0",
                        "hypotheses": 0,
                        "matches": 0,
                    }
                },
            )
        ]
    )
    fence = uow.claim_next_task(
        run_id="run-1",
        worker_id="typed-worker",
        lease_token="typed-lease",
        now=datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
        lease_duration=timedelta(minutes=5),
    ).task
    assert fence is not None
    uow.mark_task_running(fence=fence)
    artifacts = FilesystemArtifactStore(tmp_path / f"{skill_id}-artifacts")
    raw_body = json.dumps(malformed_payload, separators=(",", ":")).encode("utf-8")
    provider = FakeLLMProvider([raw_body])
    context = AgentExecutionContext(
        run_id="run-1",
        task_id=task_id,
        idempotency_key=f"{skill_id}:run-1:1",
        skill_id=skill_id,
        skill_version=load_skill(core_skill_directory(skill_id)).version,
        output_schema_id=schema_id,
        output_schema_version=1,
        research_plan_version=1,
        provider="fake",
        model_or_tool="fake-v1",
        input_snapshot_hash="sha256:input",
        attempt=fence.attempt,
        reservation_id=fence.reservation_id,
        lease_fence_fingerprint=lease_fence_fingerprint(fence),
    )

    with pytest.raises(DomainValidationError):
        await SkillExecutor(
            ExternalCallRunner(SimpleNamespace(uow=uow, artifacts=artifacts)), provider
        ).execute(
            call_id=f"{skill_id}-call",
            skill_directory=core_skill_directory(skill_id),
            inputs={},
            context=context,
            reservation_id=fence.reservation_id,
            fence=fence,
        )

    call = uow.get_external_call(f"{skill_id}-call")
    assert provider.call_count == 1
    assert call.state == "validation_failed"
    assert call.raw_artifact_ref is not None
    assert artifacts.read(call.raw_artifact_ref) == raw_body
    assert call.validated_payload is None
    assert call.agent_result is None
    assert [event.event_type for event in uow.load("run-1")] == [
        "RunStarted",
        "TaskLeaseClaimed",
        "BudgetReserved",
        "ExternalCallAttemptFailed",
    ]
    assert uow.task_state(task_id) == "running"
    assert call.usage == {}


@pytest.mark.asyncio
async def test_validator_observes_persisted_raw_artifact(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    observed = []
    provider = StubProvider()

    def validator(raw: bytes):
        observed.append(uow.external_call_state("call-1"))
        return _valid_generation_payload()

    result = await _execute(ExternalCallRunner(runtime),
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=validator,
        context=_context(),
    )

    assert observed == ["raw_response_persisted"]
    assert provider.call_count == 1
    assert result.external_call_id == "call-1"
    assert result.run_id == "r-1"
    assert result.task_id == "task-1"
    assert result.idempotency_key == "generation:r-1:1"
    assert result.skill_id == "generation"
    assert result.skill_version == "0.2.0"
    assert result.output_schema_id == "GenerationResultV1"
    assert result.output_schema_version == 1
    assert result.input_snapshot_hash == "sha256:input"
    assert result.raw_artifact_ref.path.startswith("raw/call-1/")
    assert not result.raw_artifact_ref.path.startswith("/")
    assert artifacts.read(result.raw_artifact_ref) == json.dumps(
        _valid_generation_payload(), separators=(",", ":")
    ).encode()
    assert uow.external_call_state("call-1") == "agent_result_submitted"
    observations = uow.external_call_observability("call-1")
    assert {item["milestone"] for item in observations["milestones"]} >= {
        "usage_parsed", "raw_persisted"
    }

    with pytest.raises(ValidationError, match="frozen"):
        result.status = "failed"


@pytest.mark.asyncio
async def test_provider_failure_before_response_is_durable(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    provider = ProviderWithoutResponse()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await _execute(ExternalCallRunner(runtime),
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: _valid_generation_payload(),
            context=_context(),
        )

    assert provider.call_count == 1
    assert uow.external_call_state("call-1") == "failed_before_response"

    try:
        raise ExceptionGroup("outer secret: never-persist", [ValueError("api_key=never-persist")])
    except ExceptionGroup as error:
        diagnostic = failure_diagnostic_for_exception(error)
    uow.record_external_call_failure_diagnostic(
        "call-1", diagnostic.model_dump(mode="json"), **_lease_kwargs()
    )
    persisted = uow.external_call_observability("call-1")["failure_diagnostic"]
    encoded = json.dumps(persisted)
    assert "ExternalCallFailureDiagnosticV1" in encoded
    assert "never-persist" not in encoded
    assert "api_key" not in encoded


@pytest.mark.asyncio
async def test_actual_raw_persistence_failure_is_terminal_and_skips_validation(tmp_path) -> None:
    failing_artifacts = FailingArtifactStore()
    uow, _, runtime = _runtime(tmp_path, artifacts=failing_artifacts)
    observed = []

    with pytest.raises(OSError, match="artifact store unavailable"):
        await _execute(ExternalCallRunner(runtime),
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: observed.append(raw),
            context=_context(),
        )

    assert observed == []
    assert uow.external_call_state("call-1") == "raw_persist_failed"
    failure_observation = uow.external_call_observability("call-1")
    assert failure_observation["failure_diagnostic"]["root"]["safe_code"] == "os_error"
    assert failure_observation["failure_diagnostics"][0]["capture_layer"] == (
        "external_call_runner"
    )


@pytest.mark.asyncio
async def test_validator_failure_is_terminal_with_raw_artifact_intact(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)

    def reject(raw):
        raise ValueError("invalid response")

    with pytest.raises(ValueError, match="invalid response"):
        await _execute(ExternalCallRunner(runtime),
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=reject,
            context=_context(),
        )

    persisted = uow.get_external_call("call-1")
    assert persisted.state == "validation_failed"
    assert persisted.raw_artifact_ref is not None
    assert artifacts.read(persisted.raw_artifact_ref) == json.dumps(
        _valid_generation_payload(), separators=(",", ":")
    ).encode()


@pytest.mark.asyncio
async def test_infrastructure_failure_after_durable_raw_remains_recoverable(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path, uow_type=AtomicResultFailingUnitOfWork)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await _execute(ExternalCallRunner(runtime),
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: _valid_generation_payload(),
            context=_context(),
        )

    call = uow.get_external_call("call-1")
    assert call.state == "raw_response_persisted"
    assert call.raw_artifact_ref is not None
    assert artifacts.read(call.raw_artifact_ref) == json.dumps(
        _valid_generation_payload(), separators=(",", ":")
    ).encode()
    assert call.validated_payload is None
    assert call.agent_result is None


@pytest.mark.asyncio
async def test_execute_rejects_task_run_mismatch_before_provider_call(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    uow.create_started_run(
        "r-2",
        manifest={},
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-2:0",
    )
    provider = StubProvider()

    with pytest.raises(ValueError, match="task lease fence"):
        await _execute(ExternalCallRunner(runtime),
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: {"hypotheses": []},
            context=_context(run_id="r-2"),
        )

    assert provider.call_count == 0


# Mutation caught: allowing a persisted prompt hash to describe different prompt bytes.
@pytest.mark.asyncio
async def test_execute_rejects_prompt_hash_mismatch_before_provider_call(tmp_path) -> None:
    _, _, runtime = _runtime(tmp_path)
    provider = StubProvider()
    context = _context().model_copy(
        update={"prompt_hash": "sha256:" + hashlib.sha256(b"other prompt").hexdigest()}
    )

    with pytest.raises(ValueError, match="prompt hash"):
        await _execute(ExternalCallRunner(runtime),
            call_id="call-1",
            request={"system_prompt": "actual prompt"},
            provider=provider,
            validator=lambda raw: {"hypotheses": []},
            context=context,
        )

    assert provider.call_count == 0


def test_request_fingerprint_uses_canonical_json() -> None:
    assert request_fingerprint({"b": 2, "a": 1}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )
    assert request_fingerprint({"a": 1, "b": 2}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )


def test_agent_result_payload_is_deeply_immutable_and_json_serializable() -> None:
    result = AgentResult(
        result_id="result-1",
        external_call_id="call-1",
        run_id="r-1",
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="stub",
        model_or_tool="stub-v1",
        input_snapshot_hash="sha256:input",
        status="completed",
        payload=_valid_generation_payload(),
        raw_artifact_ref=ArtifactRef(
            path="raw/call-1/digest",
            sha256="sha256:digest",
            mime_type="application/json",
            byte_length=2,
        ),
    )

    with pytest.raises(TypeError):
        result.payload["hypotheses"][0]["title"] = "mutated"
    with pytest.raises(AttributeError):
        result.payload["hypotheses"].append("extra")
    assert result.run_id == "r-1"
    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()


def test_raw_response_usage_is_deeply_immutable_and_json_serializable() -> None:
    raw = RawExternalResponse(
        body=b"{}",
        mime_type="application/json",
        usage={"tokens": {"input": 7}, "cached": [1, 2]},
    )

    with pytest.raises(TypeError):
        raw.usage["tokens"]["input"] = 8
    with pytest.raises(AttributeError):
        raw.usage["cached"].append(3)
    assert raw.model_dump(mode="json")["usage"] == {
        "tokens": {"input": 7},
        "cached": [1, 2],
    }


@pytest.mark.parametrize("invalid", [float("nan"), b"bytes", {1: "non-string-key"}])
def test_agent_result_payload_rejects_non_json_values(invalid) -> None:
    with pytest.raises(ValidationError, match="JSON-compatible|string"):
        AgentResult(
            result_id="result-1",
            external_call_id="call-1",
            run_id="r-1",
            task_id="task-1",
            idempotency_key="generation:r-1:1",
            skill_id="generation",
            skill_version="0.2.0",
            output_schema_id="GenerationResultV1",
            output_schema_version=1,
            research_plan_version=1,
            provider="stub",
            model_or_tool="stub-v1",
            input_snapshot_hash="sha256:input",
            status="completed",
            payload={
                **_valid_generation_payload(),
                "hypotheses": [
                    {
                        **_valid_generation_payload()["hypotheses"][0],
                        "title": invalid,
                    }
                ],
            },
            raw_artifact_ref=ArtifactRef(
                path="raw/call-1/digest",
                sha256="sha256:digest",
                mime_type="application/json",
                byte_length=2,
            ),
        )


@pytest.mark.parametrize("invalid", [float("nan"), b"bytes", {1: "non-string-key"}])
def test_raw_response_usage_rejects_non_json_values(invalid) -> None:
    with pytest.raises(ValidationError, match="JSON-compatible|string"):
        RawExternalResponse(
            body=b"{}",
            mime_type="application/json",
            usage={"invalid": invalid},
        )
