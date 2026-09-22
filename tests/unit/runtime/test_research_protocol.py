import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from co_scientist.adapters.llm.replay import ReplayLLMProvider
from co_scientist.agents.executor import build_skill_request
from co_scientist.agents.payloads import GenerationResultV1, RankingResultV1
from co_scientist.application.config import CoreProfile, resolve_run_config
from co_scientist.domain.research_protocol import protocol_hash, research_protocol_v1
from co_scientist.events.models import NewEvent
from co_scientist.export.run_export import SqliteRunReadModel, verify_core_release_invariants
from co_scientist.ports.external_provider import RawExternalResponse
from co_scientist.runtime.core_runner import CoreRunner
from co_scientist.runtime.task_payload import validate_result_task_binding
from co_scientist.skills.loader import core_skill_directory
from co_scientist.supervisor.scientific_context import research_inputs
from tests.core_preview_support import write_core_preview_inputs
from tests.live_full_workflow import schedule_exercise

ROOT = Path(__file__).resolve().parents[3]


def resolved(tmp_path: Path, *, protocol: bool = True):
    goal, profile_file, environment = write_core_preview_inputs(
        tmp_path, max_model_calls=50, max_hypotheses=8, max_matches=4,
    )
    profile = yaml.safe_load(profile_file.read_text())
    if protocol:
        profile.update(scientific_context=True, research_protocol_version="research-v1")
        profile_file.write_text(yaml.safe_dump(profile))
    config = resolve_run_config(goal_file=goal, profile_file=profile_file,
                                provider="replay", environment=environment)
    return config, environment


@pytest.mark.parametrize("provider,profile_file,key", [
    ("openai", "online", "OPENAI_API_KEY"), ("deepseek", "deepseek", "DEEPSEEK_API_KEY"),
    ("qwen", "qwen", "DASHSCOPE_API_KEY"), ("gemini", "gemini", "GEMINI_API_KEY"),
    ("claude", "claude", "ANTHROPIC_API_KEY"),
])
def test_five_real_templates_freeze_scientific_protocol(provider, profile_file, key):
    config = resolve_run_config(
        goal_file=ROOT / "examples/lens_regeneration_goal.yaml",
        profile_file=ROOT / f"configs/profiles/core_preview_{profile_file}.yaml",
        provider=provider, environment={key: "offline-placeholder", f"CO_SCIENTIST_{provider.upper()}_MODEL": "test-model"},
    )
    manifest = config.model_dump(mode="json")["manifest"]
    assert config.profile.scientific_context
    assert config.profile.literature_content == "abstracts"
    assert manifest["research_protocol"] == research_protocol_v1()
    assert "offline-placeholder" not in json.dumps(manifest)
    generated = research_inputs(manifest, (), {}, skill_id="generation")
    assert generated["research_goal"] == manifest["goal"]
    assert "earliest" in generated["scientific_protocol"]["role_instructions"]
    request = build_skill_request(skill_directory=core_skill_directory("generation"),
                                  inputs=generated, model="test-model")
    assert json.loads(request["user_prompt"])["input"] == generated
    events, pair = anchor_input(manifest)
    references = {
        "generation": {},
        "reflection": {"hypothesis_id": pair["left_id"], "content_hash": pair["left_content_hash"], "review_stage": "initial_review"},
        "proximity": pair, "ranking": pair,
        "evolution": {"source_content_ids": [events[0].payload["content_id"]]},
        "meta_review": {"source_content_hashes": {pair["left_id"]: pair["left_content_hash"]}},
    }
    for role, inputs in references.items():
        enriched = research_inputs(manifest, events, inputs, skill_id=role)
        rendered = build_skill_request(skill_directory=core_skill_directory(role), inputs=enriched, model="test-model")
        assert json.loads(rendered["user_prompt"])["input"]["research_goal"] == manifest["goal"]
        if role != "generation":
            assert enriched["hypothesis_contents"]


