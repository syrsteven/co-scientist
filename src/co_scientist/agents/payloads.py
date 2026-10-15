"""Closed, versioned contracts for Core Preview scientific agent output."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    ValidationError,
    model_serializer,
    model_validator,
)

from co_scientist.domain.claim_verification import (
    ClaimEvidenceBinding,
    HypothesisClaim,
    PriorArtAssessment,
    ToolRequestProposal,
)
from co_scientist.domain.ideation_prerequisites import (
    BaselineEvolutionResultV1,
    BaselineRankingResultV1,
    BaselineReflectionResultV1,
    CandidateEthicsResultV1,
    DirectiveEthicsResultV1,
    GroundedGenerationResultV1,
    RootLiteratureReviewResultV1,
    RootQueryPlanResultV1,
    RootRetrievalResultV1,
    RootRetrievalResultV2,
)
from co_scientist.domain.review import NoveltyAssessment, ReviewStage
from co_scientist.domain.source_units import SourceUnitV2
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
    evidence_context_hash: CanonicalSha256 | None = None

    @model_serializer(mode="wrap")
    def serialize_result(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if self.evidence_context_hash is None:
            document.pop("evidence_context_hash", None)
        return document

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


class ParentClaimChangeV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_claim_id: NonEmptyStr | None = None
    relation: Literal[
        "retained_from", "modified_from", "combined_from", "new_claim", "removed"
    ]
    child_source_span: NonEmptyStr | None = None

    @model_validator(mode="after")
    def check_relation(self) -> "ParentClaimChangeV1":
        if self.relation == "new_claim" and self.parent_claim_id is not None:
            raise ValueError("new claim cannot cite a parent claim")
        if self.relation not in {"new_claim"} and self.parent_claim_id is None:
            raise ValueError("parent claim relation requires a parent claim ID")
        if (self.relation == "removed") == (self.child_source_span is not None):
            raise ValueError("removed claim cannot have a child span; other relations need one")
        return self


class PopulationEvolutionResultV1(BaseModel):
    """One proposed offspring; verdicts and admission are deliberately absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    proposal_id: NonEmptyStr
    selection_decision_id: NonEmptyStr
    generation_id: NonEmptyStr
    operator: Literal["crossover", "mutation"]
    mutation_subtype: Literal[
        "simplify", "feasibility", "out_of_box", "targeted_revision"
    ] | None
    parent_ids: tuple[NonEmptyStr, ...]
    parent_content_hashes: dict[NonEmptyStr, CanonicalSha256]
    rationale: NonEmptyStr
    intended_change: NonEmptyStr
    mechanistic_contributions: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    new_causal_bridge: NonEmptyStr | None = None
    critical_new_claim: NonEmptyStr | None = None
    distinguishing_experiment: NonEmptyStr | None = None
    source_review_ids: tuple[NonEmptyStr, ...] = ()
    source_feedback_ids: tuple[NonEmptyStr, ...] = ()
    random_seed: NonEmptyStr | None = None
    parent_claim_changes: tuple[ParentClaimChangeV1, ...]
    removed_assumptions: tuple[NonEmptyStr, ...] = ()
    retained_core_claim: NonEmptyStr | None = None
    changed_experimental_path: NonEmptyStr | None = None
    target_feedback_ids: tuple[NonEmptyStr, ...] = ()
    valid: bool
    invalid_reason: NonEmptyStr | None = None
    child: HypothesisDraftV1 | None = None

    @model_validator(mode="after")
    def check_proposal(self) -> "PopulationEvolutionResultV1":
        if len(set(self.parent_ids)) != len(self.parent_ids):
            raise ValueError("parents must be distinct")
        if len(self.parent_ids) != (2 if self.operator == "crossover" else 1):
            raise ValueError("operator has the wrong parent count")
        if set(self.parent_content_hashes) != set(self.parent_ids):
            raise ValueError("parent content hashes must match parent IDs")
        if self.valid and set(self.mechanistic_contributions) != set(self.parent_ids):
            raise ValueError("each parent requires a mechanistic contribution")
        if (self.operator == "crossover") != (self.mutation_subtype is None):
            raise ValueError("mutation subtype must appear only for mutation")
        if self.valid and self.operator == "crossover" and not (
            self.new_causal_bridge and self.critical_new_claim
        ):
            raise ValueError("crossover requires a new bridge and critical claim")
        if self.valid and not self.distinguishing_experiment:
            raise ValueError("valid offspring needs a discriminating experiment")
        if self.valid != (self.child is not None) or self.valid == (self.invalid_reason is not None):
            raise ValueError("valid proposal needs a child; invalid proposal needs a reason")
        if self.child is not None and self.child.research_plan_version != self.research_plan_version:
            raise ValueError("child plan version differs from proposal")
        if self.valid and self.mutation_subtype == "simplify" and not self.removed_assumptions:
            raise ValueError("simplify must identify removed causal assumptions")
        if self.valid and self.mutation_subtype == "feasibility" and not (
            self.retained_core_claim and self.changed_experimental_path
        ):
            raise ValueError("feasibility must preserve the core claim and change the test")
        if self.valid and self.mutation_subtype == "targeted_revision" and not self.target_feedback_ids:
            raise ValueError("targeted revision requires source feedback")
        return self


class ParentClaimRefV2(BaseModel):
    """Provider proposal for one exact parent hypothesis and claim pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_hypothesis_id: NonEmptyStr
    parent_claim_id: NonEmptyStr


class LineageChangeGroupProviderV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_key: NonEmptyStr
    parent_claim_refs: tuple[ParentClaimRefV2, ...]
    relation: Literal[
        "retained_from", "modified_from", "split_from", "combined_from", "new_claim"
    ]
    intended_change: NonEmptyStr

    @model_validator(mode="after")
    def validate_relation(self) -> "LineageChangeGroupProviderV2":
        keys = [(ref.parent_hypothesis_id, ref.parent_claim_id)
                for ref in self.parent_claim_refs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate qualified parent claim ref")
        count = len(keys)
        if self.relation == "combined_from" and count < 2:
            raise ValueError("combined_from requires at least two distinct parent claims")
        if self.relation == "new_claim" and count:
            raise ValueError("new_claim cannot reference a parent")
        if self.relation not in {"combined_from", "new_claim"} and count != 1:
            raise ValueError("lineage relation requires exactly one parent claim")
        return self


class RemovedParentClaimProviderV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_claim_ref: ParentClaimRefV2
    rationale: NonEmptyStr


class HypothesisDraftLineageV2(BaseModel):
    """Scientific child draft; locally derived content hashes are not provider fields."""

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


class PopulationEvolutionResultV2(BaseModel):
    """One provider proposal; selected parents and scientific state bind locally."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["population-evolution-lineage-v2"]
    schema_version: Literal[2]
    research_plan_version: int = Field(ge=1)
    proposal_id: NonEmptyStr
    selection_decision_id: NonEmptyStr
    generation_id: NonEmptyStr
    operator: Literal["crossover", "mutation"]
    mutation_subtype: Literal[
        "simplify", "feasibility", "out_of_box", "targeted_revision"
    ] | None
    parent_ids: tuple[NonEmptyStr, ...]
    rationale: NonEmptyStr
    intended_change: NonEmptyStr
    mechanistic_contributions: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    new_causal_bridge: NonEmptyStr | None = None
    critical_new_claim: NonEmptyStr | None = None
    distinguishing_experiment: NonEmptyStr | None = None
    source_review_ids: tuple[NonEmptyStr, ...] = ()
    source_feedback_ids: tuple[NonEmptyStr, ...] = ()
    random_seed: NonEmptyStr | None = None
    change_groups: tuple[LineageChangeGroupProviderV2, ...]
    removed_parent_claims: tuple[RemovedParentClaimProviderV2, ...] = ()
    removed_assumptions: tuple[NonEmptyStr, ...] = ()
    retained_core_claim: NonEmptyStr | None = None
    changed_experimental_path: NonEmptyStr | None = None
    target_feedback_ids: tuple[NonEmptyStr, ...] = ()
    valid: bool
    invalid_reason: NonEmptyStr | None = None
    child: HypothesisDraftLineageV2 | None = None

    @model_validator(mode="after")
    def check_proposal(self) -> "PopulationEvolutionResultV2":
        if len(set(self.parent_ids)) != len(self.parent_ids):
            raise ValueError("parents must be distinct")
        if len(self.parent_ids) != (2 if self.operator == "crossover" else 1):
            raise ValueError("operator has the wrong parent count")
        if self.valid and set(self.mechanistic_contributions) != set(self.parent_ids):
            raise ValueError("each parent requires a mechanistic contribution")
        if (self.operator == "crossover") != (self.mutation_subtype is None):
            raise ValueError("mutation subtype must appear only for mutation")
        if self.valid and self.operator == "crossover" and not (
            self.new_causal_bridge and self.critical_new_claim
        ):
            raise ValueError("crossover requires a new bridge and critical claim")
        if self.valid and not self.distinguishing_experiment:
            raise ValueError("valid offspring needs a discriminating experiment")
        if self.valid != (self.child is not None) or self.valid == (self.invalid_reason is not None):
            raise ValueError("valid proposal needs a child; invalid proposal needs a reason")
        if self.child is not None and self.child.research_plan_version != self.research_plan_version:
            raise ValueError("child plan version differs from proposal")
        if self.valid and self.mutation_subtype == "simplify" and not self.removed_assumptions:
            raise ValueError("simplify must identify removed causal assumptions")
        if self.valid and self.mutation_subtype == "feasibility" and not (
            self.retained_core_claim and self.changed_experimental_path
        ):
            raise ValueError("feasibility must preserve the core claim and change the test")
        if self.valid and self.mutation_subtype == "targeted_revision" and not self.target_feedback_ids:
            raise ValueError("targeted revision requires source feedback")
        keys = [group.target_key for group in self.change_groups]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate lineage target key")
        uses: dict[tuple[str, str], list[str]] = {}
        for group in self.change_groups:
            for ref in group.parent_claim_refs:
                if ref.parent_hypothesis_id not in self.parent_ids:
                    raise ValueError("lineage ref names an unselected parent hypothesis")
                uses.setdefault((ref.parent_hypothesis_id, ref.parent_claim_id), []).append(
                    group.relation
                )
        if any(len(relations) > 1 and set(relations) != {"split_from"}
               for relations in uses.values()):
            raise ValueError("parent claim has multiple targets without explicit split_from")
        removed: set[tuple[str, str]] = set()
        for removal in self.removed_parent_claims:
            ref = removal.parent_claim_ref
            if ref.parent_hypothesis_id not in self.parent_ids:
                raise ValueError("removal names an unselected parent hypothesis")
            key = (ref.parent_hypothesis_id, ref.parent_claim_id)
            if key in uses or key in removed:
                raise ValueError("duplicate or conflicting removed parent claim")
            removed.add(key)
        return self


