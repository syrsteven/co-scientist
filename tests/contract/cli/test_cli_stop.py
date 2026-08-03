from pathlib import Path

from typer.testing import CliRunner

from co_scientist.application.commands import CreateRun
from co_scientist.application.queries import ReplayRun
from co_scientist.application.service import build_application_service
from co_scientist.cli.app import app


# Mutation caught: mapping normal stop directly to a terminal state or to hard cancellation.
def test_cli_soft_stop_finishes_through_stopping(tmp_path: Path) -> None:
    service = build_application_service(tmp_path)
    started = service.execute(
        CreateRun(
            goal_file=Path("goal.yaml"),
            profile_file=Path("core.yaml"),
            provider="replay",
            data_dir=tmp_path,
        )
    )

    stale = CliRunner().invoke(
        app,
        ["run", "stop", started.run_id, "--expected-sequence", "0"],
        obj=service,
    )
    result = CliRunner().invoke(
        app,
        [
            "run",
            "stop",
            started.run_id,
            "--expected-sequence",
            str(started.current_sequence),
        ],
        obj=service,
    )

    assert stale.exit_code != 0
    assert result.exit_code == 0, result.output
    replayed = service.query(ReplayRun(run_id=started.run_id))
    assert replayed["state_history"][-2:] == ["stopping", "completed_partial"]


# Mutation caught: implementing cancel as the same finalized soft-stop path.
def test_cli_cancel_remains_distinct_from_normal_stop(tmp_path: Path) -> None:
    service = build_application_service(tmp_path)
    started = service.execute(
        CreateRun(
            goal_file=Path("goal.yaml"),
            profile_file=Path("core.yaml"),
            provider="fake",
            data_dir=tmp_path,
        )
    )

    stale = CliRunner().invoke(
        app,
        ["run", "cancel", started.run_id, "--expected-sequence", "0"],
        obj=service,
    )
    result = CliRunner().invoke(
        app,
        [
            "run",
            "cancel",
            started.run_id,
            "--expected-sequence",
            str(started.current_sequence),
        ],
        obj=service,
    )

    assert stale.exit_code != 0
    assert result.exit_code == 0, result.output
    replayed = service.query(ReplayRun(run_id=started.run_id))
    assert replayed["state_history"][-1] == "cancelled"
    assert "completed_partial" not in replayed["state_history"]