def test_protocol_requires_context_and_research_mode(tmp_path):
    config, _ = resolved(tmp_path)
    profile = config.profile.model_dump(mode="json")
    profile["scientific_context"] = False
    with pytest.raises(ValueError, match="requires scientific_context"):
        CoreProfile.model_validate(profile)
    profile["scientific_context"] = True
    profile["tournament"]["match_mode"] = "paper_faithful_binary"
    with pytest.raises(ValueError, match="binary benchmark"):
        CoreProfile.model_validate(profile)


@pytest.mark.parametrize("protocol", [False, True])
def test_empty_scientific_body_rejected_before_domain_apply_only_for_new_protocol(tmp_path, protocol):
    _, environment = resolved(tmp_path, protocol=protocol)
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    payload = copy.deepcopy(records[0]["response"])
    payload["hypotheses"][0]["falsifiers"] = []
    result = GenerationResultV1.model_validate(payload)
    arguments = {"result": result, "task_inputs": {"scientific_protocol": {"version": "research-v1"}} if protocol else {},
                 "task_research_plan_version": 1, "provider_id": "replay"}
    if protocol:
        with pytest.raises(ValueError, match="scientific_content_completeness"):
            validate_result_task_binding(**arguments)
    else:
        validate_result_task_binding(**arguments)


def test_protocol_changes_epoch_rules_but_leaves_legacy_system_prompt(tmp_path):
    legacy, _ = resolved(tmp_path, protocol=False)
    new, _ = resolved(tmp_path)
    old_manifest = legacy.model_dump(mode="json")["manifest"]
    new_manifest = new.model_dump(mode="json")["manifest"]
    assert "research_protocol_version" not in old_manifest["profile"]
    assert "research_protocol" not in old_manifest
    old, new_contract = old_manifest["tournament_contract"], new_manifest["tournament_contract"]
    assert old["ranking_prompt_hash"] == new_contract["ranking_prompt_hash"]
    assert old["evaluation_rules_hash"] != new_contract["evaluation_rules_hash"]
    assert old["judge_profile_hash"] != new_contract["judge_profile_hash"]
    assert old["evaluation_rules_hash"] == protocol_hash({
        "evaluation_rules_id": legacy.profile.tournament.evaluation_rules_id,
        "match_mode": legacy.profile.tournament.match_mode,
    })


def anchor_input(manifest):
    members = manifest["anchor_sets"][0]["members"]
    events = []
    for member in members:
        events.append(NewEvent(event_type="HypothesisContentCreated", payload={
            **member["content"], "hypothesis_id": member["anchor_id"], "research_plan_version": 1,
        }))
        events.extend(NewEvent(event_type="ReviewCompleted", payload=review)
                      for review in member["evidence"]["reviews"])
        events.append(NewEvent(event_type="NoveltyAssessmentRecorded", payload=member["evidence"]["novelty_assessment"]))
    inputs = {**manifest["tournament_contract"], "match_id": "test-match",
              "left_id": members[0]["anchor_id"], "left_content_hash": members[0]["content_hash"],
              "right_id": members[1]["anchor_id"], "right_content_hash": members[1]["content_hash"]}
    return events, inputs


