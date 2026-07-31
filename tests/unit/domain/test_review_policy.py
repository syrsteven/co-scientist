from co_scientist.domain.review import ReviewPolicy, ReviewStage, required_review_stages


def test_initial_is_always_required_and_paper_faithful_adds_full() -> None:
    minimal = ReviewPolicy(profile_id="minimal", required_before_admission=())
    faithful = ReviewPolicy(
        profile_id="paper_faithful",
        required_before_admission=(ReviewStage.FULL,),
    )
    assert required_review_stages(minimal) == {ReviewStage.INITIAL}
    assert required_review_stages(faithful) == {ReviewStage.INITIAL, ReviewStage.FULL}
