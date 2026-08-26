import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.fake import FakeLLMProvider
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import SkillExecutor
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.task import NewTask, TaskLeaseFence, lease_fence_fingerprint
from co_scientist.events.models import NewEvent
from co_scientist.ports.artifact_store import ArtifactRef
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint
from co_scientist.skills.loader import core_skill_directory


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
        skill_version="0.2.0",
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

    with pytest.raises(ValidationError):
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
