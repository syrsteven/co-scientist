import json
from types import SimpleNamespace

import pytest

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.runtime.external_calls import ExternalCallRunner


class FailingProvider:
    call_count = 0

    async def invoke(self, request):
        self.call_count += 1
        raise AssertionError("provider must not be called")


@pytest.mark.asyncio
async def test_resume_validates_existing_raw_without_provider_recall(tmp_path) -> None:
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runtime = SimpleNamespace(uow=uow, artifacts=artifacts)
    uow.plan_external_call("call-1", "sha256:request")
    uow.transition_call("call-1", "started")
    ref = artifacts.persist_raw("call-1", b'{"hypotheses":[]}', "application/json")
    uow.record_raw_and_transition("call-1", ref, "raw_response_persisted")
    provider = FailingProvider()
    context = AgentExecutionContext(
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
    )

    result = await ExternalCallRunner(runtime).resume(
        "call-1",
        provider=provider,
        validator=lambda raw: json.loads(raw),
        context=context,
    )

    assert result.payload == {"hypotheses": []}
    assert provider.call_count == 0
