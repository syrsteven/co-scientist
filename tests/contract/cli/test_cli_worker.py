import json
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from alembic import command
from co_scientist.application.commands import RunCommand
from co_scientist.application.config import resolve_run_config
from co_scientist.application.service import (
    ApplicationConcurrencyError,
    build_application_service,
)
from co_scientist.cli.app import app
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


def test_worker_resumes_supervisor_bootstrapped_run_in_an_independent_invocation(
    tmp_path: Path,
) -> None:
    goal, profile, environment = write_core_preview_inputs(tmp_path)
    data_dir = tmp_path / "data"
    config = resolve_run_config(
        goal_file=goal,
        profile_file=profile,
        provider="replay",
        environment=environment,
    )
    core = CoreRunner(data_dir=data_dir, environment=environment)
    core.supervisor.bootstrap_run(
        run_id="run-worker-resume",
        manifest=config.model_dump(mode="json")["manifest"],
    )

    result = CliRunner().invoke(
        app,
        ["worker", "run", "run-worker-resume", "--data-dir", str(data_dir)],
        env=environment,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["state"] == "completed"


def test_worker_rejects_pre_contract_run_with_sanitized_diagnostic(tmp_path: Path) -> None:
    data_dir = tmp_path / "legacy"
    data_dir.mkdir()
    database_url = f"sqlite:///{data_dir / 'co-scientist.db'}"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0002_external_call_recovery")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO runs (run_id, state, current_sequence, manifest_json) "
                "VALUES ('legacy-run', 'running', 0, '{}')"
            )
        )
    engine.dispose()

    result = CliRunner().invoke(
        app, ["worker", "run", "legacy-run", "--data-dir", str(data_dir)]
    )

    assert result.exit_code != 0
    assert result.stderr == (
        "invalid request: run legacy-run cannot execute: "
        "execution_contract_version 3 is required\n"
    )
    assert "Traceback" not in result.stderr


def test_cli_soft_stop_immediately_after_bootstrap_is_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    goal, profile, environment = write_core_preview_inputs(tmp_path)
    data_dir = tmp_path / "data"
    config = resolve_run_config(
        goal_file=goal,
        profile_file=profile,
        provider="replay",
        environment=environment,
    )
    core = CoreRunner(data_dir=data_dir, environment=environment)
    bootstrapped = core.supervisor.bootstrap_run(
        run_id="run-immediate-stop",
        manifest=config.model_dump(mode="json")["manifest"],
    )
    data = ["--data-dir", str(data_dir)]

    first = CliRunner().invoke(
        app,
        [
            "run",
            "stop",
            "run-immediate-stop",
            "--expected-sequence",
            str(bootstrapped.last_sequence),
            *data,
        ],
        env={},
    )
    assert first.exit_code == 0, first.output
    assert "state=stopping" in first.stdout
    stopping_sequence = int(first.stdout.rsplit("sequence=", 1)[1])
    second = CliRunner().invoke(
        app,
        [
            "run",
            "stop",
            "run-immediate-stop",
            "--expected-sequence",
            str(bootstrapped.last_sequence),
            *data,
        ],
        env={},
    )
    assert second.exit_code == 0, second.output
    assert second.stdout == first.stdout

    conflicting = CliRunner().invoke(
        app,
        [
            "run",
            "stop",
            "run-immediate-stop",
            "--expected-sequence",
            str(stopping_sequence),
            *data,
        ],
        env={},
    )
    assert conflicting.exit_code != 0
    assert "concurrency conflict" in conflicting.stderr

    finalized = CliRunner().invoke(
        app,
        ["worker", "run", "run-immediate-stop", *data],
        env={},
    )
    assert finalized.exit_code == 0, finalized.output
    assert json.loads(finalized.stdout)["state"] == "completed_partial"
    terminal_sequence = json.loads(finalized.stdout)["last_sequence"]

    application = build_application_service(data_dir, environment={})
    replayed = application.execute(
        RunCommand(
            run_id="run-immediate-stop",
            expected_run_sequence=bootstrapped.last_sequence,
            command="stop",
        )
    )
    assert replayed.state.value == "completed_partial"
    with pytest.raises(ApplicationConcurrencyError):
        application.execute(
            RunCommand(
                run_id="run-immediate-stop",
                expected_run_sequence=terminal_sequence,
                command="stop",
            )
        )

    terminal_replay = CliRunner().invoke(
        app,
        [
            "run",
            "stop",
            "run-immediate-stop",
            "--expected-sequence",
            str(bootstrapped.last_sequence),
            *data,
        ],
        env={},
    )
    terminal_conflict = CliRunner().invoke(
        app,
        [
            "run",
            "stop",
            "run-immediate-stop",
            "--expected-sequence",
            str(terminal_sequence),
            *data,
        ],
        env={},
    )
    assert terminal_replay.exit_code == 0, terminal_replay.output
    assert "state=completed_partial" in terminal_replay.stdout
    assert terminal_conflict.exit_code == 4
    assert "concurrency conflict" in terminal_conflict.stderr

    events = CoreRunner(data_dir=data_dir, environment={}).uow.load(
        "run-immediate-stop"
    )
    checkpoint = next(
        event for event in events if event.event_type == "ConvergenceCheckpointRecorded"
    )
    assert checkpoint.payload["stop_cause"] == "scientist_stop"
    assert checkpoint.payload["hypothesis_count"] == 0
    assert checkpoint.payload["match_count"] == 0
    assert checkpoint.payload["unresolved_task_ids"] == (
        "generation:run-immediate-stop:1",
    )
    assert sum(event.event_type == "StopSignalObserved" for event in events) == 1
    assert events[-2].event_type == "FinalizationCompleted"
    assert events[-1].event_type == "RunCompletedPartial"
