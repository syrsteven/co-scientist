import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from co_scientist.application.commands import CreateRun, ExportRun, RunCommand
from co_scientist.application.queries import CheckConfig, GetRunStatus, ReplayRun
from co_scientist.cli.app import app


class RecordingService:
    def __init__(self) -> None:
        self.commands: list[object] = []
        self.queries: list[object] = []

    def execute(self, command: object) -> object:
        self.commands.append(command)
        if isinstance(command, CreateRun):
            return SimpleNamespace(run_id="r-1", state="running", current_sequence=1)
        if isinstance(command, ExportRun):
            command.output.write_text('{"run_id":"r-1"}\n', encoding="utf-8")
            return SimpleNamespace(output=command.output)
        return SimpleNamespace(
            run_id=getattr(command, "run_id", "r-1"),
            state=getattr(command, "command", "running"),
            current_sequence=getattr(command, "expected_run_sequence", 0) + 1,
        )

    def query(self, query: object) -> object:
        self.queries.append(query)
        if isinstance(query, CheckConfig):
            return SimpleNamespace(ok=True, message="configuration valid")
        if isinstance(query, ReplayRun):
            return {"run_id": query.run_id, "state_history": ["created", "running"]}
        return {"run_id": "r-1", "state": "running", "current_sequence": 7}


def _invoke(service: RecordingService, args: list[str]):
    return CliRunner().invoke(app, args, obj=service)


