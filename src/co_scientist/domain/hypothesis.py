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


class HypothesisProjection(BaseModel):
    hypothesis_id: str
    content_id: str
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
    safety_status: str = "pending"
    review_coverage: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    novelty_assessment_ids: tuple[str, ...] = ()
    tournament_entries_by_epoch: dict[str, str] = Field(default_factory=dict)
    ratings_by_epoch: dict[str, float] = Field(default_factory=dict)
    cluster_ids: tuple[str, ...] = ()
