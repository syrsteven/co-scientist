from typer.testing import CliRunner

from co_scientist.cli.app import app


def _start(runner: CliRunner, data_option: list[str]) -> str:
    result = runner.invoke(
        app,
        [
            "run",
            "start",
            "--goal",
            "goal.yaml",
            "--profile",
            "core.yaml",
            "--provider",
            "replay",
            *data_option,
        ],
    )
    assert result.exit_code == 0, result.output
    return result.stdout.split()[0].split("=", 1)[1]


# Mutation caught: mapping normal stop directly to a terminal state or to hard cancellation.
def test_cli_soft_stop_finishes_through_stopping(tmp_path) -> None:
    runner = CliRunner()
    data_option = ["--data-dir", str(tmp_path)]
    run_id = _start(runner, data_option)

    result = runner.invoke(
        app,
        ["run", "stop", run_id, "--expected-sequence", "1", *data_option],
    )
    stale = runner.invoke(
        app, ["run", "stop", run_id, "--expected-sequence", "1", *data_option]
    )
    replayed = runner.invoke(app, ["replay", run_id, *data_option])

    assert stale.exit_code == 4
    assert result.exit_code == 0, result.output
    assert '"state_history": ["created", "running", "stopping", "completed_partial"]' in replayed.stdout


# Mutation caught: implementing cancel as the same finalized soft-stop path.
def test_cli_cancel_remains_distinct_from_normal_stop(tmp_path) -> None:
    runner = CliRunner()
    data_option = ["--data-dir", str(tmp_path)]
    run_id = _start(runner, data_option)

    result = runner.invoke(
        app,
        ["run", "cancel", run_id, "--expected-sequence", "1", *data_option],
    )
    stale = runner.invoke(
        app, ["run", "cancel", run_id, "--expected-sequence", "1", *data_option]
    )
    replayed = runner.invoke(app, ["replay", run_id, *data_option])

    assert stale.exit_code == 4
    assert result.exit_code == 0, result.output
    assert '"state_history": ["created", "running", "cancelled"]' in replayed.stdout
    assert "completed_partial" not in replayed.stdout
