import json
from pathlib import Path

from typer.testing import CliRunner

from co_scientist.cli.app import app
from tests.core_preview_support import write_core_preview_inputs


def test_cli_exports_rich_directory_and_recursively_excludes_secrets(tmp_path: Path) -> None:
    goal, profile, environment = write_core_preview_inputs(tmp_path)
    secret = "sk-recursive-export-secret"
    environment["OPENAI_API_KEY"] = secret
    data_dir = tmp_path / "data"
    runner = CliRunner()
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
            "--data-dir",
            str(data_dir),
        ],
        env=environment,
    )
    assert executed.exit_code == 0, executed.output
    run_id = json.loads(executed.stdout)["run_id"]
    destination = tmp_path / "export"

    exported = runner.invoke(
        app,
        [
            "run",
            "export",
            run_id,
            "--output",
            str(destination),
            "--data-dir",
            str(data_dir),
        ],
        env=environment,
    )

    assert exported.exit_code == 0, exported.output
    expected = {
        "manifest.json",
        "events.jsonl",
        "hypotheses.json",
        "hypothesis_projections.json",
        "reviews.json",
        "novelty_assessments.json",
        "proximity.json",
        "tournament_epochs.json",
        "matches.json",
        "ratings.json",
        "tasks.json",
        "external_calls.json",
        "costs.json",
        "literature.json",
        "artifacts.json",
    }
    assert expected <= {path.name for path in destination.iterdir() if path.is_file()}
    all_bytes = b"\n".join(
        path.read_bytes() for path in sorted(destination.rglob("*")) if path.is_file()
    )
    assert secret.encode() not in all_bytes
    assert b"OPENAI_API_KEY" not in all_bytes
