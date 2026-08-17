import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from co_scientist.agents.payloads import HypothesisDraftV1


def canonical_hypothesis_bytes(content: "HypothesisContent") -> bytes:
    """Serialize only the complete scientific semantics of hypothesis content."""

    return json.dumps(
        {
            "assumptions": content.assumptions,
            "claim": content.claim,
            "falsifiers": content.falsifiers,
            "generation_strategy": content.generation_strategy,
            "mechanism_chain": content.mechanism_chain,
            "predictions": content.predictions,
            "title": content.title,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def compute_hypothesis_content_hash(content: "HypothesisContent") -> str:
    """Compute the system-authoritative SHA-256 for canonical scientific content."""

    return "sha256:" + hashlib.sha256(canonical_hypothesis_bytes(content)).hexdigest()


class HypothesisContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_id: str
    title: str
    claim: str
    mechanism_chain: tuple[str, ...]
    assumptions: tuple[str, ...]
    predictions: tuple[str, ...]
    falsifiers: tuple[str, ...]
    generation_strategy: str
    parent_content_ids: tuple[str, ...] = ()
    supersedes_content_id: str | None = None

    @computed_field  # type: ignore[prop-decorator]  # Pydantic computed property
    @property
    def content_hash(self) -> str:
        return compute_hypothesis_content_hash(self)


def hypothesis_content_from_draft(draft: HypothesisDraftV1) -> HypothesisContent:
    """Convert a typed draft and reject a forged provider content fingerprint."""

    content = HypothesisContent(
        content_id=draft.content_id,
        title=draft.title,
        claim=draft.claim,
        mechanism_chain=draft.mechanism_chain,
        assumptions=draft.assumptions,
        predictions=draft.predictions,
        falsifiers=draft.falsifiers,
        generation_strategy=draft.generation_strategy,
        parent_content_ids=draft.parent_content_ids,
        supersedes_content_id=draft.supersedes_content_id,
    )
    authoritative_hash = compute_hypothesis_content_hash(content)
    if draft.content_hash is not None and draft.content_hash != authoritative_hash:
        raise ValueError("provider content hash does not match canonical content hash")
    return content


class ContentRevisionProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_id: str
    content_hash: str
    research_plan_version: int
    parent_content_ids: tuple[str, ...] = ()
    supersedes_content_id: str | None = None
    created_sequence: int


class ReviewProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: str
    content_hash: str
    research_plan_version: int
    stage: str
    recommendation: str
    safety_status: str
    critical_flaws: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    sequence: int
    applies_to_current_revision: bool


class SafetyEvidenceProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: Literal["review", "meta_review"]
    source_id: str
    content_hash: str
    status: str
    sequence: int
    applies_to_current_revision: bool


class NoveltyProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: str
    content_hash: str
    research_plan_version: int
    verdict: str
    closest_prior_work_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    sequence: int
    applies_to_current_revision: bool


class ProximityProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: str
    own_content_hash: str
    other_hypothesis_id: str
    other_content_hash: str
    research_plan_version: int
    similarity: int
    mechanism_overlap: tuple[str, ...] = ()
    duplicate_likelihood: float
    cluster_suggestion: str | None = None
    rationale: str
    access_issues: tuple[str, ...] = ()
    sequence: int
    applies_to_current_revision: bool


class TournamentEntryProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    epoch_id: str
    content_hash: str
    initial_rating: float
    matches_played: int = 0
    created_sequence: int


class RatingProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    epoch_id: str
    rating: float
    rating_policy_version: str
    source: Literal["initial", "match"]
    sequence: int
    match_id: str | None = None
    before_rating: float | None = None


class MatchParticipationProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_id: str
    epoch_id: str
    opponent_id: str
    own_content_hash: str
    opponent_content_hash: str
    research_plan_version: int
    decision: str
    winner_id: str | None = None
    sequence: int
    applies_to_current_revision: bool


class HypothesisProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str
    content_revisions: tuple[ContentRevisionProjection, ...] = ()
    current_content_id: str
    current_content_hash: str
    current_research_plan_version: int
    lifecycle_state: Literal[
        "created",
        "screening",
        "admission_pending",
        "tournament_ready",
        "tournament_active",
        "rejected",
        "safety_blocked",
        "duplicate_archived",
        "archived",
    ] = "created"
    current_safety_status: str = "pending"
    safety_evidence: tuple[SafetyEvidenceProjection, ...] = ()
    review_history: tuple[ReviewProjection, ...] = ()
    review_coverage_by_content: dict[str, dict[str, tuple[str, ...]]] = Field(
        default_factory=dict
    )
    novelty_history: tuple[NoveltyProjection, ...] = ()
    current_novelty_assessment_ids: tuple[str, ...] = ()
    proximity_history: tuple[ProximityProjection, ...] = ()
    cluster_ids: tuple[str, ...] = ()
    access_issues: tuple[str, ...] = ()
    tournament_entries_by_epoch: dict[str, TournamentEntryProjection] = Field(
        default_factory=dict
    )
    rating_history: tuple[RatingProjection, ...] = ()
    current_ratings_by_epoch: dict[str, float] = Field(default_factory=dict)
    match_participation: tuple[MatchParticipationProjection, ...] = ()
    created_sequence: int
    updated_sequence: int
