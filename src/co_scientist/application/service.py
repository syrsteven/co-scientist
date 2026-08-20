"""Application facade and local developer-preview composition."""

from __future__ import annotations

import inspect as python_inspect
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork
from co_scientist.application.commands import (
    CreateRun,
    ExecuteRun,
    ExportRun,
    RunCommand,
    RunWorker,
)
from co_scientist.application.config import resolve_run_config
from co_scientist.application.queries import CheckConfig, GetRunStatus, ReplayRun
from co_scientist.domain.review import ReviewPolicy
from co_scientist.domain.states import RunState
from co_scientist.domain.transitions import InvalidTransition
from co_scientist.events.models import DomainEvent
from co_scientist.export.run_export import SqliteRunReadModel, export_run
from co_scientist.ports.event_store import ConcurrencyConflict
from co_scientist.runtime.core_runner import CoreRunner
from co_scientist.supervisor.orchestrator import Supervisor


class CommandHandler(Protocol):
    """Supervisor-facing mutation port."""

    def handle_command(self, command: object) -> object: ...

    async def handle_command_async(self, command: object) -> object: ...


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


class ApplicationError(RuntimeError):
    category = "application error"
    exit_code = 1


class ApplicationConfigurationError(ApplicationError):
    category = "configuration error"
    exit_code = 2


class ApplicationNotFoundError(ApplicationError):
    category = "not found"
    exit_code = 3


class ApplicationConcurrencyError(ApplicationError):
    category = "concurrency conflict"
    exit_code = 4


class ApplicationInvalidRequestError(ApplicationError):
    category = "invalid request"
    exit_code = 5


class ApplicationFilesystemError(ApplicationError):
    category = "filesystem error"
    exit_code = 6


_EXPECTED_APPLICATION_ERRORS = (
    ApplicationError,
    KeyError,
    ConcurrencyConflict,
    OSError,
    InvalidTransition,
    ValidationError,
    ValueError,
    SQLAlchemyError,
)


def _translate_expected_error(error: Exception) -> ApplicationError:
    if isinstance(error, ApplicationError):
        return error
    if isinstance(error, KeyError):
        return ApplicationNotFoundError(str(error.args[0]))
    if isinstance(error, ConcurrencyConflict):
        return ApplicationConcurrencyError(str(error))
    if isinstance(error, OSError):
        return ApplicationFilesystemError(str(error))
    if isinstance(error, SQLAlchemyError):
        return ApplicationConfigurationError("database operation failed")
    if isinstance(error, InvalidTransition | ValidationError | ValueError):
        return ApplicationInvalidRequestError(str(error))
    raise error


