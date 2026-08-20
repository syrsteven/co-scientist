import json
from pathlib import Path

from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from co_scientist.cli.app import app
from tests.core_preview_support import write_core_preview_inputs


def test_execute_status_and_config_failure_are_stable_across_invocations(
    tmp_path: Path,
) -> None:
    goal, profile, environment = write_core_preview_inputs(tmp_path)
    data_dir = tmp_path / "data"
    runner = CliRunner()
    data = ["--data-dir", str(data_dir)]

    executed = runner.invoke(
        app,
        [
            "run",
            "execute",
            "--goal",
            str(goal),
            "--profile",
            str(profile),
            "--provider",
            "replay",
            *data,
        ],
        env=environment,
    )
    assert executed.exit_code == 0, executed.output
    execution = json.loads(executed.stdout)
    assert execution["state"] == "completed"
    assert execution["stop_reason"] == "quality_converged"

    status = runner.invoke(
        app, ["run", "status", execution["run_id"], *data], env=environment
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout) == {
        "current_sequence": execution["last_sequence"],
        "run_id": execution["run_id"],
        "state": "completed",
    }

    broken_dir = tmp_path / "broken-data"
    broken = runner.invoke(
        app,
        [
            "run",
            "execute",
            "--goal",
            str(goal),
            "--profile",
            str(profile),
            "--provider",
            "replay",
            "--data-dir",
            str(broken_dir),
        ],
        env={},
    )
    assert broken.exit_code == 2
    assert "configuration error:" in broken.stderr
    database = broken_dir / "co-scientist.db"
    if database.exists():
        engine = create_engine(f"sqlite:///{database}")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM runs")).scalar_one() == 0
        engine.dispose()


def test_non_object_profile_is_a_sanitized_configuration_error(tmp_path: Path) -> None:
    goal, profile, environment = write_core_preview_inputs(tmp_path)
    profile.write_text("[]\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "run",
            "execute",
            "--goal",
            str(goal),
            "--profile",
            str(profile),
            "--provider",
            "replay",
            "--data-dir",
            str(tmp_path / "data"),
        ],
        env=environment,
    )

    assert result.exit_code == 2
    assert result.stderr.startswith("configuration error:")
    assert "Traceback" not in result.stderr
