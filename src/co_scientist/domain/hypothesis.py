import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class HypothesisContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_id: str
    title: str
    claim: str
    mechanism_chain: tuple[str, ...]
    assumptions: tuple[str, ...]
    predictions: tuple[str, ...]
    falsifiers: tuple[str, ...]
    parent_content_ids: tuple[str, ...] = ()
    supersedes_content_id: str | None = None

    @computed_field
    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            {
                "title": self.title,
                "claim": self.claim,
                "mechanism_chain": self.mechanism_chain,
                "assumptions": self.assumptions,
                "predictions": self.predictions,
                "falsifiers": self.falsifiers,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
