import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from co_scientist.application.commands import CreateRun, ExportRun, RunCommand
from co_scientist.application.queries import CheckConfig, GetRunStatus, ReplayRun
from co_scientist.application.service import build_application_service
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
            data_dir=tmp_path,
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


# Mutation caught: any command being a parse-only placeholder rather than durable behavior.
def test_cli_full_surface_operates_on_one_durable_run(tmp_path: Path) -> None:
    service = build_application_service(tmp_path)
    started = service.execute(
        CreateRun(
            goal_file=Path("goal.yaml"),
            profile_file=Path("profile.yaml"),
            provider="replay",
            data_dir=tmp_path,
        )
    )
    run_id = started.run_id

    checked = _invoke(service, ["config", "check"])
    status = _invoke(service, ["run", "status", run_id])
    stale_pause = _invoke(
        service,
        ["run", "pause", run_id, "--expected-sequence", "0"],
    )
    paused = _invoke(
        service,
        ["run", "pause", run_id, "--expected-sequence", str(started.current_sequence)],
    )
    stale_resume = _invoke(
        service,
        ["run", "resume", run_id, "--expected-sequence", "1"],
    )
    resumed = _invoke(service, ["run", "resume", run_id, "--expected-sequence", "3"])
    output = tmp_path / "exports" / "run.json"
    exported = _invoke(service, ["run", "export", run_id, "--output", str(output)])
    replayed = _invoke(service, ["replay", run_id])

    assert checked.exit_code == 0, checked.output
    assert status.exit_code == 0, status.output
    assert f"run_id={run_id} state=running sequence=1" in status.stdout
    assert stale_pause.exit_code != 0
    assert paused.exit_code == 0, paused.output
    assert "state=paused sequence=3" in paused.stdout
    assert stale_resume.exit_code != 0
    assert resumed.exit_code == 0, resumed.output
    assert "state=running sequence=4" in resumed.stdout
    assert exported.exit_code == 0, exported.output
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert snapshot["state_history"] == [
        "created",
        "running",
        "pausing",
        "paused",
        "running",
    ]
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.stdout) == snapshot
