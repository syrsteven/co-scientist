from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyReviewStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]


class ReviewStage(StrEnum):
    INITIAL = "initial_review"
    FULL = "full_review"
    DEEP = "deep_verification"
    OBSERVATION = "observation_review"
    SIMULATION = "simulation_review"
    RECURRENT = "recurrent_review"


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    required_before_admission: tuple[ReviewStage, ...] = ()
    trigger_rules: dict[ReviewStage, tuple[str, ...]] = Field(default_factory=dict)


def required_review_stages(policy: ReviewPolicy) -> set[ReviewStage]:
    return {ReviewStage.INITIAL, *policy.required_before_admission}


class Review(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: str
    hypothesis_id: str
    content_hash: str
    stage: ReviewStage
    recommendation: Literal["pass", "reject", "needs_more_evidence"]
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    critical_flaws: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class NoveltyVerdict(StrEnum):
    NOVEL = "novel"
    PARTIALLY_NOVEL = "partially_novel"
    NOT_NOVEL = "not_novel"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class NoveltyAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: NonEmptyReviewStr
    hypothesis_id: NonEmptyReviewStr
    content_hash: NonEmptyReviewStr
    research_plan_version: int = Field(ge=1)
    verdict: NoveltyVerdict
    closest_prior_work_ids: tuple[NonEmptyReviewStr, ...]
    evidence_ids: tuple[NonEmptyReviewStr, ...] = ()
