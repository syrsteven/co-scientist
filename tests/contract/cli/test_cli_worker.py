import json
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from alembic import command
from co_scientist.application.config import resolve_run_config
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
