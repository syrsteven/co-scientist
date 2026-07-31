import pytest
from pydantic import ValidationError

from co_scientist.domain.hypothesis import HypothesisContent, HypothesisProjection


def test_scientific_content_is_frozen_but_projection_is_rebuildable() -> None:
    content = HypothesisContent(
        content_id="h-content-1",
        title="Capsular mechanics gate lens epithelial cell fate",
        claim="Early capsule strain biases residual cells toward ordered fibers.",
        mechanism_chain=("surgery", "strain", "cell_state", "morphogenesis", "transparency"),
        assumptions=("strain is sensed before EMT commitment",),
        predictions=("early strain normalization reduces fibrosis",),
        falsifiers=("strain changes without cell-state or morphology changes",),
    )
    with pytest.raises(ValidationError):
        content.title = "mutated"

    projection = HypothesisProjection(hypothesis_id="h-1", content_id=content.content_id)
    updated = projection.model_copy(update={"lifecycle_state": "screening"})
    assert updated.lifecycle_state == "screening"
    assert content.title.startswith("Capsular")