def validate_evolution_parent_refs_v2(
    result: PopulationEvolutionResultV2, *, allowed_parent_claim_refs: tuple[Any, ...],
) -> None:
    """Check proposed refs against a frozen parent-claim scope supplied by the caller."""

    allowed = {(ref.parent_hypothesis_id, ref.parent_claim_id)
               for ref in allowed_parent_claim_refs}
    proposed = (
        [ref for group in result.change_groups for ref in group.parent_claim_refs]
        + [item.parent_claim_ref for item in result.removed_parent_claims]
    )
    if any((ref.parent_hypothesis_id, ref.parent_claim_id) not in allowed
           for ref in proposed):
        raise ValueError("unknown parent claim in frozen selection")


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


class ClaimDecompositionResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    hypothesis_id: NonEmptyStr
    hypothesis_content_hash: CanonicalSha256
    claims: tuple[HypothesisClaim, ...]
    result_tool_resolution: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def check_claims(self) -> "ClaimDecompositionResultV1":
        if not self.claims or not any(c.importance == "critical" for c in self.claims):
            raise ValueError("decomposition requires at least one critical claim")
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("claim IDs must be unique")
        if any(c.hypothesis_id != self.hypothesis_id
               or c.hypothesis_content_hash != self.hypothesis_content_hash for c in self.claims):
            raise ValueError("decomposed claim identity does not match hypothesis")
        return self


