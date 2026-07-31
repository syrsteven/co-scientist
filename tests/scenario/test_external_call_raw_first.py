from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint


class StubProvider:
    async def invoke(self, request):
        return RawExternalResponse(
            body=b'{"hypotheses":[]}',
            mime_type="application/json",
            provider_response_id="stub-1",
        )


class SubmissionFailingUnitOfWork(SqliteUnitOfWork):
    def record_submitted_result(self, call_id, result) -> None:
        raise RuntimeError("submission unavailable")


class RawMetadataFailingUnitOfWork(SqliteUnitOfWork):
    def record_raw_and_transition(self, call_id, ref, target_state, **metadata) -> None:
        raise RuntimeError("raw metadata unavailable")


class ValidatedPayloadFailingUnitOfWork(SqliteUnitOfWork):
    def record_validated(self, call_id, payload) -> None:
        raise RuntimeError("validated payload unavailable")


class ProviderWithoutResponse:
    async def invoke(self, request):
        raise RuntimeError("provider unavailable")


class FailingArtifactStore:
    def persist_raw(self, call_id, data, mime_type):
        raise OSError("artifact store unavailable")


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )


@pytest.mark.asyncio
async def test_validator_observes_persisted_raw_artifact(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
    observed = []

    def validator(raw: bytes):
        observed.append(uow.external_call_state("call-1"))
        return {"hypotheses": []}

    result = await ExternalCallRunner(runtime).execute(
        call_id="call-1",
        request={"prompt": "generate"},
        provider=StubProvider(),
        validator=validator,
        context=_context(),
    )

    assert observed == ["raw_response_persisted"]
    assert result.external_call_id == "call-1"
    assert result.task_id == "task-1"
    assert result.idempotency_key == "generation:r-1:1"
    assert result.skill_id == "generation"
    assert result.skill_version == "0.1.0"
    assert result.output_schema_version == 1
    assert result.input_snapshot_hash == "sha256:input"
    assert result.raw_artifact_ref.startswith(str(tmp_path / "artifacts"))
    assert uow.external_call_state("call-1") == "agent_result_submitted"

    with pytest.raises(ValidationError, match="frozen"):
        result.status = "failed"


@pytest.mark.asyncio
async def test_submission_failure_is_durable_after_validation(tmp_path) -> None:
    uow = SubmissionFailingUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    runtime = SimpleNamespace(
        uow=uow,
        artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    with pytest.raises(RuntimeError, match="submission unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: {"hypotheses": []},
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "submission_failed"


@pytest.mark.asyncio
async def test_provider_failure_before_response_is_durable(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    runtime = SimpleNamespace(
        uow=uow,
        artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=ProviderWithoutResponse(),
            validator=lambda raw: {"hypotheses": []},
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "failed_before_response"


@pytest.mark.asyncio
async def test_raw_persistence_failure_is_durable_and_skips_validation(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    runtime = SimpleNamespace(uow=uow, artifacts=FailingArtifactStore())
    observed = []

    with pytest.raises(OSError, match="artifact store unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: observed.append(raw),
            context=_context(),
        )

    assert observed == []
    assert uow.external_call_state("call-1") == "raw_persist_failed"


@pytest.mark.asyncio
async def test_raw_metadata_failure_is_durable_and_skips_validation(tmp_path) -> None:
    uow = RawMetadataFailingUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    artifact_root = tmp_path / "artifacts"
    runtime = SimpleNamespace(uow=uow, artifacts=FilesystemArtifactStore(artifact_root))
    observed = []

    with pytest.raises(RuntimeError, match="raw metadata unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: observed.append(raw),
            context=_context(),
        )

    assert observed == []
    raw_files = [path for path in artifact_root.rglob("*") if path.is_file()]
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == b'{"hypotheses":[]}'
    assert uow.external_call_state("call-1") == "raw_persist_failed"


@pytest.mark.asyncio
async def test_validation_failure_is_durable_with_raw_artifact_intact(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runtime = SimpleNamespace(uow=uow, artifacts=artifacts)

    def reject(raw):
        raise ValueError("invalid response")

    with pytest.raises(ValueError, match="invalid response"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=reject,
            context=_context(),
        )

    persisted = uow.get_external_call("call-1")
    assert persisted.state == "validation_failed"
    assert persisted.raw_artifact_ref is not None
    assert artifacts.read(persisted.raw_artifact_ref) == b'{"hypotheses":[]}'


@pytest.mark.asyncio
async def test_validated_payload_persistence_failure_is_durable(tmp_path) -> None:
    uow = ValidatedPayloadFailingUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    runtime = SimpleNamespace(
        uow=uow,
        artifacts=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    with pytest.raises(RuntimeError, match="validated payload unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: {"hypotheses": []},
            context=_context(),
        )

    assert uow.external_call_state("call-1") == "validation_failed"


def test_request_fingerprint_uses_canonical_json() -> None:
    assert request_fingerprint({"b": 2, "a": 1}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )
    assert request_fingerprint({"a": 1, "b": 2}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )
