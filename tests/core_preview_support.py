from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from co_scientist.agents.payloads import HypothesisDraftV1
from co_scientist.domain.hypothesis import (
    compute_hypothesis_content_hash,
    hypothesis_content_from_draft,
)
from co_scientist.runtime.external_calls import prompt_hash


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def write_core_preview_inputs(
    root: Path,
    *,
    minimum_matches: int = 2,
    top_k_stability_window: int = 2,
) -> tuple[Path, Path, dict[str, str]]:
    goal = {
        "title": "Lens regeneration mechanisms",
        "goal": "Rank falsifiable mechanisms of transparent versus fibrotic regeneration.",
        "required_causal_chain": ["surgery", "cell_state", "morphogenesis"],
        "required_outputs": ["falsifiers", "discriminating_experiments"],
    }
    profile = {
        "profile_id": "core-preview-test",
        "admission_policy_version": "admission-v1",
        "review_policy": {
            "profile_id": "core-preview-test",
            "required_before_admission": ["full_review"],
            "trigger_rules": {},
        },
        "literature_novelty_required": True,
        "duplicate_likelihood_threshold": 0.5,
        "tournament": {
            "rating_policy_version": "elo-32-v1",
            "evaluation_rules_id": "core-preview-rules-v1",
            "judge_profile_id": "core-preview-judge-v1",
            "match_mode": "research",
            "anchor_count": 2,
        },
        "stop": {
            "minimum_matches": minimum_matches,
            "minimum_hypotheses": 2,
            "minimum_model_calls": 7 + minimum_matches,
            "top_k": 2,
            "top_k_stability_window": top_k_stability_window,
            "cluster_diversity_window": 2,
            "elo_plateau_window": 2,
            "require_anchor_plateau": True,
            "require_top_k_stability": True,
            "require_cluster_diversity_plateau": True,
        },
        "budget": {
            "max_usd": None,
            "max_model_calls": 20,
            "max_input_tokens": None,
            "max_output_tokens": None,
            "max_hypotheses": 4,
            "max_matches": max(4, minimum_matches),
        },
        "providers": {"llm": "replay", "literature": "replay_pubmed"},
    }
    goal_file = root / "goal.yaml"
    profile_file = root / "profile.yaml"
    goal_file.write_text(yaml.safe_dump(goal, sort_keys=True), encoding="utf-8")
    profile_file.write_text(yaml.safe_dump(profile, sort_keys=True), encoding="utf-8")

    generation = {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [
            {
                "schema_version": 1,
                "hypothesis_id": "h-1",
                "content_id": "c-1",
                "research_plan_version": 1,
                "title": "Mechanical gate",
                "claim": "Capsule strain precedes fibrotic commitment.",
                "mechanism_chain": ["surgery", "strain", "cell_state", "morphogenesis"],
                "assumptions": ["strain is sensed early"],
                "predictions": ["normalizing strain reduces fibrosis"],
                "falsifiers": ["commitment precedes strain sensing"],
                "generation_strategy": "causal contrast",
            },
            {
                "schema_version": 1,
                "hypothesis_id": "h-2",
                "content_id": "c-2",
                "research_plan_version": 1,
                "title": "Inflammatory gate",
                "claim": "Cytokine duration precedes fibrotic commitment.",
                "mechanism_chain": ["surgery", "cytokines", "cell_state", "morphogenesis"],
                "assumptions": ["cytokine duration is measurable"],
                "predictions": ["short exposure reduces fibrosis"],
                "falsifiers": ["duration has no effect"],
                "generation_strategy": "causal contrast",
            },
        ],
    }
    hashes = {
        draft["hypothesis_id"]: compute_hypothesis_content_hash(
            hypothesis_content_from_draft(HypothesisDraftV1.model_validate(draft))
        )
        for draft in generation["hypotheses"]
    }
    generation_inputs = {
        "goal_title": goal["title"],
        "research_goal": goal["goal"],
        "required_causal_chain": goal["required_causal_chain"],
        "required_outputs": goal["required_outputs"],
    }
    records: list[dict[str, Any]] = [
        {"skill_id": "generation", "inputs": generation_inputs, "response": generation}
    ]
    for hypothesis_id in ("h-1", "h-2"):
        for stage in ("full_review", "initial_review"):
            response: dict[str, Any] = {
                "schema_version": 1,
                "research_plan_version": 1,
                "review_id": f"review-{stage}-{hypothesis_id}",
                "hypothesis_id": hypothesis_id,
                "content_hash": hashes[hypothesis_id],
                "stage": stage,
                "recommendation": "pass",
                "safety_status": "passed" if stage == "initial_review" else "not_assessed",
                "dimension_scores": {},
                "critical_flaws": [],
                "evidence_ids": [],
            }
            if stage == "full_review":
                response["novelty_assessment"] = {
                    "assessment_id": f"novelty-{hypothesis_id}",
                    "hypothesis_id": hypothesis_id,
                    "content_hash": hashes[hypothesis_id],
                    "research_plan_version": 1,
                    "verdict": "partially_novel",
                    "closest_prior_work_ids": [],
                    "evidence_ids": [],
                }
            records.append(
                {
                    "skill_id": "reflection",
                    "inputs": {
                        "hypothesis_id": hypothesis_id,
                        "content_hash": hashes[hypothesis_id],
                        "review_stage": stage,
                    },
                    "response": response,
                }
            )

    for index, (left, right, cluster) in enumerate(
        (("h-1", "h-2", "mechanical"), ("h-2", "h-1", "inflammatory")), start=1
    ):
        records.append(
            {
                "skill_id": "proximity",
                "inputs": {
                    "edge_id": f"edge-{index}",
                    "left_id": left,
                    "left_content_hash": hashes[left],
                    "right_id": right,
                    "right_content_hash": hashes[right],
                },
                "response": {
                    "schema_version": 1,
                    "research_plan_version": 1,
                    "edge_id": f"edge-{index}",
                    "left_id": left,
                    "left_content_hash": hashes[left],
                    "right_id": right,
                    "right_content_hash": hashes[right],
                    "similarity": 2,
                    "mechanism_overlap": [],
                    "duplicate_likelihood": 0.05,
                    "cluster_suggestion": cluster,
                    "rationale": "The mechanisms remain distinguishable.",
                    "access_issues": [],
                },
            }
        )

    ranking_prompt_hash = prompt_hash(
        Path("skills/ranking/prompts/system.md").read_text(encoding="utf-8")
    )
    evaluation_rules_hash = _sha256(
        {
            "evaluation_rules_id": "core-preview-rules-v1",
            "match_mode": "research",
        }
    )
    judge_profile_hash = _sha256({"judge_profile_id": "core-preview-judge-v1"})
    anchors = (
        (
            "transparent-regeneration-baseline-v1",
            _sha256("ordered transparent lens regeneration baseline"),
        ),
        (
            "fibrotic-regeneration-baseline-v1",
            _sha256("disorganized fibrotic lens regeneration baseline"),
        ),
    )
    opportunistic_matches = max(
        minimum_matches - len(anchors),
        top_k_stability_window - len(anchors),
        0,
    )
    for index in range(1, opportunistic_matches + 1):
        contract = {
            "match_id": f"opportunistic-match-{index}",
            "epoch_id": "epoch-1",
            "left_id": "h-1",
            "left_content_hash": hashes["h-1"],
            "right_id": "h-2",
            "right_content_hash": hashes["h-2"],
            "research_plan_version": 1,
            "evaluation_rules_hash": evaluation_rules_hash,
            "ranking_prompt_hash": ranking_prompt_hash,
            "judge_profile_hash": judge_profile_hash,
            "rating_policy_version": "elo-32-v1",
            "admission_policy_version": "admission-v1",
        }
        records.append(
            {
                "skill_id": "ranking",
                "inputs": {
                    **contract,
                    "anchor_set_id": "core-preview-anchors-v1",
                    "comparison_kind": "opportunistic",
                },
                "response": {
                    "schema_version": 1,
                    **contract,
                    "decision_status": "decisive",
                    "winner_slot": 1 if index % 2 else 2,
                    "dimension_reasons": {"mechanism": "Replay fixture decision."},
                    "confidence": 0.8,
                    "unresolved_disagreements": [],
                },
            }
        )
    for index, (hypothesis_id, anchor) in enumerate(zip(("h-1", "h-2"), anchors), 1):
        anchor_id, anchor_hash = anchor
        contract = {
            "match_id": f"anchor-match-{index}",
            "epoch_id": "epoch-1",
            "left_id": hypothesis_id,
            "left_content_hash": hashes[hypothesis_id],
            "right_id": anchor_id,
            "right_content_hash": anchor_hash,
            "research_plan_version": 1,
            "evaluation_rules_hash": evaluation_rules_hash,
            "ranking_prompt_hash": ranking_prompt_hash,
            "judge_profile_hash": judge_profile_hash,
            "rating_policy_version": "elo-32-v1",
            "admission_policy_version": "admission-v1",
        }
        records.append(
            {
                "skill_id": "ranking",
                "inputs": {
                    **contract,
                    "anchor_set_id": "core-preview-anchors-v1",
                    "comparison_kind": "fixed_anchor",
                },
                "response": {
                    "schema_version": 1,
                    **contract,
                    "decision_status": "decisive",
                    "winner_slot": 1,
                    "dimension_reasons": {"mechanism": "Replay fixture decision."},
                    "confidence": 0.8,
                    "unresolved_disagreements": [],
                },
            }
        )

    replay_file = root / "replay.json"
    replay_file.write_text(
        json.dumps(
            {
                "replay_version": 1,
                "model": "core-preview-replay-v1",
                "responses": records,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    search_file = root / "pubmed-search.json"
    summary_file = root / "pubmed-summary.json"
    search_file.write_text('{"esearchresult":{"idlist":[]}}\n', encoding="utf-8")
    summary_file.write_text('{"result":{"uids":[]}}\n', encoding="utf-8")
    environment = {
        "CO_SCIENTIST_REPLAY_RESPONSES": str(replay_file),
        "CO_SCIENTIST_REPLAY_PUBMED_SEARCH": str(search_file),
        "CO_SCIENTIST_REPLAY_PUBMED_SUMMARY": str(summary_file),
    }
    return goal_file, profile_file, environment