class ClaimProvenanceItemV2(BaseModel):
    """Provider proposal plus locally resolved source units; relation is descriptive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    importance: Literal["critical", "supporting"]
    claim_id: NonEmptyStr
    text: NonEmptyStr
    claim_type: Literal[
        "established_premise", "bridging_inference", "novel_causal_claim",
        "prediction", "competing_explanation",
    ]
    subject: NonEmptyStr
    relation: NonEmptyStr
    object: NonEmptyStr
    source_unit_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    semantic_relation: Literal["direct", "paraphrase", "synthesized"]
    source_unit_refs: tuple[SourceUnitV2, ...] = Field(min_length=1)
    diagnostic_quote: str | None = None

    @model_validator(mode="after")
    def references_match(self) -> "ClaimProvenanceItemV2":
        if tuple(unit.source_unit_id for unit in self.source_unit_refs) != self.source_unit_ids:
            raise ValueError("resolved SourceUnit references must match provider IDs in order")
        return self


class ClaimProvenanceProviderItemV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    importance: Literal["critical", "supporting"]
    claim_id: NonEmptyStr
    text: NonEmptyStr
    claim_type: Literal[
        "established_premise", "bridging_inference", "novel_causal_claim",
        "prediction", "competing_explanation",
    ]
    subject: NonEmptyStr
    relation: NonEmptyStr
    object: NonEmptyStr
    source_unit_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    semantic_relation: Literal["direct", "paraphrase", "synthesized"]
    diagnostic_quote: str | None = None


class ClaimDecompositionProviderOutputV2(BaseModel):
    """Provider-facing flexible output schema; no run/hypothesis metadata is requested."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: tuple[ClaimProvenanceProviderItemV2, ...] = Field(min_length=1)


class ClaimDecompositionResultV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-provenance-v2"]
    schema_version: Literal[2]
    research_plan_version: int = Field(ge=1)
    hypothesis_id: NonEmptyStr
    hypothesis_content_hash: CanonicalSha256
    claims: tuple[ClaimProvenanceItemV2, ...]

    @model_validator(mode="after")
    def validate_claims(self) -> "ClaimDecompositionResultV2":
        if not self.claims or not any(c.importance == "critical" for c in self.claims):
            raise ValueError("decomposition requires at least one critical claim")
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("claim IDs must be unique")
        return self


class ClaimProvenanceProviderItemV3(ClaimProvenanceProviderItemV2):
    """Provider claim with one explicit lineage reference or unplanned-new marker."""

    lineage_target_id: NonEmptyStr | None = None
    is_explicit_new_claim: bool = False

    @model_validator(mode="after")
    def validate_lineage_marker(self) -> "ClaimProvenanceProviderItemV3":
        if (self.lineage_target_id is None) == (not self.is_explicit_new_claim):
            raise ValueError("claim needs exactly one lineage target or explicit new marker")
        return self


class ClaimDecompositionProviderOutputV3(BaseModel):
    """Provider output contains SourceUnit and frozen target IDs, never local refs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: tuple[ClaimProvenanceProviderItemV3, ...] = Field(min_length=1)


class ClaimProvenanceItemV3(ClaimProvenanceItemV2):
    lineage_target_id: NonEmptyStr | None = None
    is_explicit_new_claim: bool = False

    @model_validator(mode="after")
    def validate_lineage_marker(self) -> "ClaimProvenanceItemV3":
        if (self.lineage_target_id is None) == (not self.is_explicit_new_claim):
            raise ValueError("claim needs exactly one lineage target or explicit new marker")
        return self


class ClaimDecompositionResultV3(BaseModel):
    """Accepted claim records with locally resolved provenance and explicit mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-provenance-lineage-v3"]
    schema_version: Literal[3]
    research_plan_version: int = Field(ge=1)
    hypothesis_id: NonEmptyStr
    hypothesis_content_hash: CanonicalSha256
    claims: tuple[ClaimProvenanceItemV3, ...]

    @model_validator(mode="after")
    def validate_claims(self) -> "ClaimDecompositionResultV3":
        if not self.claims or not any(claim.importance == "critical" for claim in self.claims):
            raise ValueError("decomposition requires at least one critical claim")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim IDs must be unique")
        return self


def validate_decomposition_target_ids_v3(
    result: ClaimDecompositionResultV3, *, allowed_target_ids: tuple[str, ...],
) -> None:
    """Require target references to exist in the caller's exact frozen target set."""

    allowed = set(allowed_target_ids)
    if len(allowed) != len(allowed_target_ids):
        raise ValueError("duplicate frozen lineage target identity")
    if any(claim.lineage_target_id is not None and claim.lineage_target_id not in allowed
           for claim in result.claims):
        raise ValueError("unknown lineage target in child decomposition")


class EvidenceBindingProposalV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: NonEmptyStr
    evidence_unit_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    relation_to_claim: Literal["supports", "contradicts", "context"]
    prior_art_role: Literal[
        "direct_prior_art", "partial_prior_art", "component_known",
        "competing_mechanism", "background",
    ]
    evidence_strength: Literal[
        "title_only", "abstract_context", "abstract_support", "abstract_contradiction",
    ]
    rationale: NonEmptyStr
    diagnostic_quote: str | None = None


