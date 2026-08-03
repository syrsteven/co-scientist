"""Typer CLI backed exclusively by typed application commands and queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import typer

from co_scientist.application.commands import CreateRun, ExportRun, RunCommand
from co_scientist.application.queries import CheckConfig, GetRunStatus, ReplayRun
from co_scientist.application.service import ApplicationService, build_application_service

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
run_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(run_app, name="run")

_DEFAULT_DATA_DIR = Path(".co-scientist")


def _service(context: typer.Context, *, data_dir: Path | None = None) -> ApplicationService:
    if context.obj is not None:
        return cast(ApplicationService, context.obj)
    service = build_application_service(data_dir or _DEFAULT_DATA_DIR)
    context.obj = service
    return service


def _value(result: object, name: str) -> Any:
    if isinstance(result, dict):
        return result[name]
    return getattr(result, name)


@config_app.command("check")
def config_check(context: typer.Context) -> None:
    """Check the composed local configuration and storage boundary."""

    result = _service(context).query(CheckConfig())
    typer.echo(_value(result, "message"))
    if not _value(result, "ok"):
        raise typer.Exit(code=1)


@run_app.command("start")
def run_start(
    context: typer.Context,
    goal: Annotated[Path, typer.Option("--goal")],
    profile: Annotated[Path, typer.Option("--profile")],
    provider: Annotated[
        Literal["fake", "replay", "openai"], typer.Option("--provider")
    ] = "fake",
    data_dir: Annotated[Path, typer.Option("--data-dir")] = _DEFAULT_DATA_DIR,
) -> None:
    """Create and start a preview run without implicitly calling a provider."""

    result = _service(context, data_dir=data_dir).execute(
        CreateRun(
            goal_file=goal,
            profile_file=profile,
            provider=provider,
            data_dir=data_dir,
        )
    )
    typer.echo(
        f"run_id={_value(result, 'run_id')} state={_value(result, 'state')} "
        f"sequence={_value(result, 'current_sequence')}"
    )


@run_app.command("status")
def run_status(context: typer.Context, run_id: str) -> None:
    """Show a run's current read projection."""

    result = _service(context).query(GetRunStatus(run_id=run_id))
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
) -> None:
    result = _service(context).execute(
        RunCommand(
            run_id=run_id,
            expected_run_sequence=expected_sequence,
            command=command,
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
) -> None:
    """Pause a run using optimistic concurrency."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="pause",
    )


@run_app.command("resume")
def run_resume(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
) -> None:
    """Resume a paused run using optimistic concurrency."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="resume",
    )


@run_app.command("stop")
def run_stop(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
) -> None:
    """Soft-stop and finalize a run as completed_partial."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="stop",
    )


@run_app.command("cancel")
def run_cancel(
    context: typer.Context,
    run_id: str,
    expected_sequence: Annotated[int, typer.Option("--expected-sequence", min=0)],
) -> None:
    """Hard-cancel a run using optimistic concurrency."""

    _execute_run_command(
        context,
        run_id=run_id,
        expected_sequence=expected_sequence,
        command="cancel",
    )


@run_app.command("export")
def run_export(
    context: typer.Context,
    run_id: str,
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Export a deterministic run snapshot."""

    result = _service(context).execute(ExportRun(run_id=run_id, output=output))
    typer.echo(f"output={_value(result, 'output')}")


@app.command("replay")
def replay(context: typer.Context, run_id: str) -> None:
    """Reconstruct and print a run from durable events."""

    result = _service(context).query(ReplayRun(run_id=run_id))
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))


def main() -> None:
    app()
