import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork, TaskRow
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.task import NewTask
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import prompt_hash, request_fingerprint
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.worker import Worker, WorkerTaskPayload
from co_scientist.supervisor.orchestrator import Supervisor

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
GENERATION_DIRECTORY = Path("skills/generation")


def _generation_body() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "research_plan_version": 1,
            "hypotheses": [
                {
                    "schema_version": 1,
                    "hypothesis_id": "h-worker",
                    "content_id": "content-worker-v1",
                    "research_plan_version": 1,
                    "title": "Fenced worker",
                    "claim": "A claimed immutable task is applied once.",
                    "mechanism_chain": ["claim", "execute", "apply"],
                    "assumptions": [],
                    "predictions": [],
                    "falsifiers": [],
                    "generation_strategy": "worker fixture",
                    "parent_content_ids": [],
                    "supersedes_content_id": None,
                    "content_hash": None,
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


class _Provider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        return RawExternalResponse(
            body=_generation_body(),
            mime_type="application/json",
            provider_response_id=f"worker-{self.call_count}",
            usage={"input_tokens": 4, "output_tokens": 8, "cost_usd": "0.01"},
        )


class _SlowProvider(_Provider):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def invoke(self, request):
        self.call_count += 1
        try:
            await anyio.sleep_forever()
        finally:
            self.cancelled = True


class _FollowupProvider(_Provider):
    async def invoke(self, request):
        self.call_count += 1
        if request["skill_id"] == "generation":
            body = _generation_body()
        else:
            inputs = request["input"]
            body = json.dumps(
                {
                    "schema_version": 1,
                    "research_plan_version": 1,
                    "review_id": "review-worker",
                    "hypothesis_id": inputs["hypothesis_id"],
                    "content_hash": inputs["content_hash"],
                    "stage": "initial_review",
                    "recommendation": "pass",
                    "dimension_scores": {},
                    "critical_flaws": [],
                    "evidence_ids": [],
                    "safety_status": "passed",
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        return RawExternalResponse(
            body=body,
            mime_type="application/json",
            provider_response_id=f"followup-{self.call_count}",
            usage={"input_tokens": 4, "output_tokens": 8, "cost_usd": "0.01"},
        )


class _RejectingHeartbeatRuntime:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self.uow = uow
        self.heartbeat_count = 0

    def heartbeat_task(self, **kwargs):
        self.heartbeat_count += 1
        raise ValueError("heartbeat rejected")

    def __getattr__(self, name):
        return getattr(self.uow, name)


def _task_payload() -> dict[str, object]:
    inputs = {"research_question": "Can a lease fence reject stale work?"}
    prompt = (GENERATION_DIRECTORY / "prompts/system.md").read_text(encoding="utf-8")
    return {
        "skill_id": "generation",
        "skill_version": "0.2.0",
        "output_schema_id": "GenerationResultV1",
        "output_schema_version": 1,
        "research_plan_version": 1,
        "provider_id": "provider-fixed",
        "model_or_tool": "model-fixed",
        "inputs": inputs,
        "input_snapshot_hash": request_fingerprint(inputs),
        "prompt_hash": prompt_hash(prompt),
        "budget_estimate": {
            "model_calls": 1,
            "input_tokens": 4,
            "output_tokens": 8,
            "cost_usd": "0.01",
            "hypotheses": 1,
            "matches": 0,
        },
    }


def _runtime(tmp_path):
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'worker.db'}")
    uow.create_schema()
    supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="worker"))
    started = supervisor.create_and_start_run(
        "r-worker",
        manifest={"execution_contract_version": 3, "budget": {}},
        start_payload={},
    )
    return uow, supervisor, started


# Mutation caught: resolving by skill ID alone silently accepts a mutable version change.
def test_registries_resolve_only_exact_immutable_identities() -> None:
    provider = _Provider()
    skills = SkillRegistry({("generation", "0.2.0"): GENERATION_DIRECTORY})
    providers = ProviderRegistry({"provider-fixed": provider})

    assert skills.resolve("generation", "0.2.0") == GENERATION_DIRECTORY
    assert providers.resolve("provider-fixed") is provider
    with pytest.raises(KeyError, match="skill identity"):
        skills.resolve("generation", "0.1.0")
    with pytest.raises(KeyError, match="provider identity"):
        providers.resolve("provider-renamed")


@pytest.mark.asyncio
# Mutation caught: Worker invents work, skips the lease lifecycle, or bypasses Supervisor apply.
async def test_worker_executes_only_existing_supervisor_task_through_fenced_lifecycle(
    tmp_path,
) -> None:
    uow, supervisor, started = _runtime(tmp_path)
    provider = _Provider()
    tokens = iter(("unused-idle-token", "lease-secret"))
    call_ids = iter(("call-worker-attempt-1",))
    worker = Worker(
        runtime=type(
            "Runtime",
            (),
            {
                "uow": uow,
                "artifacts": FilesystemArtifactStore(tmp_path / "artifacts"),
            },
        )(),
        task_runtime=uow,
        supervisor=supervisor,
        skills=SkillRegistry({("generation", "0.2.0"): GENERATION_DIRECTORY}),
        providers=ProviderRegistry({"provider-fixed": provider}),
        worker_id="worker-1",
        clock=lambda: NOW,
        token_factory=lambda: next(tokens),
        call_id_factory=lambda _task: next(call_ids),
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(seconds=30),
    )

    idle = await worker.run_once("r-worker")
    assert idle.model_dump() == {
        "status": "idle",
        "run_id": "r-worker",
        "task_id": None,
        "attempt": None,
    }
    task = NewTask(
        task_id="task-worker",
        run_id="r-worker",
        idempotency_key="generation:r-worker:1",
        intent_type="run_generation",
        payload=_task_payload(),
    )
    supervisor.enqueue_task(task=task, expected_sequence=started.last_sequence)

    completed = await worker.run_once("r-worker")

    assert completed.model_dump() == {
        "status": "completed",
        "run_id": "r-worker",
        "task_id": "task-worker",
        "attempt": 1,
    }
    assert provider.call_count == 1
    assert uow.task_state("task-worker") == "succeeded"
    assert (
        sum(event.event_type == "HypothesisContentCreated" for event in uow.load("r-worker")) == 1
    )
    call = uow.get_external_call("call-worker-attempt-1")
    assert call.state.value == "domain_result_applied"
    assert call.execution_context is not None
    assert call.execution_context["attempt"] == 1
    assert call.execution_context["reservation_id"].startswith("reservation-")
    serialized_context = json.dumps(call.execution_context, sort_keys=True)
    assert "lease-secret" not in serialized_context
    assert call.execution_context["lease_fence_fingerprint"] == (
        "sha256:" + hashlib.sha256(b"r-worker\0task-worker\0" + b"1\0lease-secret").hexdigest()
    )


@pytest.mark.asyncio
# Mutation caught: Worker trusts a task payload whose immutable input snapshot changed.
async def test_worker_rejects_mutated_task_snapshot_before_provider_invocation(tmp_path) -> None:
    uow, supervisor, started = _runtime(tmp_path)
    provider = _Provider()
    payload = _task_payload()
    payload["inputs"] = {"research_question": "mutated after snapshot"}
    supervisor.enqueue_task(
        task=NewTask(
            task_id="task-mutated",
            run_id="r-worker",
            idempotency_key="generation:r-worker:mutated",
            intent_type="run_generation",
            payload=payload,
        ),
        expected_sequence=started.last_sequence,
    )
    worker = Worker(
        runtime=type(
            "Runtime",
            (),
            {
                "uow": uow,
                "artifacts": FilesystemArtifactStore(tmp_path / "artifacts"),
            },
        )(),
        task_runtime=uow,
        supervisor=supervisor,
        skills=SkillRegistry({("generation", "0.2.0"): GENERATION_DIRECTORY}),
        providers=ProviderRegistry({"provider-fixed": provider}),
        worker_id="worker-1",
        clock=lambda: NOW,
        token_factory=lambda: "lease-secret",
        call_id_factory=lambda _task: "call-must-not-run",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(seconds=30),
    )

    with pytest.raises(ValueError, match="input snapshot"):
        await worker.run_once("r-worker")

    assert provider.call_count == 0


@pytest.mark.asyncio
# Mutation caught: a failed heartbeat lets a slow provider continue and persist stale output.
async def test_heartbeat_failure_cancels_provider_and_blocks_later_writes(tmp_path) -> None:
    uow, supervisor, started = _runtime(tmp_path)
    provider = _SlowProvider()
    supervisor.enqueue_task(
        task=NewTask(
            task_id="task-heartbeat",
            run_id="r-worker",
            idempotency_key="generation:r-worker:heartbeat",
            intent_type="run_generation",
            payload=_task_payload(),
        ),
        expected_sequence=started.last_sequence,
    )
    task_runtime = _RejectingHeartbeatRuntime(uow)
    worker = Worker(
        runtime=type(
            "Runtime",
            (),
            {
                "uow": uow,
                "artifacts": FilesystemArtifactStore(tmp_path / "artifacts"),
            },
        )(),
        task_runtime=task_runtime,
        supervisor=supervisor,
        skills=SkillRegistry({("generation", "0.2.0"): GENERATION_DIRECTORY}),
        providers=ProviderRegistry({"provider-fixed": provider}),
        worker_id="worker-1",
        clock=lambda: NOW,
        token_factory=lambda: "heartbeat-secret",
        call_id_factory=lambda _task: "call-heartbeat",
        lease_duration=timedelta(seconds=1),
        heartbeat_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ExceptionGroup) as caught:
        await worker.run_once("r-worker")

    assert any("heartbeat rejected" in str(error) for error in caught.value.exceptions)
    assert task_runtime.heartbeat_count == 1
    assert provider.call_count == 1
    assert provider.cancelled is True
    call = uow.get_external_call("call-heartbeat")
    assert call.state.value == "started"
    assert call.raw_artifact_ref is None
    assert uow.task_state("task-heartbeat") == "running"
    assert not any(event.event_type == "HypothesisContentCreated" for event in uow.load("r-worker"))


@pytest.mark.asyncio
# Mutation caught: Supervisor review follow-ups omit the immutable Worker execution snapshot.
async def test_supervisor_followup_is_a_complete_executable_worker_task(tmp_path) -> None:
    uow, supervisor, started = _runtime(tmp_path)
    provider = _FollowupProvider()
    supervisor.enqueue_task(
        task=NewTask(
            task_id="task-generation",
            run_id="r-worker",
            idempotency_key="generation:r-worker:followup",
            intent_type="run_generation",
            payload=_task_payload(),
        ),
        expected_sequence=started.last_sequence,
    )
    call_ids = iter(("call-generation", "call-reflection"))

    def new_worker(worker_id: str, token: str) -> Worker:
        return Worker(
            runtime=type(
                "Runtime",
                (),
                {
                    "uow": uow,
                    "artifacts": FilesystemArtifactStore(tmp_path / "followup-artifacts"),
                },
            )(),
            task_runtime=uow,
            supervisor=Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="worker")),
            skills=SkillRegistry(
                {
                    ("generation", "0.2.0"): GENERATION_DIRECTORY,
                    ("reflection", "0.2.0"): Path("skills/reflection"),
                }
            ),
            providers=ProviderRegistry({"provider-fixed": provider}),
            worker_id=worker_id,
            clock=lambda: NOW,
            token_factory=lambda: token,
            call_id_factory=lambda _task: next(call_ids),
        )

    await new_worker("worker-generation", "token-generation").run_once("r-worker")
    followup_id = "review:initial_review:h-worker"
    with uow.session_factory() as session:
        row = session.get(TaskRow, followup_id)
        assert row is not None
        payload = json.loads(row.payload_json)
    WorkerTaskPayload.model_validate(payload)

    completed = await new_worker("worker-reflection", "token-reflection").run_once("r-worker")

    assert completed.task_id == followup_id
    assert uow.task_state(followup_id) == "succeeded"
    assert provider.call_count == 2
    assert sum(event.event_type == "ReviewCompleted" for event in uow.load("r-worker")) == 1