class ClaimAssessmentProposalV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: NonEmptyStr
    proposed_outcome: Literal[
        "verified", "contradicted", "inconclusive", "insufficient_evidence",
    ]
    evidence_limitations: tuple[NonEmptyStr, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    unresolved_state: NonEmptyStr


class ClaimVerificationProviderOutputV2(BaseModel):
    """Provider output; evidence lists and prior-art status are intentionally absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bindings: tuple[EvidenceBindingProposalV2, ...]
    claim_assessments: tuple[ClaimAssessmentProposalV2, ...]
    strongest_supported_premise: NonEmptyStr
    weakest_causal_link: NonEmptyStr
    most_novel_looking_bridge: NonEmptyStr
    direct_prior_art_risk: NonEmptyStr
    main_competing_explanation: NonEmptyStr
    critical_unresolved_evidence_gap: NonEmptyStr


class ClaimVerificationResultV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-verification-result-v2"]
    schema_version: Literal[2]
    research_plan_version: int = Field(ge=1)
    hypothesis_id: NonEmptyStr
    hypothesis_content_hash: CanonicalSha256
    bindings: tuple[EvidenceBindingProposalV2, ...]
    claim_assessments: tuple[ClaimAssessmentProposalV2, ...]
    strongest_supported_premise: NonEmptyStr
    weakest_causal_link: NonEmptyStr
    most_novel_looking_bridge: NonEmptyStr
    direct_prior_art_risk: NonEmptyStr
    main_competing_explanation: NonEmptyStr
    critical_unresolved_evidence_gap: NonEmptyStr

    @model_validator(mode="after")
    def validate_claim_scope(self) -> "ClaimVerificationResultV2":
        assessment_ids = [item.claim_id for item in self.claim_assessments]
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("claim assessments must be unique")
        return self


class ClaimSearchPlanResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    hypothesis_id: NonEmptyStr
    hypothesis_content_hash: CanonicalSha256
    proposals: tuple[ToolRequestProposal, ...]
    result_tool_resolution: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def check_queries(self) -> "ClaimSearchPlanResultV1":
        if not self.proposals:
            raise ValueError("claim search plan requires proposals")
        identities = [(p.claim_id, p.intent, p.round) for p in self.proposals]
        if len(identities) != len(set(identities)):
            raise ValueError("claim search intents must be unique per claim and round")
        return self


class ClaimReviewSummaryV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: NonEmptyStr
    supporting_evidence_ids: tuple[NonEmptyStr, ...] = ()
    contradictory_evidence_ids: tuple[NonEmptyStr, ...] = ()
    prior_art_evidence_ids: tuple[NonEmptyStr, ...] = ()
    competing_mechanism_evidence_ids: tuple[NonEmptyStr, ...] = ()
    evidence_limitations: tuple[NonEmptyStr, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    unresolved_state: NonEmptyStr


class ClaimVerificationResultV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1)
    hypothesis_id: NonEmptyStr
    hypothesis_content_hash: CanonicalSha256
    bindings: tuple[ClaimEvidenceBinding, ...]
    claim_reviews: tuple[ClaimReviewSummaryV1, ...]
    prior_art: PriorArtAssessment
    strongest_supported_premise: NonEmptyStr
    weakest_causal_link: NonEmptyStr
    most_novel_looking_bridge: NonEmptyStr
    direct_prior_art_risk: NonEmptyStr
    main_competing_explanation: NonEmptyStr
    critical_unresolved_evidence_gap: NonEmptyStr

    @model_validator(mode="after")
    def check_review(self) -> "ClaimVerificationResultV1":
        if (self.prior_art.hypothesis_id != self.hypothesis_id
                or self.prior_art.hypothesis_content_hash != self.hypothesis_content_hash):
            raise ValueError("prior art does not match reviewed hypothesis")
        if len({b.binding_id for b in self.bindings}) != len(self.bindings):
            raise ValueError("binding IDs must be unique")
        if len({r.claim_id for r in self.claim_reviews}) != len(self.claim_reviews):
            raise ValueError("claim reviews must be unique")
        return self


CoreOutputSchemaId = Literal[
    "BaselineRankingResultV1",
    "BaselineEvolutionResultV1",
    "DirectiveEthicsResultV1",
    "RootQueryPlanResultV1",
    "RootRetrievalResultV1",
    "RootRetrievalResultV2",
    "RootLiteratureReviewResultV1",
    "GroundedGenerationResultV1",
    "CandidateEthicsResultV1",
    "BaselineReflectionResultV1",
    "GenerationResultV1",
    "ReflectionResultV1",
    "RankingResultV1",
    "EvolutionResultV1",
    "PopulationEvolutionResultV1",
    "PopulationEvolutionResultV2",
    "ProximityResultV1",
    "MetaReviewResultV1",
    "ClaimDecompositionResultV1",
    "ClaimSearchPlanResultV1",
    "ClaimVerificationResultV1",
    "ClaimDecompositionResultV2",
    "ClaimDecompositionResultV3",
    "ClaimVerificationResultV2",
]

CoreScientificResultV1: TypeAlias = (
    BaselineEvolutionResultV1
    | BaselineRankingResultV1
    | DirectiveEthicsResultV1
    | RootQueryPlanResultV1
    | RootRetrievalResultV1
    | RootRetrievalResultV2
    | RootLiteratureReviewResultV1
    | GroundedGenerationResultV1
    | CandidateEthicsResultV1
    | BaselineReflectionResultV1
    | GenerationResultV1
    | ReflectionResultV1
    | RankingResultV1
    | EvolutionResultV1
    | PopulationEvolutionResultV1
    | PopulationEvolutionResultV2
    | ProximityResultV1
    | MetaReviewResultV1
    | ClaimDecompositionResultV1
    | ClaimSearchPlanResultV1
    | ClaimVerificationResultV1
    | ClaimDecompositionResultV2
    | ClaimDecompositionResultV3
    | ClaimVerificationResultV2
)

_SCHEMA_REGISTRY: Mapping[tuple[str, int], type[BaseModel]] = MappingProxyType(
    {
        ("BaselineRankingResultV1", 1): BaselineRankingResultV1,
        ("BaselineEvolutionResultV1", 1): BaselineEvolutionResultV1,
        ("DirectiveEthicsResultV1", 1): DirectiveEthicsResultV1,
        ("RootQueryPlanResultV1", 1): RootQueryPlanResultV1,
        ("RootRetrievalResultV1", 1): RootRetrievalResultV1,
        ("RootRetrievalResultV2", 2): RootRetrievalResultV2,
        ("RootLiteratureReviewResultV1", 1): RootLiteratureReviewResultV1,
        ("GroundedGenerationResultV1", 1): GroundedGenerationResultV1,
        ("CandidateEthicsResultV1", 1): CandidateEthicsResultV1,
        ("BaselineReflectionResultV1", 1): BaselineReflectionResultV1,
        ("GenerationResultV1", 1): GenerationResultV1,
        ("ReflectionResultV1", 1): ReflectionResultV1,
        ("RankingResultV1", 1): RankingResultV1,
        ("EvolutionResultV1", 1): EvolutionResultV1,
        ("PopulationEvolutionResultV1", 1): PopulationEvolutionResultV1,
        ("PopulationEvolutionResultV2", 2): PopulationEvolutionResultV2,
        ("ProximityResultV1", 1): ProximityResultV1,
        ("MetaReviewResultV1", 1): MetaReviewResultV1,
        ("ClaimDecompositionResultV1", 1): ClaimDecompositionResultV1,
        ("ClaimSearchPlanResultV1", 1): ClaimSearchPlanResultV1,
        ("ClaimVerificationResultV1", 1): ClaimVerificationResultV1,
        ("ClaimDecompositionResultV2", 2): ClaimDecompositionResultV2,
        ("ClaimDecompositionResultV3", 3): ClaimDecompositionResultV3,
        ("ClaimVerificationResultV2", 2): ClaimVerificationResultV2,
    }
)


def resolve_output_schema(schema_id: str, schema_version: int) -> type[BaseModel]:
    """Resolve one exact Core schema identity, failing closed for all others."""

    try:
        return _SCHEMA_REGISTRY[(schema_id, schema_version)]
    except KeyError as error:
        raise ValueError(f"unknown output schema: {schema_id} v{schema_version}") from error


def output_schema_version(schema_id: CoreOutputSchemaId) -> int:
    """Read the sole registered version for an exact schema ID; never fall back."""

    matches = [version for name, version in _SCHEMA_REGISTRY if name == schema_id]
    if len(matches) != 1:
        raise ValueError(f"output schema has no unique version: {schema_id}")
    return matches[0]


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
