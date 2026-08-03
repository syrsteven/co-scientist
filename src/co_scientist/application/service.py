"""Application facade and local developer-preview composition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.commands import CreateRun, ExportRun, RunCommand
from co_scientist.application.queries import CheckConfig, GetRunStatus, ReplayRun
from co_scientist.domain.convergence import ConvergenceSnapshot
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.events.models import DomainEvent, NewEvent
from co_scientist.supervisor.orchestrator import Supervisor


class CommandHandler(Protocol):
    """Supervisor-facing mutation port."""

    def handle_command(self, command: object) -> object: ...


class ReadModel(Protocol):
    """Read-projection query port."""

    def execute(self, query: object) -> object: ...


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    state: RunState
    current_sequence: int


class ConfigResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    message: str


class ExportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    output: Path


class ApplicationService:
    """Single delivery-facing boundary for commands and read-model queries."""

    def __init__(self, *, supervisor: CommandHandler, read_model: ReadModel) -> None:
        self._supervisor = supervisor
        self._read_model = read_model

    def execute(self, command: object) -> object:
        return self._supervisor.handle_command(command)

    def query(self, query: object) -> object:
        return self._read_model.execute(query)


_EVENT_STATES: dict[str, RunState] = {
    "RunStarted": RunState.RUNNING,
    "RunPausing": RunState.PAUSING,
    "RunPaused": RunState.PAUSED,
    "RunResumed": RunState.RUNNING,
    "RunStopping": RunState.STOPPING,
    "RunCompleted": RunState.COMPLETED,
    "RunCompletedPartial": RunState.COMPLETED_PARTIAL,
    "RunCancelled": RunState.CANCELLED,
}


def _current_sequence(events: list[DomainEvent]) -> int:
    return events[-1].sequence if events else 0


def _state_history(events: list[DomainEvent]) -> list[str]:
    history = [RunState.CREATED.value]
    history.extend(
        state.value
        for event in events
        if (state := _EVENT_STATES.get(event.event_type)) is not None
    )
    return history


def _snapshot(uow: SqliteUnitOfWork, run_id: str) -> dict[str, Any]:
    events = uow.load(run_id)
    return {
        "run_id": run_id,
        "state": uow.run_state(run_id),
        "current_sequence": _current_sequence(events),
        "state_history": _state_history(events),
        "events": [event.model_dump(mode="json") for event in events],
    }


class _SqliteReadModel:
    def __init__(self, *, uow: SqliteUnitOfWork, data_dir: Path) -> None:
        self._uow = uow
        self._data_dir = data_dir

    def execute(self, query: object) -> object:
        if isinstance(query, CheckConfig):
            requested_dir = query.data_dir or self._data_dir
            if requested_dir != self._data_dir:
                return ConfigResult(
                    ok=False,
                    message=f"configured data directory is {self._data_dir}",
                )
            return ConfigResult(ok=True, message="configuration valid")
        if isinstance(query, GetRunStatus):
            events = self._uow.load(query.run_id)
            return {
                "run_id": query.run_id,
                "state": self._uow.run_state(query.run_id),
                "current_sequence": _current_sequence(events),
            }
        if isinstance(query, ReplayRun):
            return _snapshot(self._uow, query.run_id)
        raise TypeError(f"unsupported application query: {type(query).__name__}")


class _SupervisorCommandHandler:
    """Map typed application commands onto existing durable Supervisor operations."""

    def __init__(
        self,
        *,
        supervisor: Supervisor,
        read_model: _SqliteReadModel,
    ) -> None:
        self._supervisor = supervisor
        self._read_model = read_model

    @property
    def _uow(self) -> SqliteUnitOfWork:
        return self._supervisor.uow

    def _result(self, run_id: str) -> RunResult:
        events = self._uow.load(run_id)
        return RunResult(
            run_id=run_id,
            state=RunState(self._uow.run_state(run_id)),
            current_sequence=_current_sequence(events),
        )

    def _create_run(self, command: CreateRun) -> RunResult:
        run_id = f"run-{uuid4().hex}"
        self._uow.create_run(
            run_id,
            manifest={
                "goal_file": str(command.goal_file),
                "profile_file": str(command.profile_file),
                "provider": command.provider,
            },
        )
        self._uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=0,
            events=(
                NewEvent(
                    event_type="RunStarted",
                    payload={
                        "goal_file": str(command.goal_file),
                        "profile_file": str(command.profile_file),
                        "provider": command.provider,
                    },
                ),
            ),
            target_run_state=RunState.RUNNING,
            idempotency_key=f"start:{run_id}",
        )
        return self._result(run_id)

    def _commit_transition(
        self,
        *,
        run_id: str,
        expected_sequence: int,
        event_type: str,
        target: RunState,
        idempotency_key: str,
    ) -> int:
        commit = self._uow.commit_domain_batch(
            run_id=run_id,
            expected_sequence=expected_sequence,
            events=(NewEvent(event_type=event_type, payload={}),),
            target_run_state=target,
            idempotency_key=idempotency_key,
        )
        return commit.last_sequence

    def _control_run(self, command: RunCommand) -> RunResult:
        if command.command == "start":
            self._commit_transition(
                run_id=command.run_id,
                expected_sequence=command.expected_run_sequence,
                event_type="RunStarted",
                target=RunState.RUNNING,
                idempotency_key=f"start:{command.run_id}",
            )
        elif command.command == "pause":
            pausing_sequence = self._commit_transition(
                run_id=command.run_id,
                expected_sequence=command.expected_run_sequence,
                event_type="RunPausing",
                target=RunState.PAUSING,
                idempotency_key=f"pause-request:{command.run_id}",
            )
            self._commit_transition(
                run_id=command.run_id,
                expected_sequence=pausing_sequence,
                event_type="RunPaused",
                target=RunState.PAUSED,
                idempotency_key=f"pause-complete:{command.run_id}",
            )
        elif command.command == "resume":
            self._commit_transition(
                run_id=command.run_id,
                expected_sequence=command.expected_run_sequence,
                event_type="RunResumed",
                target=RunState.RUNNING,
                idempotency_key=f"resume:{command.run_id}",
            )
        elif command.command == "stop":
            stopping = self._supervisor.request_normal_completion(
                command.run_id,
                expected_sequence=command.expected_run_sequence,
                reason="scientist_stop",
            )
            finalization_task_id = f"finalize:{command.run_id}"
            self._uow.transition_task(finalization_task_id, "leased")
            self._uow.transition_task(finalization_task_id, "running")
            self._uow.transition_task(finalization_task_id, "result_received")
            self._supervisor.apply_finalization(
                command.run_id,
                expected_sequence=stopping.last_sequence,
                completeness="partial",
            )
        elif command.command == "cancel":
            self._supervisor.tick(
                run_id=command.run_id,
                expected_sequence=command.expected_run_sequence,
                convergence=ConvergenceSnapshot(
                    epoch_id="cancel-not-applicable",
                    anchor_set_id="cancel-not-applicable",
                    elo_plateau=False,
                    anchor_plateau=False,
                    top_k_stable=False,
                    cluster_diversity_plateau=False,
                    minimum_budget_satisfied=False,
                ),
                scientist_action="hard_cancel",
            )
        return self._result(command.run_id)

    def _export_run(self, command: ExportRun) -> ExportResult:
        snapshot = self._read_model.execute(ReplayRun(run_id=command.run_id))
        command.output.parent.mkdir(parents=True, exist_ok=True)
        command.output.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return ExportResult(output=command.output)

    def handle_command(self, command: object) -> object:
        if isinstance(command, CreateRun):
            return self._create_run(command)
        if isinstance(command, RunCommand):
            return self._control_run(command)
        if isinstance(command, ExportRun):
            return self._export_run(command)
        raise TypeError(f"unsupported application command: {type(command).__name__}")


def build_application_service(data_dir: Path) -> ApplicationService:
    """Compose the guarded local preview; provider selection never performs a call."""

    resolved_data_dir = data_dir.expanduser()
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    uow = SqliteUnitOfWork(f"sqlite:///{resolved_data_dir / 'co-scientist.db'}")
    uow.create_schema()
    supervisor = Supervisor(
        uow=uow,
        review_policy=ReviewPolicy(profile_id="core-preview"),
    )
    read_model = _SqliteReadModel(uow=uow, data_dir=resolved_data_dir)
    command_handler = _SupervisorCommandHandler(
        supervisor=supervisor,
        read_model=read_model,
    )
    return ApplicationService(supervisor=command_handler, read_model=read_model)
