import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.agents.executor import SkillExecutor
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.task import NewTask
from co_scientist.events.models import NewEvent
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import ExternalCallRunner, prompt_hash
from co_scientist.skills.loader import core_skill_directory
from tests._fenced_runtime import (
    budgeted_task,
    claim_running_task,
    execution_manifest,
    fenced_context,
)


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


class RealShapeOpenAIProvider:
    async def invoke(self, _request: dict) -> RawExternalResponse:
        payload = {
            "schema_version": 1,
            "research_plan_version": 1,
            "hypotheses": [
                {
                    "schema_version": 1,
                    "hypothesis_id": "h-1",
                    "content_id": "c-1",
                    "research_plan_version": 1,
                    "title": "Mechanical gate",
                    "claim": "Strain precedes fibrotic commitment.",
                    "mechanism_chain": ["strain", "cell_state"],
                    "assumptions": ["strain is measurable"],
                    "predictions": ["normalization reduces fibrosis"],
                    "falsifiers": ["commitment precedes strain"],
                    "generation_strategy": "causal contrast",
                }
            ],
        }
        envelope = {
            "id": "resp-real-shape",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(payload, separators=(",", ":")),
                        }
                    ],
                }
            ],
        }
        return RawExternalResponse(
            body=json.dumps(envelope, separators=(",", ":")).encode(),
            mime_type="application/json",
            provider_response_id="resp-real-shape",
            usage={"input_tokens": 1, "output_tokens": 1},
        )


def _runtime(tmp_path):
    uow = SqliteUnitOfWork(f"sqlite:///{tmp_path / 'core.db'}")
    uow.create_schema()
    uow.create_started_run(
        "r-1",
        manifest=execution_manifest(),
        event=NewEvent(event_type="RunStarted", payload={}),
        idempotency_key="start:r-1:0",
    )
    uow.enqueue_tasks(
        [
            budgeted_task(NewTask(
                task_id="task-1",
                run_id="r-1",
                idempotency_key="generation:r-1:1",
                intent_type="generate",
                payload={},
            ))
        ]
    )
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    claimed = claim_running_task(uow, run_id="r-1", task_id="task-1")
    return uow, artifacts, SimpleNamespace(uow=uow, artifacts=artifacts), claimed


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
        provider="openai",
        model_or_tool="configured-model",
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
    uow, artifacts, runtime, claimed = _runtime(tmp_path)

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
            context=fenced_context(_context(), claimed),
            reservation_id=claimed.reservation_id,
            fence=claimed,
        )

    call = uow.get_external_call("call-1")
    assert call.state == "validation_failed"
    assert call.raw_artifact_ref is not None
    assert artifacts.read(call.raw_artifact_ref).startswith(b'{"id":"resp-1"')


@pytest.mark.asyncio
async def test_skill_executor_validates_real_responses_output_after_raw_persistence(
    tmp_path,
) -> None:
    uow, artifacts, runtime, claimed = _runtime(tmp_path)
    context = fenced_context(
        _context().model_copy(
            update={
                "prompt_hash": None,
                "input_snapshot_hash": "sha256:input",
            }
        ),
        claimed,
    )

    result = await SkillExecutor(
        ExternalCallRunner(runtime),
        RealShapeOpenAIProvider(),
    ).execute(
        call_id="call-real-shape",
        skill_directory=core_skill_directory("generation"),
        inputs={"research_goal": "test"},
        context=context,
        reservation_id=claimed.reservation_id,
        fence=claimed,
    )

    assert result.payload["hypotheses"][0]["hypothesis_id"] == "h-1"
    call = uow.get_external_call("call-real-shape")
    assert call.state == "agent_result_submitted"
    assert call.raw_artifact_ref is not None
    assert b'"output"' in artifacts.read(call.raw_artifact_ref)
