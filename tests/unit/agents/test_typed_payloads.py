import pytest
from pydantic import BaseModel, ValidationError

from co_scientist.agents.payloads import (
    GenerationResultV1,
    NonScientificResultV1,
    ReflectionResultV1,
    validate_output_payload,
)
from co_scientist.agents.result import AgentExecutionContext


def _draft(*, hypothesis_id: str = "h-1", content_id: str = "c-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "hypothesis_id": hypothesis_id,
        "content_id": content_id,
        "research_plan_version": 1,
        "title": "Mechanical gate",
        "claim": "Capsule strain precedes EMT commitment.",
        "mechanism_chain": ["strain", "YAP", "cell fate"],
        "assumptions": ["strain is sensed before commitment"],
        "predictions": ["normalizing strain reduces fibrosis"],
        "falsifiers": ["cell fate changes before strain"],
        "generation_strategy": "causal contrast",
    }


VALID_PAYLOADS: dict[str, dict[str, object]] = {
    "GenerationResultV1": {
        "schema_version": 1,
        "research_plan_version": 1,
        "hypotheses": [_draft()],
    },
    "ReflectionResultV1": {
        "schema_version": 1,
        "research_plan_version": 1,
        "review_id": "review-1",
        "hypothesis_id": "h-1",
        "content_hash": "sha256:content",
        "stage": "initial_review",
        "recommendation": "pass",
        "dimension_scores": {"testability": 0.9},
        "critical_flaws": [],
        "evidence_ids": [],
        "safety_status": "passed",
    },
    "RankingResultV1": {
        "schema_version": 1,
        "research_plan_version": 1,
        "match_id": "match-1",
        "epoch_id": "epoch-1",
        "left_id": "h-1",
        "left_content_hash": "sha256:" + "a" * 64,
        "right_id": "h-2",
        "right_content_hash": "sha256:" + "b" * 64,
        "decision_status": "decisive",
        "winner_slot": 1,
        "evaluation_rules_hash": "sha256:rules",
        "ranking_prompt_hash": "sha256:prompt",
        "judge_profile_hash": "sha256:judge",
        "rating_policy_version": "elo-32-v1",
        "admission_policy_version": "admission-v1",
        "dimension_reasons": {"testability": "left has a direct perturbation"},
        "confidence": 0.8,
        "unresolved_disagreements": [],
    },
    "ProximityResultV1": {
        "schema_version": 1,
        "research_plan_version": 1,
        "edge_id": "edge-1",
        "left_id": "h-1",
        "left_content_hash": "sha256:" + "a" * 64,
        "right_id": "h-2",
        "right_content_hash": "sha256:" + "b" * 64,
        "similarity": 2,
        "mechanism_overlap": ["YAP"],
        "duplicate_likelihood": 0.1,
        "cluster_suggestion": "distinct mechanisms",
        "rationale": "The causal mechanisms differ.",
        "access_issues": [],
    },
    "EvolutionResultV1": {
        "schema_version": 1,
        "research_plan_version": 1,
        "children": [
            _draft(hypothesis_id="h-3", content_id="c-3")
            | {"parent_content_ids": ["c-1"]}
        ],
        "change_rationales": {"h-3": "Adds an early perturbation readout."},
    },
    "MetaReviewResultV1": {
        "schema_version": 1,
        "research_plan_version": 1,
        "source_content_hashes": {"h-1": "sha256:" + "a" * 64},
        "system_feedback": ["Separate age from surgical geometry."],
        "overview": "Candidates cover distinct causal mechanisms.",
        "coverage_gaps": ["No early timepoint."],
        "safety_direction_check": "clear",
    },
}


@pytest.mark.parametrize(("schema_id", "payload"), VALID_PAYLOADS.items())
def test_each_registered_completed_payload_validates_to_its_frozen_model(
    schema_id: str, payload: dict[str, object]
) -> None:
    validated = validate_output_payload(
        status="completed", schema_id=schema_id, schema_version=1, payload=payload
    )

    assert isinstance(validated, BaseModel)
    assert type(validated).__name__ == schema_id
    with pytest.raises(ValidationError, match="frozen"):
        validated.schema_version = 2


