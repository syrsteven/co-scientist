from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOAL = REPOSITORY_ROOT / "examples/lens_regeneration_goal.yaml"
PROFILE = REPOSITORY_ROOT / "configs/profiles/core_preview_online.yaml"


def _online_enabled() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        and os.getenv("CO_SCIENTIST_OPENAI_MODEL")
        and os.getenv("CO_SCIENTIST_NETWORK_ONLINE") == "1"
    )


def _invoke_cli(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key in (
        "CO_SCIENTIST_REPLAY_RESPONSES",
        "CO_SCIENTIST_REPLAY_PUBMED_SEARCH",
        "CO_SCIENTIST_REPLAY_PUBMED_SUMMARY",
    ):
        environment.pop(key, None)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from co_scientist.cli.app import main; main()",
            *arguments,
        ],
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=1800,
    )


def _read_json(root: Path, filename: str) -> Any:
    return json.loads((root / filename).read_text(encoding="utf-8"))


@pytest.mark.online
def test_lens_smoke_with_openai_and_pubmed_uses_the_production_cli(
    tmp_path: Path,
) -> None:
    if not _online_enabled():
        pytest.skip(
            "requires OPENAI_API_KEY, CO_SCIENTIST_OPENAI_MODEL, and "
            "CO_SCIENTIST_NETWORK_ONLINE=1"
        )

    operator_cwd = tmp_path / "researcher-cwd"
    operator_cwd.mkdir()
    data_dir = tmp_path / "data"
    destination = tmp_path / "export"
    run_id = "lens-online-smoke"

    executed = _invoke_cli(
        operator_cwd,
        "run",
        "execute",
        "--goal",
        str(GOAL),
        "--profile",
        str(PROFILE),
        "--provider",
        "openai",
        "--run-id",
        run_id,
        "--data-dir",
        str(data_dir),
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

    manifest = _read_json(destination, "manifest.json")
    calls = _read_json(destination, "external_calls.json")
    costs = _read_json(destination, "costs.json")
    artifacts = _read_json(destination, "artifacts.json")
    reservations = _read_json(destination, "budget_reservations.json")
    checkpoints = _read_json(destination, "convergence_checkpoints.json")
    stop_decisions = _read_json(destination, "stop_decisions.json")

    assert manifest["final_state"] == "completed"
    assert manifest["finalization_state"] == "completed"
    assert manifest["stop_reason"] == "quality_converged"
    assert manifest["profile"]["profile_id"] == "core_preview_online"
    assert manifest["providers"] == {"literature": "pubmed", "llm": "openai"}
    assert manifest["provider_configuration"]["model"] == os.environ[
        "CO_SCIENTIST_OPENAI_MODEL"
    ]

    configured_model = os.environ["CO_SCIENTIST_OPENAI_MODEL"]
    assert {call["provider"] for call in calls} == {
        "openai",
        "pubmed:search",
        "pubmed:summary",
    }
    assert {
        call["model_or_tool"] for call in calls if call["provider"] == "openai"
    } == {configured_model}
    assert {
        call["model_or_tool"]
        for call in calls
        if call["provider"] in {"pubmed:search", "pubmed:summary"}
    } == {"esearch", "esummary"}
    assert all(call["provider_response_id"] for call in calls)
    assert all(call["state"] == "domain_result_applied" for call in calls)
    assert all(call["raw_artifact_ref"] for call in calls)
    assert all(call["agent_result"] for call in calls)
    assert all(call["execution_context"]["output_schema_id"] for call in calls)

    call_by_id = {call["external_call_id"]: call for call in calls}
    call_ids = set(call_by_id)
    assert {cost["external_call_id"] for cost in costs} == call_ids
    assert len(costs) == len(calls)
    assert sum(
        int(cost["input_tokens"] or 0)
        for cost in costs
        if call_by_id[cost["external_call_id"]]["provider"] == "openai"
    ) > 0
    assert sum(
        int(cost["output_tokens"] or 0)
        for cost in costs
        if call_by_id[cost["external_call_id"]]["provider"] == "openai"
    ) > 0
    assert {artifact["external_call_id"] for artifact in artifacts} == call_ids
    assert all(artifact["raw_manifest"]["provider_response_id"] for artifact in artifacts)
    assert {
        reservation["external_call_id"]
        for reservation in reservations
        if reservation["state"] == "settled"
    } == call_ids
    assert checkpoints[-1]["stop_reason"] == "quality_converged"
    assert stop_decisions[-1]["finalization_state"] == "completed"
