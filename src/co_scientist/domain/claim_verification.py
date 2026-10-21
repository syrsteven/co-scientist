"""Immutable, content-bound Research v2 claim and PubMed evidence contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from co_scientist.domain.evidence_units import (
    EvidenceUnitV1,
    evidence_units_for_snapshot,
    resolve_evidence_units,
)
from co_scientist.domain.source_units import SourceUnit
from co_scientist.ports.artifact_store import ArtifactRef

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]
SearchIntent = Literal["support", "refute", "prior_work", "competing_mechanism"]


def scientific_hash(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ClaimVerificationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["claim-pubmed-v1"] = "claim-pubmed-v1"
    max_critical_claims_per_hypothesis: int = Field(default=3, ge=1, le=20, strict=True)
    max_search_rounds_per_claim: int = Field(default=2, ge=1, le=5, strict=True)
    max_queries_per_claim: int = Field(default=4, ge=1, le=12, strict=True)
    max_results_per_query: int = Field(default=5, ge=1, le=50, strict=True)
    max_sources_per_claim: int = Field(default=12, ge=1, le=50, strict=True)
    max_evidence_tokens_per_review: int = Field(default=4000, ge=100, le=32000, strict=True)
    external_call_timeout: int = Field(default=30, ge=1, le=120, strict=True)


class ClaimDecompositionOutputPolicy(BaseModel):
    """Opt-in bounded selection of claims for one hypothesis's verification pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["bounded-essential-v1"] = "bounded-essential-v1"
    max_total_claims: int = Field(default=8, ge=1, le=20, strict=True)


class HypothesisClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: Text
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    text: Text
    claim_type: Literal[
        "established_premise", "bridging_inference", "novel_causal_claim",
        "prediction", "competing_explanation",
    ]
    importance: Literal["critical", "supporting"]
    subject: Text
    relation: Text
    object: Text
    source_span: Text
    source_relation: Literal["direct", "paraphrase", "synthesized_from"] | None = Field(
        default=None, exclude_if=lambda value: value is None)
    source_unit_refs: tuple[SourceUnit, ...] = Field(
        default=(), exclude_if=lambda value: not value)
    model_quote: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ToolRequestProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: Text
    claim_content_hash: Sha256
    intent: SearchIntent
    provider: Literal["pubmed"]
    query: Text
    rationale: Text
    seen_source_ids: tuple[Text, ...] = ()
    round: int = Field(ge=1, strict=True)
    fresh_retrieval: bool = False


