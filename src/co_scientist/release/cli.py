"""Documented standalone Ideation operator commands, no hidden live defaults."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from .resources import install_openai_asset
from .service import RunService, budget

app = typer.Typer(no_args_is_help=True, help="Co-Scientist Continuous R2 G3 DEV release")
ideation = typer.Typer(no_args_is_help=True)
app.add_typer(ideation, name="ideation")


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@ideation.command("resources")
def resources(source: Annotated[Path | None, typer.Option("--from-file")] = None):
    """Explicitly install/hash-verify tokenizer data; no model/PubMed request."""
    emit({"installed": install_openai_asset(source)})


@ideation.command("validate")
def validate(
    goal: Annotated[Path, typer.Option("--goal")],
    profile: Annotated[Path | None, typer.Option("--profile")] = None,
):
    """Offline schema/resource/role/budget check; does NOT certify API account access."""
    m = RunService().validate(goal, profile)
    emit(
        {
            "valid": True,
            "budget": budget(m),
            "execution": "G3 DEV, not G10 paper replication",
            "capability": "frozen declarations; live access/pricing require operator verification",
        }
    )


@ideation.command("create")
def create(
    goal: Annotated[Path, typer.Option("--goal")],
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("runs"),
    profile: Annotated[Path | None, typer.Option("--profile")] = None,
):
    """Freeze a fresh independent Run; no database, permit or scientific dispatch."""
    emit(RunService().create(goal, data_dir, profile=profile))


@ideation.command("authorize")
def authorize(
    root: Path,
    accept_usd: Annotated[str, typer.Option("--accept-usd")],
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
    accept_unknown_risk: Annotated[bool, typer.Option("--accept-unknown-delivery-risk")] = False,
    confirm_pricing: Annotated[bool, typer.Option("--confirm-pricing-capability")] = False,
):
    """Explicit one-Run paid/risk approval. Never authorizes another Run."""
    emit(
        RunService().authorize(
            root,
            confirm=confirm,
            accept_usd=accept_usd,
            accept_unknown_risk=accept_unknown_risk,
            confirm_pricing=confirm_pricing,
        )
    )


@ideation.command("start")
def start(root: Path):
    """Drive an authorized Run; progress.jsonl and status are available concurrently."""
    emit(asyncio.run(RunService().execute(root)))


@ideation.command("resume")
def resume(root: Path):
    """Resume original durable Run/checkpoint under its unchanged authorization."""
    emit(asyncio.run(RunService().execute(root)))


@ideation.command("status")
def status(root: Path):
    emit(RunService().status(root))


@ideation.command("events")
def events(root: Path, after: Annotated[int, typer.Option("--after", min=0)] = 0):
    emit(RunService().events(root, after))


@ideation.command("stop")
def stop(root: Path):
    """Durable safe stop request; finalizes PARTIAL, cannot become a final winner."""
    emit(RunService().stop(root))


@ideation.command("export")
def export(root: Path, output: Annotated[Path | None, typer.Option("--output")] = None):
    """Read-only scientific export; never requests a provider."""
    emit(asyncio.run(RunService().export(root, output)))


@ideation.command("mock")
def mock(
    goal: Annotated[Path, typer.Option("--goal")],
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("mock-runs"),
    long: Annotated[bool, typer.Option("--long-context")] = False,
):
    """Full G3 through real adapters + synthetic MockTransport; zero real sockets."""
    service = RunService(environment={})
    created = service.create(goal, data_dir, mock=True, long=long)
    root = created["run_root"]
    service.authorize(root, confirm=True, accept_usd="60")
    emit({"run_root": root, "result": asyncio.run(service.execute(root))})


def main():
    try:
        app()
    except (ValueError, KeyError, FileNotFoundError) as error:
        typer.echo("BLOCKED: " + str(error), err=True)
        raise SystemExit(2) from None
