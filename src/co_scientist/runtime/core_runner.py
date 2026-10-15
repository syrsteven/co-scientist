"""Production single-process driver for the deterministic Core Preview."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
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
from co_scientist.domain.identifiers import validate_run_id
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.ports.external_provider import ExternalProvider, thaw_json
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.worker import Worker, WorkerStep
from co_scientist.skills.loader import (
    CORE_SKILL_CONTRACTS,
    CORE_SKILL_CONTRACTS_V2,
    CORE_SKILL_CONTRACTS_V3,
    core_skill_directory,
)
from co_scientist.supervisor.orchestrator import Supervisor

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from co_scientist.application.config import ResolvedRunConfig


class RunExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    state: RunState
    last_sequence: int
    stop_reason: str | None = None


class CoreRunner:
    """Compose and drive Supervisor-owned work through the fenced Worker."""

    def __init__(self, *, data_dir: Path, environment: Mapping[str, str],
                 offline_providers: Mapping[str, ExternalProvider] | None = None,
                 single_root_authorization=None) -> None:
        self.data_dir = data_dir.expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = f"sqlite:///{self.data_dir / 'co-scientist.db'}"
        upgrade_database(self.database_url)
        self.uow = SqliteUnitOfWork(self.database_url)
        self.artifacts = FilesystemArtifactStore(self.data_dir / "artifacts")
        self.environment = dict(environment)
        self.offline_providers = dict(offline_providers or {})
        self.single_root_authorization = single_root_authorization
        self.supervisor = Supervisor(
            uow=self.uow,
            review_policy=ReviewPolicy(profile_id="core-preview"),
        )
        self.worker: Worker | None = None
        self.literature_bridges: dict[str, ExternalProvider] = {}
        self._pubmed_client: httpx.AsyncClient | None = None
        self._openai_client: Any | None = None
        self._native_client: httpx.AsyncClient | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._clients_closed = False

    def _bind_owner_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if (self._owner_loop is not None and self._owner_loop is not loop
                and any(client is not None for client in (
                    self._openai_client, self._pubmed_client, self._native_client,
                ))):
            raise RuntimeError("CoreRunner clients are owned by a different event loop")
        self._owner_loop = loop
        return loop

    async def aclose(self) -> None:
        """Close each owned client once in the loop that executed its work.

        Cleanup is best-effort: a close error is logged using only its class
        name and cannot replace a successful/persisted Worker result.
        """
        if self._clients_closed:
            return
        loop = asyncio.get_running_loop()
        if self._owner_loop is not None and self._owner_loop is not loop:
            # Never drive an HTTPX/httpcore pool from a foreign loop. Normal
            # CoreRunner entry points bind and close in one loop; single-step
            # callers should use run_worker_step().
            _LOG.warning("CoreRunner cleanup skipped on non-owning event loop")
            return
        self._clients_closed = True
        openai_client = self._openai_client
        pubmed_client = self._pubmed_client
        native_client = self._native_client
        self._openai_client = None
        self._pubmed_client = None
        self._native_client = None

        closers: list[tuple[object, Any]] = []
        if openai_client is not None:
            closers.append((openai_client, openai_client.close))
        if pubmed_client is not None:
            closers.append((pubmed_client, pubmed_client.aclose))
        if native_client is not None:
            closers.append((native_client, native_client.aclose))
        seen: set[int] = set()
        for client, close in closers:
            if id(client) in seen:
                continue
            seen.add(id(client))
            try:
                await close()
            except Exception as error:  # noqa: BLE001 - cleanup must not mask applied work
                _LOG.warning("CoreRunner client cleanup failed (%s)", type(error).__name__)

    async def run_worker_step(self, *, run_id: str) -> WorkerStep:
        """Run at most one persisted task and close clients on the same loop.

        This is the lifecycle-safe API for bounded probes and other callers
        that must not use ``drive()`` to continue into follow-up work.
        """
        self._bind_owner_loop()
        try:
            if self.worker is None:
                manifest = self.uow.run_manifest(run_id)
                diagnostic = execution_contract_diagnostic(run_id, manifest)
                if diagnostic is not None:
                    raise ValueError(diagnostic)
                self._compose(manifest, run_id=run_id)
            assert self.worker is not None
            return await self.worker.run_once(run_id)
        finally:
            await self.aclose()

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

    def _compose(self, manifest: Mapping[str, Any], *, run_id: str | None = None) -> None:
        # A new composition owns a fresh set of clients even when this runner
        # instance was previously closed and reused by a caller.
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        existing_clients = any(client is not None for client in (
            self._openai_client, self._pubmed_client, self._native_client,
        ))
        if existing_clients and current_loop is not None and self._owner_loop not in {
            None, current_loop,
        }:
            raise RuntimeError("CoreRunner cannot recompose clients across event loops")
        if not existing_clients:
            self._owner_loop = current_loop
        self._clients_closed = False
        profile = manifest.get("profile")
        from co_scientist.domain.execution_config import frozen_execution

        effective = frozen_execution(manifest)
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
        from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled
        from co_scientist.domain.single_root import FullIdeationConfig, SingleRootConfig

        if isinstance(effective, (SingleRootConfig, FullIdeationConfig)):
            from co_scientist.runtime.single_root import compose

            compose(self, manifest, effective, run_id)
            return
        if batch2_execution_enabled(manifest):
            capability = manifest["ideation_prerequisite_contract"]["policy"]["capability"]
            if effective is not None:
                capability = effective.task("DirectiveEthicsResultV1")["capability"]
                provider_id = capability["provider"]
            if (capability["status"] != "OFFLINE_FAKE_ONLY" or capability["provider"] != "fake"
                    or provider_id != "fake" or "fake" not in self.offline_providers
                    or literature_id + ":root" not in self.offline_providers):
                raise ValueError("CAPABILITY_UNVERIFIED: Batch 2 requires isolated fake providers")
            offline = dict(self.offline_providers)
            if effective is not None and effective.version == "generation-performance-v1":
                from co_scientist.adapters.llm.performance_responses import (
                    PerformanceResponsesProvider,
                    PerformanceRoleRouter,
                )

                if "generation-performance-v1" not in offline:
                    raise ValueError("performance integration requires explicit bounded offline Generation adapter")
                responses = offline["generation-performance-v1"]
                if not isinstance(responses, PerformanceResponsesProvider):
                    raise TypeError("performance provider must be bounded MockTransport adapter")
                offline["fake"] = PerformanceRoleRouter(responses, offline["fake"])
            self._build_worker(ProviderRegistry(offline))
            if effective is not None:
                from datetime import timedelta

                assert self.worker is not None
                self.worker.lease_duration = timedelta(seconds=effective.envelope.lease_seconds)
                self.worker.heartbeat_interval = timedelta(seconds=effective.envelope.heartbeat_seconds)
            return
        dispatch = profile.get("dispatch_limits")

        def transport() -> httpx.AsyncBaseTransport | None:
            if dispatch is None:
                return None
            if run_id is None:
                raise ValueError("bounded dispatch requires durable run identity")
            from co_scientist.domain.dispatch_limits import DispatchLimits
            from co_scientist.runtime.bounded_transport import BoundedTransport

            scientific = BoundedTransport(
                self.data_dir / "dispatch" / run_id,
                DispatchLimits.model_validate(dispatch),
            )
            from co_scientist.domain.probe_execution import probe_envelope_for_manifest

            probe = probe_envelope_for_manifest(manifest)
            if probe is None:
                return scientific
            if probe.pricing != scientific.limits.pricing:
                raise ValueError("probe and scientific dispatch pricing differ")
            return BoundedTransport(
                self.data_dir / "dispatch-probe" / run_id,
                probe.dispatch_limits(), inner=scientific,
            )
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
            self._pubmed_client = httpx.AsyncClient(transport=transport())
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

            self._openai_client = AsyncOpenAI(api_key=api_key, max_retries=0)
            provider = OpenAIResponsesProvider(self._openai_client)
        elif provider_id in {"deepseek", "qwen", "gemini", "claude"}:
            from co_scientist.adapters.llm.multi_provider import KEY_NAMES, NativeJSONProvider

            key_name = KEY_NAMES[provider_id]
            api_key = self.environment.get(key_name)
            if not api_key:
                raise ValueError(f"{key_name} is required to resume this Run")
            generation = None
            if provider_id == "deepseek" and configured.get("generation") is not None:
                from co_scientist.application.config import DeepSeekGenerationProfile

                generation = DeepSeekGenerationProfile.model_validate(
                    configured["generation"]
                ).model_dump()
            timeout = generation["timeout_seconds"] if generation else 180.0
            self._native_client = httpx.AsyncClient(timeout=timeout, transport=transport())
            provider = NativeJSONProvider(
                self._native_client, provider=provider_id, api_key=api_key,
                generation=generation,
            )
        else:
            raise ValueError(f"unsupported persisted provider: {provider_id}")
        self._build_worker(ProviderRegistry({provider_id: provider, **self.literature_bridges}))

    def _build_worker(self, providers: ProviderRegistry) -> None:
        skills = SkillRegistry(
            {
                (contract.id, contract.version): core_skill_directory(contract.id)
                for contract in (
                    *CORE_SKILL_CONTRACTS.values(),
                    *CORE_SKILL_CONTRACTS_V2.values(),
                    *CORE_SKILL_CONTRACTS_V3.values(),
                )
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
                if event.event_type in {"RunStopping", "RunCancelled", "RunFailed", "RunNeedsAttention"}
                and event.payload.get("reason") is not None
            ),
            None,
        )
        from co_scientist.domain.single_root import single_root

        if single_root(self.uow.run_manifest(run_id)) and reason is None:
            reason = next((str(e.payload["reason"]) for e in reversed(events)
                if e.event_type in {"IdeationSlotResolvedV1", "IdeationSlotResolvedV2"}), None)
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
            self._compose(manifest, run_id=resolved_run_id)
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
        self._compose(manifest, run_id=run_id)
        return await self.drive(run_id=run_id)

    async def drive(self, *, run_id: str) -> RunExecutionResult:
        from datetime import UTC, datetime

        from co_scientist.domain.continuous_execution import policy_for
        from co_scientist.domain.execution_config import frozen_execution

        manifest = self.uow.run_manifest(run_id)
        if policy_for(manifest) is None:
            return await self._drive(run_id=run_id)
        events = self.uow.load(run_id)
        started = min(e.occurred_at for e in events)
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        config = frozen_execution(manifest)
        assert config is not None
        remaining = config.envelope.max_wall_seconds-(datetime.now(UTC)-started).total_seconds()
        if remaining <= 0:
            return await self._finish_continuous_partial(run_id, "RUN_WATCHDOG")
        try:
            async with asyncio.timeout(max(0, remaining)):
                return await self._drive(run_id=run_id)
        except TimeoutError:
            return await self._finish_continuous_partial(run_id, "RUN_WATCHDOG")
        except Exception as error:  # noqa: BLE001 - Run boundary records PARTIAL, never scientific success.
            return await self._finish_continuous_partial(run_id,
                "CONTINUOUS_RUN_FAILURE_"+type(error).__name__)

    async def _finish_continuous_partial(self, run_id: str, reason: str) -> RunExecutionResult:
        if self.uow.run_state(run_id) in {"completed", "completed_partial", "failed", "cancelled"}:
            return self._result(run_id)
        events = self.uow.load(run_id)
        if any(e.event_type == "IdeationFinalSelectionV1" for e in events):
            self.supervisor._resume_baseline_finalization(run_id=run_id, expected_sequence=events[-1].sequence)
        else:
            generation = max((e.payload["generation"] for e in events if e.event_type in {
                "BaselineGenerationCompletedV1", "BaselineReproductionPlannedV1"}), default=0)
            self.supervisor._baseline_search_stop(run_id=run_id, expected_sequence=events[-1].sequence,
                reason=reason, generation=generation, complete=False)
        if self.worker is None:
            self._compose(self.uow.run_manifest(run_id), run_id=run_id)
        assert self.worker is not None
        for _ in range(4):
            if self.uow.run_state(run_id) != "stopping":
                break
            await self.worker.run_once(run_id)  # Only finalize_run can be claimed.
        return self._result(run_id)

    async def _drive(self, *, run_id: str) -> RunExecutionResult:
        self._bind_owner_loop()
        if self.worker is None:
            manifest = self.uow.run_manifest(run_id)
            diagnostic = execution_contract_diagnostic(run_id, manifest)
            if diagnostic is not None:
                raise ValueError(diagnostic)
            self._compose(manifest, run_id=run_id)
        assert self.worker is not None
        for _ in range(10_000):
            if self.supervisor.pause_on_invalid_output(run_id=run_id) is not None:
                return self._result(run_id)
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
            try:
                step = await self.worker.run_once(run_id)
            except Exception as error:
                from co_scientist.domain.continuous_execution import policy_for

                if policy_for(self.uow.run_manifest(run_id)) is not None:
                    return await self._finish_continuous_partial(run_id,
                        "CONTINUOUS_UNRECOVERABLE_"+type(error).__name__)
                if self.supervisor.pause_on_invalid_output(run_id=run_id) is not None:
                    return self._result(run_id)
                raise
            if step.status in {"completed", "requeued"}:
                continue
            if step.status in {"paused", "terminal", "exhausted"}:
                return self._result(run_id)
            events = self.uow.load(run_id)
            sequence = events[-1].sequence if events else 0
            if step.status == "budget_exhausted" and self.supervisor.pause_population_on_budget_shortfall(
                run_id=run_id, expected_sequence=sequence,
            ) is not None:
                from co_scientist.domain.ideation_core_boundary import batch34_execution_enabled

                if batch34_execution_enabled(self.uow.run_manifest(run_id)):
                    # The native partial result is durable; only zero-provider
                    # finalization may now run. Historical population pauses
                    # retain their original behavior.
                    continue
                return self._result(run_id)
            advanced = self.supervisor.advance(
                run_id=run_id,
                expected_sequence=sequence,
            )
            if advanced.action in {"scheduled", "admitted", "progressed", "checkpointed"}:
                continue
            return self._result(run_id)
        raise RuntimeError("CoreRunner exceeded its internal progress safety bound")
