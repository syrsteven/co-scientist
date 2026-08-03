import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.literature.pubmed import PubMedProvider
from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider
from co_scientist.adapters.persistence.sqlite import (
    CostEntryRow,
    ExternalCallRow,
    SqliteUnitOfWork,
)
from co_scientist.agents.result import AgentExecutionContext
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import NewTask
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.external_calls import (
    ExternalCallRunner,
    execution_context_fingerprint,
    prompt_hash,
    request_fingerprint,
)
from co_scientist.supervisor.orchestrator import Supervisor


def _online_enabled() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        and os.getenv("CO_SCIENTIST_OPENAI_MODEL")
        and os.getenv("CO_SCIENTIST_NETWORK_ONLINE") == "1"
    )


def _openai_payload(raw: bytes) -> dict[str, Any]:
    envelope = json.loads(raw)
    for output in envelope.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text":
                payload = json.loads(content["text"])
                if isinstance(payload, dict):
                    return payload
    raise ValueError("OpenAI response did not contain structured output_text")


class _PubMedSearchCall:
    def __init__(self, provider: PubMedProvider) -> None:
        self.provider = provider

    async def invoke(self, request: dict[str, Any]) -> RawExternalResponse:
        return await self.provider.search(request["query"], request["limit"])


class OnlineCoreCli:
    async def start_lens(
        self,
        *,
        provider: str,
        literature_provider: str,
        data_dir: Path,
    ) -> str:
        assert provider == "openai"
        assert literature_provider == "pubmed"
        from openai import AsyncOpenAI

        run_id = "lens-online-smoke"
        uow = SqliteUnitOfWork(f"sqlite:///{data_dir / 'online-smoke.db'}")
        uow.create_schema()
        artifacts = FilesystemArtifactStore(data_dir / "online-artifacts")
        supervisor = Supervisor(uow=uow, review_policy=ReviewPolicy(profile_id="online-smoke"))
        started = supervisor.create_and_start_run(
            run_id,
            manifest={
                "provider": "openai",
                "model": os.environ["CO_SCIENTIST_OPENAI_MODEL"],
                "literature_provider": "pubmed",
            },
            start_payload={"provider": "openai"},
        )
        runner = ExternalCallRunner(SimpleNamespace(uow=uow, artifacts=artifacts))
        sequence = started.last_sequence

        generation_task = NewTask(
            task_id="online-generation",
            run_id=run_id,
            idempotency_key="online-generation",
            intent_type="run_generation",
            payload={},
        )
        scheduled = supervisor.enqueue_task(task=generation_task, expected_sequence=sequence)
        sequence = scheduled.last_sequence
        uow.transition_task(generation_task.task_id, TaskState.LEASED)
        uow.transition_task(generation_task.task_id, TaskState.RUNNING)
        generation_request = {
            "model": os.environ["CO_SCIENTIST_OPENAI_MODEL"],
            "system_prompt": (
                "Return two mechanistically distinct, falsifiable hypotheses about transparent "
                "versus fibrotic lens regeneration."
            ),
            "user_prompt": (
                "Include surgical configuration, host age, early cell state, tissue "
                "organization, and final morphology in every mechanism chain."
            ),
            "schema_name": "lens_hypotheses",
            "json_schema": {
                "type": "object",
                "properties": {
                    "hypotheses": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "hypothesis_id": {"type": "string"},
                                "content_id": {"type": "string"},
                                "content_hash": {"type": "string"},
                                "title": {"type": "string"},
                                "claim": {"type": "string"},
                                "mechanism_chain": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "assumptions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "predictions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "falsifiers": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "hypothesis_id",
                                "content_id",
                                "content_hash",
                                "title",
                                "claim",
                                "mechanism_chain",
                                "assumptions",
                                "predictions",
                                "falsifiers",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["hypotheses"],
                "additionalProperties": False,
            },
        }
        generation_context = AgentExecutionContext(
            run_id=run_id,
            task_id=generation_task.task_id,
            idempotency_key=generation_task.idempotency_key,
            skill_id="generation",
            skill_version="0.1.0",
            output_schema_version=1,
            input_snapshot_hash="sha256:online-lens-goal",
            prompt_hash=prompt_hash(str(generation_request["system_prompt"])),
        )
        uow.plan_external_call(
            "online-openai-call",
            request_fingerprint(generation_request),
            run_id=run_id,
            task_id=generation_task.task_id,
            execution_context=generation_context.model_dump(mode="json"),
            provider="openai",
            model_or_tool=os.environ["CO_SCIENTIST_OPENAI_MODEL"],
        )
        openai_result = await runner.execute(
            call_id="online-openai-call",
            request=generation_request,
            provider=OpenAIResponsesProvider(
                AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
            ),
            validator=_openai_payload,
            context=generation_context,
        )
        uow.transition_task(generation_task.task_id, TaskState.RESULT_RECEIVED)
        sequence = supervisor.handle_result(
            run_id,
            generation_task.task_id,
            openai_result,
            expected_sequence=sequence,
        ).last_sequence

        literature_task = NewTask(
            task_id="online-pubmed-search",
            run_id=run_id,
            idempotency_key="online-pubmed-search",
            intent_type="run_meta_review",
            payload={},
        )
        scheduled = supervisor.enqueue_task(task=literature_task, expected_sequence=sequence)
        uow.transition_task(literature_task.task_id, TaskState.LEASED)
        uow.transition_task(literature_task.task_id, TaskState.RUNNING)
        pubmed_request = {
            "query": "lens epithelial regeneration fibrosis",
            "limit": 5,
        }
        pubmed_context = AgentExecutionContext(
            run_id=run_id,
            task_id=literature_task.task_id,
            idempotency_key=literature_task.idempotency_key,
            skill_id="meta_review",
            skill_version="0.1.0",
            output_schema_version=1,
            input_snapshot_hash="sha256:online-pubmed-query",
        )
        uow.plan_external_call(
            "online-pubmed-call",
            request_fingerprint(pubmed_request),
            run_id=run_id,
            task_id=literature_task.task_id,
            execution_context=pubmed_context.model_dump(mode="json"),
            provider="pubmed",
            model_or_tool="esearch",
        )
        async with httpx.AsyncClient() as client:
            pubmed_result = await runner.execute(
                call_id="online-pubmed-call",
                request=pubmed_request,
                provider=_PubMedSearchCall(
                    PubMedProvider(
                        client,
                        tool=os.getenv("NCBI_TOOL", "co-scientist-core"),
                        email=os.getenv("NCBI_EMAIL"),
                    )
                ),
                validator=lambda raw: {
                    "pubmed_query": pubmed_request["query"],
                    "pmids": json.loads(raw)["esearchresult"]["idlist"],
                    "access_issues": [],
                },
                context=pubmed_context,
            )
        uow.transition_task(literature_task.task_id, TaskState.RESULT_RECEIVED)
        supervisor.handle_result(
            run_id,
            literature_task.task_id,
            pubmed_result,
            expected_sequence=scheduled.last_sequence,
        )
        self.uow = uow
        self.artifacts = artifacts
        return run_id

    def status(self, run_id: str) -> SimpleNamespace:
        events = self.uow.load(run_id)
        hypothesis_count = sum(
            event.event_type == "HypothesisContentCreated" for event in events
        )
        pubmed_source_count = sum(
            len(event.payload.get("pmids", ()))
            for event in events
            if event.event_type == "MetaReviewCompleted"
        )
        with self.uow.session_factory() as session:
            calls = session.scalars(
                select(ExternalCallRow).where(ExternalCallRow.run_id == run_id)
            ).all()
            completed_external_call_count = int(
                session.scalar(
                    select(func.count()).select_from(ExternalCallRow).where(
                        ExternalCallRow.run_id == run_id,
                        ExternalCallRow.state == "domain_result_applied",
                    )
                )
                or 0
            )
            costs = session.scalars(
                select(CostEntryRow).where(CostEntryRow.run_id == run_id)
            ).all()
        raw_manifests = []
        for row in calls:
            manifest = self.artifacts.discover_raw(row.external_call_id)
            assert manifest is not None
            self.artifacts.confirm_raw(manifest)
            context = json.loads(row.execution_context_json or "null")
            assert isinstance(context, dict)
            assert manifest.call_id == row.external_call_id
            assert manifest.run_id == row.run_id
            assert manifest.task_id == row.task_id
            assert manifest.request_fingerprint == row.request_fingerprint
            assert manifest.execution_context_fingerprint == execution_context_fingerprint(
                context
            )
            assert manifest.provider_response_id == row.provider_response_id
            assert manifest.usage == json.loads(row.usage_json)
            assert row.raw_artifact_ref_json is not None
            assert manifest.artifact_ref.model_dump(mode="json") == json.loads(
                row.raw_artifact_ref_json
            )
            raw_manifests.append(manifest)
        return SimpleNamespace(
            hypothesis_count=hypothesis_count,
            pubmed_source_count=pubmed_source_count,
            raw_artifact_count=sum(row.raw_artifact_ref_json is not None for row in calls),
            completed_external_call_count=completed_external_call_count,
            provider_models={(row.provider, row.model_or_tool) for row in calls},
            provider_response_ids={
                row.external_call_id: row.provider_response_id for row in calls
            },
            external_call_ids={row.external_call_id for row in calls},
            raw_manifest_count=len(raw_manifests),
            logical_cost_count=len(costs),
            logical_cost_call_ids={row.external_call_id for row in costs},
            openai_input_tokens=next(
                row.input_tokens
                for row in costs
                if row.external_call_id == "online-openai-call"
            ),
            openai_output_tokens=next(
                row.output_tokens
                for row in costs
                if row.external_call_id == "online-openai-call"
            ),
        )


@pytest.fixture
def online_core_cli() -> OnlineCoreCli:
    if not _online_enabled():
        pytest.skip(
            "requires OPENAI_API_KEY, CO_SCIENTIST_OPENAI_MODEL, and "
            "CO_SCIENTIST_NETWORK_ONLINE=1"
        )
    return OnlineCoreCli()


@pytest.mark.online
@pytest.mark.asyncio
async def test_lens_smoke_with_openai_and_pubmed(
    online_core_cli: OnlineCoreCli,
    tmp_path: Path,
) -> None:
    run_id = await online_core_cli.start_lens(
        provider="openai",
        literature_provider="pubmed",
        data_dir=tmp_path,
    )
    summary = online_core_cli.status(run_id)
    assert summary.hypothesis_count >= 2
    assert summary.pubmed_source_count >= 1
    assert summary.raw_artifact_count == summary.completed_external_call_count
    assert summary.provider_models == {
        ("openai", os.environ["CO_SCIENTIST_OPENAI_MODEL"]),
        ("pubmed", "esearch"),
    }
    assert all(summary.provider_response_ids.values())
    assert summary.raw_manifest_count == summary.completed_external_call_count
    assert summary.logical_cost_count == summary.completed_external_call_count
    assert summary.logical_cost_call_ids == summary.external_call_ids
    assert summary.openai_input_tokens > 0
    assert summary.openai_output_tokens > 0
