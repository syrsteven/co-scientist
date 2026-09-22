import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.application.config import CoreProfile, resolve_run_config
from co_scientist.domain.research_feedback import latest_research_feedback
from co_scientist.events.models import NewEvent
from co_scientist.export.run_export import SqliteRunReadModel, verify_core_release_invariants
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from tests.core_preview_support import write_core_preview_inputs


def setup_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, safety="clear", calls=80, rounds=2,
               capacity=False, feedback_version="meta-review-loop-v1"):
    goal, profile_file, environment = write_core_preview_inputs(
        tmp_path, max_model_calls=calls, max_hypotheses=9, max_matches=14,
    )
    profile = yaml.safe_load(profile_file.read_text())
    if capacity:
        profile["budget"].update(hypothesis_limit_policy="capacity-v2", max_hypotheses=4)
    profile.update(scientific_context=True, research_protocol_version="research-v1",
                   evolution={"max_rounds": 3, "max_children_per_round": 1},
                   meta_review={"max_rounds": rounds, "match_interval": 2, "max_children_per_round": 1})
    profile["meta_review"]["contract_version"] = feedback_version
    profile_file.write_text(yaml.safe_dump(profile))
    config = resolve_run_config(goal_file=goal, profile_file=profile_file, provider="replay", environment=environment)
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    observed: list[tuple[str, dict[str, Any]]] = []

    async def scripted(self, request):
        role, inputs = request["skill_id"], request["input"]
        observed.append((role, copy.deepcopy(inputs)))
        if role == "meta_review":
            response = {
                "schema_version": 1, "research_plan_version": 1,
                "source_content_hashes": inputs["source_content_hashes"],
                "system_feedback": [f"Round {inputs['meta_review_round']}: distinguish early causal timing"],
                "overview": "Offline meta-review fixture", "coverage_gaps": ["No wet-lab validation"],
                "safety_direction_check": safety,
            }
        elif role == "evolution":
            parent = next(iter(inputs["hypothesis_contents"].values()))
            child = copy.deepcopy(records[0]["response"]["hypotheses"][0])
            number = inputs["evolution_round"]
            child.update(hypothesis_id=f"child-{number}", content_id=f"child-content-{number}",
                         claim=f"Mechanistically distinct timing mechanism {number}",
                         parent_content_ids=[parent["content_id"]])
            response = {"schema_version": 1, "research_plan_version": 1, "children": [child],
                        "change_rationales": {child["hypothesis_id"]: inputs["research_feedback"]["system_feedback"][0]}}
        else:
            candidates = [r for r in records if r["skill_id"] == role]
            if role == "reflection":
                candidates = [r for r in candidates if r["inputs"]["review_stage"] == inputs["review_stage"]]
            response = copy.deepcopy(candidates[0]["response"])
            response.update({key: inputs[key] for key in set(inputs) & set(response)})
            if role == "reflection":
                key = inputs["hypothesis_id"]
                response["review_id"] = f"{key}:{inputs['review_stage']}"
                if response.get("novelty_assessment"):
                    response["novelty_assessment"].update(hypothesis_id=key, content_hash=inputs["content_hash"], assessment_id=f"novelty:{key}")
            elif role == "proximity":
                response["cluster_suggestion"] = "one-cluster"
            elif role == "ranking":
                response["dimension_reasons"] = {key: "Fixture comparison" for key in inputs["evaluation_rubric"]["dimensions"]}
        return RawExternalResponse(body=json.dumps(response).encode(), mime_type="application/json")

    monkeypatch.setattr(ReplayLLMProvider, "invoke", scripted)
    return config, environment, observed


