import json
from types import SimpleNamespace

import pytest

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.task import NewTask
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint


class CountingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=b'{"hypotheses":[]}',
            mime_type="application/json",
            provider_response_id=f"stub-{self.call_count}",
            usage={"input_tokens": 7},
        )


class FailingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        raise AssertionError("provider must not be called")


class CrashOnceRawMetadataUnitOfWork(SqliteUnitOfWork):
    crash_next_raw_metadata = True

    def record_raw_and_transition(self, call_id, ref, target_state, **metadata) -> None:
        if self.crash_next_raw_metadata:
            self.crash_next_raw_metadata = False
            raise RuntimeError("crash after raw manifest")
        super().record_raw_and_transition(call_id, ref, target_state, **metadata)


class CrashOnceAtomicResultUnitOfWork(SqliteUnitOfWork):
    crash_next_result = True

    def record_validated_and_submitted(self, call_id, payload, result) -> None:
        if self.crash_next_result:
            self.crash_next_result = False
            raise RuntimeError("crash before atomic result commit")
        super().record_validated_and_submitted(call_id, payload, result)


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        run_id="r-1",
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )


def _runtime(tmp_path, *, uow_type=SqliteUnitOfWork):
    uow = uow_type(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    uow.create_run("r-1", manifest={})
    uow.enqueue_tasks(
        [
            NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="generation:r-1:1",
                intent_type="generate",
                payload={},
            )
        ]
    )
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    return uow, artifacts, SimpleNamespace(uow=uow, artifacts=artifacts)


def _plan_started(uow, *, request=None) -> None:
    request = request or {"prompt": "generate"}
    context = _context()
    uow.plan_external_call(
        "call-1",
        request_fingerprint(request),
        run_id=context.run_id,
        task_id=context.task_id,
        execution_context=context.model_dump(mode="json"),
    )
    uow.transition_call("call-1", "started")


@pytest.mark.asyncio
async def test_resume_validates_existing_raw_without_provider_recall(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    ref = artifacts.persist_raw("call-1", b'{"hypotheses":[]}', "application/json")
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    provider = FailingProvider()

    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 0
    assert uow.external_call_state("call-1") == "agent_result_submitted"


@pytest.mark.asyncio
async def test_started_call_recovers_durable_manifest_without_provider_recall(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    artifacts.persist_raw(
        "call-1",
        b'{"hypotheses":[]}',
        "application/json",
        provider_response_id="response-1",
        usage={"input_tokens": 7},
    )
    provider = FailingProvider()

    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 0
    assert uow.external_call_state("call-1") == "agent_result_submitted"
    persisted = uow.get_external_call("call-1")
    assert persisted.provider_response_id == "response-1"
    assert persisted.usage == {"input_tokens": 7}


@pytest.mark.asyncio
async def test_execute_recovers_after_raw_metadata_crash_without_second_provider_call(
    tmp_path,
) -> None:
    uow, _, runtime = _runtime(tmp_path, uow_type=CrashOnceRawMetadataUnitOfWork)
    provider = CountingProvider()
    runner = ExternalCallRunner(runtime)

    with pytest.raises(RuntimeError, match="crash after raw manifest"):
        await runner.execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "started"
    result = await runner.execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_atomic_result_crash_retries_from_raw_without_provider_recall(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path, uow_type=CrashOnceAtomicResultUnitOfWork)
    provider = CountingProvider()
    runner = ExternalCallRunner(runtime)

    with pytest.raises(RuntimeError, match="crash before atomic result commit"):
        await runner.execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "raw_response_persisted"
    result = await runner.resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_duplicate_execute_returns_exact_submitted_result(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    provider = CountingProvider()
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        return json.loads(raw)

    runner = ExternalCallRunner(runtime)
    first = await runner.execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=validator,
        context=_context(),
    )
    second = await runner.execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=validator,
        context=_context(),
    )

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert uow.external_call_state("call-1") == "agent_result_submitted"
    assert provider.call_count == 1
    assert validation_count == 1


@pytest.mark.asyncio
async def test_duplicate_execute_rejects_mismatched_request_fingerprint(tmp_path) -> None:
    _, _, runtime = _runtime(tmp_path)
    provider = CountingProvider()
    runner = ExternalCallRunner(runtime)
    await runner.execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    with pytest.raises(ValueError, match="request fingerprint"):
        await runner.execute(
            call_id="call-1",
            request={"prompt": "different"},
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=_context(),
        )

    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_resume_rejects_execution_context_mismatch(tmp_path) -> None:
    _, _, runtime = _runtime(tmp_path)
    provider = CountingProvider()
    runner = ExternalCallRunner(runtime)
    await runner.execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    mismatched = _context().model_copy(update={"skill_version": "0.2.0"})

    with pytest.raises(ValueError, match="execution context"):
        await runner.resume(
            "call-1",
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=mismatched,
        )

    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_duplicate_execute_rejects_execution_context_mismatch(tmp_path) -> None:
    _, _, runtime = _runtime(tmp_path)
    provider = CountingProvider()
    runner = ExternalCallRunner(runtime)
    await runner.execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    mismatched = _context().model_copy(update={"input_snapshot_hash": "sha256:different"})

    with pytest.raises(ValueError, match="execution context"):
        await runner.execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=mismatched,
        )

    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_legacy_validated_call_submits_without_provider_or_validator_recall(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    ref = artifacts.persist_raw("call-1", b'{"hypotheses":[]}', "application/json")
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    uow.record_validated("call-1", {"hypotheses": []})
    provider = FailingProvider()
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        raise AssertionError("validator must not be called")

    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=validator,
        context=_context(),
    )

    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 0
    assert validation_count == 0
    assert uow.external_call_state("call-1") == "agent_result_submitted"


@pytest.mark.asyncio
async def test_submitted_result_reconstructs_exactly_after_runtime_restart(tmp_path) -> None:
    _, _, runtime = _runtime(tmp_path)
    provider = CountingProvider()
    first = await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    restarted_uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    restarted_runtime = SimpleNamespace(
        uow=restarted_uow,
        artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    recovered = await ExternalCallRunner(restarted_runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: (_ for _ in ()).throw(AssertionError("must not validate")),
        context=_context(),
    )

    assert recovered.model_dump(mode="json") == first.model_dump(mode="json")
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_resume_started_without_durable_manifest_does_not_call_provider(tmp_path) -> None:
    _, _, runtime = _runtime(tmp_path)
    _plan_started(runtime.uow)
    provider = FailingProvider()

    with pytest.raises(ValueError, match="durable raw response"):
        await ExternalCallRunner(runtime).resume(
            "call-1",
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=_context(),
        )

    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_resume_planned_call_does_not_advance_or_call_provider(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    context = _context()
    uow.plan_external_call(
        "call-1",
        request_fingerprint({"prompt": "generate"}),
        run_id=context.run_id,
        task_id=context.task_id,
        execution_context=context.model_dump(mode="json"),
    )
    provider = FailingProvider()

    with pytest.raises(ValueError, match="durable raw response"):
        await ExternalCallRunner(runtime).resume(
            "call-1",
            provider=provider,
            validator=lambda raw: json.loads(raw),
            context=context,
        )

    assert uow.external_call_state("call-1") == "planned"
    assert provider.call_count == 0
