"""Foreground, single-process execution of Supervisor-created tasks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import anyio
from pydantic import BaseModel, ConfigDict

from co_scientist.agents.executor import (
    LiteratureToolExecutor,
    RootRetrievalExecutor,
    SkillExecutor,
)
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import (
    ClaimedTask,
    LeaseRecovery,
    TaskLeaseFence,
    lease_fence_fingerprint,
)
from co_scientist.ports.task_runtime import TaskRuntimePort
from co_scientist.runtime.external_calls import (
    ExternalCallRunner,
    assert_baseline_no_unknown_delivery,
)
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
from co_scientist.runtime.task_payload import WorkerTaskPayload
from co_scientist.runtime.transport_observability import failure_diagnostic_for_exception
from co_scientist.supervisor.orchestrator import Supervisor


class WorkerStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal[
        "idle",
        "completed",
        "requeued",
        "exhausted",
        "paused",
        "stopping",
        "terminal",
        "budget_exhausted",
    ]
    run_id: str
    task_id: str | None = None
    attempt: int | None = None


class _HeartbeatGuard:
    def __init__(self) -> None:
        self.failure: BaseException | None = None

    def fail(self, error: BaseException) -> None:
        self.failure = error

    def assert_active(self) -> None:
        if self.failure is not None:
            raise RuntimeError("task heartbeat failed; continuation is fenced") from self.failure


class Worker:
    """Claim and execute at most one existing task in the foreground."""

    def __init__(
        self,
        *,
        runtime: Any,
        task_runtime: TaskRuntimePort,
        supervisor: Supervisor,
        skills: SkillRegistry,
        providers: ProviderRegistry,
        worker_id: str,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        call_id_factory: Callable[[ClaimedTask], str] | None = None,
        lease_duration: timedelta = timedelta(minutes=5),
        heartbeat_interval: timedelta = timedelta(minutes=1),
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if heartbeat_interval <= timedelta(0):
            raise ValueError("heartbeat_interval must be positive")
        if heartbeat_interval >= lease_duration:
            raise ValueError("heartbeat_interval must be shorter than lease_duration")
        self.runtime = runtime
        self.task_runtime = task_runtime
        self.supervisor = supervisor
        self.skills = skills
        self.providers = providers
        self.worker_id = worker_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.token_factory = token_factory or (lambda: str(uuid4()))
        self.call_id_factory = call_id_factory or (
            lambda task: f"call:{task.task_id}:{task.attempt}:{uuid4()}"
        )
        self.lease_duration = lease_duration
        self.heartbeat_interval = heartbeat_interval

    async def recover(self, run_id: str) -> tuple[LeaseRecovery, ...]:
        self._authorize_before_recovery(run_id)
        return self.task_runtime.recover_expired_leases(run_id=run_id, now=self.clock())

    def _authorize_before_recovery(self, run_id: str) -> None:
        from co_scientist.domain.execution_config import frozen_execution
        from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled

        manifest = self.runtime.uow.run_manifest(run_id)
        effective = frozen_execution(manifest)
        from co_scientist.domain.single_root import FullIdeationConfig, SingleRootConfig

        if isinstance(effective, (SingleRootConfig, FullIdeationConfig)):
            from co_scientist.runtime.single_root import validate_worker_providers

            validate_worker_providers(self, run_id, effective)
        if effective is not None and (
                self.lease_duration.total_seconds() != effective.envelope.lease_seconds
                or self.heartbeat_interval.total_seconds() != effective.envelope.heartbeat_seconds):
            raise ValueError("Worker lease/heartbeat differs from frozen runtime")
        if not batch2_execution_enabled(manifest):
            if manifest.get("ideation_prerequisite_contract", {}).get("version") == "ideation-prerequisites-v1":
                for task_id in self.runtime.uow.unresolved_task_ids(run_id):
                    self.supervisor.authorize_batch2_task(
                        self.runtime.uow.task_definition(task_id), operation="execute")
            return
        for task_id in self.runtime.uow.unresolved_task_ids(run_id):
            if (manifest.get("effective_execution_config", {}).get("continuous_policy")
                    and self.runtime.uow.run_state(run_id) == "stopping"
                    and self.runtime.uow.task_definition(task_id).intent_type != "finalize_run"):
                continue  # Partial finalization has no scientific dispatch authority.
            try:
                assert_baseline_no_unknown_delivery(self.runtime, run_id=run_id, task_id=task_id)
            except ValueError as error:
                if any(reason in str(error) for reason in (
                        "DELIVERY_UNKNOWN", "PREVIOUS_ATTEMPT_REPLAY_REQUIRED",
                        "INVALID_RESULT_REQUIRES_CONTAINMENT")):
                    self.supervisor.mark_batch2_unknown_delivery(run_id=run_id, task_id=task_id,
                                                                 reason=str(error).split(":", 1)[0])
                raise
            self.supervisor.authorize_batch2_task(
                self.runtime.uow.task_definition(task_id), operation="execute")

    def _context(self, task: ClaimedTask, payload: WorkerTaskPayload) -> AgentExecutionContext:
        fence = TaskLeaseFence.model_validate(task.model_dump())
        return AgentExecutionContext(
            run_id=task.run_id,
            task_id=task.task_id,
            idempotency_key=task.idempotency_key,
            skill_id=payload.skill_id,
            skill_version=payload.skill_version,
            output_schema_id=payload.output_schema_id,
            output_schema_version=payload.output_schema_version,
            research_plan_version=payload.research_plan_version,
            provider=payload.provider_id,
            model_or_tool=payload.model_or_tool,
            input_snapshot_hash=payload.input_snapshot_hash,
            prompt_hash=payload.prompt_hash,
            attempt=task.attempt,
            reservation_id=task.reservation_id,
            lease_fence_fingerprint=lease_fence_fingerprint(fence),
        )

    async def _execute_with_heartbeat(
        self,
        *,
        task: ClaimedTask,
        execute: Callable[[_HeartbeatGuard], Any],
    ) -> AgentResult:
        guard = _HeartbeatGuard()
        result: AgentResult | None = None

        async def invoke() -> None:
            nonlocal result
            from co_scientist.domain.execution_config import validate_task_execution

            payload = WorkerTaskPayload.model_validate(task.payload)
            parameters = payload.inputs.get("continuous_attempt")
            if parameters is not None:
                not_before = datetime.fromisoformat(parameters["not_before"])
                delay = max(0, (not_before-self.clock()).total_seconds())
                if delay:
                    await anyio.sleep(delay)  # Heartbeat runs throughout server backoff.
            validate_task_execution(self.runtime.uow.run_manifest(task.run_id), payload.output_schema_id,
                                    payload.inputs, payload.budget_estimate)
            execution = payload.inputs.get("effective_execution")
            if execution is None:
                result = await execute(guard)
            else:
                with anyio.fail_after(execution["runtime"]["deadline_seconds"]):
                    result = await execute(guard)
            task_group.cancel_scope.cancel()

        async def heartbeat() -> None:
            while True:
                await anyio.sleep(self.heartbeat_interval.total_seconds())
                try:
                    self.task_runtime.heartbeat_task(
                        fence=task,
                        now=self.clock(),
                        lease_duration=self.lease_duration,
                    )
                except BaseException as error:
                    guard.fail(error)
                    task_group.cancel_scope.cancel()
                    raise

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(invoke)
            task_group.start_soon(heartbeat)
        guard.assert_active()
        if result is None:
            raise RuntimeError("provider execution ended without a result")
        return result

    @staticmethod
    def _claim_status(status: str, run_id: str) -> WorkerStep:
        mapping = {
            "no_task": "idle",
            "paused": "paused",
            "stopping_no_finalization": "stopping",
            "terminal": "terminal",
            "budget_exhausted": "budget_exhausted",
        }
        return WorkerStep(status=mapping[status], run_id=run_id)  # type: ignore[arg-type]

    async def run_once(self, run_id: str) -> WorkerStep:
        from co_scientist.runtime.continuous_recovery import recover_expired_continuous

        wait = recover_expired_continuous(self, run_id)
        if wait:
            await anyio.sleep(wait)
            return WorkerStep(status="requeued", run_id=run_id)
        self._authorize_before_recovery(run_id)
        lease_token = self.token_factory()
        outcome = self.task_runtime.adopt_recoverable_task(
            run_id=run_id,
            worker_id=self.worker_id,
            lease_token=lease_token,
            now=self.clock(),
            lease_duration=self.lease_duration,
        )
        recoveries: tuple[LeaseRecovery, ...] = ()
        if outcome.status == "no_task":
            recoveries = await self.recover(run_id)
            outcome = self.task_runtime.claim_next_task(
                run_id=run_id,
                worker_id=self.worker_id,
                lease_token=lease_token,
                now=self.clock(),
                lease_duration=self.lease_duration,
            )
        if outcome.status != "claimed":
            if recoveries:
                recovery = recoveries[-1]
                return WorkerStep(
                    status=recovery.action,
                    run_id=run_id,
                    task_id=recovery.task_id,
                    attempt=recovery.expired_attempt,
                )
            return self._claim_status(outcome.status, run_id)
        task = outcome.task
        if task is None:
            raise RuntimeError("claimed outcome has no task")
        self.supervisor.authorize_batch2_task(
            self.runtime.uow.task_definition(task.task_id), operation="execute")
        if self.task_runtime.task_state(task.task_id) == "leased":
            task = self.task_runtime.mark_task_running(fence=task)
        if task.intent_type == "finalize_run":
            if self.task_runtime.task_state(task.task_id) == "running":
                self.task_runtime.acknowledge_task(
                    fence=task,
                    target_state=TaskState.RESULT_RECEIVED,
                )
            events = self.runtime.uow.load(run_id)
            expected_sequence = events[-1].sequence if events else 0
            self.supervisor.complete_finalization(
                run_id=run_id,
                expected_sequence=expected_sequence,
                lease_fence=task,
            )
            return WorkerStep(
                status="completed",
                run_id=run_id,
                task_id=task.task_id,
                attempt=task.attempt,
            )
        payload = WorkerTaskPayload.model_validate(dict(task.payload))
        provider = self.providers.resolve(payload.provider_id)
        existing_call = self.runtime.uow.external_call_for_task_attempt(
            run_id=task.run_id,
            task_id=task.task_id,
            attempt=task.attempt,
        )
        context = (
            AgentExecutionContext.model_validate(existing_call.execution_context)
            if existing_call is not None and existing_call.execution_context is not None
            else self._context(task, payload)
        )
        call_id = (
            existing_call.external_call_id
            if existing_call is not None
            else self.call_id_factory(task)
        )
        if payload.output_schema_id == "RootRetrievalResultV2":
            root_retrieval = RootRetrievalExecutor(ExternalCallRunner(self.runtime), provider)

            async def execute(guard: _HeartbeatGuard) -> AgentResult:
                return await root_retrieval.execute(call_id=call_id, inputs=dict(payload.inputs),
                    context=context, reservation_id=task.reservation_id, fence=task,
                    write_guard=guard.assert_active)

        elif task.intent_type in {"run_literature_search", "run_literature_summary"}:
            literature = LiteratureToolExecutor(ExternalCallRunner(self.runtime), provider)
            operation: Literal["search", "summary"] = (
                "search" if task.intent_type == "run_literature_search" else "summary"
            )

            async def execute(guard: _HeartbeatGuard) -> AgentResult:
                return await literature.execute(
                    call_id=call_id,
                    operation=operation,
                    inputs=dict(payload.inputs),
                    context=context,
                    reservation_id=task.reservation_id,
                    fence=task,
                    write_guard=guard.assert_active,
                )

        else:
            from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled
            from co_scientist.skills.loader import core_skill_directory

            if batch2_execution_enabled(self.runtime.uow.run_manifest(run_id)):
                # A two-phase skill has no ambiguous default manifest. Its exact
                # phase/schema is validated by Supervisor and the executor.
                skill_directory = core_skill_directory(payload.skill_id)
            else:
                skill_directory = self.skills.resolve(payload.skill_id, payload.skill_version)
            executor = SkillExecutor(ExternalCallRunner(self.runtime), provider)

            async def execute(guard: _HeartbeatGuard) -> AgentResult:
                return await executor.execute(
                    call_id=call_id,
                    skill_directory=skill_directory,
                    inputs=dict(payload.inputs),
                    context=context,
                    reservation_id=task.reservation_id,
                    fence=task,
                    write_guard=guard.assert_active,
                )

        try:
            result = await self._execute_with_heartbeat(task=task, execute=execute)
            from co_scientist.runtime.continuous_recovery import prepare_retrieval_retry

            if prepare_retrieval_retry(self, task, result):
                return WorkerStep(status="requeued", run_id=run_id,
                    task_id=task.task_id, attempt=task.attempt)
            events = self.runtime.uow.load(run_id)
            expected_sequence = events[-1].sequence if events else 0
            self.supervisor.handle_result(
                run_id,
                task.task_id,
                result,
                expected_sequence,
                reservation_id=task.reservation_id,
                fence=task,
            )
        except Exception as error:
            try:
                diagnostic = failure_diagnostic_for_exception(error)
                self.runtime.uow.record_external_call_failure_diagnostic(
                    call_id,
                    diagnostic.model_dump(mode="json"),
                    reservation_id=task.reservation_id,
                    fence=task,
                )
            except Exception:  # noqa: BLE001,S110 - diagnostics must not mask original failure
                # The original execution failure and current terminal state stay
                # authoritative if the additive diagnostic store is unavailable.
                pass
            manifest = self.runtime.uow.run_manifest(run_id)
            from co_scientist.domain.ideation_core_boundary import batch2_execution_enabled
            from co_scientist.runtime.continuous_recovery import (
                prepare_retry,
                recover_original_response,
            )

            if recover_original_response(self, task, call_id, error):
                return WorkerStep(status="requeued", run_id=run_id,
                    task_id=task.task_id, attempt=task.attempt)

            if prepare_retry(self, task, call_id, error):
                return WorkerStep(status="requeued", run_id=run_id,
                    task_id=task.task_id, attempt=task.attempt)

            from co_scientist.runtime.continuous_recovery import terminal_provider_failure

            fatal = terminal_provider_failure(self, task, call_id)

            if batch2_execution_enabled(manifest) and self.supervisor.contain_batch2_validation_failure(run_id=run_id,
                task_id=task.task_id, call_id=call_id, reservation_id=task.reservation_id, fence=task):
                if fatal and self.runtime.uow.run_state(run_id) == "running":
                    events = self.runtime.uow.load(run_id)
                    generation = max((e.payload["generation"] for e in events if e.event_type in {
                        "BaselineReproductionPlannedV1", "BaselineGenerationCompletedV1"}), default=0)
                    self.supervisor._baseline_search_stop(run_id=run_id, expected_sequence=events[-1].sequence,
                        reason=fatal, generation=generation, complete=False)
                return WorkerStep(status="completed", run_id=run_id, task_id=task.task_id, attempt=task.attempt)
            if manifest.get("probe_execution_envelope") is not None:
                self.supervisor.fail_compatibility_probe(
                    run_id=run_id, task_id=task.task_id,
                    reason=f"execution_{type(error).__name__}",
                )
            raise
        return WorkerStep(
            status="completed",
            run_id=run_id,
            task_id=task.task_id,
            attempt=task.attempt,
        )
