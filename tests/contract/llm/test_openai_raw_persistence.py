import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.task import NewTask
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash


class OutputValidationError(ValueError):
    """Raised when a provider envelope contains malformed structured output."""


class FakeUsage(BaseModel):
    input_tokens: int = 10
    output_tokens: int = 5


class FakeResponse(BaseModel):
    id: str = "resp-1"
    output_text: str = "not-json"
    usage: FakeUsage = FakeUsage()


class FakeResponses:
    async def create(self, **kwargs):
        return FakeResponse()


class FakeClient:
    responses = FakeResponses()


def _runtime(tmp_path):
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
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


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        run_id="r-1",
        task_id="task-1",
        idempotency_key="generation:r-1:1",
        skill_id="generation",
        skill_version="0.1.0",
        output_schema_version=1,
        input_snapshot_hash="sha256:input",
        prompt_hash=prompt_hash("Return JSON."),
    )


def _validate_response_output(raw: bytes) -> dict[str, str]:
    output = json.loads(raw)["output_text"]
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise OutputValidationError("structured output is not JSON") from error


@pytest.mark.asyncio
async def test_malformed_structured_output_is_still_durably_saved(tmp_path) -> None:
    uow, artifacts, runtime = _runtime(tmp_path)

    with pytest.raises(OutputValidationError, match="structured output is not JSON"):
        await ExternalCallRunner(runtime).execute(
            call_id="call-1",
            request={
                "model": "configured-model",
                "system_prompt": "Return JSON.",
                "user_prompt": "Generate one hypothesis.",
                "json_schema": {"type": "object"},
            },
            provider=OpenAIResponsesProvider(FakeClient()),
            validator=_validate_response_output,
            context=_context(),
        )

    call = uow.get_external_call("call-1")
    assert call.state == "validation_failed"
    assert call.raw_artifact_ref is not None
    assert artifacts.read(call.raw_artifact_ref).startswith(b'{"id":"resp-1"')
