"""Lease-fenced task runtime persistence contract."""

from collections.abc import Set as AbstractSet
from datetime import datetime, timedelta
from typing import Protocol

from co_scientist.domain.states import TaskState
from co_scientist.domain.task import (
    ClaimedTask,
    ClaimOutcome,
    LeaseRecovery,
    TaskLeaseFence,
)


class TaskRuntimePort(Protocol):
    def adopt_recoverable_task(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimOutcome: ...

    def claim_next_task(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_duration: timedelta,
        allowed_intents: AbstractSet[str] | None = None,
    ) -> ClaimOutcome: ...

    def heartbeat_task(
        self,
        *,
        fence: TaskLeaseFence,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimedTask: ...

    def mark_task_running(self, *, fence: TaskLeaseFence) -> ClaimedTask: ...

    def acknowledge_task(
        self,
        *,
        fence: TaskLeaseFence,
        target_state: TaskState,
    ) -> None: ...

    def recover_expired_leases(
        self,
        *,
        run_id: str,
        now: datetime,
        limit: int = 100,
    ) -> tuple[LeaseRecovery, ...]: ...
