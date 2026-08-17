import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import co_scientist.adapters.artifacts.filesystem as artifact_filesystem
from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.task import NewTask
from co_scientist.events.models import NewEvent
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint


def _valid_generation_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [
            {
                "schema_version": 1,
                "hypothesis_id": "h-recovery",
                "content_id": "c-recovery",
                "research_plan_version": 1,
                "title": "Recovery hypothesis",
                "claim": "Durable raw responses permit replay without provider recall.",
                "mechanism_chain": ["persist", "resume", "submit"],
                "assumptions": [],
                "predictions": [],
                "falsifiers": [],
                "generation_strategy": "recovery fixture",
                "parent_content_ids": [],
                "supersedes_content_id": None,
                "content_hash": None,
            }
        ],
    }


def _valid_generation_bytes() -> bytes:
    return json.dumps(
        _valid_generation_payload(), separators=(",", ":"), sort_keys=True
    ).encode()


class CountingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=_valid_generation_bytes(),
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


class ManifestThenRaiseArtifactStore(FilesystemArtifactStore):
    def persist_raw(self, call_id, data, mime_type, **metadata):
        super().persist_raw(call_id, data, mime_type, **metadata)
        raise OSError("directory fsync acknowledgement lost")


class MismatchedManifestThenRaiseArtifactStore(FilesystemArtifactStore):
    def __init__(self, root, mismatch) -> None:
        super().__init__(root)
        self.mismatch = mismatch

    def persist_raw(self, call_id, data, mime_type, **metadata):
        if self.mismatch == "body":
            data = b'{"hypotheses":["stale"]}'
        elif self.mismatch == "mime_type":
            mime_type = "text/plain"
        elif self.mismatch == "provider_response_id":
            metadata["provider_response_id"] = "stale-response"
        elif self.mismatch == "usage":
            metadata["usage"] = {"input_tokens": 999}
        super().persist_raw(call_id, data, mime_type, **metadata)
        raise OSError("post-manifest persist failure")


class PersistentConfirmationFailureArtifactStore(ManifestThenRaiseArtifactStore):
    def __init__(self, root) -> None:
        super().__init__(root)
        self.confirmation_count = 0

    def confirm_raw(self, manifest) -> None:
        self.confirmation_count += 1
        raise OSError("durability confirmation failed")


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        run_id="r-1",
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.2.0",
        output_schema_id="GenerationResultV1",
        output_schema_version=1,
        research_plan_version=1,
        provider="stub",
        model_or_tool="stub-model",
        input_snapshot_hash="sha256:input",
    )


def _runtime(tmp_path, *, uow_type=SqliteUnitOfWork, artifacts=None):
    uow = uow_type(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    uow.create_started_run(
        "r-1",
        manifest={},
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
                payload={},
            )
        ]
    )
    artifact_store = artifacts or FilesystemArtifactStore(tmp_path / "artifacts")
    return uow, artifact_store, SimpleNamespace(uow=uow, artifacts=artifact_store)


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


def _provenance(*, request=None, context=None) -> dict[str, str]:
    request = request or {"prompt": "generate"}
    context = context or _context()
    return {
        "request_fingerprint": request_fingerprint(request),
        "run_id": context.run_id,
        "task_id": context.task_id,
        "execution_context_fingerprint": request_fingerprint(
            context.model_dump(mode="json")
        ),
    }


def _forget_execution_context(uow) -> None:
    with uow.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE external_calls SET execution_context_json = NULL "
                "WHERE external_call_id = 'call-1'"
            )
        )


def _forged_trace_context() -> AgentExecutionContext:
    return _context().model_copy(
        update={
            "skill_id": "foreign-skill",
            "skill_version": "99.0.0",
            "output_schema_version": 99,
            "input_snapshot_hash": "sha256:foreign-input",
        }
    )