class ApplicationService:
    """Single delivery-facing boundary for commands and read-model queries."""

    def __init__(self, *, supervisor: CommandHandler, read_model: ReadModel) -> None:
        self._supervisor = supervisor
        self._read_model = read_model

    def execute(self, command: object) -> object:
        try:
            return self._supervisor.handle_command(command)
        except _EXPECTED_APPLICATION_ERRORS as error:
            raise _translate_expected_error(error) from None

    async def execute_async(self, command: object) -> object:
        try:
            handler = getattr(self._supervisor, "handle_command_async", None)
            if handler is None:
                return self._supervisor.handle_command(command)
            result = handler(command)
            return await result if python_inspect.isawaitable(result) else result
        except _EXPECTED_APPLICATION_ERRORS as error:
            raise _translate_expected_error(error) from None

    def query(self, query: object) -> object:
        try:
            return self._read_model.execute(query)
        except _EXPECTED_APPLICATION_ERRORS as error:
            raise _translate_expected_error(error) from None


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
            tables = set(inspect(self._uow.engine).get_table_names())
            required_tables = {
                "runs",
                "events",
                "tasks",
                "external_calls",
                "cost_entries",
                "idempotency_commits",
            }
            missing = sorted(required_tables - tables)
            if missing:
                raise ApplicationConfigurationError(
                    f"database schema missing tables: {', '.join(missing)}"
                )
            database = self._data_dir / "co-scientist.db"
            return ConfigResult(
                ok=True,
                message=(
                    f"configuration ready data_dir={self._data_dir} "
                    f"database={database} schema=ready"
                ),
            )
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
        runner: CoreRunner,
        environment: Mapping[str, str],
    ) -> None:
        self._supervisor = supervisor
        self._read_model = read_model
        self._runner = runner
        self._environment = dict(environment)

    def _result(self, run_id: str) -> RunResult:
        return RunResult.model_validate(
            self._read_model.execute(GetRunStatus(run_id=run_id))
        )

    def _create_run(self, command: CreateRun) -> RunResult:
        run_id = f"run-{uuid4().hex}"
        payload = {
            "goal_file": str(command.goal_file),
            "profile_file": str(command.profile_file),
            "provider": command.provider,
        }
        self._supervisor.create_and_start_run(
            run_id,
            manifest=payload,
            start_payload=payload,
        )
        return self._result(run_id)

    def _control_run(self, command: RunCommand) -> RunResult:
        if command.command == "start":
            self._supervisor.start_run(
                command.run_id,
                expected_sequence=command.expected_run_sequence,
            )
        elif command.command == "pause":
            self._supervisor.pause_run(
                command.run_id,
                expected_sequence=command.expected_run_sequence,
            )
        elif command.command == "resume":
            self._supervisor.resume_run(
                command.run_id,
                expected_sequence=command.expected_run_sequence,
            )
        elif command.command == "stop":
            self._supervisor.request_soft_stop(
                command.run_id,
                expected_sequence=command.expected_run_sequence,
            )
        elif command.command == "cancel":
            self._supervisor.cancel_run(
                command.run_id,
                expected_sequence=command.expected_run_sequence,
            )
        return self._result(command.run_id)

    def _export_run(self, command: ExportRun) -> ExportResult:
        output = export_run(
            command.run_id,
            command.output,
            SqliteRunReadModel(self._runner.uow),
            self._runner.artifacts,
        )
        return ExportResult(output=output)

    def handle_command(self, command: object) -> object:
        if isinstance(command, CreateRun):
            return self._create_run(command)
        if isinstance(command, RunCommand):
            return self._control_run(command)
        if isinstance(command, ExportRun):
            return self._export_run(command)
        raise TypeError(f"unsupported application command: {type(command).__name__}")

    async def handle_command_async(self, command: object) -> object:
        if isinstance(command, ExecuteRun):
            try:
                config = resolve_run_config(
                    goal_file=command.goal_file,
                    profile_file=command.profile_file,
                    provider=command.provider,
                    environment=self._environment,
                )
            except (FileNotFoundError, TypeError, ValidationError, ValueError) as error:
                raise ApplicationConfigurationError(str(error)) from None
            return await self._runner.execute(config=config)
        if isinstance(command, RunWorker):
            return await self._runner.resume(run_id=command.run_id)
        return self.handle_command(command)


def build_application_service(
    data_dir: Path,
    environment: Mapping[str, str] | None = None,
) -> ApplicationService:
    """Compose the guarded local preview; provider selection never performs a call."""

    resolved_data_dir = data_dir.expanduser()
    try:
        resolved_data_dir.mkdir(parents=True, exist_ok=True)
        if not resolved_data_dir.is_dir():
            raise NotADirectoryError(f"data directory is not a directory: {resolved_data_dir}")
        runner = CoreRunner(
            data_dir=resolved_data_dir,
            environment=environment if environment is not None else os.environ,
        )
        uow = runner.uow
    except OSError as error:
        raise ApplicationFilesystemError(str(error)) from None
    except SQLAlchemyError:
        raise ApplicationConfigurationError("database initialization failed") from None
    supervisor = Supervisor(
        uow=uow,
        review_policy=ReviewPolicy(profile_id="core-preview"),
    )
    read_model = _SqliteReadModel(uow=uow, data_dir=resolved_data_dir)
    command_handler = _SupervisorCommandHandler(
        supervisor=supervisor,
        read_model=read_model,
        runner=runner,
        environment=environment if environment is not None else os.environ,
    )
    return ApplicationService(supervisor=command_handler, read_model=read_model)
