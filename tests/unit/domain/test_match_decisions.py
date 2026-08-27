import pytest

from co_scientist.domain.tournament import MatchDecision, MatchResult, apply_match


@pytest.mark.parametrize(
    "decision",
    [
        MatchDecision.INCONCLUSIVE,
        MatchDecision.INVALID,
        MatchDecision.NEEDS_TIEBREAKER,
    ],
)
def test_non_decisive_match_does_not_update_rating(decision: MatchDecision) -> None:
    result = MatchResult(
        match_id="m-1",
        epoch_id="e-1",
        left_id="h-1",
        right_id="h-2",
        decision=decision,
    )

    with pytest.raises(ValueError, match="decisive"):
        apply_match(1200.0, 1200.0, result)


def test_decisive_match_requires_a_competing_winner() -> None:
    with pytest.raises(ValueError, match="valid winner"):
        MatchResult(
            match_id="m-1",
            epoch_id="e-1",
            left_id="h-1",
            right_id="h-2",
            decision=MatchDecision.DECISIVE,
            winner_id="h-3",
        )


def test_decisive_left_winner_updates_left_and_right_ratings() -> None:
    result = MatchResult(
        match_id="m-1",
        epoch_id="e-1",
        left_id="h-1",
        right_id="h-2",
        decision=MatchDecision.DECISIVE,
        winner_id="h-1",
    )

    assert apply_match(1200.0, 1200.0, result) == (1216.0, 1184.0)
