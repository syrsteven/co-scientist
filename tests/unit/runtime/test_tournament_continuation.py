import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.application.config import resolve_run_config
from co_scientist.domain.states import RunState
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


@pytest.mark.asyncio
async def test_nonconverged_tournament_resumes_until_budget_then_finalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    goal, profile_file, environment = write_core_preview_inputs(tmp_path, max_matches=4)
    profile = yaml.safe_load(profile_file.read_text())
    profile["scientific_context"] = True
    profile_file.write_text(yaml.safe_dump(profile))
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    calls: list[str] = []

    async def scripted(self: Any, request: dict[str, Any]) -> RawExternalResponse:
        skill, inputs = request["skill_id"], request["input"]
        candidates = [r for r in records if r["skill_id"] == skill]
        if skill == "reflection":
            candidates = [r for r in candidates if all(r["inputs"][key] == inputs[key]
                          for key in ("hypothesis_id", "review_stage"))]
        response = copy.deepcopy(candidates[0]["response"])
        for key in set(response) & set(inputs):
            response[key] = inputs[key]
        if skill == "proximity":
            # A single cluster must not be misreported as diversity convergence.
            response["cluster_suggestion"] = "one-cluster"
        if skill == "ranking":
            calls.append(inputs["match_id"])
        return RawExternalResponse(body=json.dumps(response).encode(), mime_type="application/json")

    monkeypatch.setattr(ReplayLLMProvider, "invoke", scripted)
    config = resolve_run_config(goal_file=goal, profile_file=profile_file,
                                provider="replay", environment=environment)
    manifest = config.model_dump(mode="json")["manifest"]
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    runner._compose(manifest)
    run_id = "bounded-tournament"
    runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
    # Stop this process at its first unsatisfied checkpoint, then restart.
    for _ in range(40):
        assert runner.worker is not None
        step = await runner.worker.run_once(run_id)
        if step.status == "idle":
            runner.supervisor.advance(run_id=run_id,
                expected_sequence=runner.uow.load(run_id)[-1].sequence)
        if any(e.event_type == "ConvergenceCheckpointRecorded" for e in runner.uow.load(run_id)):
            break
    else:
        pytest.fail("initial tournament did not checkpoint")
    assert len(calls) == 2
    restarted = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await restarted.resume(run_id=run_id)
    assert result.state is RunState.COMPLETED
    assert result.stop_reason == "hard_budget_reached"
    assert len(calls) == len(set(calls)) == 4
    events = restarted.uow.load(run_id)
    types = [event.event_type for event in events]
    assert types.index("RunStopping") < types.index("FinalizationCompleted") < types.index("RunCompleted")
    assert all(not event.payload["cluster_diversity_satisfied"] for event in events
               if event.event_type == "ConvergenceCheckpointRecorded")
    assert not restarted.uow.unresolved_task_ids(run_id)
    assert (await restarted.resume(run_id=run_id)).state is RunState.COMPLETED
    assert len(calls) == 4
