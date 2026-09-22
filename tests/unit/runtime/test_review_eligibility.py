import json
from pathlib import Path

import pytest

from co_scientist.application.config import resolve_run_config
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("blocking_case", ["reject", "critical_flaw", "not_novel", "safety"])
async def test_excluded_candidate_does_not_block_two_eligible_candidates(
    tmp_path: Path, blocking_case: str,
) -> None:
    goal, profile, environment = write_core_preview_inputs(tmp_path, hypothesis_count=3, max_hypotheses=5)
    replay_path = Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"])
    replay = json.loads(replay_path.read_text())
    for record in replay["responses"]:
        if record["skill_id"] != "reflection" or record["inputs"]["hypothesis_id"] != "h-3":
            continue
        response = record["response"]
        if response["stage"] == "full_review":
            if blocking_case == "reject":
                response["recommendation"] = "reject"
            elif blocking_case == "critical_flaw":
                response["critical_flaws"] = ["Fatal causal inconsistency"]
            elif blocking_case == "not_novel":
                response["novelty_assessment"]["verdict"] = "not_novel"
        elif blocking_case == "safety":
            response["safety_status"] = "blocked"
    replay_path.write_text(json.dumps(replay))
    config = resolve_run_config(goal_file=goal, profile_file=profile, provider="replay", environment=environment)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    manifest = config.model_dump(mode="json")["manifest"]
    runner._compose(manifest)
    run_id = "eligibility"
    runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
    assert runner.worker is not None
    for _ in range(20):
        step = await runner.worker.run_once(run_id)
        if step.status == "idle":
            break
    else:
        pytest.fail("review stage did not drain")
    events = runner.uow.load(run_id)
    outcome = runner.supervisor.advance(run_id=run_id, expected_sequence=events[-1].sequence)
    assert outcome.action == "scheduled"
    assert outcome.commit is not None
    scheduled = [event.payload["payload"]["inputs"] for event in outcome.commit.events if event.event_type == "TaskEnqueued"]
    assert len(scheduled) == 2
    assert all({item["left_id"], item["right_id"]} == {"h-1", "h-2"} for item in scheduled)
    assert any(event.event_type == "HypothesisContentCreated" and event.payload["hypothesis_id"] == "h-3" for event in events)
