from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOAL = REPOSITORY_ROOT / "examples/lens_regeneration_goal.yaml"
PROFILE = REPOSITORY_ROOT / "configs/profiles/core_preview.yaml"


def _invoke_cli(
    cwd: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    child_environment = os.environ.copy()
    for key in (
        "CO_SCIENTIST_REPLAY_RESPONSES",
        "CO_SCIENTIST_REPLAY_PUBMED_SEARCH",
        "CO_SCIENTIST_REPLAY_PUBMED_SUMMARY",
    ):
        child_environment.pop(key, None)
    child_environment.update(environment or {})
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from co_scientist.cli.app import main; main()",
            *arguments,
        ],
        cwd=cwd,
        env=child_environment,
        capture_output=True,
        check=False,
        text=True,
    )


def _read_json(root: Path, filename: str) -> Any:
    return json.loads((root / filename).read_text(encoding="utf-8"))


def _bundle_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# Mutations caught: restoring the test-owned orchestration harness, directly seeding
# scientific state, or bypassing Supervisor-owned admission/stopping/finalization.
def test_lens_replay_smoke_contains_no_scientific_state_bypass() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden_calls = (
        "commit_" + "domain_batch(",
        "transition_" + "task(",
        "admit_" + "hypothesis(",
        "Convergence" + "Snapshot(",
        "apply_" + "finalization(",
    )

    assert all(call not in source for call in forbidden_calls)


# Mutations caught: using a test-only harness, requiring repository-root CWD or
# environment-injected results, losing cross-process state, exporting incomplete
# audit evidence, leaking a reusable lease/secret, or producing unstable bytes.
def test_lens_replay_cli_exports_a_deterministic_traceable_ranked_result(
    tmp_path: Path,
) -> None:
    operator_cwd = tmp_path / "researcher-cwd"
    operator_cwd.mkdir()
    data_dir = tmp_path / "data"
    first_export = tmp_path / "export-a"
    second_export = tmp_path / "export-b"
    secret = "task-8-must-never-be-exported"
    run_id = "lens-replay-smoke"

    executed = _invoke_cli(
        operator_cwd,
        "run",
        "execute",
        "--goal",
        str(GOAL),
        "--profile",
        str(PROFILE),
        "--provider",
        "replay",
        "--run-id",
        run_id,
        "--data-dir",
        str(data_dir),
        environment={"OPENAI_API_KEY": secret},
    )
    assert executed.returncode == 0, executed.stderr
    execution = json.loads(executed.stdout)
    assert execution["run_id"] == run_id
    assert execution["state"] == "completed"
    assert execution["stop_reason"] == "quality_converged"

    status = _invoke_cli(
        operator_cwd,
        "run",
        "status",
        execution["run_id"],
        "--data-dir",
        str(data_dir),
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout) == {
        "current_sequence": execution["last_sequence"],
        "run_id": execution["run_id"],
        "state": "completed",
    }

    for destination in (first_export, second_export):
        exported = _invoke_cli(
            operator_cwd,
            "run",
            "export",
            execution["run_id"],
            "--output",
            str(destination),
            "--data-dir",
            str(data_dir),
        )
        assert exported.returncode == 0, exported.stderr
        assert exported.stdout.strip() == f"output={destination}"

    assert _bundle_bytes(first_export) == _bundle_bytes(second_export)
    assert secret.encode() not in b"".join(_bundle_bytes(first_export).values())

    manifest = _read_json(first_export, "manifest.json")
    hypotheses = _read_json(first_export, "hypotheses.json")
    projections = _read_json(first_export, "hypothesis_projections.json")
    matches = _read_json(first_export, "matches.json")
    ratings = _read_json(first_export, "ratings.json")
    tasks = _read_json(first_export, "tasks.json")
    calls = _read_json(first_export, "external_calls.json")
    artifacts = _read_json(first_export, "artifacts.json")
    reservations = _read_json(first_export, "budget_reservations.json")
    checkpoints = _read_json(first_export, "convergence_checkpoints.json")
    stop_decisions = _read_json(first_export, "stop_decisions.json")

    assert manifest["execution_contract_version"] == 3
    assert manifest["final_state"] == "completed"
    assert manifest["state_history"][-2:] == ["stopping", "completed"]
    assert manifest["stop_reason"] == "quality_converged"
    assert manifest["completeness"] == "complete"
    assert manifest["finalization_state"] == "completed"
    assert manifest["goal"]["title"] == yaml.safe_load(GOAL.read_text())["title"]
    assert manifest["profile"]["profile_id"] == "core_preview"
    assert manifest["admission_policies"]["admission-v1"]
    candidate_admissions = {
        item["hypothesis_id"]: item["evidence"]
        for item in manifest["admission_evidence"]
        if item["hypothesis_id"] in {"h-1", "h-2"}
    }
    assert set(candidate_admissions) == {"h-1", "h-2"}
    assert all(
        evidence["content_hash"].startswith("sha256:")
        for evidence in candidate_admissions.values()
    )
    assert all(evidence["source_event_sequences"] for evidence in candidate_admissions.values())
    assert all(not evidence["missing_requirements"] for evidence in candidate_admissions.values())
    assert all(not evidence["conflicting_evidence"] for evidence in candidate_admissions.values())
    assert manifest["tournament_contract"]["epoch_id"] == "epoch-1"
    assert len(manifest["anchor_sets"][0]["members"]) == 2
    assert {item["kind"] for item in manifest["replay_resources"]} == {
        "llm_responses",
        "pubmed_search",
        "pubmed_summary",
    }
    assert all(item["sha256"].startswith("sha256:") for item in manifest["replay_resources"])
    assert manifest["budget_reservation_count"] == len(reservations)
    assert manifest["convergence_checkpoint_count"] == len(checkpoints)
    assert manifest["stop_decision_count"] == len(stop_decisions)
    assert manifest["final_stop_evidence"] == stop_decisions[-1]

    assert len(hypotheses) == len(projections) == 2
    assert all(item["lifecycle_state"] == "tournament_active" for item in projections)
    assert all(item["current_novelty_assessment_ids"] for item in projections)
    assert len(matches) == 6
    assert ratings["epoch-1"]
    assert manifest["ranking_state"]["epoch-1"]
    assert all(task["attempt"] <= task["max_attempts"] for task in tasks)
    assert all("lease_token" not in json.dumps(task) for task in tasks)
    assert any(task["lease_history"] for task in tasks)
    assert calls and all(call["state"] == "domain_result_applied" for call in calls)
    assert len(calls) == len(artifacts)
    assert {row["state"] for row in reservations} <= {"settled", "released"}
    literature_reservations = [
        row
        for row in reservations
        if ":literature:" in row["task_id"] and row["state"] == "settled"
    ]
    assert {row["task_id"].rsplit(":", 1)[-1] for row in literature_reservations} == {
        "search",
        "summary",
    }
    assert all(row["estimate"]["model_calls"] == 1 for row in literature_reservations)
    assert all(row["actual"]["model_calls"] == 1 for row in literature_reservations)
    assert checkpoints[-1]["stop_reason"] == "quality_converged"
    assert stop_decisions[-1]["finalization_state"] == "completed"

    resource = json.loads(
        (REPOSITORY_ROOT / "examples/lens_regeneration_replay/core_trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert {record["skill_id"] for record in resource["responses"]} == {
        "generation",
        "reflection",
        "ranking",
        "evolution",
        "proximity",
        "meta_review",
    }