class SearchSession(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: Text
    task_id: Text
    hypothesis_id: Text
    claim_id: Text
    intent: SearchIntent
    round: int = Field(ge=1, strict=True)
    query_ids: tuple[Text, ...]
    seen_source_ids: tuple[Text, ...] = ()
    state: Literal["planned", "searching", "retrieving", "completed", "stopped"]
    stop_reason: Literal[
        "sufficient_evidence", "query_limit", "result_limit", "budget_limit",
        "no_additional_sources", "provider_error", "user_stop",
    ] | None = None

    @model_validator(mode="after")
    def check_stop(self) -> SearchSession:
        if (self.state == "stopped") != (self.stop_reason is not None):
            raise ValueError("stopped search session requires exactly one stop reason")
        return self


class EvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: Text
    provider: Literal["pubmed"]
    source_id: Text
    retrieved_at: Text
    raw_artifact_id: Text
    raw_sha256: Sha256
    title: Text
    abstract: str | None = None
    publication_metadata: dict[str, Any]
    content_level: Literal["title", "abstract"]
    snapshot_hash: Sha256

    @model_validator(mode="after")
    def verify_hash(self) -> EvidenceSnapshot:
        values = self.model_dump(mode="json", exclude={"snapshot_hash"})
        if scientific_hash(values) != self.snapshot_hash:
            raise ValueError("evidence snapshot hash mismatch")
        if self.content_level == "abstract" and not self.abstract:
            raise ValueError("abstract evidence requires abstract text")
        return self


class ClaimEvidenceBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: Text
    claim_id: Text
    claim_content_hash: Sha256
    evidence_snapshot_id: Text
    relation: Literal["supports", "contradicts", "context", "unclear"]
    evidence_strength: Literal[
        "title_only", "abstract_context", "abstract_support", "abstract_contradiction",
    ]
    rationale: Text
    source_span_or_excerpt_location: Text

    @model_validator(mode="after")
    def check_strength(self) -> ClaimEvidenceBinding:
        if self.evidence_strength == "title_only" and self.relation in {"supports", "contradicts"}:
            raise ValueError("title-only evidence cannot establish support or contradiction")
        if self.evidence_strength == "abstract_support" and self.relation != "supports":
            raise ValueError("abstract support strength requires supports relation")
        if self.evidence_strength == "abstract_contradiction" and self.relation != "contradicts":
            raise ValueError("abstract contradiction strength requires contradicts relation")
        return self


class PriorArtAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: Text
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    critical_claim_ids: tuple[Text, ...]
    status: Literal[
        "direct_prior_art_found", "partial_prior_art_found",
        "components_known_bridge_not_found", "no_related_work_retrieved_under_scope",
        "indeterminate",
    ]
    search_scope: Text
    searched_queries: tuple[Text, ...]
    source_ids: tuple[Text, ...]
    direct_prior_art: tuple[Text, ...] = ()
    partial_prior_art: tuple[Text, ...] = ()
    missing_links: tuple[Text, ...] = ()
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def check_scope(self) -> PriorArtAssessment:
        if not self.limitations:
            raise ValueError("prior-art assessment requires search limitations")
        if self.status == "no_related_work_retrieved_under_scope" and self.source_ids:
            raise ValueError("no-related-work status cannot cite retrieved sources")
        if self.status == "components_known_bridge_not_found" and not self.missing_links:
            raise ValueError("missing bridge status requires an explicit missing link")
        return self


ClaimVerificationContractStateV2 = Literal["complete", "verification_incomplete"]
RelationToClaimV2 = Literal["supports", "contradicts", "context"]
PriorArtRoleV2 = Literal[
    "direct_prior_art", "partial_prior_art", "component_known",
    "competing_mechanism", "background",
]
RequiredSearchIntentV2 = ("support", "refute", "prior_work", "competing_mechanism")
PriorArtStatusV2 = Literal[
    "direct_prior_art_found", "partial_prior_art_found",
    "components_known_bridge_not_found", "no_related_work_retrieved_under_scope",
    "indeterminate",
]


class EvidenceBindingV2(BaseModel):
    """Validated, locally bound evidence relation; the sole V2 evidence fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["evidence-binding-v2"] = "evidence-binding-v2"
    binding_id: Text
    claim_id: Text
    claim_content_hash: Sha256
    evidence_snapshot_id: Text
    evidence_snapshot_hash: Sha256
    evidence_unit_refs: tuple[EvidenceUnitV1, ...] = Field(min_length=1)
    relation_to_claim: RelationToClaimV2
    prior_art_role: PriorArtRoleV2
    evidence_strength: Literal[
        "title_only", "abstract_context", "abstract_support", "abstract_contradiction",
    ]
    rationale: Text
    diagnostic_quote: str | None = None

    @model_validator(mode="after")
    def validate_binding(self) -> EvidenceBindingV2:
        if len({unit.evidence_unit_id for unit in self.evidence_unit_refs}) != len(
            self.evidence_unit_refs
        ):
            raise ValueError("duplicate EvidenceUnit in binding")
        if any(
            unit.evidence_snapshot_id != self.evidence_snapshot_id
            or unit.evidence_snapshot_hash != self.evidence_snapshot_hash
            for unit in self.evidence_unit_refs
        ):
            raise ValueError("EvidenceBindingV2 must resolve to one exact snapshot")
        for unit in self.evidence_unit_refs:
            EvidenceUnitV1.model_validate(unit.model_dump(mode="python"))
        if self.evidence_strength == "title_only" and self.relation_to_claim != "context":
            raise ValueError("title-only evidence cannot establish support or contradiction")
        if self.evidence_strength == "abstract_support" and self.relation_to_claim != "supports":
            raise ValueError("abstract support strength requires supports relation")
        if (
            self.evidence_strength == "abstract_contradiction"
            and self.relation_to_claim != "contradicts"
        ):
            raise ValueError("abstract contradiction strength requires contradicts relation")
        return self

    @classmethod
    def from_resolved(
        cls,
        *,
        claim_id: str,
        claim_content_hash: str,
        evidence_unit_refs: tuple[EvidenceUnitV1, ...],
        relation_to_claim: RelationToClaimV2,
        prior_art_role: PriorArtRoleV2,
        evidence_strength: Literal[
            "title_only", "abstract_context", "abstract_support", "abstract_contradiction",
        ],
        rationale: str,
        diagnostic_quote: str | None = None,
    ) -> EvidenceBindingV2:
        if not evidence_unit_refs:
            raise ValueError("EvidenceBindingV2 requires EvidenceUnit provenance")
        snapshot_ids = {unit.evidence_snapshot_id for unit in evidence_unit_refs}
        snapshot_hashes = {unit.evidence_snapshot_hash for unit in evidence_unit_refs}
        if len(snapshot_ids) != 1 or len(snapshot_hashes) != 1:
            raise ValueError("EvidenceBindingV2 cannot mix snapshots")
        snapshot_id = next(iter(snapshot_ids))
        snapshot_hash = next(iter(snapshot_hashes))
        body = {
            "contract_version": "evidence-binding-v2",
            "claim_id": claim_id,
            "claim_content_hash": claim_content_hash,
            "evidence_snapshot_id": snapshot_id,
            "evidence_snapshot_hash": snapshot_hash,
            "evidence_unit_ids": [unit.evidence_unit_id for unit in evidence_unit_refs],
            "relation_to_claim": relation_to_claim,
            "prior_art_role": prior_art_role,
            "evidence_strength": evidence_strength,
            "rationale": rationale,
        }
        return cls(
            binding_id="evidence-binding-v2:" + scientific_hash(body).removeprefix("sha256:"),
            claim_id=claim_id,
            claim_content_hash=claim_content_hash,
            evidence_snapshot_id=snapshot_id,
            evidence_snapshot_hash=snapshot_hash,
            evidence_unit_refs=evidence_unit_refs,
            relation_to_claim=relation_to_claim,
            prior_art_role=prior_art_role,
            evidence_strength=evidence_strength,
            rationale=rationale,
            diagnostic_quote=diagnostic_quote,
        )


class ClaimReviewProjectionV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-review-projection-v2"] = "claim-review-projection-v2"
    claim_id: Text
    supporting_evidence_ids: tuple[Text, ...] = ()
    contradictory_evidence_ids: tuple[Text, ...] = ()
    context_evidence_ids: tuple[Text, ...] = ()
    prior_art_evidence_ids: tuple[Text, ...] = ()
    competing_mechanism_evidence_ids: tuple[Text, ...] = ()
    evidence_limitations: tuple[Text, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    unresolved_state: Text


class SearchCoverageItemV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: Text
    intent: SearchIntent
    query_ids: tuple[Text, ...] = Field(min_length=1)
    raw_persisted: bool
    response_validated: bool
    applied: bool
    pagination_complete: bool
    result_count: int = Field(ge=0, strict=True)

    @property
    def complete(self) -> bool:
        return all((self.raw_persisted, self.response_validated, self.applied,
                    self.pagination_complete))


class SearchCoverageV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["search-coverage-v2"]
    items: tuple[SearchCoverageItemV2, ...]

    @model_validator(mode="after")
    def unique_items(self) -> SearchCoverageV2:
        keys = [(item.claim_id, item.intent, item.query_ids) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate search coverage item")
        return self

    def complete_for(self, critical_claim_ids: tuple[str, ...]) -> bool:
        expected = {
            (claim_id, intent)
            for claim_id in critical_claim_ids
            for intent in RequiredSearchIntentV2
        }
        by_key: dict[tuple[str, str], list[SearchCoverageItemV2]] = {}
        for item in self.items:
            by_key.setdefault((item.claim_id, item.intent), []).append(item)
        return expected.issubset(by_key) and all(
            all(item.complete for item in by_key[key]) for key in expected
        )

    def has_retrieved_records(self, critical_claim_ids: tuple[str, ...]) -> bool:
        return any(
            item.claim_id in critical_claim_ids and item.result_count > 0
            for item in self.items
        )


class PriorArtAssessmentV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["prior-art-assessment-v2"] = "prior-art-assessment-v2"
    assessment_id: Text
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    critical_claim_ids: tuple[Text, ...]
    status: PriorArtStatusV2
    search_scope: Text
    searched_queries: tuple[Text, ...]
    source_ids: tuple[Text, ...]
    evidence_binding_ids: tuple[Text, ...]
    missing_links: tuple[Text, ...]
    limitations: tuple[Text, ...]


class ClaimStateV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal[
        "claim-verification-contract-state-v2"
    ] = "claim-verification-contract-state-v2"
    claim_id: Text
    status: ClaimVerificationContractStateV2
    reason: Text | None = None


class BindingFailureV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: Text
    category: Literal["invalid_evidence_provenance", "claim_binding_mismatch"]
    reason: Text
    binding_index: int = Field(ge=0, strict=True)
    proposal_hash: Sha256
    proposed_evidence_unit_ids: tuple[Text, ...]


class V1CompatibleClaimReview(BaseModel):
    """Frozen V1 scientific-review fields derived from V2 bindings and assessment notes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: Text
    supporting_evidence_ids: tuple[Text, ...] = ()
    contradictory_evidence_ids: tuple[Text, ...] = ()
    prior_art_evidence_ids: tuple[Text, ...] = ()
    competing_mechanism_evidence_ids: tuple[Text, ...] = ()
    evidence_limitations: tuple[Text, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    unresolved_state: Text


class V1CompatibleClaimVerificationView(BaseModel):
    """Shape adapter only; it does not create or infer a scientific verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal[
        "v1-compatible-claim-verification-view-v1"
    ] = "v1-compatible-claim-verification-view-v1"
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    claim_reviews: tuple[V1CompatibleClaimReview, ...]
    prior_art: PriorArtAssessment
    strongest_supported_premise: Text
    weakest_causal_link: Text
    most_novel_looking_bridge: Text
    direct_prior_art_risk: Text
    main_competing_explanation: Text
    critical_unresolved_evidence_gap: Text


class ClaimVerificationApplicationV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-verification-application-v2"]
    bindings: tuple[EvidenceBindingV2, ...]
    claim_reviews: tuple[ClaimReviewProjectionV2, ...]
    prior_art: PriorArtAssessmentV2
    claim_states: tuple[ClaimStateV2, ...]
    binding_failures: tuple[BindingFailureV2, ...]
    v1_compatible_view: V1CompatibleClaimVerificationView | None = None

    @model_validator(mode="after")
    def validate_projection_gate(self) -> ClaimVerificationApplicationV2:
        claim_ids = [item.claim_id for item in self.claim_states]
        if not claim_ids or len(claim_ids) != len(set(claim_ids)):
            raise ValueError("V2 application requires unique critical claim contract states")
        incomplete = any(item.status == "verification_incomplete" for item in self.claim_states)
        if incomplete == (self.v1_compatible_view is not None):
            raise ValueError("V1-compatible view presence must match complete V2 contract state")
        failed_claim_ids = {failure.claim_id for failure in self.binding_failures}
        complete_claim_ids = {
            item.claim_id for item in self.claim_states if item.status == "complete"
        }
        if failed_claim_ids & complete_claim_ids:
            raise ValueError("binding failure cannot coexist with a complete claim state")
        if set(claim_ids) != set(self.prior_art.critical_claim_ids):
            raise ValueError("V2 claim states do not cover PriorArt critical claims")
        if self.v1_compatible_view is not None and (
            self.v1_compatible_view.hypothesis_id != self.prior_art.hypothesis_id
            or self.v1_compatible_view.hypothesis_content_hash
            != self.prior_art.hypothesis_content_hash
        ):
            raise ValueError("V1-compatible view does not match V2 prior-art content binding")
        return self


class ClaimVerificationAppliedEventV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-verification-applied-v2"]
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    research_plan_version: int = Field(ge=1, strict=True)
    application: ClaimVerificationApplicationV2
    source_raw_artifact_ref: ArtifactRef
    source_result_id: Text
    source_task_id: Text

    @model_validator(mode="after")
    def validate_content_binding(self) -> ClaimVerificationAppliedEventV2:
        if (
            self.application.prior_art.hypothesis_id != self.hypothesis_id
            or self.application.prior_art.hypothesis_content_hash
            != self.hypothesis_content_hash
        ):
            raise ValueError("V2 application event does not match hypothesis content")
        return self


class ClaimVerificationBindingRejectedEventV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["claim-verification-binding-rejected-v2"]
    hypothesis_id: Text
    hypothesis_content_hash: Sha256
    claim_id: Text
    category: Literal["invalid_evidence_provenance", "claim_binding_mismatch"]
    reason: Text
    binding_index: int = Field(ge=0, strict=True)
    proposal_hash: Sha256
    proposed_evidence_unit_ids: tuple[Text, ...]
    source_raw_artifact_ref: ArtifactRef
    source_result_id: Text
    source_task_id: Text


def _unique_in_order(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def derive_claim_reviews_v2(
    *, bindings: tuple[EvidenceBindingV2, ...], assessments: tuple[Any, ...],
    critical_claim_ids: tuple[str, ...],
) -> tuple[ClaimReviewProjectionV2, ...]:
    assessment_by_claim = {item.claim_id: item for item in assessments}
    result: list[ClaimReviewProjectionV2] = []
    for claim_id in critical_claim_ids:
        rows = tuple(binding for binding in bindings if binding.claim_id == claim_id)
        assessment = assessment_by_claim.get(claim_id)
        result.append(ClaimReviewProjectionV2(
            claim_id=claim_id,
            supporting_evidence_ids=_unique_in_order([
                row.evidence_snapshot_id for row in rows if row.relation_to_claim == "supports"
            ]),
            contradictory_evidence_ids=_unique_in_order([
                row.evidence_snapshot_id for row in rows
                if row.relation_to_claim == "contradicts"
            ]),
            context_evidence_ids=_unique_in_order([
                row.evidence_snapshot_id for row in rows if row.relation_to_claim == "context"
            ]),
            prior_art_evidence_ids=_unique_in_order([
                row.evidence_snapshot_id for row in rows
                if row.prior_art_role in {"direct_prior_art", "partial_prior_art", "component_known"}
            ]),
            competing_mechanism_evidence_ids=_unique_in_order([
                row.evidence_snapshot_id for row in rows
                if row.prior_art_role == "competing_mechanism"
            ]),
            evidence_limitations=assessment.evidence_limitations if assessment else (),
            confidence=assessment.confidence if assessment else 0.0,
            unresolved_state=assessment.unresolved_state if assessment else "verification incomplete",
        ))
    return tuple(result)


def derive_prior_art_assessment_v2(
    *, hypothesis_id: str, hypothesis_content_hash: str,
    critical_claim_ids: tuple[str, ...], bindings: tuple[EvidenceBindingV2, ...],
    search_coverage: SearchCoverageV2, searched_queries: tuple[str, ...],
    retrieved_source_ids: tuple[str, ...], snapshot_source_ids: dict[str, str], search_scope: str,
    limitations: tuple[str, ...],
) -> PriorArtAssessmentV2:
    roles = {binding.prior_art_role for binding in bindings}
    coverage_complete = search_coverage.complete_for(critical_claim_ids)
    prior_art_status: PriorArtStatusV2
    if "direct_prior_art" in roles:
        prior_art_status = "direct_prior_art_found"
    elif "partial_prior_art" in roles:
        prior_art_status = "partial_prior_art_found"
    elif "component_known" in roles and coverage_complete:
        prior_art_status = "components_known_bridge_not_found"
    elif coverage_complete and not retrieved_source_ids and not search_coverage.has_retrieved_records(
        critical_claim_ids
    ):
        prior_art_status = "no_related_work_retrieved_under_scope"
    else:
        prior_art_status = "indeterminate"
    missing_links = (
        ("critical causal bridge not directly retrieved",)
        if prior_art_status == "components_known_bridge_not_found" else ()
    )
    searched_query_values = _unique_in_order(searched_queries)
    source_id_values = _unique_in_order([
            snapshot_source_ids[binding.evidence_snapshot_id]
            for binding in bindings
            if binding.evidence_snapshot_id in snapshot_source_ids
    ])
    evidence_binding_ids = _unique_in_order([binding.binding_id for binding in bindings])
    body = {
        "contract_version": "prior-art-assessment-v2",
        "hypothesis_id": hypothesis_id,
        "hypothesis_content_hash": hypothesis_content_hash,
        "critical_claim_ids": critical_claim_ids,
        "status": prior_art_status,
        "search_scope": search_scope,
        "searched_queries": searched_query_values,
        "source_ids": source_id_values,
        "evidence_binding_ids": evidence_binding_ids,
        "missing_links": missing_links,
        "limitations": limitations,
    }
    return PriorArtAssessmentV2(
        assessment_id="prior-art-assessment-v2:" + scientific_hash(body).removeprefix("sha256:"),
        hypothesis_id=hypothesis_id,
        hypothesis_content_hash=hypothesis_content_hash,
        critical_claim_ids=critical_claim_ids,
        status=prior_art_status,
        search_scope=search_scope,
        searched_queries=searched_query_values,
        source_ids=source_id_values,
        evidence_binding_ids=evidence_binding_ids,
        missing_links=missing_links,
        limitations=limitations,
    )


def derive_v1_compatible_view(
    *,
    hypothesis_id: str,
    hypothesis_content_hash: str,
    bindings: tuple[EvidenceBindingV2, ...],
    claim_reviews: tuple[ClaimReviewProjectionV2, ...],
    prior_art: PriorArtAssessmentV2,
    summary: Any,
) -> V1CompatibleClaimVerificationView:
    """Adapt deterministic V2 evidence projections to frozen V1 consumer fields."""
    reviews = tuple(V1CompatibleClaimReview(
        claim_id=review.claim_id,
        supporting_evidence_ids=review.supporting_evidence_ids,
        contradictory_evidence_ids=review.contradictory_evidence_ids,
        prior_art_evidence_ids=review.prior_art_evidence_ids,
        competing_mechanism_evidence_ids=review.competing_mechanism_evidence_ids,
        evidence_limitations=review.evidence_limitations,
        confidence=review.confidence,
        unresolved_state=review.unresolved_state,
    ) for review in claim_reviews)

    def excerpts(role: PriorArtRoleV2) -> tuple[str, ...]:
        return _unique_in_order([
            unit.exact_text
            for binding in bindings if binding.prior_art_role == role
            for unit in binding.evidence_unit_refs
        ])

    direct_prior_art = excerpts("direct_prior_art")
    partial_prior_art = excerpts("partial_prior_art")
    prior_art_body = {
        "contract_version": "prior-art-assessment-v1-compatible-v1",
        "hypothesis_id": hypothesis_id,
        "hypothesis_content_hash": hypothesis_content_hash,
        "critical_claim_ids": prior_art.critical_claim_ids,
        "status": prior_art.status,
        "search_scope": prior_art.search_scope,
        "searched_queries": prior_art.searched_queries,
        "source_ids": prior_art.source_ids,
        "direct_prior_art": direct_prior_art,
        "partial_prior_art": partial_prior_art,
        "missing_links": prior_art.missing_links,
        "limitations": prior_art.limitations,
    }
    legacy_prior_art = PriorArtAssessment(
        assessment_id=("prior-art-assessment-v1-compatible:" +
                       scientific_hash(prior_art_body).removeprefix("sha256:")),
        hypothesis_id=hypothesis_id,
        hypothesis_content_hash=hypothesis_content_hash,
        critical_claim_ids=prior_art.critical_claim_ids,
        status=prior_art.status,
        search_scope=prior_art.search_scope,
        searched_queries=prior_art.searched_queries,
        source_ids=prior_art.source_ids,
        direct_prior_art=direct_prior_art,
        partial_prior_art=partial_prior_art,
        missing_links=prior_art.missing_links,
        limitations=prior_art.limitations,
    )
    return V1CompatibleClaimVerificationView(
        hypothesis_id=hypothesis_id,
        hypothesis_content_hash=hypothesis_content_hash,
        claim_reviews=reviews,
        prior_art=legacy_prior_art,
        strongest_supported_premise=summary.strongest_supported_premise,
        weakest_causal_link=summary.weakest_causal_link,
        most_novel_looking_bridge=summary.most_novel_looking_bridge,
        direct_prior_art_risk=summary.direct_prior_art_risk,
        main_competing_explanation=summary.main_competing_explanation,
        critical_unresolved_evidence_gap=summary.critical_unresolved_evidence_gap,
    )


def bind_claim_verification_v2(
    proposal: Any, *, task_inputs: dict[str, Any] | Any,
) -> ClaimVerificationApplicationV2:
    """Resolve EvidenceUnit IDs, contain invalid bindings per claim, derive projections."""
    from co_scientist.agents.payloads import ClaimVerificationProviderOutputV2

    provider = (
        proposal if isinstance(proposal, ClaimVerificationProviderOutputV2)
        else ClaimVerificationProviderOutputV2.model_validate(proposal)
    )
    if not isinstance(task_inputs, dict):
        task_inputs = dict(task_inputs)
    critical_claims = task_inputs.get("critical_claims")
    if not isinstance(critical_claims, list) or not critical_claims:
        raise ValueError("claim verification requires immutable critical claims")
    claim_hashes = {
        str(item["claim_id"]): str(item["hypothesis_content_hash"])
        for item in critical_claims
        if isinstance(item, dict) and item.get("importance") == "critical"
    }
    if len(claim_hashes) != len(critical_claims) or not claim_hashes:
        raise ValueError("critical claim task binding is invalid")
    snapshot_data = task_inputs.get("evidence_snapshots")
    if not isinstance(snapshot_data, list):
        raise TypeError("claim verification requires immutable EvidenceSnapshots")
    snapshots = tuple(EvidenceSnapshot.model_validate(item) for item in snapshot_data)
    derived_units = tuple(
        unit for snapshot in snapshots for unit in evidence_units_for_snapshot(snapshot)
    )
    unit_data = task_inputs.get("evidence_units")
    if not isinstance(unit_data, list):
        raise TypeError("claim verification requires immutable EvidenceUnits")
    units = tuple(EvidenceUnitV1.model_validate(item) for item in unit_data)
    if units != derived_units:
        raise ValueError("EvidenceUnits do not match frozen EvidenceSnapshots")
    units_by_id = {item.evidence_unit_id: item for item in units}
    if len(units_by_id) != len(units):
        raise ValueError("duplicate EvidenceUnit in task inputs")
    assessments = {item.claim_id: item for item in provider.claim_assessments}
    if len(assessments) != len(provider.claim_assessments):
        raise ValueError("claim assessment identities must be unique")
    if set(assessments) != set(claim_hashes):
        raise ValueError("claim assessments must cover every frozen critical claim")
    bound: list[EvidenceBindingV2] = []
    failures: list[BindingFailureV2] = []
    failed_claims: set[str] = set()
    for binding_index, item in enumerate(provider.bindings):
        try:
            if item.claim_id not in claim_hashes:
                raise ValueError("binding claim is outside immutable critical claims")
            requested = [units_by_id[unit_id] for unit_id in item.evidence_unit_ids]
            snapshot_ids = {unit.evidence_snapshot_id for unit in requested}
            snapshot_hashes = {unit.evidence_snapshot_hash for unit in requested}
            if len(snapshot_ids) != 1 or len(snapshot_hashes) != 1:
                raise ValueError("binding EvidenceUnits cross snapshot identity")
            resolved = resolve_evidence_units(
                item.evidence_unit_ids,
                expected_snapshot_id=next(iter(snapshot_ids)),
                expected_snapshot_hash=next(iter(snapshot_hashes)),
                allowed_units=units,
            )
            bound.append(EvidenceBindingV2.from_resolved(
                claim_id=item.claim_id,
                claim_content_hash=claim_hashes[item.claim_id],
                evidence_unit_refs=resolved,
                relation_to_claim=item.relation_to_claim,
                prior_art_role=item.prior_art_role,
                evidence_strength=item.evidence_strength,
                rationale=item.rationale,
                diagnostic_quote=item.diagnostic_quote,
            ))
        except (KeyError, ValueError, TypeError) as exc:
            failed_claims.add(item.claim_id)
            failures.append(BindingFailureV2(
                claim_id=item.claim_id,
                category=("claim_binding_mismatch" if item.claim_id not in claim_hashes
                          else "invalid_evidence_provenance"),
                reason=str(exc),
                binding_index=binding_index,
                proposal_hash=scientific_hash(item.model_dump(mode="json")),
                proposed_evidence_unit_ids=item.evidence_unit_ids,
            ))
    coverage = SearchCoverageV2.model_validate(task_inputs.get("search_coverage"))
    complete_claims = {
        claim_id for claim_id in claim_hashes
        if coverage.complete_for((claim_id,))
    }
    claims_with_bindings = {binding.claim_id for binding in bound}
    claim_states = []
    for claim_id in claim_hashes:
        if claim_id in failed_claims:
            status: ClaimVerificationContractStateV2 = "verification_incomplete"
            reason = "binding validation failed"
        elif claim_id not in claims_with_bindings:
            status = "verification_incomplete"
            reason = "missing authoritative EvidenceBindingV2 provenance"
        elif claim_id not in complete_claims:
            status = "verification_incomplete"
            reason = "search coverage incomplete"
        else:
            status = "complete"
            reason = None
        claim_states.append(ClaimStateV2(claim_id=claim_id, status=status, reason=reason))
    critical_ids = tuple(claim_hashes)
    review_projections = derive_claim_reviews_v2(
        bindings=tuple(bound), assessments=provider.claim_assessments,
        critical_claim_ids=critical_ids,
    )
    raw_queries = task_inputs.get("searched_queries", ())
    source_ids = task_inputs.get("retrieved_source_ids", ())
    limitations = task_inputs.get("limitations", ())
    source_id_by_snapshot = {item.snapshot_id: item.source_id for item in snapshots}
    prior_art = derive_prior_art_assessment_v2(
        hypothesis_id=str(task_inputs.get("hypothesis_id", "")),
        hypothesis_content_hash=str(task_inputs.get("content_hash", "")),
        critical_claim_ids=critical_ids,
        bindings=tuple(bound), search_coverage=coverage,
        searched_queries=tuple(str(value) for value in raw_queries),
        retrieved_source_ids=tuple(str(value) for value in source_ids),
        snapshot_source_ids=source_id_by_snapshot,
        search_scope=str(task_inputs.get("search_scope", "")),
        limitations=tuple(str(value) for value in limitations),
    )
    v1_compatible_view = None
    if all(state.status == "complete" for state in claim_states):
        v1_compatible_view = derive_v1_compatible_view(
            hypothesis_id=str(task_inputs.get("hypothesis_id", "")),
            hypothesis_content_hash=str(task_inputs.get("content_hash", "")),
            bindings=tuple(bound),
            claim_reviews=review_projections,
            prior_art=prior_art,
            summary=provider,
        )
    return ClaimVerificationApplicationV2(
        contract_version="claim-verification-application-v2",
        bindings=tuple(bound), claim_reviews=review_projections, prior_art=prior_art,
        claim_states=tuple(claim_states), binding_failures=tuple(failures),
        v1_compatible_view=v1_compatible_view,
    )