@pytest.mark.parametrize("fault", [
    "bundle", "rules", "missing_goal", "empty_chain", "missing_content", "changed_body", "wrong_hash",
    "wrong_plan", "task_plan", "missing_review", "stale_review", "missing_novelty", "epoch",
])
def test_invalid_scientific_snapshots_fail_before_request(tmp_path, fault):
    config, _ = resolved(tmp_path)
    manifest = config.model_dump(mode="json")["manifest"]
    events, inputs = anchor_input(manifest)
    if fault == "bundle":
        manifest["research_protocol"]["common_instructions"] = "changed"
    elif fault == "rules":
        manifest["tournament_contract"]["evaluation_rules_hash"] = "bad"
    elif fault == "missing_goal":
        manifest["goal"].pop("goal")
    elif fault == "empty_chain":
        manifest["goal"]["required_causal_chain"] = []
    elif fault == "missing_content":
        events = events[1:]
    elif fault in {"changed_body", "wrong_plan"}:
        payload = dict(events[0].payload)
        payload["claim" if fault == "changed_body" else "research_plan_version"] = "changed" if fault == "changed_body" else 2
        events[0] = NewEvent(event_type="HypothesisContentCreated", payload=payload)
    elif fault == "wrong_hash":
        inputs["left_content_hash"] = "bad"
    elif fault == "task_plan":
        inputs["research_plan_version"] = 2
    elif fault == "missing_review":
        events = [e for e in events if e.event_type != "ReviewCompleted"]
    elif fault == "stale_review":
        events = [NewEvent(event_type=e.event_type, payload={**dict(e.payload), "content_hash": "stale"})
                  if e.event_type == "ReviewCompleted" else e for e in events]
    elif fault == "missing_novelty":
        events = [e for e in events if e.event_type != "NoveltyAssessmentRecorded"]
    else:
        inputs["epoch_id"] = "other-epoch"
    with pytest.raises(ValueError):
        research_inputs(manifest, events, inputs, skill_id="ranking")


def test_anchor_evidence_is_labelled_and_not_numeric_votes(tmp_path):
    config, _ = resolved(tmp_path)
    manifest = config.model_dump(mode="json")["manifest"]
    events, inputs = anchor_input(manifest)
    result = research_inputs(manifest, events, inputs, skill_id="ranking")
    assert len(result["evaluation_rubric"]["dimensions"]) == 6
    for evidence in result["review_context"].values():
        assert evidence["evidence_origin"] == "curated_benchmark_not_empirical_validation"
        assert evidence["source_documents"][0]["evidence_kind"] == "curated_benchmark_definition"
        assert all("dimension_scores" not in review for review in evidence["reviews"])
        assert not evidence["unavailable_source_ids"]


