"""Foreground, single-process execution of Supervisor-created tasks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import anyio
from pydantic import BaseModel, ConfigDict, Field, model_validator

from co_scientist.agents.executor import SkillExecutor
from co_scientist.agents.payloads import CoreOutputSchemaId
from co_scientist.agents.result import AgentExecutionContext, AgentResult
from co_scientist.domain.budget import BudgetEstimate
from co_scientist.domain.states import TaskState
from co_scientist.domain.task import (
    ClaimedTask,
    LeaseRecovery,
    TaskLeaseFence,
    lease_fence_fingerprint,
)
from co_scientist.runtime.external_calls import ExternalCallRunner, request_fingerprint
from co_scientist.runtime.registry import ProviderRegistry, SkillRegistry
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


class WorkerTaskPayload(BaseModel):
    """Immutable execution identity frozen into a Supervisor-created task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    skill_version: str
    output_schema_id: CoreOutputSchemaId
    output_schema_version: int = Field(ge=1)
    research_plan_version: int = Field(ge=1)
    provider_id: str
    model_or_tool: str
    inputs: dict[str, Any]
    input_snapshot_hash: str
    prompt_hash: str
    budget_estimate: BudgetEstimate

    @model_validator(mode="after")
    def validate_input_snapshot(self) -> WorkerTaskPayload:
        if request_fingerprint(self.inputs) != self.input_snapshot_hash:
            raise ValueError("task input snapshot hash does not match inputs")
        return self


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
        task_runtime: Any,
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
        return self.task_runtime.recover_expired_leases(
            run_id=run_id, now=self.clock()
        )

    def _context(
        self, task: ClaimedTask, payload: WorkerTaskPayload
    ) -> AgentExecutionContext:
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
        recoveries = await self.recover(run_id)
        outcome = self.task_runtime.claim_next_task(
            run_id=run_id,
            worker_id=self.worker_id,
            lease_token=self.token_factory(),
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
        task = self.task_runtime.mark_task_running(fence=task)
        payload = WorkerTaskPayload.model_validate(dict(task.payload))
        skill_directory = self.skills.resolve(payload.skill_id, payload.skill_version)
        provider = self.providers.resolve(payload.provider_id)
        context = self._context(task, payload)
        existing_call = self.runtime.uow.external_call_for_task_attempt(
            run_id=task.run_id,
            task_id=task.task_id,
            attempt=task.attempt,
        )
        call_id = (
            existing_call.external_call_id
            if existing_call is not None
            else self.call_id_factory(task)
        )
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

        result = await self._execute_with_heartbeat(task=task, execute=execute)
        self.task_runtime.acknowledge_task(
            fence=task, target_state=TaskState.RESULT_RECEIVED
        )
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
        return WorkerStep(
            status="completed",
            run_id=run_id,
            task_id=task.task_id,
            attempt=task.attempt,
        )