# Mutation caught: selecting replay but not sending its typed provider choice to the service.
def test_cli_runs_a_replay_fixture(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "start",
            "--goal",
            "examples/lens_regeneration_goal.yaml",
            "--profile",
            "configs/profiles/core_preview.yaml",
            "--provider",
            "replay",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "run_id=" in result.stdout


# Mutation caught: CLI delivery translating start fields incorrectly at the application boundary.
def test_cli_start_constructs_typed_create_run(tmp_path: Path) -> None:
    service = RecordingService()
    result = _invoke(
        service,
        [
            "run",
            "start",
            "--goal",
            "examples/lens_regeneration_goal.yaml",
            "--profile",
            "configs/profiles/core_preview.yaml",
            "--provider",
            "replay",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert service.commands == [
        CreateRun(
            goal_file=Path("examples/lens_regeneration_goal.yaml"),
            profile_file=Path("configs/profiles/core_preview.yaml"),
            provider="replay",
        )
    ]


@pytest.mark.parametrize(
    ("verb", "expected_command"),
    [
        ("pause", "pause"),
        ("resume", "resume"),
        ("stop", "stop"),
        ("cancel", "cancel"),
    ],
)
# Mutation caught: dropping or renaming the optimistic-concurrency sequence on run controls.
def test_cli_run_controls_preserve_expected_sequence(
    verb: str, expected_command: str
) -> None:
    service = RecordingService()

    result = _invoke(service, ["run", verb, "r-1", "--expected-sequence", "7"])

    assert result.exit_code == 0, result.output
    assert service.commands == [
        RunCommand(run_id="r-1", expected_run_sequence=7, command=expected_command)
    ]


# Mutation caught: status bypassing the read-model query boundary.
def test_cli_status_uses_typed_query() -> None:
    service = RecordingService()

    result = _invoke(service, ["run", "status", "r-1"])

    assert result.exit_code == 0, result.output
    assert "state=running" in result.stdout
    assert service.queries == [GetRunStatus(run_id="r-1")]


# Mutation caught: config check becoming a CLI-only check rather than an application query.
def test_cli_config_check_uses_typed_query() -> None:
    service = RecordingService()

    result = _invoke(service, ["config", "check"])

    assert result.exit_code == 0, result.output
    assert "configuration valid" in result.stdout
    assert service.queries == [CheckConfig()]


# Mutation caught: export reading persistence directly or ignoring the requested output path.
def test_cli_export_uses_typed_command(tmp_path: Path) -> None:
    service = RecordingService()
    output = tmp_path / "run.json"

    result = _invoke(service, ["run", "export", "r-1", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert service.commands == [ExportRun(run_id="r-1", output=output)]


# Mutation caught: replay mutating a run or bypassing deterministic read reconstruction.
def test_cli_replay_uses_typed_query() -> None:
    service = RecordingService()

    result = _invoke(service, ["replay", "r-1"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "run_id": "r-1",
        "state_history": ["created", "running"],
    }
    assert service.queries == [ReplayRun(run_id="r-1")]


# Mutation caught: provider=openai triggering provider construction or network I/O in the CLI.
def test_cli_openai_selection_only_builds_the_application_command(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "start",
            "--goal",
            "goal.yaml",
            "--profile",
            "profile.yaml",
            "--provider",
            "openai",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "run_id=" in result.stdout


# Mutation caught: later invocations silently reopening the default data directory.
def test_separate_cli_invocations_share_custom_data_dir_and_repeat_lifecycle(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    data_option = ["--data-dir", str(tmp_path)]
    started = runner.invoke(
        app,
        [
            "run",
            "start",
            "--goal",
            "goal.yaml",
            "--profile",
            "profile.yaml",
            "--provider",
            "replay",
            *data_option,
        ],
    )
    assert started.exit_code == 0, started.output
    run_id = started.stdout.split()[0].split("=", 1)[1]

    checked = runner.invoke(app, ["config", "check", *data_option])
    status = runner.invoke(app, ["run", "status", run_id, *data_option])
    first_pause = runner.invoke(
        app, ["run", "pause", run_id, "--expected-sequence", "1", *data_option]
    )
    stale_pause = runner.invoke(
        app, ["run", "pause", run_id, "--expected-sequence", "1", *data_option]
    )
    first_resume = runner.invoke(
        app, ["run", "resume", run_id, "--expected-sequence", "3", *data_option]
    )
    second_pause = runner.invoke(
        app, ["run", "pause", run_id, "--expected-sequence", "4", *data_option]
    )
    second_resume = runner.invoke(
        app, ["run", "resume", run_id, "--expected-sequence", "6", *data_option]
    )
    output = tmp_path / "exports" / "run.json"
    exported = runner.invoke(
        app, ["run", "export", run_id, "--output", str(output), *data_option]
    )
    replayed = runner.invoke(app, ["replay", run_id, *data_option])

    assert checked.exit_code == 0, checked.output
    assert f"data_dir={tmp_path}" in checked.stdout
    assert "schema=ready" in checked.stdout
    assert status.exit_code == 0, status.output
    assert f"run_id={run_id} state=running sequence=1" in status.stdout
    assert first_pause.exit_code == 0, first_pause.output
    assert "state=paused sequence=3" in first_pause.stdout
    assert stale_pause.exit_code == 4
    assert "concurrency conflict: expected 1, got 3" in stale_pause.stderr
    assert first_resume.exit_code == 0, first_resume.output
    assert "state=running sequence=4" in first_resume.stdout
    assert second_pause.exit_code == 0, second_pause.output
    assert "state=paused sequence=6" in second_pause.stdout
    assert second_resume.exit_code == 0, second_resume.output
    assert "state=running sequence=7" in second_resume.stdout
    assert exported.exit_code == 0, exported.output
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert snapshot["state_history"] == [
        "created",
        "running",
        "pausing",
        "paused",
        "running",
        "pausing",
        "paused",
        "running",
    ]
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.stdout) == snapshot


# Mutation caught: config check reporting success without validating selected storage/schema.
def test_cli_config_check_reports_filesystem_failure(tmp_path: Path) -> None:
    invalid_data_dir = tmp_path / "not-a-directory"
    invalid_data_dir.write_text("occupied", encoding="utf-8")

    result = CliRunner().invoke(
        app, ["config", "check", "--data-dir", str(invalid_data_dir)]
    )

    assert result.exit_code == 6
    assert "filesystem error:" in result.stderr
    assert str(invalid_data_dir) in result.stderr


# Mutation caught: corrupt database configuration leaking a SQLAlchemy traceback.
def test_cli_config_check_reports_database_configuration_failure(tmp_path: Path) -> None:
    (tmp_path / "co-scientist.db").write_bytes(b"not a sqlite database")

    result = CliRunner().invoke(
        app, ["config", "check", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 2
    assert "configuration error: database initialization failed:" in result.stderr
    assert "Traceback" not in result.stderr


# Mutation caught: expected application failures leaking tracebacks or unstable exit codes.
def test_cli_maps_not_found_and_invalid_transition_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    data_option = ["--data-dir", str(tmp_path)]
    missing = runner.invoke(app, ["run", "status", "missing", *data_option])
    started = runner.invoke(
        app,
        [
            "run",
            "start",
            "--goal",
            "goal.yaml",
            "--profile",
            "profile.yaml",
            *data_option,
        ],
    )
    run_id = started.stdout.split()[0].split("=", 1)[1]
    invalid = runner.invoke(
        app, ["run", "resume", run_id, "--expected-sequence", "1", *data_option]
    )

    assert missing.exit_code == 3
    assert "not found: unknown run: missing" in missing.stderr
    assert invalid.exit_code == 5
    assert "invalid request: running -> running" in invalid.stderr
    assert "Traceback" not in missing.stderr + invalid.stderr


# Mutation caught: export filesystem errors escaping the stable CLI boundary.
def test_cli_maps_export_filesystem_error(tmp_path: Path) -> None:
    runner = CliRunner()
    data_option = ["--data-dir", str(tmp_path)]
    started = runner.invoke(
        app,
        [
            "run",
            "start",
            "--goal",
            "goal.yaml",
            "--profile",
            "profile.yaml",
            *data_option,
        ],
    )
    run_id = started.stdout.split()[0].split("=", 1)[1]

    result = runner.invoke(
        app, ["run", "export", run_id, "--output", str(tmp_path), *data_option]
    )

    assert result.exit_code == 6
    assert "filesystem error:" in result.stderr


# Mutation caught: input validation returning an unstable generic application failure.
def test_cli_validation_error_has_stable_usage_exit_and_message(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "pause",
            "run-1",
            "--expected-sequence",
            "-1",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--expected-sequence'" in result.stderr