@pytest.mark.asyncio
async def test_resume_validates_existing_raw_without_provider_recall(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    ref = artifacts.persist_raw(
        "call-1",
        _valid_generation_bytes(),
        "application/json",
        **_provenance(),
    )
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    provider = FailingProvider()

    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
    assert provider.call_count == 0
    assert uow.external_call_state("call-1") == "agent_result_submitted"


@pytest.mark.asyncio
async def test_started_call_recovers_durable_manifest_without_provider_recall(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    artifacts.persist_raw(
        "call-1",
        _valid_generation_bytes(),
        "application/json",
        provider_response_id="response-1",
        usage={"input_tokens": 7},
        **_provenance(),
    )
    provider = FailingProvider()

    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
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
    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
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
    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
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
    mismatched = _context().model_copy(update={"skill_version": "0.1.0"})

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
    ref = artifacts.persist_raw(
        "call-1",
        _valid_generation_bytes(),
        "application/json",
        **_provenance(),
    )
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    uow.record_validated("call-1", _valid_generation_payload())
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

    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
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
@pytest.mark.parametrize(
    "terminal_state",
    ["agent_result_submitted", "domain_result_applied"],
)
async def test_legacy_terminal_result_without_envelope_reconstructs_without_replay(
    tmp_path, terminal_state
) -> None:
    uow, _, runtime = _runtime(tmp_path)
    initial_provider = CountingProvider()
    first = await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=initial_provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    with uow.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE external_calls SET agent_result_json = NULL, "
                "execution_context_json = NULL, state = :state "
                "WHERE external_call_id = 'call-1'"
            ),
            {"state": terminal_state},
        )
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        raise AssertionError("validator must not be called")

    recovery_provider = FailingProvider()
    recovered = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=recovery_provider,
        validator=validator,
        context=_context(),
    )

    assert recovered.model_dump(mode="json") == first.model_dump(mode="json")
    assert initial_provider.call_count == 1
    assert recovery_provider.call_count == 0
    assert validation_count == 0
    assert uow.external_call_state("call-1") == terminal_state


@pytest.mark.asyncio
async def test_terminal_result_with_envelope_does_not_relax_missing_context(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    initial_provider = CountingProvider()
    await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=initial_provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )
    _forget_execution_context(uow)
    recovery_provider = FailingProvider()

    with pytest.raises(ValueError, match="execution context"):
        await ExternalCallRunner(runtime).resume(
            "call-1",
            provider=recovery_provider,
            validator=lambda raw: json.loads(raw),
            context=_forged_trace_context(),
        )

    assert uow.external_call_state("call-1") == "agent_result_submitted"
    assert initial_provider.call_count == 1
    assert recovery_provider.call_count == 0


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("request_fingerprint", "stale-request"),
        ("run_id", "foreign-run"),
        ("task_id", "foreign-task"),
        ("execution_context_fingerprint", "foreign-context"),
    ],
)
async def test_started_recovery_rejects_forged_manifest_provenance(
    tmp_path, field, forged_value
) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    provenance = _provenance()
    provenance[field] = forged_value
    artifacts.persist_raw(
        "call-1",
        _valid_generation_bytes(),
        "application/json",
        **provenance,
    )
    provider = FailingProvider()
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        return json.loads(raw)

    with pytest.raises(ValueError, match="manifest provenance"):
        await ExternalCallRunner(runtime).resume(
            "call-1",
            provider=provider,
            validator=validator,
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "started"
    assert provider.call_count == 0
    assert validation_count == 0


@pytest.mark.asyncio
async def test_manifest_installed_before_persist_error_continues_without_terminal_failure(
    tmp_path,
) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    uow.create_started_run(
        "r-1",
        manifest={},
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
                payload={},
            )
        ]
    )
    artifacts = ManifestThenRaiseArtifactStore(tmp_path / "artifacts")
    runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
    provider = CountingProvider()

    result = await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
    assert provider.call_count == 1
    assert uow.external_call_state("call-1") == "agent_result_submitted"


