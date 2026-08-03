"""Typer CLI backed exclusively by typed application commands and queries."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, cast

import typer

from co_scientist.application.commands import CreateRun, ExportRun, RunCommand
from co_scientist.application.queries import CheckConfig, GetRunStatus, ReplayRun
from co_scientist.application.service import (
    ApplicationError,
    ApplicationService,
    build_application_service,
)

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
run_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(run_app, name="run")

_DEFAULT_DATA_DIR = Path(".co-scientist")
_ResultT = TypeVar("_ResultT")


def _service(context: typer.Context, *, data_dir: Path) -> ApplicationService:
    if context.obj is not None:
        return cast(ApplicationService, context.obj)
    service = build_application_service(data_dir)
    context.obj = service
    return service


def _value(result: object, name: str) -> Any:
    if isinstance(result, dict):
        return result[name]
    return getattr(result, name)


def _application_call(operation: Callable[[], _ResultT]) -> _ResultT:
    try:
        return operation()
    except ApplicationError as error:
        typer.echo(f"{error.category}: {error}", err=True)
        raise typer.Exit(code=error.exit_code) from None


@config_app.command("check")
def config_check(
    context: typer.Context,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Check the selected local storage and schema readiness."""

    result = _application_call(
        lambda: _service(context, data_dir=data_dir).query(CheckConfig())
    )
    typer.echo(_value(result, "message"))


@run_app.command("start")
def run_start(
    context: typer.Context,
    goal: Annotated[Path, typer.Option("--goal")],
    profile: Annotated[Path, typer.Option("--profile")],
    provider: Annotated[
        Literal["fake", "replay", "openai"], typer.Option("--provider")
    ] = "fake",
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Create and start a preview run without implicitly calling a provider."""

    result = _application_call(
        lambda: _service(context, data_dir=data_dir).execute(
            CreateRun(goal_file=goal, profile_file=profile, provider=provider)
        )
    )
    typer.echo(
        f"run_id={_value(result, 'run_id')} state={_value(result, 'state')} "
        f"sequence={_value(result, 'current_sequence')}"
    )


@run_app.command("status")
def run_status(
    context: typer.Context,
    run_id: str,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Show a run's current read projection."""

    result = _application_call(
        lambda: _service(context, data_dir=data_dir).query(GetRunStatus(run_id=run_id))
    )
    typer.echo(
        f"run_id={_value(result, 'run_id')} state={_value(result, 'state')} "
        f"sequence={_value(result, 'current_sequence')}"
    )


def _execute_run_command(
    context: typer.Context,
    *,
    run_id: str,
    expected_sequence: int,
    command: Literal["pause", "resume", "stop", "cancel"],
    data_dir: Path,
) -> None:
    result = _application_call(
        lambda: _service(context, data_dir=data_dir).execute(
            RunCommand(
                run_id=run_id,
                expected_run_sequence=expected_sequence,
                command=command,
            )
        )
    )
    typer.echo(
        f"run_id={_value(result, 'run_id')} state={_value(result, 'state')} "
        f"sequence={_value(result, 'current_sequence')}"
    )


@run_app.command("pause")
def run_pause(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Pause a run using optimistic concurrency."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="pause",
        data_dir=data_dir,
    )


@run_app.command("resume")
def run_resume(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Resume a paused run using optimistic concurrency."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="resume",
        data_dir=data_dir,
    )


@run_app.command("stop")
def run_stop(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Soft-stop and finalize a run as completed_partial."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="stop",
        data_dir=data_dir,
    )


@run_app.command("cancel")
def run_cancel(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Hard-cancel a run using optimistic concurrency."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="cancel",
        data_dir=data_dir,
    )


@run_app.command("export")
def run_export(
    context: typer.Context,
    run_id: str,
    output: Annotated[Path, typer.Option("--output")],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Export a deterministic run snapshot."""

    result = _application_call(
        lambda: _service(context, data_dir=data_dir).execute(
            ExportRun(run_id=run_id, output=output)
        )
    )
    typer.echo(f"output={_value(result, 'output')}")


@app.command("replay")
def replay(
    context: typer.Context,
    run_id: str,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", envvar="CO_SCIENTIST_DATA_DIR")
    ] = _DEFAULT_DATA_DIR,
) -> None:
    """Reconstruct and print a run from durable events."""

    result = _application_call(
        lambda: _service(context, data_dir=data_dir).query(ReplayRun(run_id=run_id))
    )
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))


def main() -> None:
    app()
