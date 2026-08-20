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
    hypothesis_count: int = 2,
    novelty_verdict: str = "partially_novel",
    max_hypotheses: int = 4,
    max_model_calls: int = 20,
    max_matches: int | None = None,
    literature_novelty_required: bool = True,
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
        "literature_novelty_required": literature_novelty_required,
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
            "max_model_calls": max_model_calls,
            "max_input_tokens": None,
            "max_output_tokens": None,
            "max_hypotheses": max_hypotheses,
            "max_matches": (
                max_matches if max_matches is not None else max(4, minimum_matches)
            ),
        },
        "providers": {"llm": "replay", "literature": "replay_pubmed"},
    }
    goal_file = root / "goal.yaml"
    profile_file = root / "profile.yaml"
    goal_file.write_text(yaml.safe_dump(goal, sort_keys=True), encoding="utf-8")
    profile_file.write_text(yaml.safe_dump(profile, sort_keys=True), encoding="utf-8")

    hypothesis_templates = [
        {
            "title": "Mechanical gate",
            "claim": "Capsule strain precedes fibrotic commitment.",
            "mechanism": "strain",
            "assumption": "strain is sensed early",
            "prediction": "normalizing strain reduces fibrosis",
            "falsifier": "commitment precedes strain sensing",
        },
        {
            "title": "Inflammatory gate",
            "claim": "Cytokine duration precedes fibrotic commitment.",
            "mechanism": "cytokines",
            "assumption": "cytokine duration is measurable",
            "prediction": "short exposure reduces fibrosis",
            "falsifier": "duration has no effect",
        },
    ]
    hypothesis_templates.extend(
        {
            "title": f"Alternative gate {index}",
            "claim": f"Alternative signal {index} precedes fibrotic commitment.",
            "mechanism": f"alternative-signal-{index}",
            "assumption": f"alternative signal {index} is measurable",
            "prediction": f"blocking alternative signal {index} reduces fibrosis",
            "falsifier": f"alternative signal {index} follows commitment",
        }
        for index in range(3, hypothesis_count + 1)
    )
    generation = {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [
            {
                "schema_version": 1,
                "hypothesis_id": f"h-{index}",
                "content_id": f"c-{index}",
                "research_plan_version": 1,
                "title": template["title"],
                "claim": template["claim"],
                "mechanism_chain": [
                    "surgery",
                    template["mechanism"],
                    "cell_state",
                    "morphogenesis",
                ],
                "assumptions": [template["assumption"]],
                "predictions": [template["prediction"]],
                "falsifiers": [template["falsifier"]],
                "generation_strategy": "causal contrast",
            }
            for index, template in enumerate(
                hypothesis_templates[:hypothesis_count], start=1
            )
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
    query = "Lens regeneration mechanisms lens epithelial regeneration fibrosis"
    source_ids = ["pubmed:1001", "pubmed:1002"]
    summary_body = Path("tests/scenario/fixtures/pubmed_summary_lens.json").read_bytes()
    literature_evidence = {
        "query": query,
        "source_ids": source_ids,
        "raw_sha256": "sha256:" + hashlib.sha256(summary_body).hexdigest(),
    }
    for hypothesis_id, content_hash in hashes.items():
        for stage in ("full_review", "initial_review"):
            response: dict[str, Any] = {
                "schema_version": 1,
                "research_plan_version": 1,
                "review_id": f"review-{stage}-{hypothesis_id}",
                "hypothesis_id": hypothesis_id,
                "content_hash": content_hash,
                "stage": stage,
                "recommendation": "pass",
                "safety_status": "passed" if stage == "initial_review" else "not_assessed",
                "dimension_scores": {},
                "critical_flaws": [],
                "evidence_ids": source_ids if stage == "full_review" else [],
            }
            if stage == "full_review":
                response["novelty_assessment"] = {
                    "assessment_id": f"novelty-{hypothesis_id}",
                    "hypothesis_id": hypothesis_id,
                    "content_hash": content_hash,
                    "research_plan_version": 1,
                    "verdict": novelty_verdict,
                    "closest_prior_work_ids": source_ids,
                    "evidence_ids": source_ids,
                }
            records.append(
                {
                    "skill_id": "reflection",
                    "inputs": {
                        "hypothesis_id": hypothesis_id,
                        "content_hash": content_hash,
                        "review_stage": stage,
                        **(
                            {"literature_evidence": literature_evidence}
                            if stage == "full_review"
                            and literature_novelty_required
                            else {}
                        ),
                    },
                    "response": response,
                }
            )

    hypothesis_ids = sorted(hashes)
    proximity_pairs = [
        (hypothesis_id, "h-1", f"alternative-{hypothesis_id}")
        for hypothesis_id in hypothesis_ids[2:]
    ]
    if len(hypothesis_ids) >= 2:
        proximity_pairs.extend(
            (("h-1", "h-2", "mechanical"), ("h-2", "h-1", "inflammatory"))
        )
    for index, (left, right, cluster) in enumerate(proximity_pairs, start=1):
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
    opportunistic_matches = (
        max(
            minimum_matches - len(anchors),
            top_k_stability_window - len(anchors),
            0,
        )
        if len(hypothesis_ids) >= 2
        else 0
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
    for index, (hypothesis_id, anchor) in enumerate(
        zip(hypothesis_ids[:2], anchors, strict=False), 1
    ):
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
    search_file.write_bytes(Path("tests/scenario/fixtures/pubmed_search_lens.json").read_bytes())
    summary_file.write_bytes(summary_body)
    environment = {
        "CO_SCIENTIST_REPLAY_RESPONSES": str(replay_file),
        "CO_SCIENTIST_REPLAY_PUBMED_SEARCH": str(search_file),
        "CO_SCIENTIST_REPLAY_PUBMED_SUMMARY": str(summary_file),
    }
    return goal_file, profile_file, environment
