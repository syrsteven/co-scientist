from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.task import NewTask
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint


class StubProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=b'{"hypotheses":[]}',
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


class FailingArtifactStore:
    def persist_raw(self, call_id, data, mime_type, **metadata):
        raise OSError("artifact store unavailable")


class AtomicResultFailingUnitOfWork(SqliteUnitOfWork):
    def record_validated_and_submitted(self, call_id, payload, result) -> None:
        raise RuntimeError("database unavailable")


def _context(
    *, run_id: str = "r-1", task_id: str = "task-1"
) -> AgentExecutionContext:
    return AgentExecutionContext(
        run_id=run_id,
        task_id=task_id,
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )


def _runtime(tmp_path, *, uow_type=SqliteUnitOfWork, artifacts=None):
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
    artifact_store = artifacts or FilesystemArtifactStore(tmp_path / "artifacts")
    return uow, artifact_store, SimpleNamespace(uow=uow, artifacts=artifact_store)


@pytest.mark.asyncio
async def test_validator_observes_persisted_raw_artifact(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)
    observed = []
    provider = StubProvider()

    def validator(raw: bytes):
        observed.append(uow.external_call_state("call-1"))
        return {"hypotheses": []}

    result = await ExternalCallRunner(runtime).execute(
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
    assert result.skill_version == "0.1.0"
    assert result.output_schema_version == 1
    assert result.input_snapshot_hash == "sha256:input"
    assert result.raw_artifact_ref.path.startswith("raw/call-1/")
    assert not result.raw_artifact_ref.path.startswith("/")
    assert artifacts.read(result.raw_artifact_ref) == b'{"hypotheses":[]}'
    assert uow.external_call_state("call-1") == "agent_result_submitted"

    with pytest.raises(ValidationError, match="frozen"):
        result.status = "failed"


@pytest.mark.asyncio
async def test_provider_failure_before_response_is_durable(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    provider = ProviderWithoutResponse()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: {"hypotheses": []},
            context=_context(),
        )

    assert provider.call_count == 1
    assert uow.external_call_state("call-1") == "failed_before_response"


@pytest.mark.asyncio
async def test_actual_raw_persistence_failure_is_terminal_and_skips_validation(tmp_path) -> None:
    failing_artifacts = FailingArtifactStore()
    uow, _, runtime = _runtime(tmp_path, artifacts=failing_artifacts)
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
async def test_validator_failure_is_terminal_with_raw_artifact_intact(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)

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
async def test_infrastructure_failure_after_durable_raw_remains_recoverable(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path, uow_type=AtomicResultFailingUnitOfWork)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=StubProvider(),
            validator=lambda raw: {"hypotheses": []},
            context=_context(),
        )

    call = uow.get_external_call("call-1")
    assert call.state == "raw_response_persisted"
    assert call.raw_artifact_ref is not None
    assert artifacts.read(call.raw_artifact_ref) == b'{"hypotheses":[]}'
    assert call.validated_payload is None
    assert call.agent_result is None


@pytest.mark.asyncio
async def test_execute_rejects_task_run_mismatch_before_provider_call(tmp_path) -> None:
    uow, _, runtime = _runtime(tmp_path)
    uow.create_run("r-2", manifest={})
    provider = StubProvider()

    with pytest.raises(ValueError, match="does not belong to run r-2"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={"prompt": "generate"},
            provider=provider,
            validator=lambda raw: {"hypotheses": []},
            context=_context(run_id="r-2"),
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
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
        status="completed",
        payload={"nested": {"score": 1}, "items": ["a", "b"]},
        raw_artifact_ref=ArtifactRef(
            path="raw/call-1/digest",
            sha256="sha256:digest",
            mime_type="application/json",
            byte_length=2,
        ),
    )

    with pytest.raises(TypeError):
        result.payload["nested"]["score"] = 2
    with pytest.raises(AttributeError):
        result.payload["items"].append("c")
    assert result.run_id == "r-1"
    assert result.model_dump(mode="json")["payload"] == {
        "nested": {"score": 1},
        "items": ["a", "b"],
    }


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
            skill_version="0.1.0",
            output_schema_version=1,
            input_snapshot_hash="sha256:input",
            status="completed",
            payload={"invalid": invalid},
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