@pytest.mark.asyncio
async def test_started_legacy_call_without_context_rejects_forged_trace_before_manifest(
    tmp_path,
) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    _forget_execution_context(uow)
    forged_context = _forged_trace_context()
    artifacts.persist_raw(
        "call-1",
        _valid_generation_bytes(),
        "application/json",
        **_provenance(context=forged_context),
    )
    provider = FailingProvider()
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        return json.loads(raw)

    with pytest.raises(ValueError, match="execution context"):
        await ExternalCallRunner(runtime).resume(
            "call-1",
            provider=provider,
            validator=validator,
            context=forged_context,
        )

    assert uow.external_call_state("call-1") == "started"
    assert provider.call_count == 0
    assert validation_count == 0


@pytest.mark.asyncio
async def test_post_raw_legacy_call_without_context_rejects_forged_trace_before_validation(
    tmp_path,
) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    _plan_started(uow)
    ref = artifacts.persist_raw(
        "call-1",
        _valid_generation_bytes(),
        "application/json",
        **_provenance(),
    )
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    _forget_execution_context(uow)
    provider = FailingProvider()
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        return json.loads(raw)

    with pytest.raises(ValueError, match="execution context"):
        await ExternalCallRunner(runtime).resume(
            "call-1",
            provider=provider,
            validator=validator,
            context=_forged_trace_context(),
        )

    assert uow.external_call_state("call-1") == "raw_response_persisted"
    assert provider.call_count == 0
    assert validation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    ["body", "mime_type", "provider_response_id", "usage"],
)
async def test_persist_error_rejects_manifest_that_does_not_match_current_response(
    tmp_path, mismatch
) -> None:
    artifacts = MismatchedManifestThenRaiseArtifactStore(
        tmp_path / "artifacts", mismatch
    )
    uow, _, runtime = _runtime(tmp_path, artifacts=artifacts)
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        return json.loads(raw)

    with pytest.raises(OSError, match="post-manifest persist failure"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=CountingProvider(),
            validator=validator,
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "raw_persist_failed"
    assert validation_count == 0


@pytest.mark.asyncio
async def test_post_rename_fsync_failure_is_recovered_by_explicit_confirmation(
    tmp_path, monkeypatch
) -> None:
    uow, _, runtime = _runtime(tmp_path)
    provider = CountingProvider()
    real_fsync = artifact_filesystem.os.fsync
    fsync_count = 0

    def fail_manifest_directory_fsync_once(file_descriptor):
        nonlocal fsync_count
        fsync_count += 1
        if fsync_count == 4:
            raise OSError("manifest directory fsync failed")
        return real_fsync(file_descriptor)

    monkeypatch.setattr(artifact_filesystem.os, "fsync", fail_manifest_directory_fsync_once)

    result = await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=_context(),
    )

    assert result.model_dump(mode="json")["payload"] == _valid_generation_payload()
    assert fsync_count >= 7
    assert provider.call_count == 1
    assert uow.external_call_state("call-1") == "agent_result_submitted"


@pytest.mark.asyncio
async def test_persistent_durability_confirmation_failure_keeps_started_recoverable(
    tmp_path,
) -> None:
    artifacts = PersistentConfirmationFailureArtifactStore(tmp_path / "artifacts")
    uow, _, runtime = _runtime(tmp_path, artifacts=artifacts)
    provider = CountingProvider()
    validation_count = 0

    def validator(raw):
        nonlocal validation_count
        validation_count += 1
        return json.loads(raw)

    runner = ExternalCallRunner(runtime)
    with pytest.raises(OSError, match="durability confirmation failed"):
        await runner.execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=validator,
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "started"
    with pytest.raises(OSError, match="durability confirmation failed"):
        await runner.resume(
            "call-1",
            provider=provider,
            validator=validator,
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "started"
    assert artifacts.confirmation_count == 2
    assert provider.call_count == 1
    assert validation_count == 0
