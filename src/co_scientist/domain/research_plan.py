"""Immutable versioned research-plan contract."""

from pydantic import BaseModel, ConfigDict

from co_scientist.domain.review import ReviewPolicy


class ResearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    version: int
    scientific_scope_hash: str
    evaluation_rules_hash: str
    ranking_prompt_hash: str
    judge_profile_hash: str
    rating_policy_version: str
    admission_policy_version: str
    review_policy: ReviewPolicy
    literature_novelty_required: bool