@pytest.mark.parametrize(
    ("schema_id", "payload"),
    [
        ("GenerationResultV1", {"schema_version": 1, "research_plan_version": 1}),
        ("ReflectionResultV1", {"schema_version": 1, "review_id": "r-1", "extra": True}),
        ("RankingResultV1", {"schema_version": 1, "match_id": ""}),
    ],
)
def test_completed_scientific_payloads_fail_closed(
    schema_id: str, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        validate_output_payload(
            status="completed", schema_id=schema_id, schema_version=1, payload=payload
        )


@pytest.mark.parametrize(
    ("schema_id", "schema_version"),
    [("UnknownResultV1", 1), ("GenerationResultV1", 2)],
)
def test_unknown_schema_identity_or_version_fails_closed(
    schema_id: str, schema_version: int
) -> None:
    with pytest.raises(ValueError, match="schema"):
        validate_output_payload(
            status="completed",
            schema_id=schema_id,
            schema_version=schema_version,
            payload=VALID_PAYLOADS["GenerationResultV1"],
        )


def test_initial_review_requires_an_authoritative_safety_verdict() -> None:
    payload = {**VALID_PAYLOADS["ReflectionResultV1"], "safety_status": "not_assessed"}

    with pytest.raises(ValidationError, match="safety"):
        ReflectionResultV1.model_validate(payload)


@pytest.mark.parametrize("status", ["partial", "rejected", "failed"])
def test_non_completed_status_rejects_scientific_fields(status: str) -> None:
    with pytest.raises(ValidationError):
        validate_output_payload(
            status=status,
            schema_id="GenerationResultV1",
            schema_version=1,
            payload=VALID_PAYLOADS["GenerationResultV1"],
        )

    validated = validate_output_payload(
        status=status,
        schema_id="GenerationResultV1",
        schema_version=1,
        payload={
            "schema_version": 1,
            "outcome": status,
            "reason_code": "provider_incomplete",
            "message": "provider could not complete",
            "retryable": status != "rejected",
        },
    )
    assert isinstance(validated, NonScientificResultV1)


@pytest.mark.parametrize(
    "elo_field", ["elo", "rating", "left_rating", "right_rating", "rating_delta"]
)
def test_ranking_never_accepts_provider_supplied_elo(elo_field: str) -> None:
    payload = {**VALID_PAYLOADS["RankingResultV1"], elo_field: 1200.0}

    with pytest.raises(ValidationError):
        validate_output_payload(
            status="completed",
            schema_id="RankingResultV1",
            schema_version=1,
            payload=payload,
        )


@pytest.mark.parametrize(
    ("decision_status", "winner_slot"),
    [
        ("decisive", None),
        ("decisive", 3),
        ("inconclusive", 1),
        ("invalid", 2),
        ("needs_tiebreaker", 1),
    ],
)
def test_ranking_enforces_exact_winner_slot_semantics(
    decision_status: str, winner_slot: int | None
) -> None:
    payload = {
        **VALID_PAYLOADS["RankingResultV1"],
        "decision_status": decision_status,
        "winner_slot": winner_slot,
    }

    with pytest.raises(ValidationError, match="winner"):
        validate_output_payload(
            status="completed",
            schema_id="RankingResultV1",
            schema_version=1,
            payload=payload,
        )


def test_generation_rejects_blank_nested_identifiers_and_mismatched_plan() -> None:
    blank = {**VALID_PAYLOADS["GenerationResultV1"], "hypotheses": [_draft(content_id=" ")]}
    wrong_plan = {
        **VALID_PAYLOADS["GenerationResultV1"],
        "hypotheses": [{**_draft(), "research_plan_version": 2}],
    }

    with pytest.raises(ValidationError):
        GenerationResultV1.model_validate(blank)
    with pytest.raises(ValidationError):
        GenerationResultV1.model_validate(wrong_plan)


@pytest.mark.parametrize(
    "novelty_mutation",
    [
        {"unexpected": True},
        {"assessment_id": " "},
        {"closest_prior_work_ids": [" "]},
        {"evidence_ids": [""]},
    ],
)
def test_reflection_rejects_extra_or_blank_nested_novelty_fields(
    novelty_mutation: dict[str, object],
) -> None:
    novelty = {
        "assessment_id": "novelty-1",
        "hypothesis_id": "h-1",
        "content_hash": "sha256:content",
        "research_plan_version": 1,
        "verdict": "novel",
        "closest_prior_work_ids": ["paper-1"],
        "evidence_ids": ["evidence-1"],
        **novelty_mutation,
    }
    payload = {
        **VALID_PAYLOADS["ReflectionResultV1"],
        "stage": "full_review",
        "novelty_assessment": novelty,
    }

    with pytest.raises(ValidationError):
        ReflectionResultV1.model_validate(payload)


def test_execution_context_rejects_noncanonical_skill_schema_pair() -> None:
    with pytest.raises(ValidationError, match="canonical skill contract"):
        AgentExecutionContext(
            run_id="run-1",
            task_id="task-1",
            idempotency_key="task-1",
            skill_id="reflection",
            skill_version="0.2.0",
            output_schema_id="GenerationResultV1",
            output_schema_version=1,
            research_plan_version=1,
            provider="fake",
            model_or_tool="fake-v1",
            input_snapshot_hash="sha256:input",
        )
