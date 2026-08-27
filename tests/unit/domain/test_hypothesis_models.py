import pytest
from pydantic import ValidationError

from co_scientist.agents.payloads import HypothesisDraftV1
from co_scientist.domain.hypothesis import (
    ContentRevisionProjection,
    HypothesisContent,
    HypothesisProjection,
    canonical_hypothesis_bytes,
    compute_hypothesis_content_hash,
    hypothesis_content_from_draft,
)


def test_scientific_content_is_frozen_but_projection_is_rebuildable() -> None:
    content = HypothesisContent(
        content_id="h-content-1",
        title="Capsular mechanics gate lens epithelial cell fate",
        claim="Early capsule strain biases residual cells toward ordered fibers.",
        mechanism_chain=("surgery", "strain", "cell_state", "morphogenesis", "transparency"),
        assumptions=("strain is sensed before EMT commitment",),
        predictions=("early strain normalization reduces fibrosis",),
        falsifiers=("strain changes without cell-state or morphology changes",),
        generation_strategy="causal contrast",
    )
    with pytest.raises(ValidationError):
        content.title = "mutated"

    projection = HypothesisProjection(
        hypothesis_id="h-1",
        content_revisions=(
            ContentRevisionProjection(
                content_id=content.content_id,
                content_hash=content.content_hash,
                research_plan_version=1,
                created_sequence=1,
            ),
        ),
        current_content_id=content.content_id,
        current_content_hash=content.content_hash,
        current_research_plan_version=1,
        created_sequence=1,
        updated_sequence=1,
    )
    updated = projection.model_copy(update={"lifecycle_state": "screening"})
    assert updated.lifecycle_state == "screening"
    assert content.title.startswith("Capsular")


def test_canonical_hash_includes_all_semantics_but_excludes_identity_and_lineage() -> None:
    content = HypothesisContent(
        content_id="content-a",
        title="Mechanical gate",
        claim="Capsule strain precedes EMT commitment.",
        mechanism_chain=("strain", "YAP", "cell fate"),
        assumptions=("strain is sensed before commitment",),
        predictions=("normalizing strain reduces fibrosis",),
        falsifiers=("cell fate changes before strain",),
        generation_strategy="causal contrast",
        parent_content_ids=("parent-a",),
        supersedes_content_id="old-a",
    )
    same_semantics = content.model_copy(
        update={
            "content_id": "content-b",
            "parent_content_ids": ("parent-b",),
            "supersedes_content_id": "old-b",
        }
    )
    changed_semantics = content.model_copy(
        update={"predictions": ("a different prediction",)}
    )

    assert canonical_hypothesis_bytes(content) == canonical_hypothesis_bytes(same_semantics)
    assert compute_hypothesis_content_hash(content) == compute_hypothesis_content_hash(
        same_semantics
    )
    assert compute_hypothesis_content_hash(content) != compute_hypothesis_content_hash(
        changed_semantics
    )
    assert content.content_hash == compute_hypothesis_content_hash(content)


def test_canonical_hash_changes_with_generation_strategy() -> None:
    content = HypothesisContent(
        content_id="content-a",
        title="Mechanical gate",
        claim="Capsule strain precedes EMT commitment.",
        mechanism_chain=("strain", "YAP", "cell fate"),
        assumptions=("strain is sensed before commitment",),
        predictions=("normalizing strain reduces fibrosis",),
        falsifiers=("cell fate changes before strain",),
        generation_strategy="causal contrast",
    )
    changed_strategy = content.model_copy(update={"generation_strategy": "analogy"})

    assert canonical_hypothesis_bytes(content) != canonical_hypothesis_bytes(
        changed_strategy
    )
    assert compute_hypothesis_content_hash(content) != compute_hypothesis_content_hash(
        changed_strategy
    )


def test_draft_conversion_rejects_a_forged_provider_content_hash() -> None:
    draft = HypothesisDraftV1(
        schema_version=1,
        hypothesis_id="h-1",
        content_id="c-1",
        research_plan_version=1,
        title="Mechanical gate",
        claim="Capsule strain precedes EMT commitment.",
        mechanism_chain=("strain", "YAP", "cell fate"),
        assumptions=("strain is sensed before commitment",),
        predictions=("normalizing strain reduces fibrosis",),
        falsifiers=("cell fate changes before strain",),
        generation_strategy="causal contrast",
        content_hash="sha256:forged",
    )

    with pytest.raises(ValueError, match="content hash"):
        hypothesis_content_from_draft(draft)


def test_draft_conversion_preserves_generation_strategy() -> None:
    draft = HypothesisDraftV1(
        schema_version=1,
        hypothesis_id="h-1",
        content_id="c-1",
        research_plan_version=1,
        title="Mechanical gate",
        claim="Capsule strain precedes EMT commitment.",
        mechanism_chain=("strain", "YAP", "cell fate"),
        assumptions=("strain is sensed before commitment",),
        predictions=("normalizing strain reduces fibrosis",),
        falsifiers=("cell fate changes before strain",),
        generation_strategy="causal contrast",
    )

    content = hypothesis_content_from_draft(draft)

    assert content.generation_strategy == "causal contrast"
