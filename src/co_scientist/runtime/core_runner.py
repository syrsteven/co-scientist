"""Production single-process driver for the deterministic Core Preview."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.artifacts.filesystem import FilesystemArtifactStore
from co_scientist.adapters.literature.pubmed import PubMedBridge, PubMedProvider
from co_scientist.adapters.literature.replay import (
    ReplayLiteratureProvider,
    ReplayPubMedBridge,
)
from co_scientist.adapters.llm.openai_responses import OpenAIResponsesProvider
from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.adapters.persistence.migrations import (
    execution_contract_diagnostic,
    upgrade_database,
)
from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.config import ResolvedRunConfig
from co_scientist.domain.identifiers import validate_run_id
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.ports.external_provider import ExternalProvider, thaw_json
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.worker import Worker
from co_scientist.skills.loader import CORE_SKILL_CONTRACTS, core_skill_directory
from co_scientist.supervisor.orchestrator import Supervisor


class RunExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    state: RunState
    last_sequence: int
    stop_reason: str | None = None


class CoreRunner:
    """Compose and drive Supervisor-owned work through the fenced Worker."""

    def __init__(self, *, data_dir: Path, environment: Mapping[str, str]) -> None:
        self.data_dir = data_dir.expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = f"sqlite:///{self.data_dir / 'co-scientist.db'}"
        upgrade_database(self.database_url)
        self.uow = SqliteUnitOfWork(self.database_url)
        self.artifacts = FilesystemArtifactStore(self.data_dir / "artifacts")
        self.environment = dict(environment)
        self.supervisor = Supervisor(
            uow=self.uow,
            review_policy=ReviewPolicy(profile_id="core-preview"),
        )
        self.worker: Worker | None = None
        self.literature_bridges: dict[str, ExternalProvider] = {}
        self._pubmed_client: httpx.AsyncClient | None = None
        self._openai_client: Any | None = None

    async def aclose(self) -> None:
        """Close any network clients composed for one foreground invocation."""

        openai_client = self._openai_client
        pubmed_client = self._pubmed_client
        self._openai_client = None
        self._pubmed_client = None
        try:
            if openai_client is not None:
                await openai_client.close()
        finally:
            if pubmed_client is not None:
                await pubmed_client.aclose()

    @staticmethod
    def _resource(manifest: Mapping[str, Any], kind: str) -> Path:
        resources = manifest.get("replay_resources")
        if not isinstance(resources, list):
            raise TypeError("run manifest has no replay resources")
        matches = [item for item in resources if item.get("kind") == kind]
        if len(matches) != 1:
            raise ValueError(f"run manifest has no unique {kind} replay resource")
        item = matches[0]
        path = Path(str(item["path"]))
        body = path.read_bytes()
        actual = "sha256:" + hashlib.sha256(body).hexdigest()
        if actual != item.get("sha256"):
            raise ValueError(f"replay resource integrity mismatch: {kind}")
        return path

    def _compose(self, manifest: Mapping[str, Any]) -> None:
        profile = manifest.get("profile")
        if not isinstance(profile, Mapping):
            raise TypeError("run manifest has no frozen profile")
        review = profile.get("review_policy")
        if not isinstance(review, Mapping):
            raise TypeError("run manifest has no frozen review policy")
        self.supervisor = Supervisor(
            uow=self.uow,
            review_policy=ReviewPolicy.model_validate(review),
        )
        providers = manifest.get("providers")
        configured = manifest.get("provider_configuration")
        if not isinstance(providers, Mapping) or not isinstance(configured, Mapping):
            raise TypeError("run manifest provider configuration is malformed")
        provider_id = str(providers.get("llm"))
        literature_id = str(providers.get("literature"))
        if literature_id == "replay_pubmed":
            replay_literature = ReplayLiteratureProvider(
                self._resource(manifest, "pubmed_search"),
                self._resource(manifest, "pubmed_summary"),
            )
            self.literature_bridges = {
                "replay_pubmed:search": ReplayPubMedBridge(replay_literature, "search"),
                "replay_pubmed:summary": ReplayPubMedBridge(replay_literature, "summary"),
            }
        elif literature_id == "pubmed":
            self._pubmed_client = httpx.AsyncClient()
            pubmed_literature = PubMedProvider(
                self._pubmed_client,
                tool="co-scientist-core",
                email=self.environment.get("CO_SCIENTIST_PUBMED_EMAIL"),
            )
            self.literature_bridges = {
                "pubmed:search": PubMedBridge(pubmed_literature, "search"),
                "pubmed:summary": PubMedBridge(pubmed_literature, "summary"),
            }
        else:
            raise ValueError(f"unsupported persisted literature provider: {literature_id}")
        provider: ExternalProvider
        if provider_id == "replay":
            provider = ReplayLLMProvider.from_file(self._resource(manifest, "llm_responses"))
        elif provider_id == "openai":
            api_key = self.environment.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required to resume this Run")
            from openai import AsyncOpenAI

            self._openai_client = AsyncOpenAI(api_key=api_key)
            provider = OpenAIResponsesProvider(self._openai_client)
        else:
            raise ValueError(f"unsupported persisted provider: {provider_id}")
        self._build_worker(ProviderRegistry({provider_id: provider, **self.literature_bridges}))

    def _build_worker(self, providers: ProviderRegistry) -> None:
        skills = SkillRegistry(
            {
                (contract.id, contract.version): core_skill_directory(contract.id)
                for contract in CORE_SKILL_CONTRACTS.values()
            }
        )
        runtime = SimpleNamespace(uow=self.uow, artifacts=self.artifacts)
        self.worker = Worker(
            runtime=runtime,
            task_runtime=self.uow,
            supervisor=self.supervisor,
            skills=skills,
            providers=providers,
            worker_id="core-preview-worker",
        )

    def _result(self, run_id: str) -> RunExecutionResult:
        events = self.uow.load(run_id)
        reason = next(
            (
                str(event.payload["reason"])
                for event in reversed(events)
                if event.event_type in {"RunStopping", "RunCancelled", "RunFailed"}
                and event.payload.get("reason") is not None
            ),
            None,
        )
        return RunExecutionResult(
            run_id=run_id,
            state=RunState(self.uow.run_state(run_id)),
            last_sequence=events[-1].sequence if events else 0,
            stop_reason=reason,
        )

    async def execute(
        self,
        *,
        config: ResolvedRunConfig,
        run_id: str | None = None,
    ) -> RunExecutionResult:
        try:
            resolved_run_id = validate_run_id(run_id or f"run-{uuid4().hex}")
            manifest = thaw_json(config.manifest)
            if not isinstance(manifest, dict):
                raise TypeError("resolved run manifest is not an object")
            manifest["manifest_hash"] = config.manifest_hash
            self._compose(manifest)
            self.supervisor.bootstrap_run(run_id=resolved_run_id, manifest=manifest)
            return await self.drive(run_id=resolved_run_id)
        finally:
            await self.aclose()

    async def resume(self, *, run_id: str) -> RunExecutionResult:
        try:
            return await self._resume(run_id=validate_run_id(run_id))
        finally:
            await self.aclose()

    async def _resume(self, *, run_id: str) -> RunExecutionResult:
        state = RunState(self.uow.run_state(run_id))
        if state in {
            RunState.COMPLETED,
            RunState.COMPLETED_PARTIAL,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.PAUSED,
            RunState.PAUSING,
            RunState.NEEDS_ATTENTION,
        }:
            return self._result(run_id)
        if state is RunState.STOPPING:
            self._build_worker(ProviderRegistry({}))
            return await self.drive(run_id=run_id)
        manifest = self.uow.run_manifest(run_id)
        diagnostic = execution_contract_diagnostic(run_id, manifest)
        if diagnostic is not None:
            raise ValueError(diagnostic)
        self._compose(manifest)
        return await self.drive(run_id=run_id)

    async def drive(self, *, run_id: str) -> RunExecutionResult:
        if self.worker is None:
            manifest = self.uow.run_manifest(run_id)
            diagnostic = execution_contract_diagnostic(run_id, manifest)
            if diagnostic is not None:
                raise ValueError(diagnostic)
            self._compose(manifest)
        assert self.worker is not None
        for _ in range(10_000):
            state = RunState(self.uow.run_state(run_id))
            if state in {
                RunState.COMPLETED,
                RunState.COMPLETED_PARTIAL,
                RunState.FAILED,
                RunState.CANCELLED,
            }:
                return self._result(run_id)
            if state in {RunState.PAUSED, RunState.PAUSING, RunState.NEEDS_ATTENTION}:
                return self._result(run_id)
            step = await self.worker.run_once(run_id)
            if step.status in {"completed", "requeued"}:
                continue
            if step.status in {"paused", "terminal", "exhausted"}:
                return self._result(run_id)
            events = self.uow.load(run_id)
            sequence = events[-1].sequence if events else 0
            advanced = self.supervisor.advance(
                run_id=run_id,
                expected_sequence=sequence,
            )
            if advanced.action in {"scheduled", "admitted", "checkpointed"}:
                continue
            return self._result(run_id)
        raise RuntimeError("CoreRunner exceeded its internal progress safety bound")