@pytest.mark.asyncio
@pytest.mark.parametrize("crash", [False, True])
@pytest.mark.parametrize("capacity", [False, True])
async def test_default_runner_two_feedback_cycles_with_child_reentry_and_resume(tmp_path, monkeypatch, crash, capacity):
    config, environment, observed = setup_loop(tmp_path, monkeypatch, capacity=capacity)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    run_id = "auto-feedback"
    if crash:
        manifest = config.model_dump(mode="json")["manifest"]
        runner._compose(manifest)
        runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
        handle = runner.supervisor.handle_result

        def crash_on_meta(*args, **kwargs):
            if args[2].skill_id == "meta_review" and args[2].provider == "replay":
                raise RuntimeError("crash after meta result submitted")
            return handle(*args, **kwargs)

        monkeypatch.setattr(runner.supervisor, "handle_result", crash_on_meta)
        with pytest.raises(RuntimeError, match="crash after meta"):
            await runner.drive(run_id=run_id)
        await runner.aclose()
        runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
        result = await runner.resume(run_id=run_id)
    else:
        result = await runner.execute(config=config, run_id=run_id)
    assert str(result.state) == "completed"
    assert result.stop_reason == "hard_budget_reached"
    metas = [inputs for role, inputs in observed if role == "meta_review"]
    evolutions = [inputs for role, inputs in observed if role == "evolution"]
    assert [m["meta_review_round"] for m in metas] == [1, 2]
    assert len(evolutions) == 2
    if capacity:
        frozen = runner.uow.run_manifest(run_id)
        assert frozen["budget"]["hypothesis_limit_policy"] == "capacity-v2"
        assert runner.uow.load_budget_snapshot(run_id).settled.hypotheses == 4
    assert [e["research_feedback"]["feedback_version"] for e in evolutions] == [1, 2]
    assert metas[1]["research_feedback"]["feedback_version"] == 1
    events = runner.uow.load(run_id)
    feedback = [e for e in events if e.event_type == "ResearchFeedbackRecorded"]
    assert len(feedback) == 2
    assert all(e.payload["source_match_ids"] and e.payload["source_content_hashes"] for e in feedback)
    for child in ("child-1", "child-2"):
        stages = {e.payload["stage"] for e in events if e.event_type == "ReviewCompleted" and e.payload["hypothesis_id"] == child}
        assert stages == {"initial_review", "full_review"}
        admission = next(e for e in events if e.event_type == "TournamentEntryCreated" and e.payload["hypothesis_id"] == child)
        match = next(e for e in events if e.event_type == "MatchEvaluated" and child in {e.payload["left_id"], e.payload["right_id"]})
        assert admission.sequence < match.sequence
        assert any(inputs.get("hypothesis_id") == child and inputs.get("research_feedback") for role, inputs in observed if role == "reflection")
    edges = [e.payload for e in events if e.event_type == "ProximityAssessed"]
    assert len({e["edge_id"] for e in edges}) == len(edges)
    assert any(inputs.get("research_feedback") for role, inputs in observed if role == "ranking")
    read_model = SqliteRunReadModel(runner.uow)
    assert verify_core_release_invariants(run_id, read_model).violation_count == 0
    assert all(c["state"] == "domain_result_applied" for c in read_model.external_calls(run_id))
    for event in events:
        if event.event_type == "ConvergenceCheckpointRecorded":
            earlier_entries = [e.sequence for e in events if e.sequence < event.sequence
                               and e.event_type == "TournamentEntryCreated"]
            assert all(seq > max(earlier_entries) for seq in event.payload["top_k_window_sequences"])
    corrupted = {**dict(feedback[-1].payload), "overview": "tampered"}
    with pytest.raises(ValueError, match="feedback hash mismatch"):
        latest_research_feedback(runner.uow.run_manifest(run_id),
                                 [NewEvent(event_type="ResearchFeedbackRecorded", payload=corrupted)])
    count = len(observed)
    assert str((await runner.resume(run_id=run_id)).state) == "completed"
    assert len(observed) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("safety", ["concern", "insufficient_evidence"])
@pytest.mark.parametrize("feedback_version", ["meta-review-loop-v1", "meta-review-loop-v2"])
async def test_meta_safety_requires_scientist_not_automatic_repair(tmp_path, monkeypatch, safety, feedback_version):
    config, environment, observed = setup_loop(tmp_path, monkeypatch, safety=safety,
                                              feedback_version=feedback_version)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await runner.execute(config=config, run_id="safety")
    assert str(result.state) == "needs_attention"
    assert result.stop_reason == "meta_review_requires_scientist_input"
    assert not any(role == "evolution" for role, _ in observed)
    assert len([role for role, _ in observed if role == "meta_review"]) == 1
    inputs = next(inputs for role, inputs in observed if role == "meta_review")
    if feedback_version == "meta-review-loop-v2":
        context = inputs["supervisor_review_context"]
        assert context["safety_gate_stage"] == "initial_review"
        for key, candidate in context["candidates"].items():
            assert candidate["content_hash"] == inputs["source_content_hashes"][key]
            assert candidate["admitted_in_current_epoch"]
            assert any(r["stage"] == "initial_review" and r["safety_status"] == "passed"
                       for r in candidate["safety_review_records"])
        from co_scientist.supervisor.scientific_context import research_inputs

        key = next(iter(context["candidates"]))
        events = [e for e in runner.uow.load("safety")
                  if not (e.event_type == "TournamentEntryCreated"
                          and e.payload.get("hypothesis_id") == key)]
        events.append(NewEvent(event_type="ReviewCompleted", payload={
            "hypothesis_id": key, "content_hash": "sha256:stale", "research_plan_version": 1,
            "stage": "initial_review", "safety_status": "blocked"}))
        rebuilt = research_inputs(runner.uow.run_manifest("safety"), events, inputs,
                                  skill_id="meta_review")["supervisor_review_context"]["candidates"][key]
        assert not rebuilt["admitted_in_current_epoch"]
        assert rebuilt["safety_review_records"] == context["candidates"][key]["safety_review_records"]
    else:
        assert "supervisor_review_context" not in inputs


