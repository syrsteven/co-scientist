"""Closed, versioned contracts for Core Preview scientific agent output."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from co_scientist.domain.review import NoveltyAssessment, ReviewStage
from co_scientist.domain.tournament import MatchDecision

NonEmptyStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
CanonicalSha256 = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$"),
]


class HypothesisDraftV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    hypothesis_id: NonEmptyStr
    content_id: NonEmptyStr
    research_plan_version: int = Field(ge=1)
    title: NonEmptyStr
    claim: NonEmptyStr
    mechanism_chain: tuple[NonEmptyStr, ...]
    assumptions: tuple[NonEmptyStr, ...]
    predictions: tuple[NonEmptyStr, ...]
    falsifiers: tuple[NonEmptyStr, ...]
    generation_strategy: NonEmptyStr
    parent_content_ids: tuple[NonEmptyStr, ...] = ()
    supersedes_content_id: NonEmptyStr | None = None
    content_hash: NonEmptyStr | None = None


class GenerationResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    hypotheses: tuple[HypothesisDraftV1, ...]

    @model_validator(mode="after")
    def validate_hypotheses(self) -> "GenerationResultV1":
        if not self.hypotheses:
            raise ValueError("generation requires at least one hypothesis draft")
        if any(
            draft.research_plan_version != self.research_plan_version
            for draft in self.hypotheses
        ):
            raise ValueError("draft research plan version must match generation result")
        return self


class ReflectionResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    review_id: NonEmptyStr
    hypothesis_id: NonEmptyStr
    content_hash: NonEmptyStr
    stage: ReviewStage
    recommendation: Literal["pass", "reject", "needs_more_evidence"]
    safety_status: Literal["passed", "blocked", "not_assessed"]
    dimension_scores: dict[NonEmptyStr, float] = Field(default_factory=dict)
    critical_flaws: tuple[NonEmptyStr, ...] = ()
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    novelty_assessment: NoveltyAssessment | None = None

    @model_validator(mode="after")
    def validate_review_scope(self) -> "ReflectionResultV1":
        if self.stage is ReviewStage.INITIAL and self.safety_status == "not_assessed":
            raise ValueError("initial review requires an assessed safety status")
        novelty = self.novelty_assessment
        if novelty is not None and (
            novelty.hypothesis_id != self.hypothesis_id
            or novelty.content_hash != self.content_hash
            or novelty.research_plan_version != self.research_plan_version
        ):
            raise ValueError("novelty assessment does not match the reviewed content")
        return self


class RankingResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    match_id: NonEmptyStr
    epoch_id: NonEmptyStr
    left_id: NonEmptyStr
    left_content_hash: NonEmptyStr
    right_id: NonEmptyStr
    right_content_hash: NonEmptyStr
    evaluation_rules_hash: NonEmptyStr
    ranking_prompt_hash: NonEmptyStr
    judge_profile_hash: NonEmptyStr
    rating_policy_version: NonEmptyStr
    admission_policy_version: NonEmptyStr
    decision_status: MatchDecision
    winner_slot: Literal[1, 2] | None = None
    dimension_reasons: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    unresolved_disagreements: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_match(self) -> "RankingResultV1":
        if self.left_id == self.right_id:
            raise ValueError("ranking requires different participants")
        decisive = self.decision_status is MatchDecision.DECISIVE
        if decisive and self.winner_slot is None:
            raise ValueError("decisive ranking requires a winner slot")
        if not decisive and self.winner_slot is not None:
            raise ValueError("non-decisive ranking cannot have a winner slot")
        return self


class ProximityResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    edge_id: NonEmptyStr
    left_id: NonEmptyStr
    left_content_hash: CanonicalSha256
    right_id: NonEmptyStr
    right_content_hash: CanonicalSha256
    similarity: int = Field(ge=1, le=5)
    mechanism_overlap: tuple[NonEmptyStr, ...] = ()
    duplicate_likelihood: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    cluster_suggestion: NonEmptyStr | None = None
    rationale: NonEmptyStr
    access_issues: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_participants(self) -> "ProximityResultV1":
        if self.left_id == self.right_id:
            raise ValueError("proximity requires different participants")
        return self


class EvolutionResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    children: tuple[HypothesisDraftV1, ...]
    change_rationales: dict[NonEmptyStr, NonEmptyStr]

    @model_validator(mode="after")
    def validate_children(self) -> "EvolutionResultV1":
        if not self.children:
            raise ValueError("evolution requires at least one child draft")
        if any(
            draft.research_plan_version != self.research_plan_version
            for draft in self.children
        ):
            raise ValueError("draft research plan version must match evolution result")
        child_ids = {draft.hypothesis_id for draft in self.children}
        if len(child_ids) != len(self.children):
            raise ValueError("evolution child hypothesis IDs must be unique")
        if set(self.change_rationales) != child_ids:
            raise ValueError("change rationale keys must equal child hypothesis IDs")
        return self


class MetaReviewResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    source_content_hashes: dict[NonEmptyStr, CanonicalSha256]
    system_feedback: tuple[NonEmptyStr, ...]
    overview: NonEmptyStr
    coverage_gaps: tuple[NonEmptyStr, ...] = ()
    safety_direction_check: Literal["clear", "concern", "insufficient_evidence"]


class NonScientificResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    outcome: Literal["partial", "rejected", "failed"]
    reason_code: NonEmptyStr
    message: NonEmptyStr
    retryable: bool
    missing_requirements: tuple[NonEmptyStr, ...] = ()


CoreOutputSchemaId = Literal[
    "GenerationResultV1",
    "ReflectionResultV1",
    "RankingResultV1",
    "EvolutionResultV1",
    "ProximityResultV1",
    "MetaReviewResultV1",
]

CoreScientificResultV1: TypeAlias = (
    GenerationResultV1
    | ReflectionResultV1
    | RankingResultV1
    | EvolutionResultV1
    | ProximityResultV1
    | MetaReviewResultV1
)

_SCHEMA_REGISTRY: Mapping[tuple[str, int], type[BaseModel]] = MappingProxyType(
    {
        ("GenerationResultV1", 1): GenerationResultV1,
        ("ReflectionResultV1", 1): ReflectionResultV1,
        ("RankingResultV1", 1): RankingResultV1,
        ("EvolutionResultV1", 1): EvolutionResultV1,
        ("ProximityResultV1", 1): ProximityResultV1,
        ("MetaReviewResultV1", 1): MetaReviewResultV1,
    }
)


def resolve_output_schema(schema_id: str, schema_version: int) -> type[BaseModel]:
    """Resolve one exact Core schema identity, failing closed for all others."""

    try:
        return _SCHEMA_REGISTRY[(schema_id, schema_version)]
    except KeyError as error:
        raise ValueError(f"unknown output schema: {schema_id} v{schema_version}") from error


def validate_output_payload(
    *,
    status: Literal["completed", "partial", "rejected", "failed"],
    schema_id: str,
    schema_version: int,
    payload: Mapping[str, Any],
) -> CoreScientificResultV1 | NonScientificResultV1:
    """Validate raw JSON against the status-selected, closed output contract."""

    schema = resolve_output_schema(schema_id, schema_version)
    if status == "completed":
        return cast(CoreScientificResultV1, schema.model_validate(payload))
    validated = NonScientificResultV1.model_validate(payload)
    if validated.outcome != status:
        raise ValidationError.from_exception_data(
            "NonScientificResultV1",
            [
                {
                    "type": "value_error",
                    "loc": ("outcome",),
                    "input": validated.outcome,
                    "ctx": {"error": ValueError("outcome must match AgentResult status")},
                }
            ],
        )
    return validated
