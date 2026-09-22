import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.agents.payloads import EvolutionResultV1
from co_scientist.application.config import CoreProfile, resolve_run_config
from co_scientist.domain.states import RunState
from co_scientist.export.run_export import SqliteRunReadModel
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from co_scientist.runtime.task_payload import validate_result_task_binding
from tests.core_preview_support import write_core_preview_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("child_pass,crash,max_hypotheses", [
    (False, False, 6), (True, False, 6), (False, True, 6), (True, True, 6),
    (False, False, 3),
])
async def test_repair_reenters_review_and_admission_without_repeating_paid_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, child_pass: bool, crash: bool,
    max_hypotheses: int,
) -> None:
    goal, profile_file, environment = write_core_preview_inputs(
        tmp_path, max_hypotheses=max_hypotheses, max_model_calls=40,
    )
    profile = yaml.safe_load(profile_file.read_text())
    profile.update(scientific_context=True, evolution={"max_rounds": 1, "max_children_per_round": 2})
    profile_file.write_text(yaml.safe_dump(profile))
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    generation = records[0]["response"]
    evolution_calls = []

    async def scripted(self: Any, request: dict[str, Any], **kwargs: Any) -> RawExternalResponse:
        skill = request["skill_id"]
        inputs = json.loads(request["user_prompt"])["input"]
        if skill == "generation":
            response = generation
        elif skill == "evolution":
            evolution_calls.append(inputs)
            assert inputs["review_feedback"]
            assert inputs["research_plan_version"] == 1
            assert len(inputs["hypothesis_contents"]) == 2
            assert inputs["literature_evidence"]["source_documents"]
            children = copy.deepcopy(generation["hypotheses"])
            for index, child in enumerate(children, 1):
                child.update(hypothesis_id=f"child-{index}", content_id=f"cc-{index}",
                             parent_content_ids=[child["content_id"]],
                             claim=f"Revised causal mechanism {index}")
            response = {"schema_version": 1, "research_plan_version": 1,
                        "children": children,
                        "change_rationales": {child["hypothesis_id"]: "Add causal contrast" for child in children}}
        elif skill == "reflection":
            response = copy.deepcopy(next(record["response"] for record in records
                if record["skill_id"] == skill and record["inputs"]["review_stage"] == inputs["review_stage"]))
            key = inputs["hypothesis_id"]
            response.update(hypothesis_id=key, content_hash=inputs["content_hash"],
                            review_id=f"review-{key}-{inputs['review_stage']}")
            if inputs["review_stage"] == "full_review":
                response["novelty_assessment"].update(hypothesis_id=key,
                    content_hash=inputs["content_hash"], assessment_id=f"novelty-{key}")
                response["critical_flaws"] = [] if child_pass and key.startswith("child-") else ["Causal ambiguity"]
        elif skill == "proximity":
            response = copy.deepcopy(next(record["response"] for record in records if record["skill_id"] == skill))
            for field in ("edge_id", "left_id", "right_id", "left_content_hash", "right_content_hash"):
                response[field] = inputs[field]
            response["cluster_suggestion"] = inputs["left_id"]
        else:
            raise AssertionError(f"unexpected skill {skill}")
        return RawExternalResponse(body=json.dumps(response).encode(), mime_type="application/json")

    monkeypatch.setattr(ReplayLLMProvider, "invoke", scripted)
    config = resolve_run_config(goal_file=goal, profile_file=profile_file,
                                provider="replay", environment=environment)
    manifest = config.model_dump(mode="json")["manifest"]
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    runner._compose(manifest)
    run_id = "repair"
    runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
    original_handle = runner.supervisor.handle_result

    def handle(*args: Any, **kwargs: Any) -> Any:
        if crash and args[2].skill_id == "evolution":
            raise RuntimeError("crash after evolution submission")
        return original_handle(*args, **kwargs)

    monkeypatch.setattr(runner.supervisor, "handle_result", handle)
    crashed = False
    for _ in range(50):
        assert runner.worker is not None
        try:
            step = await runner.worker.run_once(run_id)
        except RuntimeError as error:
            assert str(error) == "crash after evolution submission" and not crashed
            crashed = True
            runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
            runner._compose(manifest)
            continue
        if step.status != "idle":
            continue
        events = runner.uow.load(run_id)
        outcome = runner.supervisor.advance(run_id=run_id, expected_sequence=events[-1].sequence)
        admitted_children = [event for event in runner.uow.load(run_id)
                             if event.event_type == "TournamentEntryCreated"
                             and str(event.payload["hypothesis_id"]).startswith("child-")]
        if len(admitted_children) == 2 or runner.uow.run_state(run_id) == "needs_attention":
            break
        if outcome.action == "admitted":
            continue
        assert outcome.action == "scheduled"
        # Repeated scheduler ticks while work is pending cannot enqueue another round.
        assert runner.supervisor.advance(run_id=run_id,
            expected_sequence=runner.uow.load(run_id)[-1].sequence).action == "waiting"
    else:
        pytest.fail("repair did not finish bounded re-review")
    if max_hypotheses == 3:
        assert not evolution_calls
        assert runner.uow.run_state(run_id) == "needs_attention"
        return
    assert len(evolution_calls) == 1
    assert crashed == crash
    events = runner.uow.load(run_id)
    contents = [event for event in events if event.event_type == "HypothesisContentCreated"]
    assert {event.payload["hypothesis_id"] for event in contents} >= {"h-1", "h-2", "child-1", "child-2"}
    reviews = [event for event in events if event.event_type == "ReviewCompleted"
               and str(event.payload["hypothesis_id"]).startswith("child-")]
    assert len(reviews) == 4
    assert all(event.payload["parent_content_ids"] for event in contents
               if str(event.payload["hypothesis_id"]).startswith("child-"))
    calls = SqliteRunReadModel(runner.uow).external_calls(run_id)
    assert all(call["raw_artifact_ref"] and call["state"] == "domain_result_applied" for call in calls)
    assert sum(str(call["provider"]).endswith(":summary") for call in calls) == 1
    if child_pass:
        assert outcome.action == "admitted"
        admitted = [event for event in events if event.event_type == "TournamentEntryCreated"]
        assert {event.payload["hypothesis_id"] for event in admitted} == {"child-1", "child-2"}
        assert all(event.payload["rating"] == 1200 for event in events
                   if event.event_type == "InitialRatingAssigned")
    else:
        assert runner.uow.run_state(run_id) == RunState.NEEDS_ATTENTION.value
        assert not any(event.event_type == "ProximityAssessed"
                       and str(event.payload.get("left_id", "")).startswith("child-")
                       for event in events)


@pytest.mark.parametrize("mutation", ["parent", "reuse_hypothesis", "reuse_content", "count", "duplicate_content", "plan_version"])
def test_evolution_rejects_invalid_lineage_identity_or_size(tmp_path: Path, mutation: str) -> None:
    _, _, environment = write_core_preview_inputs(tmp_path)
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    child = copy.deepcopy(records[0]["response"]["hypotheses"][0])
    child.update(hypothesis_id="child", content_id="new-content", parent_content_ids=["c-1"])
    inputs = {"source_content_ids": ["c-1"], "max_children": 1,
              "existing_hypothesis_ids": ["h-1"], "existing_content_ids": ["c-1"]}
    children = [child]
    if mutation == "parent":
        child["parent_content_ids"] = []
    elif mutation == "reuse_hypothesis":
        child["hypothesis_id"] = "h-1"
    elif mutation == "reuse_content":
        child["content_id"] = "c-1"
    elif mutation == "plan_version":
        child["research_plan_version"] = 2
    else:
        children.append({**child, "hypothesis_id": "child-2",
                         "content_id": "new-content" if mutation == "duplicate_content" else "new-2"})
        if mutation == "duplicate_content":
            inputs["max_children"] = 2
    result = EvolutionResultV1.model_validate({"schema_version": 1,
        "research_plan_version": 2 if mutation == "plan_version" else 1,
        "children": children, "change_rationales": {c["hypothesis_id"]: "revision" for c in children}})
    with pytest.raises(ValueError, match="typed result does not match"):
        validate_result_task_binding(task_inputs=inputs, task_research_plan_version=1,
                                     provider_id="replay", result=result)


@pytest.mark.parametrize("evolution", [{"max_rounds": -1}, {"max_rounds": True}, {"max_children_per_round": 0}])
def test_invalid_evolution_limits(evolution: dict[str, Any]) -> None:
    document = yaml.safe_load(Path("configs/profiles/core_preview_deepseek.yaml").read_text())
    document["evolution"] = evolution
    with pytest.raises(ValueError):
        CoreProfile.model_validate(document)