@pytest.mark.asyncio
async def test_six_role_offline_workflow_and_frozen_resume(tmp_path, monkeypatch):
    config, environment = resolved(tmp_path)
    manifest = config.model_dump(mode="json")["manifest"]
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    observed: dict[str, list] = {}

    async def scripted(self: Any, request: dict[str, Any]) -> RawExternalResponse:
        skill, inputs = request["skill_id"], request["input"]
        observed.setdefault(skill, []).append(copy.deepcopy(inputs))
        assert inputs["research_goal"] == manifest["goal"]
        assert inputs["scientific_protocol"]["role_instructions"] == manifest["research_protocol"]["roles"][skill]
        assert inputs["research_plan_version"] == 1
        assert json.loads(request["user_prompt"])["input"] == inputs
        if skill == "evolution":
            children = copy.deepcopy(records[0]["response"]["hypotheses"])
            for index, child in enumerate(children, 1):
                child.update(hypothesis_id=f"child-{index}", content_id=f"cc-{index}",
                             parent_content_ids=[child["content_id"]], claim=f"Revised causal mechanism {index}")
            response = {"schema_version": 1, "research_plan_version": 1, "children": children,
                        "change_rationales": {c["hypothesis_id"]: "Distinguish a timing contrast" for c in children}}
        elif skill == "meta_review":
            response = {"schema_version": 1, "research_plan_version": 1,
                        "source_content_hashes": inputs["source_content_hashes"],
                        "system_feedback": ["Compare early interventions"], "overview": "Offline fixture synthesis",
                        "coverage_gaps": ["No actual experimental validation"], "safety_direction_check": "clear"}
        else:
            candidates = [r for r in records if r["skill_id"] == skill]
            if skill == "reflection":
                candidates = [r for r in candidates if r["inputs"]["review_stage"] == inputs["review_stage"]]
            response = copy.deepcopy(candidates[0]["response"])
            for key in set(response) & set(inputs):
                response[key] = inputs[key]
            if skill == "reflection":
                key = inputs["hypothesis_id"]
                response["review_id"] = f"{key}-{inputs['review_stage']}"
                if response.get("novelty_assessment"):
                    response["novelty_assessment"].update(hypothesis_id=key, content_hash=inputs["content_hash"], assessment_id=f"novelty-{key}")
            if skill == "proximity":
                response["cluster_suggestion"] = "one-cluster"
            if skill == "ranking":
                response["dimension_reasons"] = {k: "Offline fixture comparison" for k in inputs["evaluation_rubric"]["dimensions"]}
                assert all(c["reviews"] and c["novelty_assessment"] and c["source_documents"]
                           for c in inputs["review_context"].values())
        return RawExternalResponse(body=json.dumps(response).encode(), mime_type="application/json")

    monkeypatch.setattr(ReplayLLMProvider, "invoke", scripted)
    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
    runner._compose(manifest)
    run_id = "research-v1-six-roles"
    runner.supervisor.bootstrap_run(run_id=run_id, manifest=manifest)
    scheduled, restarted = set(), False
    try:
        for _ in range(100):
            assert runner.worker is not None
            step = await runner.worker.run_once(run_id)
            if step.status != "idle":
                continue
            if "evolution" not in scheduled:
                schedule_exercise(runner, run_id, "evolution")
                scheduled.add("evolution")
                continue
            events = runner.uow.load(run_id)
            if any(e.event_type == "MatchEvaluated" for e in events):
                if "meta_review" not in scheduled:
                    schedule_exercise(runner, run_id, "meta_review")
                    scheduled.add("meta_review")
                    continue
                if not restarted:
                    # New code definitions must not replace the frozen protocol on resume.
                    monkeypatch.setattr("co_scientist.application.config.research_protocol_v1",
                                        lambda: {"version": "unreleased"})
                    await runner.aclose()
                    runner = CoreRunner(data_dir=tmp_path / "data", environment=environment)
                    result = await runner.resume(run_id=run_id)
                    restarted = True
                    assert str(result.state) == "completed"
                    break
            runner.supervisor.advance(run_id=run_id, expected_sequence=events[-1].sequence)
        else:
            pytest.fail("offline workflow exceeded bound")
        assert restarted
        assert set(observed) == set(manifest["research_protocol"]["roles"])
        events = runner.uow.load(run_id)
        for child in ("child-1", "child-2"):
            stages = {e.payload["stage"] for e in events if e.event_type == "ReviewCompleted" and e.payload["hypothesis_id"] == child}
            assert stages == {"initial_review", "full_review"}
        read_model = SqliteRunReadModel(runner.uow)
        assert all(c["state"] == "domain_result_applied" for c in read_model.external_calls(run_id))
        assert verify_core_release_invariants(run_id, read_model).violation_count == 0
    finally:
        await runner.aclose()


@pytest.mark.parametrize("protocol,status,complete,valid", [
    (True, "decisive", False, False), (True, "decisive", True, True),
    (False, "decisive", False, True), (True, "inconclusive", False, True),
    (True, "invalid", False, True), (True, "needs_tiebreaker", False, True),
])
def test_new_decisive_ranking_requires_rubric_reasons(tmp_path, protocol, status, complete, valid):
    config, environment = resolved(tmp_path)
    manifest = config.model_dump(mode="json")["manifest"]
    events, inputs = anchor_input(manifest)
    if protocol:
        inputs = research_inputs(manifest, events, inputs, skill_id="ranking")
    records = json.loads(Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"]).read_text())["responses"]
    response = copy.deepcopy(next(r["response"] for r in records if r["skill_id"] == "ranking"))
    response.update({k: inputs[k] for k in set(response) & set(inputs)})
    response.update(decision_status=status, winner_slot=1 if status == "decisive" else None)
    response["dimension_reasons"] = {k: "Reasoned comparison" for k in research_protocol_v1()["ranking_dimensions"]} if complete else {}
    result = RankingResultV1.model_validate(response)
    if valid:
        validate_result_task_binding(result=result, task_inputs=inputs, task_research_plan_version=1, provider_id="replay")
    else:
        with pytest.raises(ValueError, match="dimension_reasons"):
            validate_result_task_binding(result=result, task_inputs=inputs, task_research_plan_version=1, provider_id="replay")
