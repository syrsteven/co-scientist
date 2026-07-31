from co_scientist.domain.proximity import ProximityEdge
from co_scientist.domain.review import NoveltyAssessment, NoveltyVerdict


def test_proximity_has_no_literature_novelty_verdict() -> None:
    edge = ProximityEdge(left_id="h-1", right_id="h-2", similarity=4)
    assert "novelty_verdict" not in type(edge).model_fields
    assessment = NoveltyAssessment(
        assessment_id="n-1",
        hypothesis_id="h-1",
        content_hash="sha256:abc",
        research_plan_version=1,
        verdict=NoveltyVerdict.PARTIALLY_NOVEL,
        closest_prior_work_ids=("pmid:1",),
    )
    assert assessment.verdict is NoveltyVerdict.PARTIALLY_NOVEL