def test_feedback_v2_freezes_distinct_epoch_without_changing_legacy(tmp_path, monkeypatch):
    from co_scientist.domain.research_feedback import feedback_contract_v1

    old, _, _ = setup_loop(tmp_path, monkeypatch)
    new, _, _ = setup_loop(tmp_path, monkeypatch, feedback_version="meta-review-loop-v2")
    before = old.model_dump(mode="json")["manifest"]
    after = new.model_dump(mode="json")["manifest"]
    assert "contract_version" not in before["profile"]["meta_review"]
    assert before["feedback_contract"] == feedback_contract_v1()
    assert after["feedback_contract"]["version"] == "meta-review-loop-v2"
    assert before["tournament_contract"]["evaluation_rules_hash"] != after["tournament_contract"]["evaluation_rules_hash"]


@pytest.mark.asyncio
async def test_loop_respects_tight_call_budget_and_zero_rounds(tmp_path, monkeypatch):
    config, environment, observed = setup_loop(tmp_path, monkeypatch, calls=12, rounds=0)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await runner.execute(config=config, run_id="no-feedback")
    assert str(result.state) == "completed"
    assert not any(role in {"evolution", "meta_review"} for role, _ in observed)


@pytest.mark.asyncio
async def test_enabled_loop_cannot_exceed_call_budget(tmp_path, monkeypatch):
    config, environment, observed = setup_loop(tmp_path, monkeypatch, calls=12)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    result = await runner.execute(config=config, run_id="tight-budget")
    assert str(result.state) in {"completed", "completed_partial"}
    assert result.stop_reason == "hard_budget_reached"
    assert runner.uow.load_budget_snapshot("tight-budget").total_usage.model_calls <= 12
    assert not any(role == "evolution" for role, _ in observed)


@pytest.mark.asyncio
async def test_pause_then_scientist_stop_prevents_feedback_evolution(tmp_path, monkeypatch):
    config, environment, observed = setup_loop(tmp_path, monkeypatch)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    manifest = config.model_dump(mode="json")["manifest"]
    runner._compose(manifest)
    run_id = "stop-feedback"
    runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
    try:
        for _ in range(60):
            step = await runner.worker.run_once(run_id)
            events = runner.uow.load(run_id)
            if any(e.event_type == "ResearchFeedbackRecorded" for e in events):
                break
            if step.status == "idle":
                runner.supervisor.advance(run_id=run_id, expected_sequence=events[-1].sequence)
        else:
            pytest.fail("no automatic feedback")
        count = len(observed)
        runner.supervisor.pause_run(run_id, expected_sequence=events[-1].sequence)
        assert runner.supervisor.advance(run_id=run_id, expected_sequence=runner.uow.load(run_id)[-1].sequence).action == "waiting"
        assert str((await runner.drive(run_id=run_id)).state) == "paused"
        runner.supervisor.request_soft_stop(run_id, expected_sequence=runner.uow.load(run_id)[-1].sequence)
        assert str((await runner.drive(run_id=run_id)).state) == "completed"
        assert len(observed) == count
        assert not any(role == "evolution" for role, _ in observed)
    finally:
        await runner.aclose()


@pytest.mark.parametrize("change", ["legacy", "no_evolution", "unbounded_calls", "unbounded_matches"])
def test_loop_configuration_dependencies(tmp_path, monkeypatch, change):
    config, _, _ = setup_loop(tmp_path, monkeypatch)
    profile = config.profile.model_dump(mode="json")
    if change == "legacy":
        profile["research_protocol_version"] = None
    elif change == "no_evolution":
        profile["evolution"]["max_rounds"] = 0
    else:
        profile["budget"]["max_model_calls" if change == "unbounded_calls" else "max_matches"] = None
    with pytest.raises(ValueError, match="meta_review requires"):
        CoreProfile.model_validate(profile)


def test_feedback_hash_tampering_and_literature_exclusion(tmp_path, monkeypatch):
    config, _, _ = setup_loop(tmp_path, monkeypatch)
    manifest = config.model_dump(mode="json")["manifest"]
    assert latest_research_feedback(manifest, [NewEvent(event_type="MetaReviewCompleted", payload={"literature_operation": "summary"})]) is None
    manifest["feedback_contract"]["context_instruction"] = "changed"
    with pytest.raises(ValueError, match="contract mismatch"):
        latest_research_feedback(manifest, [])
